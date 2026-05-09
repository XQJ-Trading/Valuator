"""Query contracts shared across the pipeline core."""

from __future__ import annotations

from dataclasses import dataclass, field

from .company import Subject
from .time import YearRange, year_range_from_iso_dates

TaskId = str

_COMMON_TOOLS = {"code_execute_tool", "web_search_tool"}
_KRX_TOOLS = {"opendart_financial_tool"}
_USA_TOOLS = {"sec_tool", "yfinance_balance_sheet"}
_ALL_MARKET_TOOLS = _COMMON_TOOLS | _KRX_TOOLS | _USA_TOOLS

DEFAULT_GENERIC_TOOLS = sorted(_ALL_MARKET_TOOLS)

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
class TemporalContract:
    as_of_kst: str = ""
    time_scope: str = ""
    target_start: str = ""
    target_end: str = ""
    year_range: YearRange | None = None


@dataclass(slots=True)
class QueryIntent:
    query: str
    subjects: tuple[Subject, ...] = field(default_factory=tuple)
    entities: tuple[str, ...] = field(default_factory=tuple)

    def concrete_values(self) -> list[str]:
        values: list[str] = []
        candidates: list[str] = list(self.entities)
        for subject in self.subjects:
            candidates.append(subject.company.company_name)
            if subject.listing is None:
                continue
            candidates.append(subject.listing.security_code)
            candidates.extend(subject.listing.vendor_symbols.values())
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
    entity_ids: list[str] = field(default_factory=list)
    time_scope: str = ""
    target_start: str = ""
    target_end: str = ""
    parent_unit_id: str = ""


@dataclass(slots=True)
class QueryRequirement:
    id: str
    acceptance: str
    unit_ids: list[int] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    provenance: str = ""
    required: bool = True


@dataclass(slots=True)
class QueryAnalysis:
    """Internal canonical query spec produced by boundary translation.

    Step = QueryUnit, entity = entries in ``entities``, relation = step-to-entity
    participation derived from ``QueryUnit.entity_ids``.
    """

    as_of_kst: str = ""
    query_intent: QueryIntent = field(default_factory=lambda: QueryIntent(query=""))
    entities: dict[str, str] = field(default_factory=dict)
    entity_kinds: dict[str, str] = field(default_factory=dict)
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
    entity_ids: list[str] = field(default_factory=list)
    time_scope: str = ""
    target_start: str = ""
    target_end: str = ""
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
            entity_ids=list(unit.entity_ids),
            time_scope=unit.time_scope,
            target_start=unit.target_start,
            target_end=unit.target_end,
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


def summarize_temporal_contract(
    *,
    as_of_kst: str,
    units: list[QueryUnit],
) -> TemporalContract:
    if not units:
        return TemporalContract(as_of_kst=as_of_kst)

    scopes = list(dict.fromkeys(unit.time_scope for unit in units if unit.time_scope))
    starts = list(
        dict.fromkeys(unit.target_start for unit in units if unit.target_start)
    )
    ends = list(dict.fromkeys(unit.target_end for unit in units if unit.target_end))

    time_scope = scopes[0] if len(scopes) == 1 else "mixed" if scopes else ""
    if len(scopes) == 1:
        target_start = starts[0] if len(starts) == 1 else ""
        target_end = ends[0] if len(ends) == 1 else ""
    else:
        target_start = ""
        target_end = ""

    return TemporalContract(
        as_of_kst=as_of_kst,
        time_scope=time_scope,
        target_start=target_start,
        target_end=target_end,
        year_range=year_range_from_iso_dates(target_start, target_end),
    )


def fill_routing_defaults(analysis: QueryAnalysis) -> QueryAnalysis:
    """Fill allowed_tools when the query analysis omitted them."""
    if analysis.allowed_tools:
        return analysis

    analysis.allowed_tools = sorted(_tools_for_subjects(analysis.query_intent.subjects))
    return analysis


def _tools_for_subjects(subjects: tuple[Subject, ...]) -> set[str]:
    markets: set[str] = set()
    for subject in subjects:
        if subject.listing is not None:
            markets.add(subject.listing.market)

    if not markets:
        return set(_ALL_MARKET_TOOLS)

    tools = set(_COMMON_TOOLS)
    if "KRX" in markets:
        tools |= _KRX_TOOLS
    if markets - {"KRX"}:
        tools |= _USA_TOOLS
    return tools
