"""Tests for query analysis and planner behavior under the reduced core contract."""

from __future__ import annotations

import asyncio
import unittest
from datetime import date

from valuator.core.planner.service import Planner
from valuator.domain import (
    DomainLoader,
    DomainModuleContext,
    QueryAnalysis,
    QueryAnalyzer,
    QueryIntent,
    QueryRequirement,
    QueryUnit,
    analyze_query,
    build_query_breakdown,
    expand,
    find_company,
    fill_routing_defaults,
)
from valuator.tools.specs import registered_tool_names


def _canonical_analysis(
    *,
    domain_ids: list[str],
    allowed_tools: list[str] | None = None,
    entities: dict[str, str] | None = None,
    intent_tags: list[str] | None = None,
    unit_objective: str = "Analyze Amazon intrinsic value",
    retrieval_query: str = "Amazon valuation and filings",
) -> QueryAnalysis:
    entity_map = entities or {"amazon": "Amazon"}
    entity_ids = list(entity_map)
    return QueryAnalysis(
        domain_ids=domain_ids,
        entities=entity_map,
        units=[
            QueryUnit(
                id="Q-001",
                objective=unit_objective,
                retrieval_query=retrieval_query,
                domain_ids=list(domain_ids),
                entity_ids=entity_ids,
                time_scope="2021-01-01 to 2026-03-06",
            )
        ],
        requirements=[
            QueryRequirement(
                id="R-001",
                acceptance="Explain the investment conclusion with valuation evidence.",
                unit_ids=[0],
                domain_ids=list(domain_ids),
                entity_ids=entity_ids,
                provenance="Derived from user query.",
            )
        ],
        intent_tags=intent_tags or [],
        allowed_tools=allowed_tools or [],
        rationale="Canonical analysis for valuation coverage.",
    )


class _AnalyzerStub:
    def __init__(self, result: QueryAnalysis) -> None:
        self.result = result

    async def analyze(self, **_kwargs: object) -> QueryAnalysis:
        return self.result


class _NoopClient:
    def bind_usage_writer(self, _usage_writer: object) -> None:
        return None

    async def generate_json(self, **_kwargs: object) -> dict[str, object]:
        return {
            "tool_name": "web_search_tool",
            "tool_args": {"query": "fallback query"},
        }


class _QueryAnalyzerClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def bind_usage_writer(self, _usage_writer: object) -> None:
        return None

    async def generate_json(self, **_kwargs: object) -> dict[str, object]:
        return dict(self.payload)


def _intent(
    *,
    query: str,
    ticker: str = "",
    security_code: str = "",
    company_name: str = "",
) -> QueryIntent:
    company = find_company(
        ticker=ticker,
        security_code=security_code,
        company_name=company_name,
    )
    if company is None:
        return QueryIntent(query=query)
    return QueryIntent(query=query, company=company)


def _ticker(intent: QueryIntent) -> str:
    company = intent.company
    if company is None:
        return ""
    return company.yahoo_symbol


def _market(intent: QueryIntent) -> str:
    company = intent.company
    if company is None:
        return ""
    return company.legacy_market


def _security_code(intent: QueryIntent) -> str:
    company = intent.company
    return company.security_code if company is not None else ""


def _company_name(intent: QueryIntent) -> str:
    company = intent.company
    return company.issuer_name if company is not None else ""


def _company_names(intent: QueryIntent) -> list[str]:
    company_name = _company_name(intent)
    return [company_name] if company_name else []


class QueryIntentTests(unittest.TestCase):
    def test_query_intent_minimal(self) -> None:
        intent = QueryIntent(query="Amazon DCF valuation")
        self.assertEqual(intent.query, "Amazon DCF valuation")
        self.assertEqual(intent.entities, [])
        self.assertEqual(_ticker(intent), "")
        self.assertEqual(_market(intent), "")
        self.assertEqual(_security_code(intent), "")
        self.assertEqual(_company_names(intent), [])
        self.assertEqual(_company_name(intent), "")

    def test_query_intent_projects_company_fields(self) -> None:
        intent = _intent(
            query="Amazon",
            ticker="AMZN",
            company_name="Amazon",
        )
        self.assertEqual(_ticker(intent), "AMZN")
        self.assertEqual(_market(intent), "USA")
        self.assertEqual(_company_name(intent), "Amazon")


class QueryAnalysisTests(unittest.TestCase):
    def test_query_analysis_keeps_cross_references(self) -> None:
        analysis = _canonical_analysis(domain_ids=["dcf"])
        self.assertEqual(analysis.domain_ids, ["dcf"])
        self.assertEqual(analysis.entities["amazon"], "Amazon")
        self.assertEqual(analysis.units[0].domain_ids, ["dcf"])
        self.assertEqual(analysis.requirements[0].unit_ids, [0])

    def test_loader_reads_domain_relationship_files_only(self) -> None:
        loader = DomainLoader()
        _, modules = loader.load()

        self.assertIn("Warren Buffett", modules["ceo"].persona)
        self.assertEqual(
            [aspect.id for aspect in modules["ceo"].rubric],
            [
                "integrity",
                "capital_allocation",
                "governance",
                "strategic_vision",
                "talent_culture",
            ],
        )
        self.assertIn("### [ASPECT:{aspect_id}]", modules["ceo"].format_spec)
        self.assertEqual(
            [check.id for check in modules["ceo"].contract],
            ["rating_defined", "risks_explained", "investment_view_defined"],
        )
        self.assertEqual(modules["dcf"].depends_on, ["risk_transmission"])
        self.assertIn("discount_rate", [aspect.id for aspect in modules["dcf"].rubric])
        self.assertIn("assumptions", modules["dcf"].format_spec)

    def test_expand_splits_dense_high_priority_units(self) -> None:
        loader = DomainLoader()
        _, modules = loader.load()
        analysis = QueryAnalysis(
            domain_ids=["ceo", "risk_transmission"],
            entities={"amazon": "Amazon"},
            units=[
                QueryUnit(
                    id="Q-001",
                    objective="Analyze governance and transmission",
                    retrieval_query="Amazon governance and transmission",
                    domain_ids=["ceo", "risk_transmission"],
                    entity_ids=["amazon"],
                    time_scope="2021-01-01 to 2026-03-06",
                )
            ],
            requirements=[
                QueryRequirement(
                    id="R-001",
                    acceptance="Cover governance and transmission.",
                    unit_ids=[0],
                    domain_ids=["ceo", "risk_transmission"],
                    entity_ids=["amazon"],
                    provenance="Derived from user query.",
                )
            ],
            rationale="Expansion candidate.",
        )

        expanded = expand(
            analysis,
            {module_id: modules[module_id] for module_id in ["ceo", "risk_transmission"]},
        )

        self.assertEqual(len(expanded.units), 2)
        self.assertTrue(all(unit.parent_unit_id == "Q-001" for unit in expanded.units))
        self.assertTrue(all(unit.id.startswith("Q-001_") for unit in expanded.units))

    def test_build_query_breakdown_projects_steps_entities_and_relations(self) -> None:
        analysis = _canonical_analysis(
            domain_ids=["dcf", "ceo"],
            entities={
                "amazon": "Amazon",
                "aws": "Amazon Web Services",
            },
            unit_objective="Compare Amazon core retail and AWS value drivers",
            retrieval_query="Amazon and AWS value drivers",
        )
        analysis.units[0].entity_ids = ["amazon", "aws"]
        breakdown = build_query_breakdown(analysis)

        self.assertEqual(len(breakdown.steps), 1)
        self.assertEqual(breakdown.steps[0].id, "Q-001")
        self.assertEqual(breakdown.steps[0].entity_ids, ["amazon", "aws"])
        self.assertEqual(
            [(entity.id, entity.label) for entity in breakdown.entities],
            [("amazon", "Amazon"), ("aws", "Amazon Web Services")],
        )
        self.assertEqual(len(breakdown.relations), 1)
        self.assertEqual(breakdown.relations[0].step_id, "Q-001")
        self.assertEqual(breakdown.relations[0].entity_ids, ["amazon", "aws"])


class FillRoutingDefaultsTests(unittest.TestCase):
    def test_empty_domain_ids_uses_generic_tools(self) -> None:
        analysis = QueryAnalysis(
            domain_ids=[],
            entities={},
            units=[],
            requirements=[],
            allowed_tools=[],
            rationale="No domains yet.",
        )
        loader = DomainLoader()
        _, modules = loader.load()
        result = fill_routing_defaults(analysis, modules)
        self.assertIn("web_search_tool", result.allowed_tools)
        self.assertIn("code_execute_tool", result.allowed_tools)

    def test_domain_ids_fill_from_modules(self) -> None:
        analysis = QueryAnalysis(
            domain_ids=["dcf", "ceo"],
            entities={},
            units=[],
            requirements=[],
            allowed_tools=[],
            rationale="Use module tools.",
        )
        loader = DomainLoader()
        _, modules = loader.load()
        result = fill_routing_defaults(analysis, modules)
        self.assertIn("domain_tool", result.allowed_tools)
        self.assertIn("yfinance_balance_sheet", result.allowed_tools)
        self.assertEqual(result.allowed_tools.count("domain_tool"), 1)


class RouterAndPlannerIdentifierTests(unittest.TestCase):
    def test_router_preserves_identifier_fields_and_hydrates_company_names(self) -> None:
        loader = DomainLoader()
        index, modules = loader.load()
        intent = _intent(
            query="Amazon valuation",
            ticker="AMZN",
            company_name="Amazon",
        )
        analyzer = _AnalyzerStub(
            _canonical_analysis(
                domain_ids=["dcf"],
                allowed_tools=["domain_tool"],
            )
        )

        updated_intent, analysis = asyncio.run(
            analyze_query(intent, index, modules, analyzer=analyzer)
        )

        self.assertEqual(_ticker(updated_intent), "AMZN")
        self.assertEqual(_market(updated_intent), "USA")
        self.assertEqual(_company_names(updated_intent), ["Amazon"])
        self.assertEqual(updated_intent.entities, ["Amazon"])
        self.assertEqual(analysis.domain_ids, ["dcf"])

    def test_router_preserves_recommendation_without_placeholder_company(self) -> None:
        loader = DomainLoader()
        index, modules = loader.load()
        intent = QueryIntent(query="종목 추천 좀")
        analyzer = _AnalyzerStub(
            QueryAnalysis(
                domain_ids=["dcf", "ceo"],
                entities={},
                units=[
                    QueryUnit(
                        id="Q-001",
                        objective="Recommend stock candidates",
                        retrieval_query="Recommend stock candidates",
                        domain_ids=["dcf", "ceo"],
                        entity_ids=[],
                        time_scope="2026-01-01 to 2026-03-06",
                    )
                ],
                requirements=[
                    QueryRequirement(
                        id="R-001",
                        acceptance="Provide explicit candidate picks.",
                        unit_ids=[0],
                        domain_ids=["dcf", "ceo"],
                        entity_ids=[],
                        provenance="Derived from recommendation ask.",
                    )
                ],
                intent_tags=["recommendation"],
                allowed_tools=["web_search_tool", "domain_tool"],
                rationale="Recommendation query without a concrete issuer.",
            )
        )

        updated_intent, analysis = asyncio.run(
            analyze_query(intent, index, modules, analyzer=analyzer)
        )

        self.assertEqual(_company_names(updated_intent), [])
        self.assertEqual(_company_name(updated_intent), "")
        self.assertEqual(analysis.intent_tags, ["recommendation"])

    def test_router_promotes_subject_from_query_analysis_boundary(self) -> None:
        loader = DomainLoader()
        index, modules = loader.load()
        intent = QueryIntent(query="Amazon valuation")
        analyzer = _AnalyzerStub(
            QueryAnalysis(
                domain_ids=["dcf"],
                query_intent=_intent(
                    query="Amazon valuation",
                    ticker="AMZN",
                    company_name="Amazon",
                ),
                entities={},
                units=[
                    QueryUnit(
                        id="Q-001",
                        objective="Analyze intrinsic value",
                        retrieval_query="Amazon valuation upside",
                        domain_ids=["dcf"],
                        entity_ids=[],
                        time_scope="2024-01-01 to 2026-03-06",
                    )
                ],
                requirements=[
                    QueryRequirement(
                        id="R-001",
                        acceptance="Explain the valuation conclusion.",
                        unit_ids=[0],
                        domain_ids=["dcf"],
                        entity_ids=[],
                        provenance="Derived from user query.",
                    )
                ],
                rationale="Single-company valuation query.",
            )
        )

        updated_intent, _ = asyncio.run(
            analyze_query(intent, index, modules, analyzer=analyzer)
        )

        self.assertEqual(_ticker(updated_intent), "AMZN")
        self.assertEqual(_market(updated_intent), "USA")
        self.assertEqual(_company_names(updated_intent), ["Amazon"])
        self.assertEqual(updated_intent.entities, ["Amazon"])

    def test_planner_excludes_sec_tool_without_us_ticker(self) -> None:
        loader = DomainLoader()
        _, modules = loader.load()
        analysis = _canonical_analysis(
            domain_ids=["risk_transmission"],
            allowed_tools=["sec_tool", "web_search_tool"],
            entities={"hyundai-movex": "현대무벡스"},
            unit_objective="핵심 리스크 전이 경로 추출",
            retrieval_query="현대무벡스 핵심 리스크 전이 경로 추출",
        )
        planner = Planner(client=_NoopClient())
        planner.bind_domain_context(
            DomainModuleContext(
                module_ids=["risk_transmission"],
                modules={"risk_transmission": modules["risk_transmission"]},
                query_intent=_intent(
                    query="현대무벡스",
                    security_code="319400",
                    company_name="현대무벡스",
                ),
                query_analysis=analysis,
            )
        )

        self.assertEqual(planner._ticker, "319400.KQ")
        self.assertNotIn("sec_tool", planner._allowed_tools_for_context())
        tool = planner._choose_tool_deterministic(
            analysis.units[0],
            "현대무벡스",
            date(2026, 3, 6),
        )
        self.assertEqual(tool.name, "web_search_tool")
        self.assertEqual(tool.args["query"], "현대무벡스 핵심 리스크 전이 경로 추출")

    def test_planner_uses_legacy_single_unit_plan_without_domain_context(self) -> None:
        planner = Planner(client=_NoopClient())

        self.assertEqual(planner._allowed_tools_for_context(), registered_tool_names())

        plan = asyncio.run(planner.plan("Analyze Amazon valuation"))

        self.assertEqual(plan.analysis.domain_ids, [])
        self.assertEqual(plan.analysis.allowed_tools, registered_tool_names())
        self.assertEqual(len(plan.analysis.units), 1)
        self.assertEqual(plan.analysis.units[0].objective, "Analyze Amazon valuation")
        self.assertEqual(len(plan.analysis.requirements), 1)
        self.assertEqual(plan.analysis.requirements[0].unit_ids, [0])
        self.assertEqual(len([task for task in plan.tasks if task.task_type == "leaf"]), 1)

    def test_planner_keeps_company_name_distinct_from_ticker(self) -> None:
        loader = DomainLoader()
        _, modules = loader.load()
        analysis = _canonical_analysis(
            domain_ids=["dcf"],
            allowed_tools=["domain_tool"],
        )
        planner = Planner(client=_NoopClient())
        planner.bind_domain_context(
            DomainModuleContext(
                module_ids=["dcf"],
                modules={"dcf": modules["dcf"]},
                query_intent=_intent(
                    query="Analyze Amazon",
                    ticker="AMZN",
                    company_name="Amazon",
                ),
                query_analysis=analysis,
            )
        )

        tool = planner._choose_tool_deterministic(
            analysis.units[0],
            "Analyze Amazon",
            date(2026, 3, 6),
        )

        self.assertEqual(tool.name, "domain_tool")
        self.assertEqual(tool.args["ticker"], "AMZN")
        self.assertEqual(tool.args["company_name"], "Amazon")
        self.assertEqual(tool.args["corp"], "Amazon")


class QueryAnalyzerBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        loader = DomainLoader()
        self.index, self.modules = loader.load()

    def test_query_analyzer_projects_subject_into_canonical_analysis(self) -> None:
        analyzer = QueryAnalyzer(
            client=_QueryAnalyzerClient(
                {
                    "query_intent": {
                        "ticker": "AMZN",
                        "security_code": "",
                        "company_names": ["Amazon"],
                    },
                    "domain_ids": ["dcf"],
                    "entities": [],
                    "units": [
                        {
                            "id": "Q-001",
                            "objective": "Analyze valuation upside",
                            "retrieval_query": "Amazon valuation upside",
                            "domain_ids": ["dcf"],
                            "entity_ids": [],
                            "time_scope": "2024-01-01 to 2026-03-06",
                        }
                    ],
                    "requirements": [
                        {
                            "acceptance": "Cover valuation evidence.",
                            "unit_ids": [0],
                            "domain_ids": ["dcf"],
                            "entity_ids": [],
                            "provenance": "Derived from user query.",
                        }
                    ],
                    "intent_tags": [],
                    "rationale": "Need one domain.",
                }
            )
        )

        analysis = asyncio.run(
            analyzer.analyze(
                query="Amazon valuation",
                index=self.index,
                modules=self.modules,
            )
        )

        self.assertIsNotNone(analysis.query_intent.company)
        self.assertEqual(_ticker(analysis.query_intent), "AMZN")
        self.assertEqual(_market(analysis.query_intent), "USA")
        self.assertEqual(_company_names(analysis.query_intent), ["Amazon"])

    def test_query_analyzer_maps_unit_id_strings_to_zero_based_indices(self) -> None:
        analyzer = QueryAnalyzer(
            client=_QueryAnalyzerClient(
                {
                    "domain_ids": ["dcf", "ceo"],
                    "entities": [],
                    "units": [
                        {
                            "id": "Q-DCF",
                            "objective": "Analyze valuation upside",
                            "retrieval_query": "Amazon valuation upside",
                            "domain_ids": ["dcf"],
                            "entity_ids": [],
                            "time_scope": "2024-01-01 to 2026-03-06",
                        },
                        {
                            "id": "Q-CEO",
                            "objective": "Analyze leadership quality",
                            "retrieval_query": "Amazon leadership quality",
                            "domain_ids": ["ceo"],
                            "entity_ids": [],
                            "time_scope": "2024-01-01 to 2026-03-06",
                        },
                    ],
                    "requirements": [
                        {
                            "acceptance": "Cover both valuation and leadership evidence.",
                            "unit_ids": ["Q-DCF", "Q-CEO"],
                            "domain_ids": ["dcf", "ceo"],
                            "entity_ids": [],
                            "provenance": "Derived from user query.",
                        }
                    ],
                    "intent_tags": ["comparison"],
                    "rationale": "Need both domains.",
                }
            )
        )

        analysis = asyncio.run(
            analyzer.analyze(
                query="Amazon valuation and CEO review",
                index=self.index,
                modules=self.modules,
            )
        )

        self.assertEqual(analysis.requirements[0].unit_ids, [0, 1])
        self.assertEqual(analysis.requirements[0].id, "R-001")

    def test_query_analyzer_maps_one_based_unit_ids(self) -> None:
        analyzer = QueryAnalyzer(
            client=_QueryAnalyzerClient(
                {
                    "domain_ids": ["dcf", "ceo"],
                    "entities": [],
                    "units": [
                        {
                            "id": "Q-001",
                            "objective": "Analyze valuation upside",
                            "retrieval_query": "Amazon valuation upside",
                            "domain_ids": ["dcf"],
                            "entity_ids": [],
                            "time_scope": "2024-01-01 to 2026-03-06",
                        },
                        {
                            "id": "Q-002",
                            "objective": "Analyze leadership quality",
                            "retrieval_query": "Amazon leadership quality",
                            "domain_ids": ["ceo"],
                            "entity_ids": [],
                            "time_scope": "2024-01-01 to 2026-03-06",
                        },
                    ],
                    "requirements": [
                        {
                            "id": "R-002",
                            "acceptance": "Cover both valuation and leadership evidence.",
                            "unit_ids": [1, 2],
                            "domain_ids": ["dcf", "ceo"],
                            "entity_ids": [],
                            "provenance": "Derived from user query.",
                        }
                    ],
                    "intent_tags": ["comparison"],
                    "rationale": "Need both domains.",
                }
            )
        )

        analysis = asyncio.run(
            analyzer.analyze(
                query="Amazon valuation and CEO review",
                index=self.index,
                modules=self.modules,
            )
        )

        self.assertEqual(analysis.requirements[0].unit_ids, [0, 1])
        self.assertEqual(analysis.requirements[0].id, "R-002")

    def test_query_analyzer_maps_numeric_string_unit_ids(self) -> None:
        analyzer = QueryAnalyzer(
            client=_QueryAnalyzerClient(
                {
                    "domain_ids": ["dcf"],
                    "entities": [],
                    "units": [
                        {
                            "id": "Q-001",
                            "objective": "Analyze valuation upside",
                            "retrieval_query": "Amazon valuation upside",
                            "domain_ids": ["dcf"],
                            "entity_ids": [],
                            "time_scope": "2024-01-01 to 2026-03-06",
                        }
                    ],
                    "requirements": [
                        {
                            "acceptance": "Cover valuation evidence.",
                            "unit_ids": ["0"],
                            "domain_ids": ["dcf"],
                            "entity_ids": [],
                            "provenance": "Derived from user query.",
                        }
                    ],
                    "intent_tags": [],
                    "rationale": "Need one domain.",
                }
            )
        )

        analysis = asyncio.run(
            analyzer.analyze(
                query="Amazon valuation",
                index=self.index,
                modules=self.modules,
            )
        )

        self.assertEqual(analysis.requirements[0].unit_ids, [0])

    def test_query_analyzer_drops_non_concrete_entities(self) -> None:
        analyzer = QueryAnalyzer(
            client=_QueryAnalyzerClient(
                {
                    "domain_ids": ["dcf"],
                    "entities": [
                        {
                            "id": "stock-universe",
                            "label": "Investment Candidates",
                            "kind": "screening_universe",
                        }
                    ],
                    "units": [
                        {
                            "id": "Q-001",
                            "objective": "Recommend candidates",
                            "retrieval_query": "Recommend candidates",
                            "domain_ids": ["dcf"],
                            "entity_ids": ["stock-universe"],
                            "time_scope": "2026-01-01 to 2026-03-06",
                        }
                    ],
                    "requirements": [
                        {
                            "acceptance": "Provide picks.",
                            "unit_ids": [0],
                            "domain_ids": ["dcf"],
                            "entity_ids": ["stock-universe"],
                            "provenance": "Derived from user query.",
                        }
                    ],
                    "intent_tags": ["recommendation"],
                    "rationale": "Recommendation query.",
                }
            )
        )

        analysis = asyncio.run(
            analyzer.analyze(
                query="종목 추천 좀",
                index=self.index,
                modules=self.modules,
            )
        )

        self.assertEqual(analysis.entities, {})
        self.assertEqual(analysis.units[0].entity_ids, [])
        self.assertEqual(analysis.requirements[0].entity_ids, [])

    def test_query_analyzer_rejects_unknown_unit_refs(self) -> None:
        analyzer = QueryAnalyzer(
            client=_QueryAnalyzerClient(
                {
                    "domain_ids": ["dcf"],
                    "entities": [],
                    "units": [
                        {
                            "id": "Q-001",
                            "objective": "Analyze valuation upside",
                            "retrieval_query": "Amazon valuation upside",
                            "domain_ids": ["dcf"],
                            "entity_ids": [],
                            "time_scope": "2024-01-01 to 2026-03-06",
                        }
                    ],
                    "requirements": [
                        {
                            "acceptance": "Cover valuation evidence.",
                            "unit_ids": ["Q-404"],
                            "domain_ids": ["dcf"],
                            "entity_ids": [],
                            "provenance": "Derived from user query.",
                        }
                    ],
                    "intent_tags": [],
                    "rationale": "Need one domain.",
                }
            )
        )

        with self.assertRaises(ValueError):
            asyncio.run(
                analyzer.analyze(
                    query="Amazon valuation",
                    index=self.index,
                    modules=self.modules,
                )
            )


if __name__ == "__main__":
    unittest.main()
