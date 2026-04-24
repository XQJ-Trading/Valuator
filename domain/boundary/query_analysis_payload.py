from __future__ import annotations

from typing import Any, Callable, Iterable, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from domain.company import ListingSeed, resolve_company_surfaces, resolve_subjects
from domain.query import (
    QueryAnalysis,
    QueryIntent,
    QueryRequirement,
    QueryUnit,
    is_concrete_subject_kind,
)

from .query_temporal import normalize_target_date_token


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _dedupe_ints(values: list[int]) -> list[int]:
    return list(dict.fromkeys(values))


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
    entity_ids: list[str] = Field(default_factory=list)
    time_scope: str = ""
    target_start: str = ""
    target_end: str = ""
    parent_unit_id: str = ""

    @model_validator(mode="after")
    def _normalize_temporal_bounds(self, info: ValidationInfo) -> "QueryUnitPayload":
        ctx = info.context or {}
        as_of = ctx.get("as_of_kst")
        as_of_s = as_of if isinstance(as_of, str) else None
        self.target_start = normalize_target_date_token(
            self.target_start, as_of_kst=as_of_s
        )
        self.target_end = normalize_target_date_token(
            self.target_end, as_of_kst=as_of_s
        )
        return self


class QueryRequirementPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = ""
    acceptance: str = Field(min_length=1)
    unit_ids: list[Union[int, str]] = Field(default_factory=list, min_length=1)
    entity_ids: list[str] = Field(default_factory=list)
    provenance: str = Field(min_length=1)


class QueryAnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query_intent: QueryIntentPayload = Field(default_factory=QueryIntentPayload)
    entities: list[QueryEntityPayload] = Field(default_factory=list)
    units: list[QueryUnitPayload] = Field(default_factory=list, min_length=1)
    requirements: list[QueryRequirementPayload] = Field(
        default_factory=list, min_length=1
    )
    intent_tags: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)


def _response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "query_intent",
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
                        "entity_ids",
                        "time_scope",
                    ],
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "objective": {"type": "string", "minLength": 1},
                        "retrieval_query": {"type": "string", "minLength": 1},
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


def _build_entities(
    raw_entities: list[QueryEntityPayload],
) -> tuple[dict[str, str], dict[str, str]]:
    entities: dict[str, str] = {}
    entity_kinds: dict[str, str] = {}
    for item in raw_entities:
        if item.id in entities:
            raise ValueError(f"duplicate query entity id: {item.id}")
        entities[item.id] = item.label
        entity_kinds[item.id] = item.kind
    return entities, entity_kinds


def _build_units(
    raw_units: list[QueryUnitPayload],
    *,
    entity_id_set: set[str],
) -> tuple[list[QueryUnit], dict[str, int]]:
    units: list[QueryUnit] = []
    unit_id_to_index: dict[str, int] = {}
    for item in raw_units:
        if item.id in unit_id_to_index:
            raise ValueError(f"duplicate query unit id: {item.id}")

        unit_id_to_index[item.id] = len(units)
        units.append(
            QueryUnit(
                id=item.id,
                objective=item.objective,
                retrieval_query=item.retrieval_query,
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
        key = raw_ref.strip()
        if key in unit_id_to_index:
            resolved_unit_ids.append(unit_id_to_index[key])
            continue
        casefold_matches = [
            unit_id_to_index[k]
            for k in unit_id_to_index
            if k.casefold() == key.casefold()
        ]
        if len(casefold_matches) == 1:
            resolved_unit_ids.append(casefold_matches[0])
            continue
        if len(casefold_matches) > 1:
            raise ValueError(
                f"query requirement unit_ids reference {raw_ref!r} matches multiple unit ids"
            )
        if key.isdigit():
            resolved_unit_ids.append(int(key))
            continue
        known = ", ".join(sorted(unit_id_to_index))
        raise ValueError(
            f"query requirement references unknown unit id {raw_ref!r}; "
            f"known unit ids: {known or '(none)'}"
        )

    uses_one_based = all(
        1 <= unit_id <= unit_count for unit_id in resolved_unit_ids
    ) and (0 not in resolved_unit_ids)
    if uses_one_based:
        resolved_unit_ids = [unit_id - 1 for unit_id in resolved_unit_ids]
    bad = [
        unit_id
        for unit_id in resolved_unit_ids
        if unit_id < 0 or unit_id >= unit_count
    ]
    if bad:
        raise ValueError(
            f"query requirement unit_ids out of range for {unit_count} unit(s): {bad}"
        )
    return _dedupe_ints(resolved_unit_ids)


def _build_requirements(
    raw_requirements: list[QueryRequirementPayload],
    *,
    entity_id_set: set[str],
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

        requirements.append(
            QueryRequirement(
                id=requirement_id,
                acceptance=item.acceptance,
                unit_ids=_resolve_requirement_unit_ids(
                    item.unit_ids,
                    unit_id_to_index=unit_id_to_index,
                    unit_count=unit_count,
                ),
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


def _merge_ticker_enrichment_payload(
    payload: dict[str, Any],
    enrich: dict[str, Any],
) -> dict[str, Any]:
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
    resolution = resolve_company_surfaces(
        company_names=tuple(combined),
        on_miss=on_miss,
    )
    return not resolution.unresolved_surface_forms


def _build_query_analysis(
    payload: dict[str, Any],
    *,
    query: str,
    on_miss: Callable[[str], Iterable[ListingSeed]] | None = None,
    as_of_kst: str = "",
) -> QueryAnalysis:
    validation_ctx = {"as_of_kst": as_of_kst} if as_of_kst.strip() else None
    raw = QueryAnalysisPayload.model_validate(payload, context=validation_ctx)
    query_intent = _build_query_intent(
        raw.query_intent,
        query=query,
        raw_entities=raw.entities,
        on_miss=on_miss,
    )
    entities, entity_kinds = _build_entities(raw.entities)
    entity_id_set = set(entities)
    units, unit_id_to_index = _build_units(
        raw.units,
        entity_id_set=entity_id_set,
    )
    requirements = _build_requirements(
        raw.requirements,
        entity_id_set=entity_id_set,
        unit_id_to_index=unit_id_to_index,
        unit_count=len(units),
    )
    return QueryAnalysis(
        as_of_kst=as_of_kst,
        query_intent=query_intent,
        entities=entities,
        entity_kinds=entity_kinds,
        units=units,
        requirements=requirements,
        intent_tags=_dedupe_strings(raw.intent_tags),
        rationale=raw.rationale,
    )
