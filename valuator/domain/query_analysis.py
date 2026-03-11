"""LLM-based query analysis for domain module selection."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..models.gemini_direct import GeminiClient
from ..utils.config import config
from .query import (
    QueryAnalysis,
    QueryIntent,
    QueryRequirement,
    QueryUnit,
    is_concrete_subject_kind,
)
from .types import DomainIndex, DomainModule

_SYSTEM_PROMPT = (
    "Return concise JSON only. No markdown. "
    "Do not include any keys except the requested schema."
)


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _dedupe_ints(values: list[int]) -> list[int]:
    return list(dict.fromkeys(values))


class QueryIntentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticker: str = ""
    market: str = ""
    security_code: str = ""
    company_names: list[str] = Field(default_factory=list)


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


class QueryRequirementPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = ""
    acceptance: str = Field(min_length=1)
    unit_ids: list[int | str] = Field(default_factory=list, min_length=1)
    domain_ids: list[str] = Field(default_factory=list, min_length=1)
    entity_ids: list[str] = Field(default_factory=list)
    provenance: str = Field(min_length=1)


class QueryAnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query_intent: QueryIntentPayload = Field(default_factory=QueryIntentPayload)
    domain_ids: list[str] = Field(default_factory=list, min_length=1)
    entities: list[QueryEntityPayload] = Field(default_factory=list)
    units: list[QueryUnitPayload] = Field(default_factory=list, min_length=1)
    requirements: list[QueryRequirementPayload] = Field(default_factory=list, min_length=1)
    intent_tags: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)


def _build_query_analysis(
    payload: dict[str, Any],
    *,
    query: str,
    valid_domain_ids: set[str],
) -> QueryAnalysis:
    raw = QueryAnalysisPayload.model_validate(payload)
    domain_ids = _dedupe_strings(raw.domain_ids)
    if not domain_ids:
        raise ValueError("query analysis returned no valid domain_ids")
    domain_id_set = set(domain_ids)
    unknown_domains = sorted(domain_id_set - valid_domain_ids)
    if unknown_domains:
        raise ValueError(
            "query analysis returned unknown domain_ids: "
            + ", ".join(unknown_domains)
        )

    query_intent = QueryIntent(
        query=query,
        ticker=raw.query_intent.ticker,
        market=raw.query_intent.market,
        security_code=raw.query_intent.security_code,
        company_names=_dedupe_strings(raw.query_intent.company_names),
    )

    entities: dict[str, str] = {}
    for item in raw.entities:
        if not is_concrete_subject_kind(item.kind):
            continue
        if item.id in entities:
            raise ValueError(f"duplicate query entity id: {item.id}")
        entities[item.id] = item.label

    entity_id_set = set(entities)
    units: list[QueryUnit] = []
    unit_id_to_index: dict[str, int] = {}
    for item in raw.units:
        unit_domains = _dedupe_strings(item.domain_ids)
        entity_ids = _dedupe_strings(
            [entity_id for entity_id in item.entity_ids if entity_id in entity_id_set]
        )
        if item.id in unit_id_to_index:
            raise ValueError(f"duplicate query unit id: {item.id}")
        unknown_unit_domains = sorted(set(unit_domains) - domain_id_set)
        if unknown_unit_domains:
            raise ValueError(
                f"query unit references unknown domain_ids: {item.id}"
            )
        if not unit_domains:
            raise ValueError(f"query unit missing domain_ids: {item.id}")
        unit_id_to_index[item.id] = len(units)
        units.append(
            QueryUnit(
                id=item.id,
                objective=item.objective,
                retrieval_query=item.retrieval_query,
                domain_ids=unit_domains,
                entity_ids=entity_ids,
                time_scope=item.time_scope,
            )
        )

    unit_count = len(units)
    requirements: list[QueryRequirement] = []
    seen_requirement_ids: set[str] = set()
    for index, item in enumerate(raw.requirements, start=1):
        requirement_id = item.id or f"R-{index:03d}"
        requirement_domains = _dedupe_strings(item.domain_ids)
        requirement_entities = _dedupe_strings(
            [entity_id for entity_id in item.entity_ids if entity_id in entity_id_set]
        )
        if requirement_id in seen_requirement_ids:
            raise ValueError(f"duplicate query requirement id: {requirement_id}")
        seen_requirement_ids.add(requirement_id)
        if not requirement_domains:
            raise ValueError("query requirement missing domain_ids")
        if set(requirement_domains) - domain_id_set:
            raise ValueError("query requirement references unknown domain_ids")

        resolved_unit_ids: list[int] = []
        for raw_ref in item.unit_ids:
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

        requirements.append(
            QueryRequirement(
                id=requirement_id,
                acceptance=item.acceptance,
                unit_ids=_dedupe_ints(resolved_unit_ids),
                domain_ids=requirement_domains,
                entity_ids=requirement_entities,
                provenance=item.provenance,
            )
        )

    intent_tags = _dedupe_strings(raw.intent_tags)

    return QueryAnalysis(
        domain_ids=domain_ids,
        query_intent=query_intent,
        entities=entities,
        units=units,
        requirements=requirements,
        intent_tags=intent_tags,
        rationale=raw.rationale,
    )


class QueryAnalyzer:
    """Analyzes the raw user query into the canonical query spec."""

    def __init__(self, client: GeminiClient | None = None) -> None:
        self.client = client or GeminiClient(config.agent_model)

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        self.client.bind_usage_writer(usage_writer)

    async def analyze(
        self,
        *,
        query: str,
        index: DomainIndex,
        modules: dict[str, DomainModule],
    ) -> QueryAnalysis:
        valid_ids = set(index.modules)
        if not valid_ids:
            raise ValueError("domain index must include at least one module")

        summaries = dict(index.module_summaries)
        for module_id in index.modules:
            if module_id not in summaries and module_id in modules:
                summaries[module_id] = modules[module_id].description or module_id

        scope = index.valuation_scope.strip() or "Apply all modules for valuation-related queries."
        exclusion = index.exclusion_signals.strip() or "None."
        selective = index.selective_signals.strip() or "None."
        module_lines = "\n".join(
            f"  - {module_id}: {summaries.get(module_id, module_id)}"
            for module_id in index.modules
        )
        prompt = (
            "Analyze the user query into a canonical valuation query specification.\n\n"
            "[VALUATION_SCOPE]\n"
            f"{scope}\n\n"
            "[EXCLUSION_SIGNALS]\n"
            f"{exclusion}\n\n"
            "[SELECTIVE_SIGNALS]\n"
            f"{selective}\n\n"
            "[AVAILABLE_MODULES]\n"
            f"{module_lines}\n\n"
            "Rules:\n"
            "- Return query_intent, domain_ids, entities, units, requirements, intent_tags, rationale.\n"
            "- query_intent must include ticker, market, security_code, company_names.\n"
            "- Use empty strings or an empty array in query_intent when the query does not identify a concrete subject.\n"
            "- units must be semantic retrieval units, not formatting instructions.\n"
            "- Every unit must include id, objective, retrieval_query, domain_ids, entity_ids, time_scope.\n"
            "- Every requirement must include acceptance, unit_ids, domain_ids, entity_ids, provenance.\n"
            "- requirement unit_ids may refer to units by zero-based position, one-based position, or unit id string.\n"
            "- Include only user-requested analytical content in requirements.\n"
            "- Do not turn formatting preferences or preferred table styles into requirements.\n"
            "- Preserve the user's response intent (for example: recommendation, screening, comparison, single-company analysis) instead of rewriting it into a generic valuation essay.\n"
            "- Preserve user constraints such as requested market, count, style lens, and actionability if they are present in the query.\n"
            "- If the query does not name a concrete company/security, do not invent placeholder company entities such as 'investment candidates'. In that case entities may be empty.\n"
            "- Use entity kind `company`/`ticker`/`security` only for concrete issuers or securities explicitly present in the query or clearly recoverable from it.\n"
            "- If the query is valuation/investment-related, prefer selecting all relevant modules rather than omitting needed domains.\n\n"
            f"[QUERY]\n{query}\n"
        )

        schema: dict[str, Any] = {
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
                    "required": [
                        "ticker",
                        "market",
                        "security_code",
                        "company_names",
                    ],
                    "properties": {
                        "ticker": {"type": "string"},
                        "market": {"type": "string"},
                        "security_code": {"type": "string"},
                        "company_names": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
                "domain_ids": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(index.modules)},
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
                                "items": {"type": "string", "enum": list(index.modules)},
                                "minItems": 1,
                            },
                            "entity_ids": {
                                "type": "array",
                                "items": {"type": "string", "minLength": 1},
                            },
                            "time_scope": {"type": "string"},
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
                                "items": {"type": "string", "enum": list(index.modules)},
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

        payload = await self.client.generate_json(
            prompt=prompt,
            system_prompt=_SYSTEM_PROMPT,
            response_json_schema=schema,
            trace_method="query_analysis.analyze",
        )
        return _build_query_analysis(payload, query=query, valid_domain_ids=valid_ids)
