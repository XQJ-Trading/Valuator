"""LLM-based query analysis for domain module selection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Iterable, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from valuator.utils.config import config
from .boundary.types import ListingSeed
from .boundary.query_temporal import normalize_target_date_token
from .company import resolve_subjects, resolve_surfaces
from .query import (
    QueryAnalysis,
    QueryIntent,
    QueryRequirement,
    QueryUnit,
    is_concrete_subject_kind,
)
from .types import DomainIndex, DomainModule

if TYPE_CHECKING:
    from valuator.models.gemini_direct import GeminiClient

_SYSTEM_PROMPT = (
    "Return concise JSON only. No markdown. "
    "Do not include any keys except the requested schema."
)
_QUERY_ANALYSIS_RULES = (
    "- Return query_intent, domain_ids, entities, units, requirements, intent_tags, rationale.",
    "- query_intent must contain company_names and tickers. company_names: concrete company/security names or aliases. For Korean-listed companies, use the Korean name as commonly known (for example, '삼성전자', '현대모비스'). For overseas issuers, use the official English company name. tickers: stock ticker symbols for every company mentioned (for example, 'NOW' for ServiceNow, '005930' for 삼성전자). Always populate tickers when the company is identifiable. If no concrete subject is named, use empty arrays for both.",
    "- entities are for non-security items such as business units, products, CEOs, themes, or macro variables. Use entity kind `company`/`ticker`/`security` only for concrete issuers or securities explicitly present or clearly recoverable.",
    "- units must be semantic retrieval units, not formatting instructions.",
    "- Every unit must include id, objective, retrieval_query, domain_ids, entity_ids, time_scope.",
    "- Every requirement must include acceptance, unit_ids, domain_ids, entity_ids, provenance. Requirements are for analytical content only, not formatting preferences or table styles.",
    "- requirement unit_ids may refer to units by zero-based position, one-based position, or unit id string.",
    "- Preserve the user's response intent and constraints, such as recommendation, screening, comparison, requested market, count, style lens, and actionability, instead of rewriting the query into a generic valuation essay.",
    "- If the query does not name a concrete company/security, do not invent placeholder company entities such as 'investment candidates'.",
    "- If the query is valuation/investment-related, prefer selecting all relevant modules rather than omitting needed domains.",
    "- For valuation or investment-related queries, shape requirements so the downstream report can be trading- and investment-first: include acceptance criteria that imply decision framing, market price vs thesis where data allows, relative multiples (vs peers or history), bull/base/bear (or equivalent) scenarios, and quantitative entry/exit or re-evaluation triggers. Do not emit a DCF-only or intrinsic-value-only requirement set unless the user explicitly restricts the task to DCF or intrinsic value alone.",
    "- When a requirement calls for intrinsic value or DCF, add complementary requirements for relative multiples and scenario differentiation unless the user explicitly forbids one of them.",
)


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _dedupe_ints(values: list[int]) -> list[int]:
    return list(dict.fromkeys(values))


def _validated_domain_ids(
    raw_domain_ids: list[str],
    *,
    valid_domain_ids: set[str],
) -> list[str]:
    domain_ids = _dedupe_strings(raw_domain_ids)
    if not domain_ids:
        raise ValueError("query analysis returned no valid domain_ids")
    unknown_domains = sorted(set(domain_ids) - valid_domain_ids)
    if unknown_domains:
        raise ValueError(
            "query analysis returned unknown domain_ids: " + ", ".join(unknown_domains)
        )
    return domain_ids


def _intent_entities(raw_entities: list[QueryEntityPayload]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            item.label
            for item in raw_entities
            if not is_concrete_subject_kind(item.kind)
        )
    )


def _build_query_intent(
    raw_intent: QueryIntentPayload,
    *,
    query: str,
    raw_entities: list[QueryEntityPayload],
    on_miss: Callable[[str], Iterable[ListingSeed]] | None = None,
) -> QueryIntent:
    company_names = _dedupe_strings([*raw_intent.tickers, *raw_intent.company_names])
    return QueryIntent(
        query=query,
        subjects=resolve_subjects(
            company_names=tuple(company_names),
            on_miss=on_miss,
        ),
        entities=_intent_entities(raw_entities),
    )


def _build_entities(raw_entities: list[QueryEntityPayload]) -> dict[str, str]:
    entities: dict[str, str] = {}
    for item in raw_entities:
        if item.id in entities:
            raise ValueError(f"duplicate query entity id: {item.id}")
        entities[item.id] = item.label
    return entities


def _build_units(
    raw_units: list[QueryUnitPayload],
    *,
    entity_id_set: set[str],
    domain_id_set: set[str],
) -> tuple[list[QueryUnit], dict[str, int]]:
    units: list[QueryUnit] = []
    unit_id_to_index: dict[str, int] = {}
    for item in raw_units:
        if item.id in unit_id_to_index:
            raise ValueError(f"duplicate query unit id: {item.id}")

        unit_domains = _dedupe_strings(item.domain_ids)
        if not unit_domains:
            raise ValueError(f"query unit missing domain_ids: {item.id}")
        if set(unit_domains) - domain_id_set:
            raise ValueError(f"query unit references unknown domain_ids: {item.id}")

        unit_id_to_index[item.id] = len(units)
        units.append(
            QueryUnit(
                id=item.id,
                objective=item.objective,
                retrieval_query=item.retrieval_query,
                domain_ids=unit_domains,
                entity_ids=_dedupe_strings(
                    [
                        entity_id
                        for entity_id in item.entity_ids
                        if entity_id in entity_id_set
                    ]
                ),
                time_scope=item.time_scope,
                target_start=item.target_start,
                target_end=item.target_end,
                parent_unit_id=item.parent_unit_id,
            )
        )
    return units, unit_id_to_index


def _resolve_requirement_unit_ids(
    raw_unit_ids: list[Union[int, str]],
    *,
    unit_id_to_index: dict[str, int],
    unit_count: int,
) -> list[int]:
    resolved_unit_ids: list[int] = []
    for raw_ref in raw_unit_ids:
        if isinstance(raw_ref, int):
            resolved_unit_ids.append(raw_ref)
            continue
        if raw_ref in unit_id_to_index:
            resolved_unit_ids.append(unit_id_to_index[raw_ref])
            continue
        if raw_ref.isdigit():
            resolved_unit_ids.append(int(raw_ref))
            continue
        raise ValueError("query requirement references unknown unit_ids")

    uses_one_based = (
        all(1 <= unit_id <= unit_count for unit_id in resolved_unit_ids)
        and 0 not in resolved_unit_ids
    )
    if uses_one_based:
        resolved_unit_ids = [unit_id - 1 for unit_id in resolved_unit_ids]
    if any(unit_id < 0 or unit_id >= unit_count for unit_id in resolved_unit_ids):
        raise ValueError("query requirement references unknown unit_ids")
    return _dedupe_ints(resolved_unit_ids)


def _build_requirements(
    raw_requirements: list[QueryRequirementPayload],
    *,
    entity_id_set: set[str],
    domain_id_set: set[str],
    unit_id_to_index: dict[str, int],
    unit_count: int,
) -> list[QueryRequirement]:
    requirements: list[QueryRequirement] = []
    seen_requirement_ids: set[str] = set()
    for index, item in enumerate(raw_requirements, start=1):
        requirement_id = item.id or f"R-{index:03d}"
        if requirement_id in seen_requirement_ids:
            raise ValueError(f"duplicate query requirement id: {requirement_id}")
        seen_requirement_ids.add(requirement_id)

        requirement_domains = _dedupe_strings(item.domain_ids)
        if not requirement_domains:
            raise ValueError("query requirement missing domain_ids")
        if set(requirement_domains) - domain_id_set:
            raise ValueError("query requirement references unknown domain_ids")

        requirements.append(
            QueryRequirement(
                id=requirement_id,
                acceptance=item.acceptance,
                unit_ids=_resolve_requirement_unit_ids(
                    item.unit_ids,
                    unit_id_to_index=unit_id_to_index,
                    unit_count=unit_count,
                ),
                domain_ids=requirement_domains,
                entity_ids=_dedupe_strings(
                    [
                        entity_id
                        for entity_id in item.entity_ids
                        if entity_id in entity_id_set
                    ]
                ),
                provenance=item.provenance,
            )
        )
    return requirements


def _module_summaries(
    index: DomainIndex,
    modules: dict[str, DomainModule],
) -> dict[str, str]:
    summaries = dict(index.module_summaries)
    for module_id in index.modules:
        if module_id in summaries or module_id not in modules:
            continue
        summaries[module_id] = modules[module_id].description or module_id
    return summaries


def _analysis_prompt(
    *,
    index: DomainIndex,
    modules: dict[str, DomainModule],
    query: str,
) -> str:
    scope = (
        index.valuation_scope.strip()
        or "Apply all modules for valuation-related queries."
    )
    exclusion = index.exclusion_signals.strip() or "None."
    selective = index.selective_signals.strip() or "None."
    summaries = _module_summaries(index, modules)
    module_lines = "\n".join(
        f"  - {module_id}: {summaries.get(module_id, module_id)}"
        for module_id in index.modules
    )
    rules = "\n".join(_QUERY_ANALYSIS_RULES)
    return (
        "Analyze the user query into a canonical specification for downstream agent steps "
        "(evidence gathering, valuation, and trading/investment synthesis).\n\n"
        "[VALUATION_SCOPE]\n"
        f"{scope}\n\n"
        "[EXCLUSION_SIGNALS]\n"
        f"{exclusion}\n\n"
        "[SELECTIVE_SIGNALS]\n"
        f"{selective}\n\n"
        "[AVAILABLE_MODULES]\n"
        f"{module_lines}\n\n"
        "Rules:\n"
        f"{rules}\n\n"
        f"[QUERY]\n{query}\n"
    )


def _response_schema(module_ids: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "query_intent",
            "domain_ids",
            "entities",
            "units",
            "requirements",
            "intent_tags",
            "rationale",
        ],
        "properties": {
            "query_intent": {
                "type": "object",
                "additionalProperties": False,
                "required": ["company_names", "tickers"],
                "properties": {
                    "company_names": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
            "domain_ids": {
                "type": "array",
                "items": {"type": "string", "enum": module_ids},
            },
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "label", "kind"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "label": {"type": "string", "minLength": 1},
                        "kind": {"type": "string", "minLength": 1},
                    },
                },
            },
            "units": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "id",
                        "objective",
                        "retrieval_query",
                        "domain_ids",
                        "entity_ids",
                        "time_scope",
                    ],
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "objective": {"type": "string", "minLength": 1},
                        "retrieval_query": {"type": "string", "minLength": 1},
                        "domain_ids": {
                            "type": "array",
                            "items": {"type": "string", "enum": module_ids},
                            "minItems": 1,
                        },
                        "entity_ids": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                        },
                        "time_scope": {"type": "string"},
                        "target_start": {"type": "string"},
                        "target_end": {"type": "string"},
                        "parent_unit_id": {"type": "string"},
                    },
                },
            },
            "requirements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "acceptance",
                        "unit_ids",
                        "domain_ids",
                        "entity_ids",
                        "provenance",
                    ],
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "acceptance": {"type": "string", "minLength": 1},
                        "unit_ids": {
                            "type": "array",
                            "items": {
                                "anyOf": [
                                    {"type": "integer", "minimum": 0},
                                    {"type": "string", "minLength": 1},
                                ]
                            },
                            "minItems": 1,
                        },
                        "domain_ids": {
                            "type": "array",
                            "items": {"type": "string", "enum": module_ids},
                            "minItems": 1,
                        },
                        "entity_ids": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                        },
                        "provenance": {"type": "string", "minLength": 1},
                    },
                },
            },
            "intent_tags": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "rationale": {"type": "string", "minLength": 1},
        },
    }


class QueryIntentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    company_names: list[str] = Field(default_factory=list)
    tickers: list[str] = Field(default_factory=list)


class QueryEntityPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: str = Field(min_length=1)


class QueryUnitPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    retrieval_query: str = Field(min_length=1)
    domain_ids: list[str] = Field(default_factory=list, min_length=1)
    entity_ids: list[str] = Field(default_factory=list)
    time_scope: str = ""
    target_start: str = ""
    target_end: str = ""
    parent_unit_id: str = ""

    @model_validator(mode="after")
    def _normalize_temporal_bounds(self, info: ValidationInfo) -> "QueryUnitPayload":
        ctx = info.context or {}
        as_of = ctx.get("as_of_utc")
        as_of_s = as_of if isinstance(as_of, str) else None
        self.target_start = normalize_target_date_token(
            self.target_start, as_of_utc=as_of_s
        )
        self.target_end = normalize_target_date_token(
            self.target_end, as_of_utc=as_of_s
        )
        return self


class QueryRequirementPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = ""
    acceptance: str = Field(min_length=1)
    unit_ids: list[Union[int, str]] = Field(default_factory=list, min_length=1)
    domain_ids: list[str] = Field(default_factory=list, min_length=1)
    entity_ids: list[str] = Field(default_factory=list)
    provenance: str = Field(min_length=1)


class QueryAnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query_intent: QueryIntentPayload = Field(default_factory=QueryIntentPayload)
    domain_ids: list[str] = Field(default_factory=list, min_length=1)
    entities: list[QueryEntityPayload] = Field(default_factory=list)
    units: list[QueryUnitPayload] = Field(default_factory=list, min_length=1)
    requirements: list[QueryRequirementPayload] = Field(
        default_factory=list, min_length=1
    )
    intent_tags: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)


def _merge_ticker_enrichment_payload(
    payload: dict[str, Any],
    enrich: dict[str, Any],
) -> dict[str, Any]:
    """Merge ticker-resolution enrichment into a raw LLM analysis payload dict."""
    merged = dict(payload)
    qi = dict(merged.get("query_intent") or {})
    tickers = _dedupe_strings([*qi.get("tickers", []), *enrich.get("tickers", [])])
    company_names = _dedupe_strings(
        [*qi.get("company_names", []), *enrich.get("canonical_company_names", [])]
    )
    qi["tickers"] = tickers
    qi["company_names"] = company_names
    merged["query_intent"] = qi
    return merged


def _company_surfaces_fully_resolved(
    raw: QueryIntentPayload,
    on_miss: Callable[[str], Iterable[ListingSeed]] | None,
) -> bool:
    combined = _dedupe_strings([*raw.tickers, *raw.company_names])
    if not combined:
        return True
    resolution = resolve_surfaces(
        company_names=tuple(combined),
        on_miss=on_miss,
    )
    return not resolution.unresolved_surface_forms


def _build_query_analysis(
    payload: dict[str, Any],
    *,
    query: str,
    valid_domain_ids: set[str],
    on_miss: Callable[[str], Iterable[ListingSeed]] | None = None,
    as_of_utc: str = "",
) -> QueryAnalysis:
    validation_ctx = {"as_of_utc": as_of_utc} if as_of_utc.strip() else None
    raw = QueryAnalysisPayload.model_validate(payload, context=validation_ctx)
    domain_ids = _validated_domain_ids(
        raw.domain_ids, valid_domain_ids=valid_domain_ids
    )
    domain_id_set = set(domain_ids)
    query_intent = _build_query_intent(
        raw.query_intent,
        query=query,
        raw_entities=raw.entities,
        on_miss=on_miss,
    )
    entities = _build_entities(raw.entities)
    entity_id_set = set(entities)
    units, unit_id_to_index = _build_units(
        raw.units,
        entity_id_set=entity_id_set,
        domain_id_set=domain_id_set,
    )
    requirements = _build_requirements(
        raw.requirements,
        entity_id_set=entity_id_set,
        domain_id_set=domain_id_set,
        unit_id_to_index=unit_id_to_index,
        unit_count=len(units),
    )
    return QueryAnalysis(
        as_of_utc=as_of_utc,
        domain_ids=domain_ids,
        query_intent=query_intent,
        entities=entities,
        units=units,
        requirements=requirements,
        intent_tags=_dedupe_strings(raw.intent_tags),
        rationale=raw.rationale,
    )


class QueryAnalyzer:
    """Analyzes the raw user query into the canonical query spec."""

    def __init__(
        self,
        client: GeminiClient | None = None,
        on_miss: Callable[[str], Iterable[ListingSeed]] | None = None,
    ) -> None:
        if client is None:
            from valuator.models.gemini_direct import (
                GeminiClient as RuntimeGeminiClient,
            )

            client = RuntimeGeminiClient(config.agent_model)
        self.client = client
        self._on_miss = on_miss

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        self.client.bind_usage_writer(usage_writer)

    async def analyze(
        self,
        *,
        query: str,
        index: DomainIndex,
        modules: dict[str, DomainModule],
        as_of_utc: str = "",
    ) -> QueryAnalysis:
        valid_ids = set(index.modules)
        if not valid_ids:
            raise ValueError("domain index must include at least one module")

        payload = await self.client.generate_json(
            prompt=_analysis_prompt(index=index, modules=modules, query=query),
            system_prompt=_SYSTEM_PROMPT,
            response_json_schema=_response_schema(list(index.modules)),
            trace_method="query_analysis.analyze",
        )
        return _build_query_analysis(
            payload,
            query=query,
            valid_domain_ids=valid_ids,
            on_miss=self._on_miss,
            as_of_utc=as_of_utc,
        )
