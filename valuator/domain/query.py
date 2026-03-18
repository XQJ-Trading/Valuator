"""Query contracts shared across the pipeline core."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .company import Company

if TYPE_CHECKING:
    from .types import DomainModule

DomainId = str
TaskId = str

DEFAULT_GENERIC_TOOLS = [
    "web_search_tool",
    "sec_tool",
    "yfinance_balance_sheet",
    "code_execute_tool",
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
    company: Company | None = None
    entities: list[str] = field(default_factory=list)

    def concrete_values(self) -> list[str]:
        values: list[str] = []
        candidates: list[str] = list(self.entities)
        if self.company is not None:
            candidates.append(self.company.issuer_name)
            candidates.append(self.company.security_code)
            candidates.extend(self.company.vendor_symbols.values())
        for candidate in candidates:
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
    parent_unit_id: str = ""


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
    parent_unit_id: str = ""


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
            parent_unit_id=unit.parent_unit_id,
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
    _modules: dict[str, DomainModule],
) -> QueryAnalysis:
    """Fill allowed_tools when the query analysis omitted them."""
    if not analysis.domain_ids:
        analysis.allowed_tools = list(DEFAULT_GENERIC_TOOLS)
        return analysis

    if analysis.allowed_tools:
        return analysis

    analysis.allowed_tools = sorted(
        {
            "code_execute_tool",
            "domain_tool",
            "sec_tool",
            "web_search_tool",
            "yfinance_balance_sheet",
        }
    )
    return analysis
