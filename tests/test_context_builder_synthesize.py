from __future__ import annotations

from domain.query import QueryAnalysis
from valuator.core.agent.context_builder import build_task_context
from valuator.core.ontology import FactAddress, NumericValue
from valuator.core.scheduler import Scheduler
from valuator.core.shared_state import Fact, SharedState
from valuator.core.task import ComplexTask
from valuator.core.types import TaskWorkPhase
from valuator.tools.base import ToolRegistry


def _fact(key: str, value: float, source: str, *, query_unit_ids: tuple[int, ...] = ()) -> Fact:
    addr = FactAddress(node_type="Observation", subject="test", property_key=key)
    return Fact(
        address=addr,
        value=NumericValue(amount=value),
        source_task_id=source,
        query_unit_ids=query_unit_ids,
    )


def test_synthesize_phase_omits_shared_keys_duplicated_in_child_outputs() -> None:
    shared = SharedState()
    entity_a = _fact("entity_a", 1, "root.0", query_unit_ids=(0,))
    extra = _fact("extra", 2, "root.1", query_unit_ids=(0,))
    shared.publish(entity_a)
    shared.publish(extra)

    scheduler = Scheduler(max_steps_per_task=10, concurrency=1)
    parent = ComplexTask(id="root", description="parent", query_unit_ids=[0])
    parent.work_phase = TaskWorkPhase.SYNTHESIZE
    parent.child_outputs = {
        "root.0": {
            "status": "facts_only",
            "facts": {entity_a.key: {"x": 1}},
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

    assert entity_a.key not in ctx.shared.facts
    assert extra.key in ctx.shared.facts
