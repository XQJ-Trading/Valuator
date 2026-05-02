from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from .context import TaskContext
from .ontology import PROPERTY_KEY_BY_RESULT_KEY
from .task import Task
from .types import Action, TaskDecision

_FINANCIAL_TOOL_NAMES: frozenset[str] = frozenset(
    {"opendart_financial_tool", "yfinance_balance_sheet"}
)


class _PeriodRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    year: int
    corp_name: str | None = None
    identifier: str | None = Field(
        default=None, validation_alias=AliasChoices("corp", "ticker")
    )

    def metrics(self) -> dict[str, Any]:
        return _known_metrics(self.__pydantic_extra__ or {})


class _FinancialPayload(BaseModel):
    results: list[_PeriodRow]


def _known_metrics(raw: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    input_key_values: list[tuple[str, Any]] = []

    for key, value in raw.items():
        if not _has_fact_value(value):
            continue
        property_key = PROPERTY_KEY_BY_RESULT_KEY.get(key.strip())
        if property_key is None:
            continue
        if property_key == key.strip():
            metrics[property_key] = value
        else:
            input_key_values.append((property_key, value))

    for property_key, value in input_key_values:
        if property_key not in metrics:
            metrics[property_key] = value
    return metrics


def _has_fact_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def augment_decision_with_official_facts(
    *,
    task: Task,
    decision: TaskDecision,
    ctx: TaskContext,
) -> TaskDecision:
    if decision.action is not Action.AGGREGATE:
        return decision

    official_facts = official_financial_facts(task=task, ctx=ctx)
    if not official_facts:
        return decision

    merged = dict(decision.facts)
    merged.update(official_facts)
    return TaskDecision(
        action=decision.action,
        children=decision.children,
        tool_request=decision.tool_request,
        wait_for=decision.wait_for,
        output=decision.output,
        facts=merged,
    )


def official_financial_facts(*, task: Task, ctx: TaskContext) -> dict[str, Any]:
    tool_name = task.last_tool_request.tool_name if task.last_tool_request else ""
    if tool_name not in _FINANCIAL_TOOL_NAMES:
        return {}

    facts: dict[str, Any] = {}
    for tool_result in task.tool_results:
        if not tool_result.success:
            continue
        payload = _FinancialPayload.model_validate(tool_result.result)
        for row in sorted(payload.results, key=lambda r: r.year, reverse=True):
            subject = _subject_label(row=row, task=task, ctx=ctx)
            for key, value in row.metrics().items():
                facts[f"{subject}:{key}:{row.year}"] = value
    return facts


def _subject_label(*, row: _PeriodRow, task: Task, ctx: TaskContext) -> str:
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
