from __future__ import annotations

import asyncio
import json
from time import perf_counter
from typing import Any, Awaitable, Callable

from domain.query import QueryAnalysis
from valuator.tools.base import ToolRegistry
from valuator.utils.time_utils import Measurement, utc_isoformat

from ..context import TaskContext
from ..decomposition import DecompositionCritic, GateConfig, GateController
from ..scheduler import Scheduler
from ..shared_state import SharedState
from ..planning import StepPlanner
from ..task import Task
from ..types import Action, AgentEvent, EventType, TaskDecision, TaskState
from . import context_builder, trace as agent_trace


def _tool_request_signature(*, tool_name: str, args: dict[str, Any]) -> str:
    return f"{tool_name}:{json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)}"


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
        from valuator.utils.config import config

        self._scheduler = scheduler
        self._shared = shared_state
        self._tools = tool_registry
        self._analysis = query_analysis
        self._on_event = on_event
        self._step_planner = step_planner or StepPlanner(llm_client)
        self._session_store = session_store
        self._trace_writer = session_store.trace_writer if session_store is not None else trace_writer
        self._gate = GateController(
            llm_client=llm_client,
            scheduler=self._scheduler,
            step_planner=self._step_planner,
            emit=self._emit,
            gate_config=gate_config,
            decomposition_critic=decomposition_critic,
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
                        in_flight.add(asyncio.create_task(self._step_one(ready_task, query)))

                if self._scheduler.is_complete() and not in_flight:
                    break
                if not in_flight:
                    if self._scheduler.has_deadlock():
                        woken = self._scheduler.break_deadlock(self._shared)
                        if not woken and self._scheduler.has_deadlock():
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

        final_root = self._scheduler.get_task(root_task.id) or root_task
        if final_root.state is TaskState.FAILED:
            raise RuntimeError(f"root task failed: {final_root.error}")
        return final_root.completion_payload()

    async def _step_one(self, task: Task, query: str) -> None:
        if task.step_count >= self._scheduler._max_steps:
            await self._fail_task(
                task,
                task_seq=task.step_count + 1,
                reason="max steps exceeded",
            )
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

        ctx = context_builder.build_task_context(
            task=task,
            query=query,
            scheduler=self._scheduler,
            analysis=self._analysis,
            shared=self._shared,
            tools=self._tools,
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
            return
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
            return

        decision_duration_ms = decision_measurement.latency_seconds() * 1000.0
        if decision.action is Action.EXECUTE and decision.tool_request is None:
            await self._reject_step(
                task=task,
                task_seq=task_seq,
                ctx=ctx,
                decision=decision,
                started_at=decision_measurement.started_at,
                duration_ms=decision_duration_ms,
                error="execute action missing tool_request",
            )
            return

        if decision.tool_request is not None and ctx.available_tools and decision.tool_request.tool_name not in ctx.available_tools:
            error = f"tool not allowed: {decision.tool_request.tool_name}"
            agent_trace.log_step_decision(
                self._trace_writer,
                task=task,
                task_seq=task_seq,
                ctx=ctx,
                decision=decision,
                status="failed",
                started_at=decision_measurement.started_at,
                duration_ms=decision_duration_ms,
                error=error,
            )
            await self._fail_task(task, task_seq=task_seq, reason=error)
            return

        if decision.action is Action.EXECUTE and task.last_tool_success is True:
            await self._reject_step(
                task=task,
                task_seq=task_seq,
                ctx=ctx,
                decision=decision,
                started_at=decision_measurement.started_at,
                duration_ms=decision_duration_ms,
                error=(
                    "execute action is not allowed after a successful tool result; "
                    "use aggregate, decompose, wait, or fail"
                ),
            )
            return

        if decision.action is Action.DECOMPOSE:
            error = self._scheduler.validate_decomposition(task, decision.children)
            if error is not None:
                await self._reject_step(
                    task=task,
                    task_seq=task_seq,
                    ctx=ctx,
                    decision=decision,
                    started_at=decision_measurement.started_at,
                    duration_ms=decision_duration_ms,
                    error=error,
                )
                return

        if decision.action is Action.WAIT:
            error = self._scheduler.validate_wait(task.id, decision.wait_for)
            if error is not None:
                await self._reject_step(
                    task=task,
                    task_seq=task_seq,
                    ctx=ctx,
                    decision=decision,
                    started_at=decision_measurement.started_at,
                    duration_ms=decision_duration_ms,
                    error=error,
                )
                return

        effective_decision = decision
        if decision.action is Action.EXECUTE and decision.tool_request is not None:
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
                    started_at=decision_measurement.started_at,
                    duration_ms=decision_duration_ms,
                    error=(
                        "execute action repeats a previously failed tool request; "
                        "change the tool, change the args, or decompose"
                    ),
                )
                return

        task.last_invalid_error = None
        agent_trace.log_step_decision(
            self._trace_writer,
            task=task,
            task_seq=task_seq,
            ctx=ctx,
            decision=effective_decision,
            status="success",
            started_at=decision_measurement.started_at,
            duration_ms=decision_duration_ms,
        )
        conflict_count = len(self._shared.view().conflicts)

        if effective_decision.action is Action.EXECUTE and effective_decision.tool_request is not None:
            task.last_tool_request = effective_decision.tool_request
            self._scheduler.apply_decision(task, effective_decision, self._shared, ctx=ctx)
            tool_started_at = utc_isoformat()
            started = perf_counter()
            result = await self._tools.execute_tool(
                effective_decision.tool_request.tool_name,
                **effective_decision.tool_request.args,
            )
            duration_ms = (perf_counter() - started) * 1000.0
            if not result.success:
                task.failed_tool_request_signatures.add(
                    _tool_request_signature(
                        tool_name=effective_decision.tool_request.tool_name,
                        args=effective_decision.tool_request.args,
                    )
                )
            self._scheduler.mark_tool_complete(task, result)
            self._write_execution_result(
                task_id=task.id,
                tool_name=effective_decision.tool_request.tool_name,
                args=effective_decision.tool_request.args,
                result=result,
                started_at=tool_started_at,
                duration_ms=duration_ms,
            )
            self._sync_session_tree()
            agent_trace.log_tool_execution(
                self._trace_writer,
                task_id=task.id,
                task_seq=task_seq,
                tool_name=effective_decision.tool_request.tool_name,
                args=effective_decision.tool_request.args,
                result=result,
                started_at=tool_started_at,
                duration_ms=duration_ms,
            )
            await self._emit(
                AgentEvent(
                    type=EventType.TOOL_EXECUTED,
                    task_id=task.id,
                    detail={
                        "tool": effective_decision.tool_request.tool_name,
                        "args": effective_decision.tool_request.args,
                        "duration_ms": round(duration_ms, 3),
                        "tool_result": result.model_dump(),
                        "task_name": task.task_name,
                    },
                )
            )
            return

        self._scheduler.apply_decision(task, effective_decision, self._shared, ctx=ctx)
        self._write_task_report(task, effective_decision)
        self._sync_session_tree()
        if effective_decision.action is Action.DECOMPOSE:
            self._save_decomposition_snapshot(task)
        if effective_decision.action is Action.AGGREGATE and self._gate.has_prediction(task.id):
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

        if effective_decision.action is Action.DECOMPOSE:
            parent = self._scheduler.get_task(task.id) or task
            n = len(effective_decision.children)
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
                        "child_count": len(effective_decision.children),
                        "children": children_detail,
                        "task_name": parent.task_name,
                    },
                )
            )
        elif effective_decision.action not in (
            Action.AGGREGATE,
            Action.FINALIZE,
            Action.FAIL,
        ):
            await self._emit(
                AgentEvent(
                    type=EventType.STEP_COMPLETED,
                    task_id=task.id,
                    detail={"action": effective_decision.action.value},
                )
            )

        if effective_decision.action in (Action.AGGREGATE, Action.FINALIZE):
            completion_payload = task.completion_payload()
            agent_trace.log_task_result(
                self._trace_writer,
                task,
                task_seq=task.step_count,
                action=effective_decision.action.value,
                status="success",
                output=completion_payload,
            )
            await self._emit(
                AgentEvent(
                    type=(
                        EventType.AGGREGATED
                        if effective_decision.action is Action.AGGREGATE
                        else EventType.FINALIZED
                    ),
                    task_id=task.id,
                    detail={
                        "output": completion_payload,
                        "task_name": task.task_name,
                    },
                )
            )
        elif effective_decision.action is Action.FAIL:
            error = (
                task.error
                or (
                    str(effective_decision.output)
                    if effective_decision.output is not None
                    else None
                )
                or "task failed"
            )
            agent_trace.log_task_result(
                self._trace_writer,
                task,
                task_seq=task.step_count,
                action=effective_decision.action.value,
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
        await self._handle_invalid_step(task, error)

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
            output=task.completion_payload(),
        )
