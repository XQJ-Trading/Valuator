"""Query -> domain-module routing."""

from __future__ import annotations

from dataclasses import replace

from .boundary import combined_on_miss
from .company import merge_subjects
from .query import QueryAnalysis, QueryIntent, QueryRequirement, fill_routing_defaults
from .query_analysis import QueryAnalyzer
from .types import DomainIndex, DomainModule


async def analyze_query(
    intent: QueryIntent,
    domain_index: DomainIndex,
    modules: dict[str, DomainModule],
    analyzer: QueryAnalyzer | None = None,
    *,
    as_of_utc: str = "",
) -> tuple[QueryIntent, QueryAnalysis]:
    _analyzer = analyzer or QueryAnalyzer(on_miss=combined_on_miss)
    analysis = await _analyzer.analyze(
        query=intent.query or "",
        as_of_utc=as_of_utc,
        index=domain_index,
        modules=modules,
    )
    domain_ids = analysis.domain_ids or list(domain_index.modules)

    analyzed_intent = analysis.query_intent
    updated_intent = QueryIntent(
        query=intent.query,
        subjects=merge_subjects(intent.subjects, analyzed_intent.subjects),
        entities=tuple(dict.fromkeys([*analyzed_intent.entities, *intent.entities])),
    )
    intent_tags = _merged_intent_tags(analysis, updated_intent)
    routed_analysis = replace(
        analysis,
        domain_ids=domain_ids,
        query_intent=updated_intent,
        intent_tags=intent_tags,
        primary_task_id=None,
    )
    routed_analysis = _append_recommendation_requirement(routed_analysis)
    routed_analysis = fill_routing_defaults(routed_analysis, modules)
    return updated_intent, routed_analysis


class DomainRouter:
    """Routes a user query to domain modules via Query Analysis."""

    def __init__(self, analyzer: QueryAnalyzer | None = None) -> None:
        self._analyzer = analyzer or QueryAnalyzer(on_miss=combined_on_miss)

    def bind_usage_writer(self, usage_writer: object | None) -> None:
        self._analyzer.bind_usage_writer(usage_writer)

    async def analyze(
        self,
        intent: QueryIntent,
        index: DomainIndex,
        modules: dict[str, DomainModule],
        *,
        as_of_utc: str = "",
    ) -> tuple[QueryIntent, QueryAnalysis]:
        return await analyze_query(
            intent,
            index,
            modules,
            self._analyzer,
            as_of_utc=as_of_utc,
        )


def _merged_intent_tags(
    analysis: QueryAnalysis,
    intent: QueryIntent,
) -> list[str]:
    tags = [tag.strip().lower() for tag in analysis.intent_tags if tag.strip()]
    return list(dict.fromkeys([*tags, *_subject_intent_tags(intent)]))


def _append_recommendation_requirement(analysis: QueryAnalysis) -> QueryAnalysis:
    intent_tags = {tag.strip().lower() for tag in analysis.intent_tags if tag.strip()}
    if "recommendation" not in intent_tags and "screening" not in intent_tags:
        return analysis

    existing_acceptance = " ".join(
        requirement.acceptance.lower() for requirement in analysis.requirements
    )
    if any(keyword in existing_acceptance for keyword in ("recommend", "pick", "shortlist", "추천", "선정")):
        return analysis

    requirement = QueryRequirement(
        id=f"R-{len(analysis.requirements) + 1:03d}",
        acceptance=(
            "Respond with explicit candidate picks or shortlist outputs that satisfy the user's recommendation intent, "
            "including why each name is selected and the no-buy or trim triggers."
        ),
        unit_ids=list(range(len(analysis.units))),
        domain_ids=list(dict.fromkeys(analysis.domain_ids)),
        entity_ids=[],
        provenance="Derived from recommendation/screening intent in the user query.",
    )
    return replace(analysis, requirements=[*analysis.requirements, requirement])


def _subject_intent_tags(intent: QueryIntent) -> list[str]:
    subject_count = len(intent.subjects)
    if subject_count == 1:
        return ["single_subject"]
    if subject_count > 1:
        return ["multi_subject"]
    return []
