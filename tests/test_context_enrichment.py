"""Tests for tool request enrichment (temporal contract)."""

from domain.query import QueryUnit

from valuator.core.agent.context_builder import enrich_tool_request
from valuator.core.context import TaskContext
from valuator.core.types import ToolRequest


def _ctx_with_unit(unit: QueryUnit) -> TaskContext:
    return TaskContext(
        task_id="t",
        description="d",
        step_count=0,
        as_of_kst="2026-03-30 09:00:00",
        query_units=[unit],
    )


def test_enrich_web_search_injects_temporal_contract() -> None:
    ctx = TaskContext(
        task_id="t",
        description="d",
        step_count=0,
        as_of_kst="2026-03-30 09:00:00",
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
    assert req.args["as_of_kst"] == "2026-03-30 09:00:00"
    assert req.args["time_scope"] == "historical"
    assert req.args["target_start"] == "2020-01-01"
    assert req.args["target_end"] == "2023-12-31"


def test_enrich_does_not_inject_year_range_for_financial_tools() -> None:
    """Financial tools take start_year/end_year directly from the LLM."""
    ctx = _ctx_with_unit(
        QueryUnit(
            id="u0",
            objective="o",
            retrieval_query="q",
            time_scope="historical",
            target_start="2020-01-01",
            target_end="2023-12-31",
        )
    )
    for tool_name, args in [
        ("opendart_financial_tool", {"corp": "삼성전자"}),
        ("yfinance_balance_sheet", {"ticker": "AMZN"}),
    ]:
        req = enrich_tool_request(
            tool_request=ToolRequest(tool_name=tool_name, args=args),
            ctx=ctx,
        )
        assert "year_range" not in req.args
        assert "start_year" not in req.args
        assert "end_year" not in req.args
        assert req.args == args
