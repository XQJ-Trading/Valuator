from __future__ import annotations

from typing import Any

from domain.company import Company, Listing, Subject
from domain.query import QueryAnalysis, QueryIntent
from valuator.core.context import TaskContext
from valuator.core.fact_extraction import augment_decision_with_official_facts
from valuator.core.task import AtomicTask
from valuator.core.types import Action, TaskDecision, ToolRequest, ToolResult


def _decision_for_results(results: list[dict[str, Any]]) -> TaskDecision:
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

    return augment_decision_with_official_facts(
        task=task,
        decision=TaskDecision(action=Action.AGGREGATE),
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


def test_augment_decision_promotes_official_financial_per_facts() -> None:
    decision = _decision_for_results(
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

    assert decision.facts["LIG넥스원:per:2025"] == 81.09
    assert decision.facts["LIG넥스원:per:2024"] == 92.5
    assert decision.facts["LIG넥스원:eps:2025"] == 11604
    assert decision.facts["LIG넥스원:revenue:2025"] == 4306936127418
    assert decision.facts["LIG넥스원:revenue:2024"] == 3276339508425
    assert decision.facts["LIG넥스원:stock_price:2025"] == 930000
    assert "LIG넥스원:total_revenue:2025" not in decision.facts
    assert "LIG넥스원:current_price:2025" not in decision.facts


def test_augment_decision_does_not_promote_current_price_as_annual_stock_price() -> None:
    decision = _decision_for_results(
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

    assert "LIG넥스원:stock_price:2025" not in decision.facts
    assert "LIG넥스원:current_price:2025" not in decision.facts


def test_official_financial_facts_prefers_property_key_over_input_key() -> None:
    decision = _decision_for_results(
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

    assert decision.facts["LIG넥스원:revenue:2025"] == 2
