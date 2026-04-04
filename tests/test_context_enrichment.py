"""Tests for tool request enrichment (temporal contract)."""

from domain.query import QueryUnit

from valuator.core.agent.context_builder import enrich_tool_request
from valuator.core.context import TaskContext
from valuator.core.shared_state import SharedStateView
from valuator.core.types import ToolRequest


def test_enrich_web_search_injects_temporal_contract() -> None:
    ctx = TaskContext(
        task_id="t",
        description="d",
        step_count=0,
        as_of_utc="2026-03-30T00:00:00Z",
        shared=SharedStateView({}, []),
        query_units=[
            QueryUnit(
                id="u0",
                objective="o",
                retrieval_query="q",
                time_scope="historical",
                target_start="2020-01-01",
                target_end="2023-12-31",
            )
        ],
    )
    req = enrich_tool_request(
        tool_request=ToolRequest(
            tool_name="web_search_tool",
            args={"query": "test"},
        ),
        ctx=ctx,
    )
    assert req.args["as_of_utc"] == "2026-03-30T00:00:00Z"
    assert req.args["time_scope"] == "historical"
    assert req.args["target_start"] == "2020-01-01"
    assert req.args["target_end"] == "2023-12-31"


# def test_enrich_domain_tool_synthesis_when_no_shared_facts() -> None:
#     ctx = TaskContext(
#         task_id="t",
#         description="d",
#         step_count=0,
#         as_of_utc="2026-03-30T00:00:00Z",
#         shared=SharedStateView({}, []),
#     )
#     req = enrich_tool_request(
#         tool_request=ToolRequest(
#             tool_name="domain_tool",
#             args={
#                 "query": "analyze",
#                 "company_name": "X",
#                 "grounding_mode": "grounded_required",
#             },
#         ),
#         ctx=ctx,
#     )
#     assert req.args["grounding_mode"] == "synthesis_only"
#
#
# def test_enrich_domain_tool_keeps_grounded_when_facts_provide_context() -> None:
#     ctx = TaskContext(
#         task_id="t",
#         description="d",
#         step_count=0,
#         as_of_utc="2026-03-30T00:00:00Z",
#         shared=SharedStateView(
#             facts={
#                 "seg": Fact(
#                     key="seg",
#                     value={"revenue": 100},
#                     source_task_id="s0",
#                     grounded=True,
#                 )
#             },
#             conflicts=[],
#         ),
#     )
#     req = enrich_tool_request(
#         tool_request=ToolRequest(
#             tool_name="domain_tool", args={"query": "analyze", "company_name": "X"}
#         ),
#         ctx=ctx,
#     )
#     assert req.args["grounding_mode"] == "grounded_required"
#     assert "[GROUNDING_FACTS]" in str(req.args.get("context", ""))
