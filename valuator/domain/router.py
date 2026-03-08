"""Query -> domain-module routing."""

from __future__ import annotations

import re
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
    primary_task_id = None
    for domain_id in domain_ids:
        module = modules.get(domain_id)
        if module and module.tasks:
            primary_task_id = module.tasks[0].id
            break

    analyzed_intent = analysis.query_intent
    concrete_labels = list(dict.fromkeys(analysis.entities.values()))
    updated_intent = QueryIntent(
        query=intent.query,
        ticker=intent.ticker or analyzed_intent.ticker,
        market=intent.market or analyzed_intent.market,
        security_code=intent.security_code or analyzed_intent.security_code,
        company_names=(
            intent.company_names or analyzed_intent.company_names or concrete_labels
        ),
        entities=list(
            dict.fromkeys(
                [
                    *analysis.entities.values(),
                    *analyzed_intent.company_names,
                    *intent.entities,
                ]
            )
        ),
    )
    routed_analysis = replace(
        analysis,
        domain_ids=domain_ids,
        intent_tags=intent_tags,
        primary_task_id=primary_task_id,
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
            [*analysis.query_intent.concrete_values(), *analysis.entities.values()]
        )
    )

    recommend_patterns = (
        r"\b(recommend|recommended|pick|picks|idea|ideas|top|best)\b",
        r"(추천|종목\s*추천|픽|유망주|매수\s*추천)",
    )
    compare_patterns = (
        r"\b(compare|comparison|versus|vs\.)\b",
        r"(비교|대비|vs)",
    )
    screen_patterns = (
        r"\b(screen|screening|shortlist|candidate|candidates)\b",
        r"(선별|스크리닝|후보|찾아줘)",
    )
    portfolio_patterns = (
        r"\b(portfolio|allocation|weighting|basket)\b",
        r"(포트폴리오|비중|배분|바스켓)",
    )

    if any(re.search(pattern, text) for pattern in recommend_patterns):
        tags.append("recommendation")
    if any(re.search(pattern, text) for pattern in screen_patterns):
        tags.append("screening")
    if any(re.search(pattern, text) for pattern in compare_patterns):
        tags.append("comparison")
    if any(re.search(pattern, text) for pattern in portfolio_patterns):
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
