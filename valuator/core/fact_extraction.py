from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from .context import TaskContext
from .ontology import PROPERTY_KEY_BY_RESULT_KEY
from .task import Task

FINANCIAL_FACT_TOOL_NAMES: frozenset[str] = frozenset(
    {"opendart_financial_tool", "yfinance_balance_sheet"}
)
IGNORED_FINANCIAL_RESULT_KEYS: frozenset[str] = frozenset({"current_price"})


class FinancialResultRow(BaseModel):
    """One year of financial data returned by a financial tool."""

    model_config = ConfigDict(extra="allow")

    year: int
    corp_name: str | None = None
    identifier: str | None = Field(
        default=None, validation_alias=AliasChoices("corp", "ticker")
    )


class FinancialToolPayload(BaseModel):
    results: list[FinancialResultRow]


def extract_facts(*, task: Task, ctx: TaskContext) -> dict[str, Any]:
    tool_name = task.last_tool_request.tool_name if task.last_tool_request else ""
    if tool_name not in FINANCIAL_FACT_TOOL_NAMES:
        return {}

    facts: dict[str, Any] = {}
    for tool_result in task.tool_results:
        if not tool_result.success:
            continue

        payload = FinancialToolPayload.model_validate(tool_result.result)
        for row in sorted(payload.results, key=lambda r: r.year, reverse=True):
            subject = fact_subject(row=row, task=task, ctx=ctx)
            metrics = metric_values(row.model_extra or {})
            for property_key, value in metrics.items():
                facts[f"{subject}:{property_key}:{row.year}"] = value

    return facts


def metric_values(raw: dict[str, Any]) -> dict[str, Any]:
    """Return non-empty financial metrics keyed by ontology property keys.

    Tool result keys can be either standard property keys, such as ``revenue``,
    or source-specific aliases, such as ``total_revenue``. Standard keys win
    when both are present.
    """

    metrics: dict[str, Any] = {}
    alias_metric_values: list[tuple[str, Any]] = []

    for key, value in raw.items():
        result_key = key.strip()
        if result_key in IGNORED_FINANCIAL_RESULT_KEYS:
            continue
        if not _has_fact_value(value):
            continue
        property_key = PROPERTY_KEY_BY_RESULT_KEY.get(result_key)
        if property_key is None:
            continue
        if property_key == result_key:
            metrics[property_key] = value
        else:
            alias_metric_values.append((property_key, value))

    for property_key, value in alias_metric_values:
        if property_key not in metrics:
            metrics[property_key] = value
    return metrics


def _has_fact_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def fact_subject(
    *,
    row: FinancialResultRow,
    task: Task,
    ctx: TaskContext,
) -> str:
    name = (row.corp_name or "").strip()
    identifier = (row.identifier or "").strip()

    for subject in ctx.query_analysis.query_intent.subjects:
        company_name = subject.company.company_name
        listing = subject.listing
        candidates = {company_name}
        if listing is not None:
            candidates.add(listing.security_code)
            candidates.add(listing.yahoo_symbol)
            candidates.update(str(value) for value in listing.vendor_symbols.values())
        if name in candidates or identifier in candidates:
            return company_name

    return name or identifier or task.task_name or task.id
