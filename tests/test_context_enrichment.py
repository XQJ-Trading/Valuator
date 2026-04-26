"""Tests for tool request enrichment (temporal contract)."""

from domain.query import QueryUnit
from domain.time import YearRange

from valuator.core.agent.context_builder import enrich_tool_request
from valuator.core.context import TaskContext
from valuator.core.shared_state import SharedStateView
from valuator.core.types import ToolRequest


def _ctx_with_unit(unit: QueryUnit) -> TaskContext:
    return TaskContext(
        task_id="t",
        description="d",
        step_count=0,
        as_of_kst="2026-03-30 09:00:00",
        shared=SharedStateView({}, []),
        query_units=[unit],
    )


def test_enrich_web_search_injects_temporal_contract() -> None:
    ctx = TaskContext(
        task_id="t",
        description="d",
        step_count=0,
        as_of_kst="2026-03-30 09:00:00",
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
    assert req.args["as_of_kst"] == "2026-03-30 09:00:00"
    assert req.args["time_scope"] == "historical"
    assert req.args["target_start"] == "2020-01-01"
    assert req.args["target_end"] == "2023-12-31"
    assert "year_range" not in req.args


def test_enrich_opendart_injects_year_range() -> None:
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
    req = enrich_tool_request(
        tool_request=ToolRequest(
            tool_name="opendart_financial_tool",
            args={"corp": "삼성전자"},
        ),
        ctx=ctx,
    )
    assert req.args["year_range"] == YearRange(start=2020, end=2023)
    assert "target_start" not in req.args


def test_enrich_yfinance_injects_year_range() -> None:
    ctx = _ctx_with_unit(
        QueryUnit(
            id="u0",
            objective="o",
            retrieval_query="q",
            time_scope="historical",
            target_start="2024-01-01",
            target_end="2024-12-31",
        )
    )
    req = enrich_tool_request(
        tool_request=ToolRequest(
            tool_name="yfinance_balance_sheet",
            args={"ticker": "AMZN"},
        ),
        ctx=ctx,
    )
    assert req.args["year_range"] == YearRange(start=2024, end=2024)


def test_enrich_skips_when_no_temporal_contract() -> None:
    ctx = _ctx_with_unit(
        QueryUnit(id="u0", objective="o", retrieval_query="q")
    )
    req = enrich_tool_request(
        tool_request=ToolRequest(
            tool_name="opendart_financial_tool",
            args={"corp": "삼성전자"},
        ),
        ctx=ctx,
    )
    assert "year_range" not in req.args
