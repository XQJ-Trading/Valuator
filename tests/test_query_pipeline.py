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
    fill_routing_defaults,
)


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


class QueryIntentTests(unittest.TestCase):
    def test_query_intent_minimal(self) -> None:
        intent = QueryIntent(query="Amazon DCF valuation")
        self.assertEqual(intent.query, "Amazon DCF valuation")
        self.assertEqual(intent.ticker, "")
        self.assertEqual(intent.market, "")
        self.assertEqual(intent.security_code, "")
        self.assertEqual(intent.company_names, [])
        self.assertEqual(intent.entities, [])
        self.assertEqual(intent.company_name, "")

    def test_query_intent_prefers_first_company_name(self) -> None:
        intent = QueryIntent(
            query="Amazon",
            ticker="AMZN",
            market="USA",
            company_names=["Amazon", "Amazon.com"],
        )
        self.assertEqual(intent.ticker, "AMZN")
        self.assertEqual(intent.market, "USA")
        self.assertEqual(intent.company_name, "Amazon")


class QueryAnalysisTests(unittest.TestCase):
    def test_query_analysis_keeps_cross_references(self) -> None:
        analysis = _canonical_analysis(domain_ids=["dcf"])
        self.assertEqual(analysis.domain_ids, ["dcf"])
        self.assertEqual(analysis.entities["amazon"], "Amazon")
        self.assertEqual(analysis.units[0].domain_ids, ["dcf"])
        self.assertEqual(analysis.requirements[0].unit_ids, [0])

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
        self.assertIn("dcf_pipeline_tool", result.allowed_tools)
        self.assertIn("ceo_analysis_tool", result.allowed_tools)


class RouterAndPlannerIdentifierTests(unittest.TestCase):
    def test_router_preserves_identifier_fields_and_hydrates_company_names(self) -> None:
        loader = DomainLoader()
        index, modules = loader.load()
        intent = QueryIntent(
            query="Amazon valuation",
            ticker="AMZN",
            market="USA",
        )
        analyzer = _AnalyzerStub(
            _canonical_analysis(
                domain_ids=["dcf"],
                allowed_tools=["dcf_pipeline_tool"],
            )
        )

        updated_intent, analysis = asyncio.run(
            analyze_query(intent, index, modules, analyzer=analyzer)
        )

        self.assertEqual(updated_intent.ticker, "AMZN")
        self.assertEqual(updated_intent.market, "USA")
        self.assertEqual(updated_intent.company_names, ["Amazon"])
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
                allowed_tools=["web_search_tool", "dcf_pipeline_tool"],
                rationale="Recommendation query without a concrete issuer.",
            )
        )

        updated_intent, analysis = asyncio.run(
            analyze_query(intent, index, modules, analyzer=analyzer)
        )

        self.assertEqual(updated_intent.company_names, [])
        self.assertEqual(updated_intent.company_name, "")
        self.assertEqual(analysis.intent_tags, ["recommendation"])

    def test_planner_excludes_sec_tool_without_us_ticker(self) -> None:
        loader = DomainLoader()
        _, modules = loader.load()
        analysis = _canonical_analysis(
            domain_ids=["balance_sheet"],
            allowed_tools=[
                "sec_tool",
                "web_search_tool",
                "yfinance_balance_sheet",
                "balance_sheet_extraction_tool",
            ],
            entities={"hyundai-movex": "현대무벡스"},
            unit_objective="최근 5개년 재무제표 추출",
            retrieval_query="현대무벡스 최근 5개년 재무제표 추출",
        )
        planner = Planner(client=_NoopClient())
        planner.bind_domain_context(
            DomainModuleContext(
                module_ids=["balance_sheet"],
                modules={"balance_sheet": modules["balance_sheet"]},
                query_intent=QueryIntent(
                    query="현대무벡스",
                    market="KRX",
                    security_code="319400",
                ),
                query_analysis=analysis,
            )
        )

        self.assertEqual(planner._ticker, "")
        self.assertNotIn("sec_tool", planner._allowed_tools_for_context())
        self.assertNotIn("yfinance_balance_sheet", planner._allowed_tools_for_context())
        self.assertNotIn(
            "balance_sheet_extraction_tool",
            planner._allowed_tools_for_context(),
        )
        tool = planner._choose_tool_deterministic(
            analysis.units[0],
            "현대무벡스",
            date(2026, 3, 6),
        )
        self.assertEqual(tool.name, "web_search_tool")
        self.assertEqual(tool.args["query"], "현대무벡스 최근 5개년 재무제표 추출")

    def test_planner_skips_balance_sheet_module_task_when_domain_has_no_specialist_tool(
        self,
    ) -> None:
        loader = DomainLoader()
        _, modules = loader.load()
        analysis = _canonical_analysis(
            domain_ids=["balance_sheet"],
            allowed_tools=["web_search_tool", "balance_sheet_extraction_tool"],
            entities={"amazon": "Amazon"},
            unit_objective="최근 5개년 재무제표 추출",
            retrieval_query="Amazon recent five year balance sheet trends",
        )
        planner = Planner(client=_NoopClient())
        planner.bind_domain_context(
            DomainModuleContext(
                module_ids=["balance_sheet"],
                modules={"balance_sheet": modules["balance_sheet"]},
                query_intent=QueryIntent(
                    query="Amazon balance sheet analysis",
                    ticker="AMZN",
                    market="USA",
                    company_names=["Amazon"],
                ),
                query_analysis=analysis,
            )
        )

        plan = asyncio.run(planner.plan("Amazon balance sheet analysis"))

        module_tasks = [task for task in plan.tasks if task.task_type == "module"]
        leaf_tasks = [task for task in plan.tasks if task.task_type == "leaf"]
        self.assertEqual(module_tasks, [])
        self.assertEqual(len(leaf_tasks), 1)
        self.assertEqual(leaf_tasks[0].tool.name, "web_search_tool")

    def test_planner_keeps_company_name_distinct_from_ticker(self) -> None:
        loader = DomainLoader()
        _, modules = loader.load()
        analysis = _canonical_analysis(
            domain_ids=["dcf"],
            allowed_tools=["dcf_pipeline_tool"],
        )
        planner = Planner(client=_NoopClient())
        planner.bind_domain_context(
            DomainModuleContext(
                module_ids=["dcf"],
                modules={"dcf": modules["dcf"]},
                query_intent=QueryIntent(
                    query="Analyze Amazon",
                    ticker="AMZN",
                    market="USA",
                    company_names=["Amazon"],
                ),
                query_analysis=analysis,
            )
        )

        tool = planner._choose_tool_deterministic(
            analysis.units[0],
            "Analyze Amazon",
            date(2026, 3, 6),
        )

        self.assertEqual(tool.name, "dcf_pipeline_tool")
        self.assertEqual(tool.args["ticker"], "AMZN")
        self.assertEqual(tool.args["company_name"], "Amazon")
        self.assertEqual(tool.args["corp"], "Amazon")


class QueryAnalyzerBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        loader = DomainLoader()
        self.index, self.modules = loader.load()

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
