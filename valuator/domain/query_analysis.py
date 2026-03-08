"""LLM-based query analysis for domain module selection."""

from __future__ import annotations

from typing import Any

from ..models.gemini_direct import GeminiClient
from ..utils.config import config
from .query import (
    QueryAnalysis,
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


def _build_query_analysis(payload: dict[str, Any], *, valid_domain_ids: set[str]) -> QueryAnalysis:
    raw_domain_ids = payload.get("domain_ids") or []
    domain_ids = _dedupe_strings(
        [
            str(domain_id).strip()
            for domain_id in raw_domain_ids
            if str(domain_id).strip()
        ]
    )
    if not domain_ids:
        raise ValueError("query analysis returned no valid domain_ids")
    unknown_domains = sorted(set(domain_ids) - valid_domain_ids)
    if unknown_domains:
        raise ValueError(
            "query analysis returned unknown domain_ids: "
            + ", ".join(unknown_domains)
        )

    raw_entities = payload.get("entities") or []
    entities: dict[str, str] = {}
    for item in raw_entities:
        if not isinstance(item, dict):
            raise ValueError("query analysis returned invalid entity payload")
        entity_id = str(item.get("id") or "").strip()
        label = str(item.get("label") or "").strip()
        kind = str(item.get("kind") or "").strip()
        if not entity_id or not label or not kind:
            raise ValueError("query analysis returned incomplete entity payload")
        if not is_concrete_subject_kind(kind):
            continue
        if entity_id in entities:
            raise ValueError(f"duplicate query entity id: {entity_id}")
        entities[entity_id] = label

    raw_units = payload.get("units") or []
    if not isinstance(raw_units, list) or not raw_units:
        raise ValueError("query analysis returned no units")
    units: list[QueryUnit] = []
    unit_id_to_index: dict[str, int] = {}
    for item in raw_units:
        if not isinstance(item, dict):
            raise ValueError("query analysis returned invalid unit payload")
        unit_id = str(item.get("id") or "").strip()
        objective = str(item.get("objective") or "").strip()
        retrieval_query = str(item.get("retrieval_query") or "").strip()
        raw_unit_domains = item.get("domain_ids") or []
        unit_domains = _dedupe_strings(
            [str(domain_id).strip() for domain_id in raw_unit_domains if str(domain_id).strip()]
        )
        raw_entity_ids = item.get("entity_ids") or []
        entity_ids = _dedupe_strings(
            [
                str(entity_id).strip()
                for entity_id in raw_entity_ids
                if str(entity_id).strip() in entities
            ]
        )
        time_scope = str(item.get("time_scope") or "").strip()
        if not unit_id or not objective or not retrieval_query:
            raise ValueError("query analysis returned incomplete unit payload")
        if unit_id in unit_id_to_index:
            raise ValueError(f"duplicate query unit id: {unit_id}")
        unknown_unit_domains = sorted(set(unit_domains) - set(domain_ids))
        if unknown_unit_domains:
            raise ValueError(
                f"query unit references unknown domain_ids: {unit_id}"
            )
        if not unit_domains:
            raise ValueError(f"query unit missing domain_ids: {unit_id}")
        unit_id_to_index[unit_id] = len(units)
        units.append(
            QueryUnit(
                id=unit_id,
                objective=objective,
                retrieval_query=retrieval_query,
                domain_ids=unit_domains,
                entity_ids=entity_ids,
                time_scope=time_scope,
            )
        )

    raw_requirements = payload.get("requirements") or []
    if not isinstance(raw_requirements, list) or not raw_requirements:
        raise ValueError("query analysis returned no requirements")

    unit_count = len(units)
    requirements: list[QueryRequirement] = []
    seen_requirement_ids: set[str] = set()
    for index, item in enumerate(raw_requirements, start=1):
        if not isinstance(item, dict):
            raise ValueError("query analysis returned invalid requirement payload")
        requirement_id = str(item.get("id") or f"R-{index:03d}").strip()
        acceptance = str(item.get("acceptance") or "").strip()
        provenance = str(item.get("provenance") or "").strip()
        raw_requirement_domains = item.get("domain_ids") or []
        requirement_domains = _dedupe_strings(
            [
                str(domain_id).strip()
                for domain_id in raw_requirement_domains
                if str(domain_id).strip()
            ]
        )
        raw_requirement_entities = item.get("entity_ids") or []
        requirement_entities = _dedupe_strings(
            [
                str(entity_id).strip()
                for entity_id in raw_requirement_entities
                if str(entity_id).strip() in entities
            ]
        )
        raw_unit_refs = item.get("unit_ids") or []
        if not requirement_id or not acceptance or not provenance:
            raise ValueError("query analysis returned incomplete requirement payload")
        if requirement_id in seen_requirement_ids:
            raise ValueError(f"duplicate query requirement id: {requirement_id}")
        seen_requirement_ids.add(requirement_id)
        if not requirement_domains:
            raise ValueError("query requirement missing domain_ids")
        if set(requirement_domains) - set(domain_ids):
            raise ValueError("query requirement references unknown domain_ids")
        if not raw_unit_refs:
            raise ValueError("query requirement missing unit_ids")

        resolved_unit_ids: list[int] = []
        for raw_ref in raw_unit_refs:
            if isinstance(raw_ref, int):
                resolved_unit_ids.append(raw_ref)
                continue
            text = str(raw_ref).strip()
            if not text:
                raise ValueError("query requirement references unknown unit_ids")
            if text in unit_id_to_index:
                resolved_unit_ids.append(unit_id_to_index[text])
                continue
            if text.isdigit():
                resolved_unit_ids.append(int(text))
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
                acceptance=acceptance,
                unit_ids=_dedupe_ints(resolved_unit_ids),
                domain_ids=requirement_domains,
                entity_ids=requirement_entities,
                provenance=provenance,
            )
        )

    rationale = str(payload.get("rationale") or "").strip()
    if not rationale:
        raise ValueError("query analysis returned empty rationale")

    intent_tags = _dedupe_strings(
        [str(tag).strip() for tag in (payload.get("intent_tags") or []) if str(tag).strip()]
    )

    return QueryAnalysis(
        domain_ids=domain_ids,
        entities=entities,
        units=units,
        requirements=requirements,
        intent_tags=intent_tags,
        rationale=rationale,
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
            "- Return domain_ids, entities, units, requirements, intent_tags, rationale.\n"
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
                "domain_ids",
                "entities",
                "units",
                "requirements",
                "intent_tags",
                "rationale",
            ],
            "properties": {
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
        if not isinstance(payload, dict):
            raise ValueError("query analysis returned non-object payload")
        return _build_query_analysis(payload, valid_domain_ids=valid_ids)
