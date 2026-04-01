from __future__ import annotations

import math

from ..task import AtomicTask, Task
from ..types import TaskSpec, TaskState
from .gate_config import GateConfig
from .types import (
    CriticVerdict,
    DecompositionOutcome,
    FilterResult,
    FilterVerdict,
    GateDecision,
    StaticBreakdown,
)


def depth_cost(depth: int, max_depth: int) -> float:
    d = min(depth, max_depth)
    return (d / max_depth) ** 2


def breadth_cost(child_count: int, max_children: int) -> float:
    if child_count <= 1:
        return 0.0
    return math.log2(child_count) / math.log2(max_children)


def token_pressure(
    child_count: int,
    depth: int,
    max_steps_per_task: int,
    avg_tokens_per_step: int = 2000,
) -> float:
    estimated_tokens = child_count * avg_tokens_per_step
    budget_per_branch = max_steps_per_task * avg_tokens_per_step / (depth + 1)
    return estimated_tokens / budget_per_branch


def pre_filter(
    *,
    task_depth: int,
    children: list[TaskSpec],
    max_steps_per_task: int,
    config: GateConfig,
) -> FilterResult:
    breakdown = StaticBreakdown(
        depth_cost=depth_cost(task_depth, config.max_depth),
        breadth_cost=breadth_cost(len(children), config.max_children),
        token_pressure=token_pressure(len(children), task_depth, max_steps_per_task),
    )
    penalty = (
        config.weights.depth * breakdown.depth_cost
        + config.weights.breadth * breakdown.breadth_cost
        + config.weights.token_pressure * breakdown.token_pressure
    )
    static_score = -penalty

    if static_score >= config.accept_bound:
        verdict = FilterVerdict.ACCEPT
    elif static_score <= config.reject_bound:
        verdict = FilterVerdict.REJECT
    else:
        verdict = FilterVerdict.UNCERTAIN

    reason = (
        f"static_score={static_score:.3f}; "
        f"depth_cost={breakdown.depth_cost:.3f}; "
        f"breadth_cost={breakdown.breadth_cost:.3f}; "
        f"token_pressure={breakdown.token_pressure:.3f}; "
    )
    return FilterResult(
        verdict=verdict,
        static_score=static_score,
        breakdown=breakdown,
        reason=reason,
    )


def critic_to_score(
    verdict: CriticVerdict,
    actual_children: int,
) -> float:
    score = 0.0
    if verdict.single_tool_possible:
        score -= 0.5
    score -= 0.35 * len(verdict.redundant_pairs)
    score += verdict.coverage_pct / 100.0
    excess = actual_children - verdict.min_children
    if excess > 0:
        score -= 0.1 * excess
    score += 0.3 if verdict.allow else -0.3
    return score


def combine(
    *,
    filter_result: FilterResult,
    critic_verdict: CriticVerdict,
    actual_children: int,
    config: GateConfig,
    threshold: float,
) -> GateDecision:
    critic_score = critic_to_score(critic_verdict, actual_children=actual_children)
    net_score = (
        config.static_weight * filter_result.static_score
        + config.critic_weight * critic_score
    )
    return GateDecision(
        net_score=net_score,
        threshold=threshold,
        rejected=net_score <= threshold,
        used_critic=True,
        reason=critic_verdict.reason or filter_result.reason,
        static_result=filter_result,
        critic_verdict=critic_verdict,
    )


class BackpropagationTracker:
    def __init__(self, initial_threshold: float, learning_rate: float) -> None:
        self._threshold = initial_threshold
        self._lr = learning_rate
        self._predictions: dict[str, DecompositionOutcome] = {}

    def current_threshold(self) -> float:
        return self._threshold

    def record_prediction(self, outcome: DecompositionOutcome) -> None:
        self._predictions[outcome.task_id] = outcome

    def has_prediction(self, task_id: str) -> bool:
        return task_id in self._predictions

    def observe_outcome(self, task_id: str, children: list[Task]) -> None:
        outcome = self._predictions.pop(task_id, None)
        if outcome is None:
            return

        total_children = len(children)
        if total_children <= 0:
            actual_efficiency = 0.0
        else:
            atomic_done_children = sum(
                1
                for child in children
                if isinstance(child, AtomicTask)
                and child.state is TaskState.DONE
                and child.step_count <= 2
            )
            actual_efficiency = atomic_done_children / total_children

        outcome.actual_efficiency = actual_efficiency
        predicted_signal = max(-0.5, min(outcome.predicted_score, 0.5))
        actual_signal = actual_efficiency - 0.5
        self._threshold = max(
            -0.5,
            min(
                self._threshold + self._lr * (predicted_signal - actual_signal),
                0.5,
            ),
        )
