from __future__ import annotations

from domain.query import QueryAnalysis
from valuator.core.agent.context_builder import build_task_context
from valuator.core.scheduler import Scheduler
from valuator.core.shared_state import SharedState
from valuator.core.task import ComplexTask
from valuator.core.types import TaskWorkPhase
from valuator.tools.base import ToolRegistry


def test_synthesize_phase_omits_shared_keys_duplicated_in_child_outputs() -> None:
    shared = SharedState()
    shared.publish("EntityA", {"x": 1}, "root.0", query_unit_ids=(0,))
    shared.publish("Extra", {"y": 2}, "root.1", query_unit_ids=(0,))

    scheduler = Scheduler(max_steps_per_task=10, concurrency=1)
    parent = ComplexTask(id="root", description="parent", query_unit_ids=[0])
    parent.work_phase = TaskWorkPhase.SYNTHESIZE
    parent.child_outputs = {
        "root.0": {
            "status": "facts_only",
            "facts": {"EntityA": {"x": 1}},
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

    assert "EntityA" not in ctx.shared.facts
    assert "Extra" in ctx.shared.facts
