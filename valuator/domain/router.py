"""Query -> domain-module routing."""

from __future__ import annotations

from dataclasses import replace

from .query import QueryAnalysis, QueryIntent, QueryRequirement, fill_routing_defaults
from .query_analysis import QueryAnalyzer
from .types import DomainIndex, DomainModule


async def analyze_query(
    intent: QueryIntent,
    domain_index: DomainIndex,
    modules: dict[str, DomainModule],
    analyzer: QueryAnalyzer | None = None,
) -> tuple[QueryIntent, QueryAnalysis]:
    _analyzer = analyzer or QueryAnalyzer()
    analysis = await _analyzer.analyze(
        query=intent.query or "",
        index=domain_index,
        modules=modules,
    )
    intent_tags = _merged_intent_tags(intent.query, analysis)
    domain_ids = analysis.domain_ids or list(domain_index.modules)

    analyzed_intent = analysis.query_intent
    updated_intent = QueryIntent(
        query=intent.query,
        company=intent.company or analyzed_intent.company,
        entities=list(
            dict.fromkeys(
                [
                    *analysis.entities.values(),
                    *_intent_labels(analyzed_intent),
                    *_intent_labels(intent),
                    *intent.entities,
                ]
            )
        ),
    )
    routed_analysis = replace(
        analysis,
        domain_ids=domain_ids,
        intent_tags=intent_tags,
        primary_task_id=None,
    )
    routed_analysis = _append_recommendation_requirement(routed_analysis)
    routed_analysis = fill_routing_defaults(routed_analysis, modules)
    return updated_intent, routed_analysis


class DomainRouter:
    """Routes a user query to domain modules via Query Analysis."""

    def __init__(self, analyzer: QueryAnalyzer | None = None) -> None:
        self._analyzer = analyzer or QueryAnalyzer()

    def bind_usage_writer(self, usage_writer: object | None) -> None:
        self._analyzer.bind_usage_writer(usage_writer)

    async def analyze(
        self,
        intent: QueryIntent,
        index: DomainIndex,
        modules: dict[str, DomainModule],
    ) -> tuple[QueryIntent, QueryAnalysis]:
        return await analyze_query(intent, index, modules, self._analyzer)


def _merged_intent_tags(query: str, analysis: QueryAnalysis) -> list[str]:
    tags = [tag.strip().lower() for tag in analysis.intent_tags if tag.strip()]
    if tags:
        return list(dict.fromkeys(tags))
    return _infer_intent_tags(query=query, analysis=analysis)


def _infer_intent_tags(*, query: str, analysis: QueryAnalysis) -> list[str]:
    text = query.strip().lower()
    tags: list[str] = []
    concrete_entities = list(
        dict.fromkeys(
            [
                *analysis.entities.values(),
                *_intent_labels(analysis.query_intent),
            ]
        )
    )

    if _contains_any(
        text,
        (
            "recommend",
            "recommended",
            "pick",
            "picks",
            "idea",
            "ideas",
            "top",
            "best",
            "추천",
            "종목 추천",
            "픽",
            "유망주",
            "매수 추천",
        ),
    ):
        tags.append("recommendation")
    if _contains_any(
        text,
        (
            "screen",
            "screening",
            "shortlist",
            "candidate",
            "candidates",
            "선별",
            "스크리닝",
            "후보",
            "찾아줘",
        ),
    ):
        tags.append("screening")
    if _contains_any(text, ("compare", "comparison", "versus", "vs.", "비교", "대비", "vs")):
        tags.append("comparison")
    if _contains_any(
        text,
        ("portfolio", "allocation", "weighting", "basket", "포트폴리오", "비중", "배분", "바스켓"),
    ):
        tags.append("portfolio")

    if concrete_entities:
        tags.append("single_subject" if len(concrete_entities) == 1 else "multi_subject")
    elif "recommendation" in tags or "screening" in tags:
        tags.append("multi_subject")

    return list(dict.fromkeys(tags))


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


def _intent_labels(intent: QueryIntent) -> list[str]:
    if intent.company is not None:
        return [intent.company.issuer_name]
    return []


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)
