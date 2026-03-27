from __future__ import annotations

import pytest

from valuator.core.decomposition_gate import (
    BackpropagationTracker,
    breadth_cost,
    combine,
    critic_to_score,
    depth_cost,
    pre_filter,
    token_pressure,
    tool_resolvability,
)
from valuator.core.decomposition_types import CriticVerdict, DecompositionOutcome, FilterVerdict, GateConfig
from valuator.core.task import AtomicTask, ComplexTask
from valuator.core.types import TaskSpec, TaskState


def test_depth_cost_matches_spec_curve() -> None:
    assert depth_cost(0, 4) == pytest.approx(0.0)
    assert depth_cost(1, 4) == pytest.approx(0.0625)
    assert depth_cost(2, 4) == pytest.approx(0.25)
    assert depth_cost(3, 4) == pytest.approx(0.5625)
    assert depth_cost(4, 4) == pytest.approx(1.0)


def test_breadth_cost_matches_spec_curve() -> None:
    assert breadth_cost(2, 8) == pytest.approx(1.0 / 3.0)
    assert breadth_cost(3, 8) == pytest.approx(0.5283208336)
    assert breadth_cost(5, 8) == pytest.approx(0.7739760316)
    assert breadth_cost(8, 8) == pytest.approx(1.0)


def test_tool_resolvability_uses_available_tools_only() -> None:
    children = [
        TaskSpec(description="collect alpha", tool_hint="dummy_tool"),
        TaskSpec(description="collect beta", tool_hint="other_tool"),
        TaskSpec(description="collect gamma"),
    ]

    score = tool_resolvability(children, frozenset({"dummy_tool"}))

    assert score == pytest.approx(1.0 / 3.0)


def test_token_pressure_matches_budget_formula() -> None:
    pressure = token_pressure(child_count=3, depth=1, max_steps_per_task=30)

    assert pressure == pytest.approx(0.2)


def test_pre_filter_returns_accept_with_custom_accept_bound() -> None:
    result = pre_filter(
        task_depth=0,
        children=[TaskSpec(description="collect alpha", tool_hint="dummy_tool")],
        executable_tools=frozenset({"dummy_tool"}),
        max_steps_per_task=30,
        config=GateConfig(accept_bound=0.2),
    )

    assert result.verdict is FilterVerdict.ACCEPT
    assert result.static_score == pytest.approx(0.2933333333)


def test_pre_filter_returns_reject_with_unresolvable_children() -> None:
    result = pre_filter(
        task_depth=0,
        children=[
            TaskSpec(description="alpha"),
            TaskSpec(description="beta"),
        ],
        executable_tools=frozenset(),
        max_steps_per_task=10,
        config=GateConfig(reject_bound=-0.05),
    )

    assert result.verdict is FilterVerdict.REJECT
    assert result.static_score == pytest.approx(-0.1066666667)


def test_pre_filter_returns_uncertain_in_gray_zone() -> None:
    result = pre_filter(
        task_depth=0,
        children=[TaskSpec(description="collect alpha", tool_hint="dummy_tool")],
        executable_tools=frozenset({"dummy_tool"}),
        max_steps_per_task=10,
        config=GateConfig(accept_bound=0.5, reject_bound=-0.05),
    )

    assert result.verdict is FilterVerdict.UNCERTAIN
    assert result.static_score == pytest.approx(0.28)


def test_critic_to_score_matches_spec_formula() -> None:
    score = critic_to_score(
        CriticVerdict(
            allow=False,
            single_tool_possible=True,
            redundant_pairs=[(0, 1)],
            coverage_pct=80,
            min_children=1,
            reason="single tool is enough",
        ),
        actual_children=3,
    )

    assert score == pytest.approx(-0.4)


def test_combine_uses_weighted_static_and_critic_scores() -> None:
    filter_result = pre_filter(
        task_depth=0,
        children=[TaskSpec(description="collect alpha", tool_hint="dummy_tool")],
        executable_tools=frozenset({"dummy_tool"}),
        max_steps_per_task=10,
        config=GateConfig(accept_bound=0.5, reject_bound=-0.05),
    )
    verdict = CriticVerdict(
        allow=True,
        single_tool_possible=False,
        redundant_pairs=[],
        coverage_pct=0,
        min_children=1,
        reason="acceptable split",
    )

    decision = combine(
        filter_result=filter_result,
        critic_verdict=verdict,
        actual_children=1,
        config=GateConfig(),
        threshold=0.0,
    )

    assert decision.net_score == pytest.approx(0.292)
    assert decision.rejected is False
    assert decision.used_critic is True


def test_backpropagation_tracker_updates_threshold_from_observed_efficiency() -> None:
    tracker = BackpropagationTracker(initial_threshold=0.0, learning_rate=0.1)
    tracker.record_prediction(
        DecompositionOutcome(
            task_id="root",
            predicted_score=0.3,
            child_count=2,
            depth=0,
            used_critic=True,
        )
    )

    atomic = AtomicTask(id="root.0", description="collect alpha")
    atomic.state = TaskState.DONE
    atomic.step_count = 2
    promoted = ComplexTask(id="root.1", description="re-decomposed child")
    promoted.state = TaskState.DONE
    promoted.step_count = 3

    tracker.observe_outcome("root", [atomic, promoted])

    assert tracker.current_threshold() == pytest.approx(0.03)
    assert tracker.has_prediction("root") is False
