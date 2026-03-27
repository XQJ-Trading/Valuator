from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Awaitable, Callable

from domain.query import QueryAnalysis
from valuator.tools.base import ToolRegistry
from valuator.utils.config import config

from .context import TaskContext, TaskSummary
from .decomposition_critic import DecompositionCritic
from .decomposition_gate import BackpropagationTracker, combine, pre_filter
from .decomposition_types import DecompositionOutcome, FilterVerdict, GateConfig, GateDecision, PenaltyWeights
from .llm_usage import Measurement
from .scheduler import Scheduler
from .shared_state import SharedState
from .step_planner import StepPlanner
from .task import Task
from .types import Action, AgentEvent, TaskDecision, TaskState


def _utc_isoformat() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
    ) -> None:
        self._scheduler = scheduler
        self._shared = shared_state
        self._tools = tool_registry
        self._analysis = query_analysis
        self._on_event = on_event
        self._step_planner = step_planner or StepPlanner(llm_client)
        self._session_store = session_store
        self._trace_writer = (
            session_store.trace_writer if session_store is not None else trace_writer
        )
        self._gate_config = gate_config or GateConfig(
            enabled=config.decomposition_gate_enabled,
            weights=PenaltyWeights(
                depth=config.decomposition_gate_weight_depth,
                breadth=config.decomposition_gate_weight_breadth,
                tool_resolvability=config.decomposition_gate_weight_tool,
                token_pressure=config.decomposition_gate_weight_token_pressure,
            ),
            initial_threshold=config.decomposition_gate_initial_threshold,
            learning_rate=config.decomposition_gate_learning_rate,
            max_depth=config.decomposition_gate_max_depth,
            max_children=config.decomposition_gate_max_children,
            accept_bound=config.decomposition_gate_accept_bound,
            reject_bound=config.decomposition_gate_reject_bound,
            static_weight=config.decomposition_gate_static_weight,
            critic_weight=config.decomposition_gate_critic_weight,
        )
        self._critic = decomposition_critic
        if self._gate_config.enabled and self._critic is None:
            self._critic = DecompositionCritic(llm_client)
        self._tracker = BackpropagationTracker(
            initial_threshold=self._gate_config.initial_threshold,
            learning_rate=self._gate_config.learning_rate,
        )
        self._max_invalid_decisions_per_task = max(
            int(config.agent_max_invalid_decisions_per_task),
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
                    for ready_task in self._scheduler.ready_tasks(limit=available_slots):
                        ready_task.state = TaskState.RUNNING
                        in_flight.add(
                            asyncio.create_task(self._step_one(ready_task, query))
                        )

                if self._scheduler.is_complete() and not in_flight:
                    break
                if not in_flight:
                    if self._scheduler.has_deadlock():
                        raise RuntimeError("deadlock: no tasks ready, not all complete")
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

        if root_task.state.value == "failed":
            raise RuntimeError(f"root task failed: {root_task.error}")
        return root_task.output

    async def _step_one(self, task: Task, query: str) -> None:
        if task.step_count >= self._scheduler.max_steps_per_task:
            self._scheduler.mark_failed(task, "max steps exceeded")
            self._sync_session_tree()
            self._log_task_result(
                task,
                task_seq=task.step_count + 1,
                action=Action.FAIL.value,
                status="failed",
                error=task.error or "max steps exceeded",
            )
            await self._emit(
                AgentEvent(
                    type="task_failed",
                    task_id=task.id,
                    detail={"error": task.error or "max steps exceeded"},
                )
            )
            return

        self._global_step_sequence += 1
        task_seq = task.step_count + 1
        await self._emit(
            AgentEvent(
                type="step_start",
                task_id=task.id,
                detail={
                    "global_seq": self._global_step_sequence,
                    "step": task_seq,
                    "description": task.description,
                },
            )
        )

        ctx = self._build_context(task, query)
        decision_measurement = Measurement.start()
        try:
            decision = await task.step(ctx)
            if decision.action is Action.DECOMPOSE:
                decision = await self._gate_decompose(task, decision, ctx)
        except ValueError as exc:
            self._log_step_decision(
                task=task,
                task_seq=task_seq,
                ctx=ctx,
                status="failed",
                started_at=decision_measurement.started_at,
                duration_ms=decision_measurement.latency_seconds() * 1000.0,
                error=str(exc),
            )
            await self._handle_invalid_step(task, str(exc))
            return
        except Exception as exc:
            self._log_step_decision(
                task=task,
                task_seq=task_seq,
                ctx=ctx,
                status="failed",
                started_at=decision_measurement.started_at,
                duration_ms=decision_measurement.latency_seconds() * 1000.0,
                error=str(exc),
            )
            self._scheduler.mark_failed(task, f"step failed: {exc}")
            self._sync_session_tree()
            self._log_task_result(
                task,
                task_seq=task_seq,
                action=Action.FAIL.value,
                status="failed",
                error=task.error or str(exc),
            )
            await self._emit(
                AgentEvent(
                    type="task_failed",
                    task_id=task.id,
                    detail={"error": task.error or str(exc)},
                )
            )
            return

        decision_duration_ms = decision_measurement.latency_seconds() * 1000.0
        if decision.action is Action.EXECUTE and decision.tool_request is None:
            self._log_step_decision(
                task=task,
                task_seq=task_seq,
                ctx=ctx,
                decision=decision,
                status="failed",
                started_at=decision_measurement.started_at,
                duration_ms=decision_duration_ms,
                error="execute action missing tool_request",
            )
            await self._handle_invalid_step(task, "execute action missing tool_request")
            return

        if (
            decision.tool_request is not None
            and ctx.available_tools
            and decision.tool_request.tool_name not in ctx.available_tools
        ):
            error = f"tool not allowed: {decision.tool_request.tool_name}"
            self._log_step_decision(
                task=task,
                task_seq=task_seq,
                ctx=ctx,
                decision=decision,
                status="failed",
                started_at=decision_measurement.started_at,
                duration_ms=decision_duration_ms,
                error=error,
            )
            self._scheduler.mark_failed(
                task,
                error,
            )
            self._sync_session_tree()
            self._log_task_result(
                task,
                task_seq=task_seq,
                action=Action.FAIL.value,
                status="failed",
                error=task.error or "tool not allowed",
            )
            await self._emit(
                AgentEvent(
                    type="task_failed",
                    task_id=task.id,
                    detail={"error": task.error or "tool not allowed"},
                )
            )
            return

        if decision.action is Action.EXECUTE and task.last_tool_success is not None:
            self._log_step_decision(
                task=task,
                task_seq=task_seq,
                ctx=ctx,
                decision=decision,
                status="failed",
                started_at=decision_measurement.started_at,
                duration_ms=decision_duration_ms,
                error=(
                    "execute action is not allowed after a tool result; "
                    "use aggregate, decompose, wait, or fail"
                ),
            )
            await self._handle_invalid_step(
                task,
                "execute action is not allowed after a successful tool result; "
                "use aggregate, decompose, wait, or fail",
            )
            return

        if decision.action is Action.DECOMPOSE:
            error = self._scheduler.validate_decomposition(task, decision.children)
            if error is not None:
                self._log_step_decision(
                    task=task,
                    task_seq=task_seq,
                    ctx=ctx,
                    decision=decision,
                    status="failed",
                    started_at=decision_measurement.started_at,
                    duration_ms=decision_duration_ms,
                    error=error,
                )
                await self._handle_invalid_step(task, error)
                return

        task.last_invalid_error = None
        self._log_step_decision(
            task=task,
            task_seq=task_seq,
            ctx=ctx,
            decision=decision,
            status="success",
            started_at=decision_measurement.started_at,
            duration_ms=decision_duration_ms,
        )
        conflict_count = self._shared.conflict_count()

        if decision.action is Action.EXECUTE and decision.tool_request is not None:
            task.last_tool_request = decision.tool_request
            self._scheduler.apply_decision(task, decision, self._shared)
            tool_started_at = _utc_isoformat()
            started = perf_counter()
            result = await self._tools.execute_tool(
                decision.tool_request.tool_name,
                **decision.tool_request.args,
            )
            duration_ms = (perf_counter() - started) * 1000.0
            self._scheduler.mark_tool_complete(task, result)
            self._write_execution_result(
                task_id=task.id,
                tool_name=decision.tool_request.tool_name,
                args=decision.tool_request.args,
                result=result,
                started_at=tool_started_at,
                duration_ms=duration_ms,
            )
            self._sync_session_tree()
            self._log_tool_execution(
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
                    type="tool_execute",
                    task_id=task.id,
                    detail={
                        "tool": decision.tool_request.tool_name,
                        "args": decision.tool_request.args,
                        "duration_ms": round(duration_ms, 3),
                        "tool_result": result.model_dump(),
                    },
                )
            )
            return

        self._scheduler.apply_decision(task, decision, self._shared)
        self._write_task_report(task, decision)
        self._sync_session_tree()
        if decision.action is Action.DECOMPOSE:
            self._save_decomposition_snapshot(task)
        if decision.action is Action.AGGREGATE and self._tracker.has_prediction(task.id):
            self._tracker.observe_outcome(task.id, task.children())
        for conflict in self._shared.view().conflicts[conflict_count:]:
            await self._emit(
                AgentEvent(
                    type="conflict",
                    task_id=task.id,
                    detail={
                        "key": conflict.key,
                        "existing": conflict.existing.value,
                        "incoming": conflict.incoming.value,
                    },
                )
            )

        await self._emit(
            AgentEvent(
                type="decision",
                task_id=task.id,
                detail={
                    "action": decision.action.value,
                    "reason": decision.reason,
                },
            )
        )

        if decision.action in (Action.AGGREGATE, Action.FINALIZE):
            self._log_task_result(
                task,
                task_seq=task.step_count,
                action=decision.action.value,
                status="success",
                output=task.output,
            )
            await self._emit(
                AgentEvent(
                    type="task_done",
                    task_id=task.id,
                    detail={"output": task.output},
                )
            )
        elif decision.action is Action.FAIL:
            self._log_task_result(
                task,
                task_seq=task.step_count,
                action=decision.action.value,
                status="failed",
                error=task.error or decision.reason,
            )
            await self._emit(
                AgentEvent(
                    type="task_failed",
                    task_id=task.id,
                    detail={"error": task.error or decision.reason},
                )
            )

    def _build_context(self, task: Task, query: str) -> TaskContext:
        return TaskContext(
            task_id=task.id,
            description=task.description,
            step_count=task.step_count,
            tool_results=list(task.tool_results),
            child_outputs=dict(task.child_outputs),
            current_children=[
                TaskSummary(
                    id=child.id,
                    description=child.description,
                    state=child.state,
                    output=child.output if child.state.value == "done" else None,
                )
                for child in task.children()
            ],
            ancestry=self._build_ancestry(task),
            siblings=self._build_siblings(task),
            shared=self._shared.view(),
            query=query,
            query_analysis=self._analysis,
            available_tools=self._analysis.allowed_tools or self._registered_tools(),
        )

    def _build_ancestry(self, task: Task) -> list[TaskSummary]:
        ancestry: list[TaskSummary] = []
        parent_id = task.parent_id
        while parent_id:
            parent = self._scheduler.get_task(parent_id)
            if parent is None:
                break
            ancestry.append(
                TaskSummary(
                    id=parent.id,
                    description=parent.description,
                    state=parent.state,
                    output=parent.output if parent.state.value == "done" else None,
                )
            )
            parent_id = parent.parent_id
        return ancestry

    def _build_siblings(self, task: Task) -> dict[str, TaskSummary]:
        if not task.parent_id:
            return {}
        parent = self._scheduler.get_task(task.parent_id)
        if parent is None:
            return {}
        return {
            sibling.id: TaskSummary(
                id=sibling.id,
                description=sibling.description,
                state=sibling.state,
                output=sibling.output if sibling.state.value == "done" else None,
            )
            for sibling in parent.children()
            if sibling.id != task.id
        }

    def _registered_tools(self) -> list[str]:
        return sorted(
            str(tool_info["name"])
            for tool_info in self._tools.list_tools()
            if isinstance(tool_info, dict) and "name" in tool_info
        )

    async def _emit(self, event: AgentEvent) -> None:
        if self._on_event is None:
            return
        await self._on_event(event)

    async def _gate_decompose(
        self,
        task: Task,
        decision: TaskDecision,
        ctx: TaskContext,
    ) -> TaskDecision:
        if not self._gate_config.enabled:
            return decision

        threshold = self._tracker.current_threshold()
        filter_result = pre_filter(
            task_depth=len(ctx.ancestry),
            children=decision.children,
            executable_tools=frozenset(ctx.available_tools),
            max_steps_per_task=self._scheduler.max_steps_per_task,
            config=self._gate_config,
        )

        if filter_result.verdict is FilterVerdict.ACCEPT:
            self._record_decomposition_prediction(
                task=task,
                decision=decision,
                ctx=ctx,
                predicted_score=filter_result.static_score,
                used_critic=False,
            )
            return decision

        if filter_result.verdict is FilterVerdict.REJECT:
            gate_decision = GateDecision(
                net_score=filter_result.static_score,
                threshold=threshold,
                rejected=True,
                used_critic=False,
                reason=filter_result.reason,
                static_result=filter_result,
            )
            await self._emit_decomposition_gated(task, gate_decision)
            return await self._step_planner.requery_without_decompose(
                task,
                ctx,
                gate_decision.reason,
            )

        gate_decision: GateDecision
        if self._critic is None:
            gate_decision = GateDecision(
                net_score=filter_result.static_score,
                threshold=threshold,
                rejected=filter_result.static_score <= threshold,
                used_critic=False,
                reason=filter_result.reason,
                static_result=filter_result,
            )
        else:
            try:
                critic_verdict = await self._critic.evaluate(task, decision, ctx)
            except Exception as exc:
                gate_decision = GateDecision(
                    net_score=filter_result.static_score,
                    threshold=threshold,
                    rejected=filter_result.static_score <= threshold,
                    used_critic=False,
                    reason=f"critic failed; fallback to static score: {exc}",
                    static_result=filter_result,
                )
            else:
                gate_decision = combine(
                    filter_result=filter_result,
                    critic_verdict=critic_verdict,
                    actual_children=len(decision.children),
                    config=self._gate_config,
                    threshold=threshold,
                )

        if gate_decision.rejected:
            await self._emit_decomposition_gated(task, gate_decision)
            return await self._step_planner.requery_without_decompose(
                task,
                ctx,
                gate_decision.reason,
            )

        self._record_decomposition_prediction(
            task=task,
            decision=decision,
            ctx=ctx,
            predicted_score=gate_decision.net_score,
            used_critic=gate_decision.used_critic,
        )
        return decision

    def _record_decomposition_prediction(
        self,
        *,
        task: Task,
        decision: TaskDecision,
        ctx: TaskContext,
        predicted_score: float,
        used_critic: bool,
    ) -> None:
        self._tracker.record_prediction(
            DecompositionOutcome(
                task_id=task.id,
                predicted_score=predicted_score,
                child_count=len(decision.children),
                depth=len(ctx.ancestry),
                used_critic=used_critic,
            )
        )

    async def _emit_decomposition_gated(
        self,
        task: Task,
        gate_decision: GateDecision,
    ) -> None:
        await self._emit(
            AgentEvent(
                type="decomposition_gated",
                task_id=task.id,
                detail={
                    "static_verdict": gate_decision.static_result.verdict.value,
                    "used_critic": gate_decision.used_critic,
                    "static_score": gate_decision.static_result.static_score,
                    "net_score": gate_decision.net_score,
                    "threshold": gate_decision.threshold,
                    "reason": gate_decision.reason,
                },
            )
        )

    def _log_step_decision(
        self,
        *,
        task: Task,
        task_seq: int,
        ctx: TaskContext,
        status: str,
        started_at: str,
        duration_ms: float,
        decision: TaskDecision | None = None,
        error: str | None = None,
    ) -> None:
        if self._trace_writer is None:
            return
        result_payload: dict[str, Any]
        if decision is None:
            result_payload = {"error": error}
        else:
            result_payload = self._decision_payload(decision)
            if error is not None:
                result_payload["error"] = error
        if decision is None:
            summary = error or "step decision failed"
        else:
            summary = f"action={decision.action.value}"
            if error is not None:
                summary = f"{summary} error={error}"
        children_created = None
        if decision is not None and decision.action is Action.DECOMPOSE:
            children_created = [
                child["id"] for child in self._planned_child_records(task, decision)
            ]
            result_payload["children"] = self._planned_child_records(task, decision)
        tool_name = None
        tool_args = None
        if decision is not None and decision.tool_request is not None:
            tool_name = decision.tool_request.tool_name
            tool_args = decision.tool_request.args
        self._trace_writer.write_task_step(
            task_id=task.id,
            task_seq=task_seq,
            phase="decision",
            status=status,
            action=decision.action.value if decision is not None else None,
            summary=summary,
            started_at=started_at,
            duration_ms=round(duration_ms, 3),
            reason=decision.reason if decision is not None else None,
            tool_name=tool_name,
            tool_args=tool_args,
            children_created=children_created,
            wait_for=list(decision.wait_for) if decision is not None else None,
            wait_for_facts=list(decision.wait_for_facts) if decision is not None else None,
            input_payload=self._decision_input_payload(task, ctx),
            result_payload=result_payload,
            error=error,
        )

    def _log_tool_execution(
        self,
        *,
        task_id: str,
        task_seq: int,
        tool_name: str,
        args: dict[str, Any],
        result: Any,
        started_at: str,
        duration_ms: float,
    ) -> None:
        if self._trace_writer is None:
            return
        self._trace_writer.write_task_step(
            task_id=task_id,
            task_seq=task_seq,
            phase="tool_result",
            status="success" if bool(result.success) else "failed",
            action=Action.EXECUTE.value,
            summary=f"tool={tool_name} success={bool(result.success)}",
            started_at=started_at,
            duration_ms=round(duration_ms, 3),
            tool_name=tool_name,
            tool_args=args,
            tool_success=bool(result.success),
            input_payload={"tool_name": tool_name, "args": args},
            result_payload=result.model_dump(),
            error=result.error,
        )

    def _log_task_result(
        self,
        task: Task,
        *,
        task_seq: int,
        action: str | None,
        status: str,
        output: Any = None,
        error: str | None = None,
    ) -> None:
        if self._trace_writer is None:
            return
        summary = task.state.value
        if error:
            summary = error
        self._trace_writer.write_task_step(
            task_id=task.id,
            task_seq=task_seq,
            phase="task_result",
            status=status,
            action=action,
            summary=summary,
            started_at=_utc_isoformat(),
            duration_ms=0.0,
            input_payload=self._task_runtime_payload(task),
            result_payload={
                "state": task.state.value,
                "output": output,
                "error": error,
            },
            error=error,
        )

    def _decision_input_payload(self, task: Task, ctx: TaskContext) -> dict[str, Any]:
        return {
            "task": self._task_runtime_payload(task),
            "context": {
                "query": ctx.query,
                "available_tools": list(ctx.available_tools),
                "tool_results": [result.model_dump() for result in ctx.tool_results],
                "child_outputs": dict(ctx.child_outputs),
                "ancestry": [self._task_summary_payload(item) for item in ctx.ancestry],
                "siblings": {
                    task_id: self._task_summary_payload(summary)
                    for task_id, summary in ctx.siblings.items()
                },
                "shared": {
                    "facts": {
                        key: asdict(fact) for key, fact in ctx.shared.facts.items()
                    },
                    "conflicts": [asdict(conflict) for conflict in ctx.shared.conflicts],
                },
            },
        }

    @staticmethod
    def _decision_payload(decision: TaskDecision) -> dict[str, Any]:
        payload = asdict(decision)
        payload["action"] = decision.action.value
        return payload

    @staticmethod
    def _task_runtime_payload(task: Task) -> dict[str, Any]:
        return {
            "id": task.id,
            "description": task.description,
            "state": task.state.value,
            "parent_id": task.parent_id,
            "step_count": task.step_count,
            "invalid_decision_count": task.invalid_decision_count,
            "tool_hint": task.tool_hint,
            "last_tool_request": (
                {
                    "tool_name": task.last_tool_request.tool_name,
                    "args": dict(task.last_tool_request.args),
                }
                if task.last_tool_request is not None
                else None
            ),
            "last_tool_success": task.last_tool_success,
            "last_invalid_error": task.last_invalid_error,
            "child_output_ids": sorted(task.child_outputs),
            "tool_result_count": len(task.tool_results),
        }

    @staticmethod
    def _task_summary_payload(summary: TaskSummary) -> dict[str, Any]:
        return {
            "id": summary.id,
            "description": summary.description,
            "state": summary.state.value,
            "output": summary.output,
        }

    @staticmethod
    def _planned_child_records(task: Task, decision: TaskDecision) -> list[dict[str, Any]]:
        start_index = len(task.children())
        return [
            {
                "id": f"{task.id}.{start_index + offset}",
                "description": child.description,
                "tool_hint": child.tool_hint,
            }
            for offset, child in enumerate(decision.children)
        ]

    async def _handle_invalid_step(self, task: Task, error: str) -> None:
        task.invalid_decision_count += 1
        task.last_invalid_error = error
        if task.invalid_decision_count >= self._max_invalid_decisions_per_task:
            self._scheduler.mark_failed(task, f"too many invalid decisions: {error}")
            self._sync_session_tree()
            self._log_task_result(
                task,
                task_seq=task.step_count + 1,
                action=Action.FAIL.value,
                status="failed",
                error=task.error or error,
            )
            await self._emit(
                AgentEvent(
                    type="task_failed",
                    task_id=task.id,
                    detail={"error": task.error or error},
                )
            )
            return

        task.state = TaskState.READY
        self._scheduler.requeue_ready(task)
        self._sync_session_tree()
        await self._emit(
            AgentEvent(
                type="step_invalid",
                task_id=task.id,
                detail={
                    "error": error,
                    "invalid_decision_count": task.invalid_decision_count,
                    "step_count": task.step_count,
                },
            )
        )

    def _sync_session_tree(self) -> None:
        if self._session_store is None or self._root_task is None:
            return
        self._session_store.sync_task_tree(self._root_task)

    def _save_decomposition_snapshot(self, task: Task) -> None:
        if self._session_store is None:
            return
        current = self._scheduler.get_task(task.id) or task
        self._session_store.save_decomposition_snapshot(current, current.children())

    def _write_execution_result(
        self,
        *,
        task_id: str,
        tool_name: str,
        args: dict[str, Any],
        result: Any,
        started_at: str,
        duration_ms: float,
    ) -> None:
        if self._session_store is None:
            return
        self._session_store.write_execution_result(
            task_id=task_id,
            tool_name=tool_name,
            args=args,
            result=result,
            started_at=started_at,
            duration_ms=duration_ms,
        )

    def _write_task_report(self, task: Task, decision: TaskDecision) -> None:
        if self._session_store is None:
            return
        if decision.action not in (Action.AGGREGATE, Action.FINALIZE):
            return
        self._session_store.write_aggregation_report(
            task_id=task.id,
            output=task.output,
        )
