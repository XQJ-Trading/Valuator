"""Query analysis routing (subjects, tools, requirements)."""

from __future__ import annotations

from dataclasses import replace

from .boundary import combined_on_miss
from .company import merge_subjects
from .query import QueryAnalysis, QueryIntent, QueryRequirement, fill_routing_defaults
from .query_analysis import QueryAnalyzer


async def analyze_query(
    intent: QueryIntent,
    analyzer: QueryAnalyzer | None = None,
    *,
    as_of_utc: str = "",
) -> tuple[QueryIntent, QueryAnalysis]:
    _analyzer = analyzer or QueryAnalyzer(on_miss=combined_on_miss)
    analysis = await _analyzer.analyze(
        query=intent.query or "",
        as_of_utc=as_of_utc,
    )

    analyzed_intent = analysis.query_intent
    updated_intent = QueryIntent(
        query=intent.query,
        subjects=merge_subjects(intent.subjects, analyzed_intent.subjects),
        entities=tuple(dict.fromkeys([*analyzed_intent.entities, *intent.entities])),
    )
    intent_tags = _merged_intent_tags(analysis, updated_intent)
    routed_analysis = replace(
        analysis,
        query_intent=updated_intent,
        intent_tags=intent_tags,
        primary_task_id=None,
    )
    routed_analysis = _append_recommendation_requirement(routed_analysis)
    routed_analysis = fill_routing_defaults(routed_analysis)
    return updated_intent, routed_analysis


class DomainRouter:
    """Runs query analysis to produce a canonical QueryAnalysis."""

    def __init__(self, analyzer: QueryAnalyzer | None = None) -> None:
        self._analyzer = analyzer or QueryAnalyzer(on_miss=combined_on_miss)

    def bind_usage_writer(self, usage_writer: object | None) -> None:
        self._analyzer.bind_usage_writer(usage_writer)

    async def analyze(
        self,
        intent: QueryIntent,
        *,
        as_of_utc: str = "",
    ) -> tuple[QueryIntent, QueryAnalysis]:
        return await analyze_query(
            intent,
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
    if any(
        keyword in existing_acceptance
        for keyword in ("recommend", "pick", "shortlist", "추천", "선정")
    ):
        return analysis

    requirement = QueryRequirement(
        id=f"R-{len(analysis.requirements) + 1:03d}",
        acceptance=(
            "Respond with explicit candidate picks or shortlist outputs that satisfy the user's recommendation intent, "
            "including why each name is selected and the no-buy or trim triggers."
        ),
        unit_ids=list(range(len(analysis.units))),
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
