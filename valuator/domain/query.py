"""Query contracts shared across the pipeline core."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import DomainModule

DomainId = str
TaskId = str

DEFAULT_GENERIC_TOOLS = [
    "web_search_tool",
    "sec_tool",
    "yfinance_balance_sheet",
    "code_execute_tool",
    "ceo_analysis_tool",
    "dcf_pipeline_tool",
    "balance_sheet_extraction_tool",
]

CONCRETE_SUBJECT_KINDS = frozenset(
    {
        "company",
        "issuer",
        "security",
        "stock",
        "ticker",
    }
)


def is_concrete_subject_kind(kind: str) -> bool:
    return kind.strip().lower() in CONCRETE_SUBJECT_KINDS


@dataclass(slots=True)
class QueryIntent:
    query: str
    ticker: str = ""
    market: str = ""
    security_code: str = ""
    company_names: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)

    @property
    def company_name(self) -> str:
        for candidate in self.company_names:
            text = candidate.strip()
            if text:
                return text
        return ""

    def concrete_values(self) -> list[str]:
        values: list[str] = []
        for candidate in [
            *self.company_names,
            *self.entities,
            self.ticker,
            self.security_code,
        ]:
            text = candidate.strip()
            if text and text not in values:
                values.append(text)
        return values


@dataclass(slots=True)
class QueryUnit:
    """One analysis step derived from the user query."""

    id: str
    objective: str
    retrieval_query: str
    domain_ids: list[DomainId] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    time_scope: str = ""


@dataclass(slots=True)
class QueryRequirement:
    id: str
    acceptance: str
    unit_ids: list[int] = field(default_factory=list)
    domain_ids: list[DomainId] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    provenance: str = ""
    required: bool = True


@dataclass(slots=True)
class QueryAnalysis:
    """Internal canonical query spec produced by boundary translation.

    Step = QueryUnit, entity = entries in ``entities``, relation = step-to-entity
    participation derived from ``QueryUnit.entity_ids``.
    """

    domain_ids: list[DomainId] = field(default_factory=list)
    query_intent: QueryIntent = field(default_factory=lambda: QueryIntent(query=""))
    entities: dict[str, str] = field(default_factory=dict)
    units: list[QueryUnit] = field(default_factory=list)
    requirements: list[QueryRequirement] = field(default_factory=list)
    intent_tags: list[str] = field(default_factory=list)
    primary_task_id: TaskId | None = None
    allowed_tools: list[str] = field(default_factory=list)
    rationale: str | None = None


@dataclass(slots=True)
class QueryStep:
    index: int
    id: str
    objective: str
    retrieval_query: str
    domain_ids: list[DomainId] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    time_scope: str = ""


@dataclass(slots=True)
class QueryEntity:
    id: str
    label: str


@dataclass(slots=True)
class QueryRelation:
    """Minimal relation model for final reporting: step -> entity participation."""

    step_index: int
    step_id: str
    entity_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class QueryBreakdown:
    steps: list[QueryStep] = field(default_factory=list)
    entities: list[QueryEntity] = field(default_factory=list)
    relations: list[QueryRelation] = field(default_factory=list)


def build_query_breakdown(analysis: QueryAnalysis) -> QueryBreakdown:
    steps = [
        QueryStep(
            index=index,
            id=unit.id,
            objective=unit.objective,
            retrieval_query=unit.retrieval_query,
            domain_ids=list(unit.domain_ids),
            entity_ids=list(unit.entity_ids),
            time_scope=unit.time_scope,
        )
        for index, unit in enumerate(analysis.units)
    ]
    entities = [
        QueryEntity(id=entity_id, label=label)
        for entity_id, label in analysis.entities.items()
    ]
    relations = [
        QueryRelation(
            step_index=index,
            step_id=unit.id,
            entity_ids=list(unit.entity_ids),
        )
        for index, unit in enumerate(analysis.units)
    ]
    return QueryBreakdown(
        steps=steps,
        entities=entities,
        relations=relations,
    )


def fill_routing_defaults(
    analysis: QueryAnalysis,
    modules: dict[str, DomainModule],
) -> QueryAnalysis:
    """Fill allowed_tools from domain modules when empty."""
    if not analysis.domain_ids:
        analysis.allowed_tools = list(DEFAULT_GENERIC_TOOLS)
        return analysis

    if analysis.allowed_tools:
        return analysis

    tool_ids: set[str] = set()
    for domain_id in analysis.domain_ids:
        module = modules.get(domain_id)
        if module is not None:
            tool_ids.update(module.tools)
    analysis.allowed_tools = sorted(tool_ids) if tool_ids else list(DEFAULT_GENERIC_TOOLS)
    return analysis
