"""Tests for reviewer requirement, domain, and semantic gating."""

from __future__ import annotations

import asyncio
import unittest

from valuator.core.contracts.plan import (
    AggregationResult,
    DomainCoverage,
    ExecutionResult,
    Plan,
    Task,
    ToolCall,
)
from valuator.core.reviewer.service import Reviewer
from valuator.domain import (
    DomainLoader,
    DomainModuleContext,
    QueryAnalysis,
    QueryIntent,
    QueryRequirement,
    QueryUnit,
)


def _query_analysis() -> QueryAnalysis:
    return QueryAnalysis(
        domain_ids=["dcf", "ceo"],
        entities={"amazon": "Amazon"},
        units=[
            QueryUnit(
                id="Q-001",
                objective="Analyze valuation drivers",
                retrieval_query="Amazon valuation drivers and filings",
                domain_ids=["dcf"],
                entity_ids=["amazon"],
                time_scope="2021-01-01 to 2026-03-06",
            ),
            QueryUnit(
                id="Q-002",
                objective="Analyze leadership and governance",
                retrieval_query="Amazon leadership governance and board independence",
                domain_ids=["ceo"],
                entity_ids=["amazon"],
                time_scope="2021-01-01 to 2026-03-06",
            ),
        ],
        requirements=[
            QueryRequirement(
                id="R-001",
                acceptance="Explain the valuation conclusion with cash-flow or valuation evidence.",
                unit_ids=[0],
                domain_ids=["dcf"],
                entity_ids=["amazon"],
                provenance="Derived from valuation ask.",
            ),
            QueryRequirement(
                id="R-002",
                acceptance="Explain the leadership and governance risks relevant to capital allocation.",
                unit_ids=[1],
                domain_ids=["ceo"],
                entity_ids=["amazon"],
                provenance="Derived from governance ask.",
            ),
        ],
        rationale="Two-unit canonical query analysis.",
    )


def _plan() -> Plan:
    return Plan(
        query="Analyze Amazon as an investment",
        analysis=_query_analysis(),
        root_task_id="T-ROOT",
        tasks=[
            Task(
                id="T-LEAF-1",
                task_type="leaf",
                query_unit_ids=[0],
                tool=ToolCall(name="sec_tool", args={"ticker": "AMZN", "year": 2025, "query": "valuation"}),
                domain_id="dcf",
                output="/execution/outputs/T-LEAF-1/result.md",
                description="Analyze valuation drivers",
            ),
            Task(
                id="T-LEAF-2",
                task_type="leaf",
                query_unit_ids=[1],
                tool=ToolCall(name="web_search_tool", args={"query": "Amazon governance"}),
                domain_id="ceo",
                output="/execution/outputs/T-LEAF-2/result.md",
                description="Analyze leadership and governance",
            ),
            Task(
                id="T-ROOT",
                task_type="merge",
                query_unit_ids=[0, 1],
                deps=["T-LEAF-1", "T-LEAF-2"],
                description="Final synthesis",
            ),
        ],
    )


def _execution_result() -> ExecutionResult:
    return ExecutionResult(completed_leaf_task_ids=["T-LEAF-1", "T-LEAF-2"])


class _ReviewerClient:
    def __init__(
        self,
        *,
        missing_requirement_ids: list[str] | None = None,
        missing_final_domain_ids: list[str] | None = None,
        actions: list[dict[str, object]] | None = None,
        quant_axes: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self.missing_requirement_ids = missing_requirement_ids or []
        self.missing_final_domain_ids = missing_final_domain_ids or []
        self.actions = actions or []
        self.quant_axes = quant_axes

    def bind_usage_writer(self, _usage_writer: object) -> None:
        return None

    async def generate_json(self, **_kwargs: object) -> dict[str, object]:
        return {
            "missing_requirement_ids": list(self.missing_requirement_ids),
            "missing_final_domain_ids": list(self.missing_final_domain_ids),
            "actions": list(self.actions),
            "self_assessment": {
                "decomposition": {"verdict": "pass", "reason": "ok"},
                "execution": {"verdict": "pass", "reason": "ok"},
                "propagation": {"verdict": "pass", "reason": "ok"},
                "overall": "ok",
            },
            "quant_axes": self.quant_axes
            or {
                "time_alignment": {"grade": "equal", "reason": "ok", "evidence": ["ok"]},
                "segment_economics": {"grade": "equal", "reason": "ok", "evidence": ["ok"]},
                "capital_efficiency": {"grade": "equal", "reason": "ok", "evidence": ["ok"]},
                "risk_transmission": {"grade": "equal", "reason": "ok", "evidence": ["ok"]},
                "actionability": {"grade": "equal", "reason": "ok", "evidence": ["ok"]},
            },
        }


class ReviewerCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        loader = DomainLoader()
        _, modules = loader.load()
        self.plan = _plan()
        self.domain_context = DomainModuleContext(
            module_ids=["dcf", "ceo"],
            modules={module_id: modules[module_id] for module_id in ["dcf", "ceo"]},
            query_intent=QueryIntent(
                query="Analyze Amazon as an investment",
                ticker="AMZN",
                market="USA",
                company_names=["Amazon"],
            ),
            query_analysis=_query_analysis(),
        )

    def test_reviewer_detects_missing_requirement_and_domain(self) -> None:
        reviewer = Reviewer(
            client=_ReviewerClient(
                missing_requirement_ids=["R-002"],
                missing_final_domain_ids=["ceo"],
                actions=[],
            )
        )
        reviewer.bind_domain_context(self.domain_context)
        aggregation = AggregationResult(
            final_markdown="# Report\n\n[DOMAIN:dcf] valuation section\n\n[CONTRACT_COVERAGE] R-001",
            aggregated_query_unit_ids=[0, 1],
            final_included_query_unit_ids=[0],
            domain_coverage=DomainCoverage(
                final_ids=["dcf"],
                evidence_ids=["dcf", "ceo"],
            ),
        )

        result = asyncio.run(
            reviewer.review(self.plan, _execution_result(), aggregation)
        )

        signals = result.coverage_feedback["signals"]
        self.assertEqual(signals["query"]["missing_ids"], ["R-002"])
        self.assertEqual(signals["query"]["missing_unit_ids"], [1])
        self.assertEqual(signals["domains"]["missing_ids_in_final"], ["ceo"])
        self.assertEqual(signals["units"]["final_ids"], [0])
        self.assertEqual(result.status, "revise")
        self.assertTrue(result.actions)
        self.assertEqual(result.actions[0]["node"], 1)

    def test_reviewer_query_spec_includes_query_breakdown(self) -> None:
        reviewer = Reviewer(client=_ReviewerClient())
        reviewer.bind_domain_context(self.domain_context)

        blob = reviewer._query_spec_blob(self.plan)

        self.assertIn("query_breakdown", blob)
        self.assertEqual(blob["query_breakdown"]["steps"][0]["id"], "Q-001")
        self.assertEqual(blob["query_breakdown"]["entities"][0]["id"], "amazon")
        self.assertEqual(
            blob["query_breakdown"]["relations"][0]["entity_ids"],
            ["amazon"],
        )

    def test_reviewer_passes_when_query_and_domains_are_covered(self) -> None:
        reviewer = Reviewer(
            client=_ReviewerClient(
                missing_requirement_ids=[],
                missing_final_domain_ids=[],
                actions=[],
            )
        )
        reviewer.bind_domain_context(self.domain_context)
        aggregation = AggregationResult(
            final_markdown=(
                "# Report\n\n"
                "[DOMAIN:dcf] valuation section\n\n"
                "[DOMAIN:ceo] governance section\n\n"
                "[CONTRACT_COVERAGE] R-001, R-002"
            ),
            aggregated_query_unit_ids=[0, 1],
            final_included_query_unit_ids=[0, 1],
            domain_coverage=DomainCoverage(
                final_ids=["dcf", "ceo"],
                evidence_ids=["dcf", "ceo"],
            ),
        )

        result = asyncio.run(
            reviewer.review(self.plan, _execution_result(), aggregation)
        )

        signals = result.coverage_feedback["signals"]
        self.assertEqual(signals["query"]["covered"], 2)
        self.assertEqual(signals["query"]["total"], 2)
        self.assertEqual(signals["units"]["final"], 2)
        self.assertEqual(signals["domains"]["final"], 2)
        self.assertEqual(signals["missing_contract"], 0)
        self.assertEqual(result.actions, [])
        self.assertEqual(result.status, "pass")

    def test_reviewer_revises_when_final_domain_lacks_evidence(self) -> None:
        reviewer = Reviewer(
            client=_ReviewerClient(
                missing_requirement_ids=[],
                missing_final_domain_ids=[],
                actions=[],
            )
        )
        reviewer.bind_domain_context(self.domain_context)
        aggregation = AggregationResult(
            final_markdown=(
                "# Report\n\n"
                "[DOMAIN:dcf] valuation section\n\n"
                "[DOMAIN:ceo] governance section\n\n"
                "[CONTRACT_COVERAGE] R-001, R-002"
            ),
            aggregated_query_unit_ids=[0, 1],
            final_included_query_unit_ids=[0, 1],
            domain_coverage=DomainCoverage(
                final_ids=["dcf", "ceo"],
                evidence_ids=["dcf"],
            ),
        )

        result = asyncio.run(
            reviewer.review(self.plan, _execution_result(), aggregation)
        )

        domain_signals = result.coverage_feedback["signals"]["domains"]
        self.assertEqual(domain_signals["missing_ids_in_evidence"], ["ceo"])
        self.assertEqual(domain_signals["unsupported_final_ids"], ["ceo"])
        self.assertTrue(result.actions)
        self.assertEqual(result.actions[0]["node"], 1)
        self.assertEqual(result.status, "revise")

    def test_reviewer_revises_when_aggregation_error_exists(self) -> None:
        reviewer = Reviewer(
            client=_ReviewerClient(
                missing_requirement_ids=[],
                missing_final_domain_ids=[],
                actions=[],
            )
        )
        reviewer.bind_domain_context(self.domain_context)
        aggregation = AggregationResult(
            final_markdown=(
                "# Report\n\n"
                "[DOMAIN:dcf] valuation section\n\n"
                "[DOMAIN:ceo] governance section\n\n"
                "[CONTRACT_COVERAGE] R-001, R-002"
            ),
            aggregated_query_unit_ids=[0, 1],
            final_included_query_unit_ids=[0, 1],
            domain_coverage=DomainCoverage(
                final_ids=["dcf", "ceo"],
                evidence_ids=["dcf", "ceo"],
            ),
            aggregation_error="Detected unit mismatch in final tables.",
        )

        result = asyncio.run(
            reviewer.review(self.plan, _execution_result(), aggregation)
        )

        self.assertEqual(result.coverage_feedback["signals"]["aggregation_error"], 1)
        self.assertTrue(result.actions)
        self.assertEqual(result.status, "revise")

    def test_reviewer_revises_when_quant_axis_is_below(self) -> None:
        reviewer = Reviewer(
            client=_ReviewerClient(
                missing_requirement_ids=[],
                missing_final_domain_ids=[],
                actions=[],
                quant_axes={
                    "time_alignment": {"grade": "equal", "reason": "ok", "evidence": ["ok"]},
                    "segment_economics": {"grade": "equal", "reason": "ok", "evidence": ["ok"]},
                    "capital_efficiency": {"grade": "equal", "reason": "ok", "evidence": ["ok"]},
                    "risk_transmission": {"grade": "equal", "reason": "ok", "evidence": ["ok"]},
                    "actionability": {
                        "grade": "below",
                        "reason": "The report does not provide explicit picks or triggers.",
                        "evidence": ["missing explicit recommendation protocol"],
                    },
                },
            )
        )
        reviewer.bind_domain_context(self.domain_context)
        aggregation = AggregationResult(
            final_markdown=(
                "# Report\n\n"
                "[DOMAIN:dcf] valuation section\n\n"
                "[DOMAIN:ceo] governance section\n\n"
                "[CONTRACT_COVERAGE] R-001, R-002"
            ),
            aggregated_query_unit_ids=[0, 1],
            final_included_query_unit_ids=[0, 1],
            domain_coverage=DomainCoverage(
                final_ids=["dcf", "ceo"],
                evidence_ids=["dcf", "ceo"],
            ),
        )

        result = asyncio.run(
            reviewer.review(self.plan, _execution_result(), aggregation)
        )

        self.assertEqual(
            result.coverage_feedback["signals"]["semantic"]["below_axes"],
            ["actionability"],
        )
        self.assertTrue(result.actions)
        self.assertEqual(result.status, "revise")


if __name__ == "__main__":
    unittest.main()
