from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ..context import TaskContext
from ..scheduler import Scheduler
from ..planning import StepPlanner
from ..task import Task
from ..types import AgentEvent, EventType, TaskDecision
from .critic import DecompositionCritic
from .gate import BackpropagationTracker, combine, pre_filter
from .gate_config import GateConfig
from .types import DecompositionOutcome, FilterVerdict, GateDecision


class MCTSGateController:
    def __init__(
        self,
        *,
        llm_client: Any,
        scheduler: Scheduler,
        step_planner: StepPlanner,
        emit: Callable[[AgentEvent], Awaitable[None]] | None = None,
        gate_config: GateConfig | None = None,
        decomposition_critic: DecompositionCritic | None = None,
    ) -> None:
        self._scheduler = scheduler
        self._step_planner = step_planner
        self._emit = emit
        self._config = gate_config or GateConfig()
        self._critic = decomposition_critic
        if self._config.enabled and self._critic is None:
            self._critic = DecompositionCritic(llm_client)
        self._tracker = BackpropagationTracker(
            initial_threshold=self._config.initial_threshold,
            learning_rate=self._config.learning_rate,
        )

    async def gate(
        self,
        task: Task,
        decision: TaskDecision,
        ctx: TaskContext,
    ) -> TaskDecision:
        threshold = self._tracker.current_threshold()
        filter_result = pre_filter(
            task_depth=len(ctx.ancestry),
            children=list(decision.children),
            max_steps_per_task=self._scheduler.max_steps_per_task,
            config=self._config,
        )

        if filter_result.verdict is FilterVerdict.ACCEPT:
            self._record_prediction(
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
                    config=self._config,
                    threshold=threshold,
                )

        if gate_decision.rejected:
            await self._emit_decomposition_gated(task, gate_decision)
            return await self._step_planner.requery_without_decompose(
                task,
                ctx,
                gate_decision.reason,
            )

        self._record_prediction(
            task=task,
            decision=decision,
            ctx=ctx,
            predicted_score=gate_decision.net_score,
            used_critic=gate_decision.used_critic,
        )
        return decision

    def has_prediction(self, task_id: str) -> bool:
        return self._tracker.has_prediction(task_id)

    def observe_outcome(self, task_id: str, children: list[Task]) -> None:
        self._tracker.observe_outcome(task_id, children)

    def _record_prediction(
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
        if self._emit is None:
            return
        await self._emit(
            AgentEvent(
                type=EventType.DECOMPOSITION_GATED,
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
