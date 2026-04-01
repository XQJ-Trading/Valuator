"""Tests for tool request enrichment (temporal contract, domain grounding)."""

from valuator.core.agent.context_builder import enrich_tool_request
from valuator.core.context import TaskContext
from valuator.core.shared_state import Fact, SharedStateView
from valuator.core.types import ToolRequest


def test_enrich_domain_tool_synthesis_when_no_shared_facts() -> None:
    ctx = TaskContext(
        task_id="t",
        description="d",
        step_count=0,
        as_of_utc="2026-03-30T00:00:00Z",
        shared=SharedStateView({}, []),
    )
    req = enrich_tool_request(
        tool_request=ToolRequest(
            tool_name="domain_tool",
            args={
                "query": "analyze",
                "company_name": "X",
                "grounding_mode": "grounded_required",
            },
        ),
        ctx=ctx,
    )
    assert req.args["grounding_mode"] == "synthesis_only"


def test_enrich_domain_tool_keeps_grounded_when_facts_provide_context() -> None:
    ctx = TaskContext(
        task_id="t",
        description="d",
        step_count=0,
        as_of_utc="2026-03-30T00:00:00Z",
        shared=SharedStateView(
            facts={
                "seg": Fact(
                    key="seg",
                    value={"revenue": 100},
                    source_task_id="s0",
                    grounded=True,
                )
            },
            conflicts=[],
        ),
    )
    req = enrich_tool_request(
        tool_request=ToolRequest(
            tool_name="domain_tool",
            args={"query": "analyze", "company_name": "X"},
        ),
        ctx=ctx,
    )
    assert req.args["grounding_mode"] == "grounded_required"
    assert "[GROUNDING_FACTS]" in str(req.args.get("context", ""))
