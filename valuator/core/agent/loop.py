from __future__ import annotations

import asyncio
import json
from time import perf_counter
from typing import Any, Awaitable, Callable

from domain.query import QueryAnalysis
from valuator.evidence import EvidenceRow, SqliteEvidenceStore, stable_args_hash
from valuator.tools.base import ToolRegistry
from valuator.utils.time_utils import Measurement, kst_isoformat

from ..context import TaskContext
from ..decomposition import (
    DecompositionCritic,
    DecompositionGate,
    GateConfig,
    MCTSGateController,
    PassthroughGate,
)
from ..scheduler import Scheduler
from ..shared_state import SharedState
from ..planning import StepPlanner
from ..task import ComplexTask, Task
from ..types import (
    Action,
    AgentEvent,
    EventType,
    FailedAttempt,
    TaskDecision,
    TaskState,
    TaskWorkPhase,
)
from . import context_builder, trace as agent_trace


def _tool_request_signature(*, tool_name: str, args: dict[str, Any]) -> str:
    return f"{tool_name}:{json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)}"


def _tool_result_status(*, tool_name: str, result: Any) -> str:
    if not result.success:
        return "failed"
    if _is_empty_tool_result(tool_name=tool_name, result=result):
        return "empty"
    return "satisfied"


def _is_empty_tool_result(*, tool_name: str, result: Any) -> bool:
    payload = result.result
    if payload in (None, "", [], {}):
        return True
    if tool_name == "web_search_tool":
        findings = payload.get("findings") if isinstance(payload, dict) else None
        return not (isinstance(findings, str) and findings.strip())
    if tool_name == "sec_tool":
        if result.metadata.get("selected_count") == 0:
            return True
        findings = payload.get("findings") if isinstance(payload, dict) else None
        return not (isinstance(findings, str) and findings.strip())
    return False


def _tool_result_summary(result: Any) -> str:
    if not result.success:
        return (result.error or "").strip()
    payload = result.result
    if isinstance(payload, str):
        return " ".join(payload.split())[:240]
    if isinstance(payload, dict):
        for key in ("domain_summary", "summary", "findings", "result", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())[:240]
        preview_parts: list[str] = []
        for key, value in payload.items():
            if value in (None, "", [], {}):
                continue
            if isinstance(value, (str, int, float, bool)):
                preview_parts.append(f"{key}={value}")
            if len(preview_parts) >= 3:
                break
        return ", ".join(preview_parts)[:240]
    if isinstance(payload, list):
        return f"{len(payload)} items"
    return str(payload).strip()[:240]


class Agent:
    def __init__(
        self,
        *,
        scheduler: Scheduler,
        shared_state: SharedState,
        tool_registry: ToolRegistry,
        llm_client: Any,
        query_analysis: QueryAnalysis,
        on_event: Callable[[AgentEvent], Awaitable[None]] | None = None,
        step_planner: StepPlanner | None = None,
        trace_writer: Any | None = None,
        session_store: Any | None = None,
        gate_config: GateConfig | None = None,
        decomposition_critic: DecompositionCritic | None = None,
        evidence_store: SqliteEvidenceStore | None = None,
        evidence_session_id: str = "",
    ) -> None:
        from valuator.utils.config import config

        gate_cfg = gate_config or GateConfig()
        self._scheduler = scheduler
        self._shared = shared_state
        self._tools = tool_registry
        self._analysis = query_analysis
        self._on_event = on_event
        self._step_planner = step_planner or StepPlanner(
            llm_client,
        )
        self._session_store = session_store
        self._trace_writer = (
            session_store.trace_writer if session_store is not None else trace_writer
        )
        self._evidence_store = evidence_store
        if self._evidence_store is None and session_store is not None:
            self._evidence_store = SqliteEvidenceStore(session_store.session_dir / "evidence.db")
        self._evidence_session_id = (
            evidence_session_id
            or (
                str(getattr(session_store, "session_id", "")).strip()
                if session_store is not None
                else ""
            )
        )
        self._gate: DecompositionGate
        if gate_cfg.enabled:
            self._gate = MCTSGateController(
                llm_client=llm_client,
                scheduler=self._scheduler,
                step_planner=self._step_planner,
                emit=self._emit,
                gate_config=gate_cfg,
                decomposition_critic=decomposition_critic,
            )
        else:
            self._gate = PassthroughGate()
        self._max_invalid_decisions_per_task = max(
            int(config.agent_max_invalid_decisions_per_task),
            1,
        )
        self._max_consecutive_tool_failures = max(
            int(config.agent_max_consecutive_tool_failures),
            1,
        )
        self._global_step_sequence = 0
        self._root_task: Task | None = None

    async def run(self, query: str, root_task: Task) -> Any:
        self._root_task = root_task
        root_task.bind_step(self._step_planner.decide)
        self._scheduler.register(root_task)
        self._sync_session_tree()

        in_flight: set[asyncio.Task[None]] = set()
        try:
            while not self._scheduler.is_complete() or in_flight:
                available_slots = self._scheduler.concurrency - len(in_flight)
                if available_slots > 0:
                    for ready_task in self._scheduler.ready_tasks(
                        limit=available_slots
                    ):
                        ready_task.state = TaskState.RUNNING
                        in_flight.add(
                            asyncio.create_task(self._step_one(ready_task, query))
                        )

                if self._scheduler.is_complete() and not in_flight:
                    break
                if not in_flight:
                    if self._scheduler.has_deadlock():
                        woken = self._scheduler.break_deadlock(self._shared)
                        if not woken and self._scheduler.has_deadlock():
                            raise RuntimeError(
                                "deadlock: no tasks ready, not all complete"
                            )
                    continue

                completed, pending = await asyncio.wait(
                    in_flight,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                in_flight = set(pending)
                for completed_task in completed:
                    await completed_task
        finally:
            for running_task in in_flight:
                running_task.cancel()
            if in_flight:
                await asyncio.gather(*in_flight, return_exceptions=True)

        final_root = self._scheduler.get_task(root_task.id) or root_task
        if final_root.state is TaskState.FAILED:
            raise RuntimeError(f"root task failed: {final_root.error}")
        if self._session_store is not None:
            self._session_store.write_shared_facts(self._shared)
        return final_root.completion_payload()

    async def _step_one(self, task: Task, query: str) -> None:
        if task.step_count >= self._scheduler._max_steps:
            await self._force_finalize(task)
            return

        self._global_step_sequence += 1
        task_seq = task.step_count + 1
        await self._emit(
            AgentEvent(
                type=EventType.STEP_STARTED,
                task_id=task.id,
                detail={
                    "global_seq": self._global_step_sequence,
                    "step": task_seq,
                    "description": task.description,
                    "task_name": task.task_name,
                },
            )
        )

        decided = await self._decide_step(task, query=query, task_seq=task_seq)
        if decided is None:
            return
        ctx, decision, decision_started_at, decision_duration_ms = decided

        if not await self._validate_step_decision(
            task=task,
            task_seq=task_seq,
            ctx=ctx,
            decision=decision,
            started_at=decision_started_at,
            duration_ms=decision_duration_ms,
        ):
            return

        effective_decision = await self._effective_decision(
            task=task,
            task_seq=task_seq,
            ctx=ctx,
            decision=decision,
            started_at=decision_started_at,
            duration_ms=decision_duration_ms,
        )
        if effective_decision is None:
            return

        task.last_invalid_error = None
        agent_trace.log_step_decision(
            self._trace_writer,
            task=task,
            task_seq=task_seq,
            ctx=ctx,
            decision=effective_decision,
            status="success",
            started_at=decision_started_at,
            duration_ms=decision_duration_ms,
        )
        conflict_count = len(self._shared.view().conflicts)

        if (
            effective_decision.action is Action.EXECUTE
            and effective_decision.tool_request is not None
        ):
            await self._execute_tool_step(
                task=task,
                task_seq=task_seq,
                ctx=ctx,
                decision=effective_decision,
            )
            return

        await self._complete_non_execute_step(
            task=task,
            task_seq=task_seq,
            ctx=ctx,
            decision=effective_decision,
            conflict_count=conflict_count,
        )

    async def _decide_step(
        self,
        task: Task,
        *,
        query: str,
        task_seq: int,
    ) -> tuple[TaskContext, TaskDecision, str, float] | None:
        ctx = context_builder.build_task_context(
            task=task,
            query=query,
            scheduler=self._scheduler,
            analysis=self._analysis,
            shared=self._shared,
            tools=self._tools,
            evidence_store=self._evidence_store,
            evidence_session_id=self._evidence_session_id,
        )
        decision_measurement = Measurement.start()
        try:
            decision = await task.step(ctx)
            if decision.action is Action.DECOMPOSE:
                decision = await self._gate.gate(task, decision, ctx)
        except ValueError as exc:
            await self._reject_step(
                task=task,
                task_seq=task_seq,
                ctx=ctx,
                started_at=decision_measurement.started_at,
                duration_ms=decision_measurement.latency_seconds() * 1000.0,
                error=str(exc),
            )
            return None
        except Exception as exc:
            agent_trace.log_step_decision(
                self._trace_writer,
                task=task,
                task_seq=task_seq,
                ctx=ctx,
                decision=None,
                status="failed",
                started_at=decision_measurement.started_at,
                duration_ms=decision_measurement.latency_seconds() * 1000.0,
                error=str(exc),
            )
            await self._fail_task(task, task_seq=task_seq, reason=f"step failed: {exc}")
            return None

        return (
            ctx,
            decision,
            decision_measurement.started_at,
            decision_measurement.latency_seconds() * 1000.0,
        )

    async def _validate_step_decision(
        self,
        *,
        task: Task,
        task_seq: int,
        ctx: TaskContext,
        decision: TaskDecision,
        started_at: str,
        duration_ms: float,
    ) -> bool:
        invalid_error: str | None = None
        if decision.action is Action.EXECUTE and decision.tool_request is None:
            invalid_error = "execute action missing tool_request"
        elif (
            decision.tool_request is not None
            and ctx.available_tools
            and decision.tool_request.tool_name not in ctx.available_tools
        ):
            error = f"tool not allowed: {decision.tool_request.tool_name}"
            agent_trace.log_step_decision(
                self._trace_writer,
                task=task,
                task_seq=task_seq,
                ctx=ctx,
                decision=decision,
                status="failed",
                started_at=started_at,
                duration_ms=duration_ms,
                error=error,
            )
            await self._fail_task(task, task_seq=task_seq, reason=error)
            return False
        elif decision.action is Action.EXECUTE and task.last_tool_success is True:
            invalid_error = (
                "execute action is not allowed after a successful tool result; "
                "use aggregate, decompose, wait, or fail"
            )
        elif decision.action is Action.DECOMPOSE:
            if (
                isinstance(task, ComplexTask)
                and task.work_phase is TaskWorkPhase.SYNTHESIZE
            ):
                invalid_error = (
                    "decompose is not allowed in synthesize phase; use aggregate, "
                    "wait, or fail"
                )
            else:
                invalid_error = self._scheduler.validate_decomposition(
                    task,
                    decision.children,
                )
        elif decision.action is Action.WAIT:
            invalid_error = self._scheduler.validate_wait(task.id, decision.wait_for)

        if invalid_error is None:
            return True

        await self._reject_step(
            task=task,
            task_seq=task_seq,
            ctx=ctx,
            decision=decision,
            started_at=started_at,
            duration_ms=duration_ms,
            error=invalid_error,
        )
        return False

    async def _effective_decision(
        self,
        *,
        task: Task,
        task_seq: int,
        ctx: TaskContext,
        decision: TaskDecision,
        started_at: str,
        duration_ms: float,
    ) -> TaskDecision | None:
        if decision.action is not Action.EXECUTE or decision.tool_request is None:
            return decision

        effective_request = context_builder.enrich_tool_request(
            tool_request=decision.tool_request,
            ctx=ctx,
        )
        effective_decision = TaskDecision(
            action=decision.action,
            children=decision.children,
            tool_request=effective_request,
            wait_for=decision.wait_for,
            output=decision.output,
            facts=dict(decision.facts),
        )
        if effective_request.tool_name in task.blocked_tools:
            await self._reject_step(
                task=task,
                task_seq=task_seq,
                ctx=ctx,
                decision=effective_decision,
                started_at=started_at,
                duration_ms=duration_ms,
                error=(
                    "execute action uses a tool blocked after repeated consecutive "
                    f"failures: {effective_request.tool_name}; "
                    "choose another tool or decompose"
                ),
            )
            return None

        evidence = self._lookup_evidence(
            tool_name=effective_request.tool_name,
            args=effective_request.args,
        )
        if evidence is not None and evidence.status == "satisfied":
            summary = evidence.value_summary or "already collected"
            await self._reject_step(
                task=task,
                task_seq=task_seq,
                ctx=ctx,
                decision=effective_decision,
                started_at=started_at,
                duration_ms=duration_ms,
                error=(
                    "execute action repeats evidence already collected in "
                    f"task {evidence.task_id}: {summary}"
                ),
            )
            return None

        request_signature = _tool_request_signature(
            tool_name=effective_request.tool_name,
            args=effective_request.args,
        )
        if request_signature in task.failed_tool_request_signatures:
            await self._reject_step(
                task=task,
                task_seq=task_seq,
                ctx=ctx,
                decision=effective_decision,
                started_at=started_at,
                duration_ms=duration_ms,
                error=(
                    "execute action repeats a previously failed tool request; "
                    "change the tool, change the args, or decompose"
                ),
            )
            return None

        return effective_decision

    async def _execute_tool_step(
        self,
        *,
        task: Task,
        task_seq: int,
        ctx: TaskContext,
        decision: TaskDecision,
    ) -> None:
        assert decision.tool_request is not None
        task.last_tool_request = decision.tool_request
        self._scheduler.apply_decision(task, decision, self._shared, ctx=ctx)
        tool_started_at = kst_isoformat()
        started = perf_counter()
        result = await self._tools.execute_tool(
            decision.tool_request.tool_name,
            **decision.tool_request.args,
        )
        duration_ms = (perf_counter() - started) * 1000.0
        tool_name = decision.tool_request.tool_name
        artifact_refs: dict[str, str] = {}
        if result.success:
            task.tool_failure_counts.pop(tool_name, None)
        else:
            task.failed_tool_request_signatures.add(
                _tool_request_signature(
                    tool_name=tool_name,
                    args=decision.tool_request.args,
                )
            )
            task.tool_failure_counts[tool_name] = (
                task.tool_failure_counts.get(tool_name, 0) + 1
            )
            if (
                task.tool_failure_counts[tool_name]
                >= self._max_consecutive_tool_failures
            ):
                task.blocked_tools.add(tool_name)
            self._append_failed_attempt(
                task=task,
                tool_name=tool_name,
                args=decision.tool_request.args,
                error=result.error or "tool execution failed",
                kind="tool_error",
            )
        self._scheduler.mark_tool_complete(task, result)
        if self._session_store is not None:
            artifact_refs = self._session_store.write_execution_result(
                task_id=task.id,
                tool_name=decision.tool_request.tool_name,
                args=decision.tool_request.args,
                result=result,
                started_at=tool_started_at,
                duration_ms=duration_ms,
            )
            task.artifacts.update(artifact_refs)
            result.metadata["artifacts"] = artifact_refs
        self._record_evidence(
            task=task,
            ctx=ctx,
            tool_name=tool_name,
            args=decision.tool_request.args,
            result=result,
            value_ref=artifact_refs.get("execution_result_path", ""),
        )
        self._sync_session_tree()
        agent_trace.log_tool_execution(
            self._trace_writer,
            task_id=task.id,
            task_seq=task_seq,
            tool_name=decision.tool_request.tool_name,
            args=decision.tool_request.args,
            result=result,
            started_at=tool_started_at,
            duration_ms=duration_ms,
        )
        await self._emit(
            AgentEvent(
                type=EventType.TOOL_EXECUTED,
                task_id=task.id,
                detail={
                    "tool": decision.tool_request.tool_name,
                    "args": decision.tool_request.args,
                    "duration_ms": round(duration_ms, 3),
                    "tool_result": result.model_dump(),
                    "task_name": task.task_name,
                },
            )
        )

    async def _complete_non_execute_step(
        self,
        *,
        task: Task,
        task_seq: int,
        ctx: TaskContext,
        decision: TaskDecision,
        conflict_count: int,
    ) -> None:
        self._scheduler.apply_decision(task, decision, self._shared, ctx=ctx)
        if (
            self._session_store is not None
            and decision.action in (Action.AGGREGATE, Action.FINALIZE)
        ):
            artifact_refs = self._session_store.write_aggregation_report(
                task_id=task.id,
                output=task.completion_payload(),
            )
            task.artifacts.update(artifact_refs)
        self._sync_session_tree()
        if decision.action is Action.DECOMPOSE and self._session_store is not None:
            current = self._scheduler.get_task(task.id) or task
            self._session_store.save_decomposition_snapshot(
                current,
                current.children(),
            )
        if decision.action is Action.AGGREGATE and self._gate.has_prediction(task.id):
            self._gate.observe_outcome(task.id, task.children())
        for conflict in self._shared.view().conflicts[conflict_count:]:
            await self._emit(
                AgentEvent(
                    type=EventType.STEP_COMPLETED,
                    task_id=task.id,
                    detail={
                        "kind": "conflict",
                        "key": conflict.key,
                        "existing": conflict.existing.value,
                        "incoming": conflict.incoming.value,
                    },
                )
            )

        if decision.action is Action.DECOMPOSE:
            parent = self._scheduler.get_task(task.id) or task
            n = len(decision.children)
            new_children = parent.children()[-n:] if n else []
            children_detail = [
                {
                    "id": c.id,
                    "task_name": c.task_name,
                    "description": c.description,
                }
                for c in new_children
            ]
            await self._emit(
                AgentEvent(
                    type=EventType.DECOMPOSED,
                    task_id=task.id,
                    detail={
                        "child_count": len(decision.children),
                        "children": children_detail,
                        "task_name": parent.task_name,
                    },
                )
            )
            return

        if decision.action is Action.WAIT:
            await self._emit(
                AgentEvent(
                    type=EventType.STEP_COMPLETED,
                    task_id=task.id,
                    detail={"action": decision.action.value},
                )
            )
            return

        if decision.action in (Action.AGGREGATE, Action.FINALIZE):
            completion_payload = task.completion_payload()
            agent_trace.log_task_result(
                self._trace_writer,
                task,
                task_seq=task.step_count,
                action=decision.action.value,
                status="success",
                output=completion_payload,
            )
            await self._emit(
                AgentEvent(
                    type=(
                        EventType.AGGREGATED
                        if decision.action is Action.AGGREGATE
                        else EventType.FINALIZED
                    ),
                    task_id=task.id,
                    detail={
                        "output": completion_payload,
                        "task_name": task.task_name,
                    },
                )
            )
            return

        if decision.action is Action.FAIL:
            error = (
                task.error
                or (str(decision.output) if decision.output is not None else None)
                or "task failed"
            )
            agent_trace.log_task_result(
                self._trace_writer,
                task,
                task_seq=task.step_count,
                action=decision.action.value,
                status="failed",
                error=error,
            )
            await self._emit(
                AgentEvent(
                    type=EventType.FAILED,
                    task_id=task.id,
                    detail={"error": error, "task_name": task.task_name},
                )
            )
            return

    def _append_failed_attempt(
        self,
        *,
        task: Task,
        tool_name: str,
        args: dict[str, Any],
        error: str,
        kind: str,
    ) -> None:
        task.failed_attempts.append(
            FailedAttempt(
                tool_name=tool_name,
                args=dict(args),
                error=error,
                kind=kind,
            )
        )

    def _lookup_evidence(
        self,
        *,
        tool_name: str,
        args: dict[str, Any],
    ) -> EvidenceRow | None:
        if self._evidence_store is None or not self._evidence_session_id:
            return None
        return self._evidence_store.lookup(
            session_id=self._evidence_session_id,
            tool_name=tool_name,
            args=args,
        )

    def _record_evidence(
        self,
        *,
        task: Task,
        ctx: TaskContext,
        tool_name: str,
        args: dict[str, Any],
        result: Any,
        value_ref: str,
    ) -> None:
        if self._evidence_store is None or not self._evidence_session_id:
            return
        status = _tool_result_status(tool_name=tool_name, result=result)
        self._evidence_store.record(
            EvidenceRow(
                session_id=self._evidence_session_id,
                tool_name=tool_name,
                stable_args_hash=stable_args_hash(tool_name, args),
                status=status,
                value_summary=_tool_result_summary(result),
                value_ref=value_ref,
                task_id=task.id,
                unit_objective=" / ".join(unit.objective for unit in ctx.query_units),
                created_at=kst_isoformat(),
                updated_at=kst_isoformat(),
                stable_args=dict(args),
            )
        )

    async def _emit(self, event: AgentEvent) -> None:
        if self._on_event is None:
            return
        await self._on_event(event)

    async def _handle_invalid_step(self, task: Task, error: str) -> None:
        task.invalid_decision_count += 1
        task.last_invalid_error = error
        if task.invalid_decision_count >= self._max_invalid_decisions_per_task:
            await self._fail_task(
                task,
                task_seq=task.step_count + 1,
                reason=f"too many invalid decisions: {error}",
            )
            return

        task.state = TaskState.READY
        self._scheduler.requeue_ready(task)
        self._sync_session_tree()
        await self._emit(
            AgentEvent(
                type=EventType.FAILED,
                task_id=task.id,
                detail={
                    "kind": "step_invalid",
                    "error": error,
                    "invalid_decision_count": task.invalid_decision_count,
                    "step_count": task.step_count,
                    "task_name": task.task_name,
                },
            )
        )

    async def _reject_step(
        self,
        *,
        task: Task,
        task_seq: int,
        ctx: "TaskContext",
        started_at: str,
        duration_ms: float,
        error: str,
        decision: TaskDecision | None = None,
    ) -> None:
        agent_trace.log_step_decision(
            self._trace_writer,
            task=task,
            task_seq=task_seq,
            ctx=ctx,
            decision=decision,
            status="failed",
            started_at=started_at,
            duration_ms=duration_ms,
            error=error,
        )
        if decision is not None and decision.tool_request is not None:
            self._append_failed_attempt(
                task=task,
                tool_name=decision.tool_request.tool_name,
                args=decision.tool_request.args,
                error=error,
                kind="decision_rejected",
            )
        await self._handle_invalid_step(task, error)

    async def _force_finalize(self, task: Task) -> None:
        """Max steps reached — finalize subtree bottom-up, then this task."""
        for child in task.children():
            if child.state in (TaskState.DONE, TaskState.FAILED):
                continue
            await self._force_finalize(child)

        for child in task.children():
            if child.state == TaskState.DONE and child.id not in task.child_outputs:
                task.child_outputs[child.id] = child.completion_payload()

        output, facts = task.implicit_aggregate_payload()
        if facts:
            for key, value in facts.items():
                self._shared.publish(
                    key,
                    value,
                    source_task_id=task.id,
                    query_unit_ids=tuple(task.query_unit_ids),
                )
        decision = TaskDecision(
            action=Action.FINALIZE,
            output=output,
            facts=facts,
            children=[],
        )
        self._scheduler.apply_decision(task, decision, self._shared)
        if self._session_store is not None:
            artifact_refs = self._session_store.write_aggregation_report(
                task_id=task.id,
                output=task.completion_payload(),
            )
            task.artifacts.update(artifact_refs)
        self._sync_session_tree()
        completion_payload = task.completion_payload()
        agent_trace.log_task_result(
            self._trace_writer,
            task,
            task_seq=task.step_count,
            action=Action.FINALIZE.value,
            status="success",
            output=completion_payload,
        )
        await self._emit(
            AgentEvent(
                type=EventType.FINALIZED,
                task_id=task.id,
                detail={
                    "output": completion_payload,
                    "task_name": task.task_name,
                    "reason": "max_steps_reached",
                },
            )
        )

    async def _fail_task(
        self,
        task: Task,
        *,
        task_seq: int,
        reason: str,
    ) -> None:
        self._scheduler.mark_failed(task, reason)
        self._sync_session_tree()
        error = task.error or reason
        agent_trace.log_task_result(
            self._trace_writer,
            task,
            task_seq=task_seq,
            action=Action.FAIL.value,
            status="failed",
            error=error,
        )
        await self._emit(
            AgentEvent(
                type=EventType.FAILED,
                task_id=task.id,
                detail={"error": error, "task_name": task.task_name},
            )
        )

    def _sync_session_tree(self) -> None:
        if self._session_store is None or self._root_task is None:
            return
        self._session_store.sync_task_tree(self._root_task)
        self._session_store.build_browse_tree()
