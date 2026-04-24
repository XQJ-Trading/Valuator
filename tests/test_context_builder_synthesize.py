"""Context builder synthesize tests — fact-layer filtering removed.

After removing the fact layer, SharedState.view_for() always returns an
empty view.  The test verifies that build_task_context still succeeds
in SYNTHESIZE phase and returns an empty shared view.
"""

from __future__ import annotations

from domain.query import QueryAnalysis
from valuator.core.agent.context_builder import build_task_context
from valuator.core.scheduler import Scheduler
from valuator.core.shared_state import SharedState
from valuator.core.task import ComplexTask
from valuator.core.types import TaskWorkPhase
from valuator.tools.base import ToolRegistry


def test_synthesize_phase_returns_empty_shared_view() -> None:
    shared = SharedState()
    scheduler = Scheduler(max_steps_per_task=10, concurrency=1)
    parent = ComplexTask(id="root", description="parent", query_unit_ids=[0])
    parent.work_phase = TaskWorkPhase.SYNTHESIZE
    parent.child_outputs = {
        "root.0": {
            "status": "facts_only",
            "facts": {"entity_a": {"x": 1}},
        }
    }
    scheduler.register(parent)

    ctx = build_task_context(
        task=parent,
        query="q",
        scheduler=scheduler,
        analysis=QueryAnalysis(allowed_tools=["web_search_tool"]),
        shared=shared,
        tools=ToolRegistry(),
    )

    assert ctx.shared.facts == {}
    assert ctx.child_outputs == parent.child_outputs
