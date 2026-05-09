from __future__ import annotations

from typing import Any

from domain.company import Company, Listing, Subject
from domain.query import QueryAnalysis, QueryIntent
from valuator.core.context import TaskContext
from valuator.core.fact_extraction import extract_facts
from valuator.core.task import AtomicTask
from valuator.core.types import ToolRequest, ToolResult


def _facts_for_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    task = AtomicTask(
        id="root.0",
        description="collect official financials",
        task_name="collect_financials",
        tool_hint="opendart_financial_tool",
    )
    task.last_tool_request = ToolRequest(
        tool_name="opendart_financial_tool",
        args={"corp": "079550", "start_year": 2024, "end_year": 2025},
    )
    task.tool_results.append(
        ToolResult(
            success=True,
            result={
                "corp": "079550",
                "results": results,
            },
            metadata={"source": "opendart"},
        )
    )

    return extract_facts(
        task=task,
        ctx=_ctx(task),
    )


def _ctx(task: AtomicTask) -> TaskContext:
    subject = Subject(
        company=Company(company_id="KRX:079550", company_name="LIG넥스원", aliases=()),
        listing=Listing(
            listing_id="KRX:079550",
            company_id="KRX:079550",
            security_code="079550",
            exchange="KOSPI",
            vendor_symbols={"yahoo": "079550.KS"},
        ),
    )
    return TaskContext(
        task_id=task.id,
        description=task.description,
        step_count=1,
        query_analysis=QueryAnalysis(
            query_intent=QueryIntent(query="LIG넥스원 분석", subjects=(subject,))
        ),
    )


def test_extract_facts_adds_metrics() -> None:
    facts = _facts_for_results(
        [
            {
                "corp": "079550",
                "corp_name": "LIG넥스원",
                "year": 2024,
                "total_revenue": 3276339508425,
                "eps": 10173,
                "per": 92.5,
            },
            {
                "corp": "079550",
                "corp_name": "LIG넥스원",
                "year": 2025,
                "total_revenue": 4306936127418,
                "current_price": 941000,
                "stock_price": 930000,
                "eps": 11604,
                "per": 81.09,
            },
        ]
    )

    assert facts["LIG넥스원:per:2025"] == 81.09
    assert facts["LIG넥스원:per:2024"] == 92.5
    assert facts["LIG넥스원:eps:2025"] == 11604
    assert facts["LIG넥스원:revenue:2025"] == 4306936127418
    assert facts["LIG넥스원:revenue:2024"] == 3276339508425
    assert facts["LIG넥스원:stock_price:2025"] == 930000
    assert "LIG넥스원:total_revenue:2025" not in facts
    assert "LIG넥스원:current_price:2025" not in facts


def test_extract_facts_skips_current_price() -> None:
    facts = _facts_for_results(
        [
            {
                "corp": "079550",
                "corp_name": "LIG넥스원",
                "year": 2025,
                "current_price": 941000,
                "eps": 11604,
            },
        ]
    )

    assert "LIG넥스원:stock_price:2025" not in facts
    assert "LIG넥스원:current_price:2025" not in facts


def test_extract_facts_prefers_property_key() -> None:
    facts = _facts_for_results(
        [
            {
                "corp": "079550",
                "corp_name": "LIG넥스원",
                "year": 2025,
                "total_revenue": 1,
                "revenue": 2,
            },
        ]
    )

    assert facts["LIG넥스원:revenue:2025"] == 2
