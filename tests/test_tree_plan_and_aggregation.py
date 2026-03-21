"""Tests for planning, execution artifacts, and aggregation coverage."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _field(default=..., *, default_factory=None, **_kwargs):
    if default_factory is not None:
        return default_factory()
    if default is ...:
        return None
    return default


class _BaseModel:
    def __init__(self, **data: object) -> None:
        for name, value in self.__class__.__dict__.items():
            if name.startswith("_") or callable(value):
                continue
            if name in data:
                continue
            if isinstance(value, dict):
                setattr(self, name, dict(value))
                continue
            if isinstance(value, list):
                setattr(self, name, list(value))
                continue
            setattr(self, name, value)
        for key, value in data.items():
            setattr(self, key, value)

    @classmethod
    def model_validate(cls, payload: dict[str, object]) -> "_BaseModel":
        return cls(**payload)

    def model_dump(self) -> dict[str, object]:
        return dict(self.__dict__)


sys.modules.setdefault(
    "dotenv",
    SimpleNamespace(load_dotenv=lambda *_args, **_kwargs: None),
)
sys.modules.setdefault(
    "pydantic",
    SimpleNamespace(BaseModel=_BaseModel, ConfigDict=dict, Field=_field),
)

from valuator.core.aggregator.extractor import StructuredExtractor
from valuator.core.aggregator.service import Aggregation
from valuator.core.contracts.plan import (
    AggregationResult,
    ExecutionArtifact,
    ExecutionResult,
    Plan,
    ReviewResult,
    Task,
    TaskReport,
    ToolCall,
)
from valuator.core.executor.domain_fields import build_domain_artifact_fields
from valuator.core.executor.service import Executor
from valuator.core.orchestrator.engine import Engine
from valuator.core.planner.service import Planner
from valuator.core.workspace.service import Workspace
from valuator.domain import (
    DomainLoader,
    DomainModuleContext,
    QueryAnalysis,
    QueryIntent,
    QueryRequirement,
    QueryUnit,
    resolve_subjects,
)
from valuator.tools.base import ToolResult
from valuator.utils.config import config as runtime_config


def _intent(
    *,
    query: str,
    ticker: str = "",
    security_code: str = "",
    company_name: str = "",
) -> QueryIntent:
    subjects = resolve_subjects(
        ticker=ticker,
        security_code=security_code,
        company_names=(company_name,) if company_name else (),
    )
    return QueryIntent(query=query, subjects=subjects)


def _analysis() -> QueryAnalysis:
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
                acceptance="Explain the valuation conclusion with cash-flow evidence.",
                unit_ids=[0],
                domain_ids=["dcf"],
                entity_ids=["amazon"],
                provenance="Derived from valuation ask.",
            ),
            QueryRequirement(
                id="R-002",
                acceptance="Explain governance risks relevant to capital allocation.",
                unit_ids=[1],
                domain_ids=["ceo"],
                entity_ids=["amazon"],
                provenance="Derived from governance ask.",
            ),
        ],
        allowed_tools=[
            "sec_tool",
            "web_search_tool",
            "domain_tool",
        ],
        rationale="Two unit canonical analysis.",
    )


class _PlannerClient:
    def bind_usage_writer(self, _usage_writer: object) -> None:
        return None

    async def generate_json(self, **kwargs: object) -> dict[str, object]:
        trace_method = kwargs["trace_method"]
        if trace_method != "planner._select_tool_for_unit":
            raise AssertionError(f"unexpected trace_method: {trace_method}")
        prompt = str(kwargs["prompt"])
        if "leadership governance" in prompt:
            return {
                "tool_name": "web_search_tool",
                "tool_args": {"query": "Amazon governance"},
            }
        return {
            "tool_name": "sec_tool",
            "tool_args": {"ticker": "AMZN", "year": 2026, "query": "Amazon valuation"},
        }


class _CapturePlannerClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def bind_usage_writer(self, _usage_writer: object) -> None:
        return None

    async def generate_json(self, **kwargs: object) -> dict[str, object]:
        self.prompts.append(str(kwargs["prompt"]))
        return {
            "tool_name": "web_search_tool",
            "tool_args": {"query": "aspect gap search"},
        }


class _SynthesisClient:
    def bind_usage_writer(self, _usage_writer: object) -> None:
        return None

    async def generate(self, **_kwargs: object) -> str:
        return "# Final\n\n[DOMAIN:dcf] valuation section\n\n[CONTRACT_COVERAGE] R-001"


class _CaptureSynthesisClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def bind_usage_writer(self, _usage_writer: object) -> None:
        return None

    async def generate(self, **kwargs: object) -> str:
        self.prompts.append(str(kwargs["prompt"]))
        return "### [DOMAIN:dcf] scoped section"


class _FakeGenericDomainTool:
    def bind_usage_writer(self, _usage_writer: object) -> None:
        return None

    async def execute(self, **_kwargs: object) -> ToolResult:
        return ToolResult(
            success=True,
            result={"summary": "generic domain output"},
            metadata={},
        )


class _ThinRetrievalTool:
    def bind_usage_writer(self, _usage_writer: object) -> None:
        return None

    async def execute(self, **_kwargs: object) -> ToolResult:
        return ToolResult(
            success=True,
            result={"findings": "No chunks selected"},
            metadata={"selected_count": 0, "source": "test"},
        )


class _NoopPlanner:
    def bind_usage_writer(self, _usage_writer: object) -> None:
        return None

    def bind_now_utc(self, _now_utc: object) -> None:
        return None

    def bind_domain_context(self, _domain_context: object) -> None:
        return None


class _SamePlanPlanner(_NoopPlanner):
    def __init__(self, plan: Plan | None = None) -> None:
        self.plan_to_return = plan
        self.replan_calls = 0

    async def plan(self, _query: str) -> Plan:
        if self.plan_to_return is None:
            raise AssertionError("plan_to_return is required")
        return self.plan_to_return

    async def replan(
        self,
        current_plan: Plan,
        _review: ReviewResult,
        _aggregation: AggregationResult | None = None,
    ) -> Plan:
        self.replan_calls += 1
        return current_plan


class _SingleLeafExecutor:
    def bind_domain_context(self, _domain_context: object) -> None:
        return None

    async def execute_batch(self, **kwargs: object) -> list[ExecutionArtifact]:
        task_ids = list(kwargs["task_ids"])
        return [
            ExecutionArtifact(
                task_id=task_id,
                path=f"/execution/outputs/{task_id}/result.md",
                content=f"artifact for {task_id}",
            )
            for task_id in task_ids
        ]


class _StaticAggregator:
    def bind_usage_writer(self, _usage_writer: object) -> None:
        return None

    def bind_domain_context(self, _domain_context: object) -> None:
        return None

    async def build_task_report(self, **kwargs: object) -> TaskReport:
        task_id = str(kwargs["task_id"])
        return TaskReport(
            task_id=task_id,
            markdown=f"# Report for {task_id}",
            ledger={"task_id": task_id, "source_reports": ["T-LEAF-1"]},
        )

    def finalize_aggregation(self, **_kwargs: object) -> AggregationResult:
        return AggregationResult(
            final_markdown="# Final\n\n[CONTRACT_COVERAGE] R-001",
            root_task_id="T-ROOT",
            aggregated_query_unit_ids=[0],
            final_included_query_unit_ids=[0],
            covered_requirement_ids=["R-001"],
            root_ledger={"task_id": "T-ROOT", "source_reports": ["T-LEAF-1"]},
            final_trace={
                "root_task_id": "T-ROOT",
                "source_reports": ["T-LEAF-1"],
                "covered_requirement_ids": ["R-001"],
            },
        )


class _PassReviewer:
    def bind_usage_writer(self, _usage_writer: object) -> None:
        return None

    def bind_now_utc(self, _now_utc: object) -> None:
        return None

    def bind_domain_context(self, _domain_context: object) -> None:
        return None

    async def review(self, *_args: object, **_kwargs: object) -> ReviewResult:
        return ReviewResult(status="pass")


class _ReviseReviewer(_PassReviewer):
    def __init__(self) -> None:
        self.calls = 0

    async def review(self, *_args: object, **_kwargs: object) -> ReviewResult:
        self.calls += 1
        return ReviewResult(
            status="revise",
            actions=[{"node": 0, "reason": "coverage gap"}],
        )


class _ReviewerClient:
    def bind_usage_writer(self, _usage_writer: object) -> None:
        return None

    async def generate_json(self, **_kwargs: object) -> dict[str, object]:
        assessment = {"verdict": "pass", "reason": "ok"}
        quant = {"grade": "equal", "reason": "ok", "evidence": ["ok"]}
        return {
            "missing_requirement_ids": [],
            "missing_final_domain_ids": [],
            "actions": [],
            "self_assessment": {
                "decomposition": assessment,
                "execution": assessment,
                "propagation": assessment,
                "overall": "ok",
            },
            "quant_axes": {
                "time_alignment": quant,
                "segment_economics": quant,
                "capital_efficiency": quant,
                "risk_transmission": quant,
                "actionability": quant,
            },
        }


class PlannerTests(unittest.TestCase):
    def test_planner_builds_tasks_from_canonical_query_analysis(self) -> None:
        loader = DomainLoader()
        _, modules = loader.load()
        planner = Planner(client=_PlannerClient())
        planner.bind_domain_context(
            DomainModuleContext(
                module_ids=["dcf", "ceo"],
                modules={module_id: modules[module_id] for module_id in ["dcf", "ceo"]},
                query_intent=_intent(
                    query="Analyze Amazon as an investment",
                    ticker="AMZN",
                    company_name="Amazon",
                ),
                query_analysis=_analysis(),
            )
        )

        plan = asyncio.run(planner.plan("Analyze Amazon as an investment"))

        leaf_tasks = [task for task in plan.tasks if task.task_type == "leaf"]
        merge_tasks = [task for task in plan.tasks if task.task_type == "merge"]
        module_tasks = [task for task in plan.tasks if task.task_type == "module"]
        root_task = next(task for task in plan.tasks if task.id == "T-ROOT")

        self.assertEqual(plan.analysis.units, _analysis().units)
        self.assertEqual(len(leaf_tasks), 2)
        self.assertEqual(len(module_tasks), 0)
        self.assertEqual(len(merge_tasks), 3)
        self.assertEqual(len(root_task.deps), 2)
        self.assertEqual(sorted(root_task.deps), ["T-MERGE-1", "T-MERGE-2"])

    def test_replan_stops_after_two_leaf_attempts_for_same_unit(self) -> None:
        plan = Plan(
            query="Analyze Amazon as an investment",
            analysis=_analysis(),
            root_task_id="T-ROOT",
            tasks=[
                Task(
                    id="T-LEAF-1",
                    task_type="leaf",
                    query_unit_ids=[0],
                    tool=ToolCall(
                        name="sec_tool",
                        args={"ticker": "AMZN", "year": 2025, "query": "valuation"},
                    ),
                    domain_id="dcf",
                    output="/execution/outputs/T-LEAF-1/result.md",
                    description="Analyze valuation drivers",
                ),
                Task(
                    id="T-LEAF-2",
                    task_type="leaf",
                    query_unit_ids=[0],
                    tool=ToolCall(
                        name="web_search_tool",
                        args={"query": "Amazon valuation"},
                    ),
                    domain_id="dcf",
                    output="/execution/outputs/T-LEAF-2/result.md",
                    description="Retry valuation drivers",
                ),
                Task(
                    id="T-MERGE-1",
                    task_type="merge",
                    query_unit_ids=[0],
                    deps=["T-LEAF-1", "T-LEAF-2"],
                    description="Valuation unit",
                ),
                Task(
                    id="T-ROOT",
                    task_type="merge",
                    query_unit_ids=[0, 1],
                    deps=["T-MERGE-1"],
                    description="Final synthesis",
                ),
            ],
        )
        review = ReviewResult(actions=[{"node": 0, "reason": "coverage gap"}])
        planner = Planner(client=_PlannerClient())

        replanned = asyncio.run(planner.replan(plan, review))

        self.assertIs(replanned, plan)

    def test_replan_includes_uncovered_aspect_coverage_hint(self) -> None:
        plan = Plan(
            query="Analyze Amazon as an investment",
            analysis=_analysis(),
            root_task_id="T-ROOT",
            tasks=[
                Task(
                    id="T-LEAF-1",
                    task_type="leaf",
                    query_unit_ids=[0],
                    tool=ToolCall(
                        name="sec_tool",
                        args={"ticker": "AMZN", "year": 2025, "query": "valuation"},
                    ),
                    domain_id="dcf",
                    output="/execution/outputs/T-LEAF-1/result.md",
                    description="Analyze valuation drivers",
                    depth=2,
                ),
                Task(
                    id="T-MERGE-1",
                    task_type="merge",
                    query_unit_ids=[0],
                    deps=["T-LEAF-1"],
                    description="Valuation unit",
                    depth=1,
                ),
                Task(
                    id="T-ROOT",
                    task_type="merge",
                    query_unit_ids=[0, 1],
                    deps=["T-MERGE-1"],
                    description="Final synthesis",
                    depth=0,
                ),
            ],
        )
        review = ReviewResult(actions=[{"node": 0, "reason": "coverage gap"}])
        aggregation = AggregationResult(
            aspect_coverage={
                "discount_rate": "uncovered",
                "profitability": "covered",
            }
        )
        client = _CapturePlannerClient()
        planner = Planner(client=client)

        replanned = asyncio.run(planner.replan(plan, review, aggregation))

        self.assertIsNot(replanned, plan)
        self.assertGreaterEqual(len(client.prompts), 1)
        self.assertIn("[ASPECT_COVERAGE]", client.prompts[0])
        self.assertIn("- discount_rate", client.prompts[0])
        self.assertNotIn("- profitability", client.prompts[0])


class AggregationTests(unittest.TestCase):
    def test_extractor_preserves_full_tagged_evidence_text(self) -> None:
        evidence = ("discount-rate calibration " * 80) + "TAIL-MARKER"
        extractor = StructuredExtractor()

        result = extractor._parse_tagged(
            "### [ASPECT:discount_rate] 할인율과 자본비용\n"
            f"- summary: {evidence}",
            [],
        )

        self.assertEqual(len(result.aspect_facts), 1)
        self.assertIn("TAIL-MARKER", result.aspect_facts[0].evidence)

    def test_aggregation_maps_requirement_coverage_to_final_unit_ids(self) -> None:
        plan = Plan(
            query="Analyze Amazon as an investment",
            analysis=_analysis(),
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
                    id="T-MERGE-1",
                    task_type="merge",
                    query_unit_ids=[0],
                    deps=["T-LEAF-1"],
                    description="Valuation unit",
                ),
                Task(
                    id="T-MERGE-2",
                    task_type="merge",
                    query_unit_ids=[1],
                    deps=["T-LEAF-2"],
                    description="Governance unit",
                ),
                Task(
                    id="T-ROOT",
                    task_type="merge",
                    query_unit_ids=[0, 1],
                    deps=["T-MERGE-1", "T-MERGE-2"],
                    description="Final synthesis",
                ),
            ],
        )
        execution = ExecutionResult(
            completed_leaf_task_ids=["T-LEAF-1", "T-LEAF-2"],
            artifacts=[
                ExecutionArtifact(
                    task_id="T-LEAF-1",
                    path="leaf1.md",
                    content="leaf1",
                    raw_result={"summary": "Valuation evidence"},
                    domain_id="dcf",
                    domain_summary="Valuation evidence",
                ),
                ExecutionArtifact(
                    task_id="T-LEAF-2",
                    path="leaf2.md",
                    content="leaf2",
                    raw_result={"summary": "Governance evidence"},
                    domain_id="ceo",
                    domain_summary="Governance evidence",
                ),
            ],
        )
        aggregation = Aggregation(client=_SynthesisClient())

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Workspace(session_id="S-TEST", base_dir=Path(tmpdir))
            workspace.prepare()
            workspace.set_round(1)
            result = asyncio.run(
                aggregation.aggregate(
                    "Analyze Amazon as an investment",
                    plan,
                    execution,
                    workspace,
                )
            )

        self.assertEqual(result.aggregated_query_unit_ids, [0, 1])
        self.assertEqual(result.final_included_query_unit_ids, [0])
        self.assertEqual(result.covered_requirement_ids, ["R-001"])
        self.assertEqual(result.missing_requirement_ids, ["R-002"])
        self.assertEqual(result.domain_coverage.final_ids, ["dcf"])

    def test_finalize_aggregation_flags_numeric_discrepancy_marker(self) -> None:
        plan = Plan(
            query="unit mismatch test",
            analysis=QueryAnalysis(
                domain_ids=[],
                entities={},
                units=[],
                requirements=[],
                rationale="Minimal analysis.",
            ),
            root_task_id="T-ROOT",
            tasks=[
                Task(
                    id="T-ROOT",
                    task_type="merge",
                    query_unit_ids=[],
                    description="Final synthesis",
                )
            ],
        )
        aggregation = Aggregation(client=_SynthesisClient())

        result = aggregation.finalize_aggregation(
            plan=plan,
            task_map={"T-ROOT": plan.tasks[0]},
            artifact_materials={},
            artifact_index={},
            reports={
                "T-ROOT": TaskReport(
                    task_id="T-ROOT",
                    markdown="# Final\n\n단위 불일치로 숫자 비교를 보류한다.",
                )
            },
        )

        self.assertIn("unit mismatch", result.aggregation_error)

    def test_non_root_merge_scopes_prompt_to_task_domains_and_keeps_leaf_materials(self) -> None:
        loader = DomainLoader()
        _, modules = loader.load()
        analysis = replace(_analysis(), intent_tags=["recommendation", "single_subject"])
        long_evidence = ("discount-rate calibration " * 80) + "TAIL-MARKER"
        plan = Plan(
            query="Recommend stocks",
            analysis=analysis,
            root_task_id="T-ROOT",
            tasks=[
                Task(
                    id="T-LEAF-1",
                    task_type="leaf",
                    query_unit_ids=[0],
                    tool=ToolCall(name="web_search_tool", args={"query": "valuation"}),
                    domain_id="dcf",
                    output="/execution/outputs/T-LEAF-1/result.md",
                    description="Valuation search",
                ),
                Task(
                    id="T-LEAF-2",
                    task_type="leaf",
                    query_unit_ids=[1],
                    tool=ToolCall(name="web_search_tool", args={"query": "governance"}),
                    domain_id="ceo",
                    output="/execution/outputs/T-LEAF-2/result.md",
                    description="Governance search",
                ),
                Task(
                    id="T-MERGE-1",
                    task_type="merge",
                    query_unit_ids=[0],
                    deps=["T-LEAF-1"],
                    description="Valuation unit",
                ),
                Task(
                    id="T-MERGE-2",
                    task_type="merge",
                    query_unit_ids=[1],
                    deps=["T-LEAF-2"],
                    description="Governance unit",
                ),
                Task(
                    id="T-ROOT",
                    task_type="merge",
                    query_unit_ids=[0, 1],
                    deps=["T-MERGE-1", "T-MERGE-2"],
                    description="Final synthesis",
                ),
            ],
        )
        execution = ExecutionResult(
            completed_leaf_task_ids=["T-LEAF-1", "T-LEAF-2"],
            artifacts=[
                ExecutionArtifact(
                    task_id="T-LEAF-1",
                    path="leaf1.md",
                    content="leaf1",
                    raw_result={
                        "findings": (
                            "### [ASPECT:discount_rate] 할인율과 자본비용\n"
                            "- wacc: 10%\n"
                            f"- note: {long_evidence}"
                        ),
                        "sources": ["https://example.com/dcf"],
                    },
                    domain_id="dcf",
                    domain_summary="Valuation evidence",
                ),
                ExecutionArtifact(
                    task_id="T-LEAF-2",
                    path="leaf2.md",
                    content="leaf2",
                    raw_result={
                        "findings": (
                            "### [ASPECT:governance] 지배구조·이사회 독립성\n"
                            "- independence: majority independent"
                        ),
                        "sources": ["https://example.com/ceo"],
                    },
                    domain_id="ceo",
                    domain_summary="Governance evidence",
                ),
            ],
        )
        client = _CaptureSynthesisClient()
        aggregation = Aggregation(client=client)
        aggregation.bind_domain_context(
            DomainModuleContext(
                module_ids=["dcf", "ceo"],
                modules={module_id: modules[module_id] for module_id in ["dcf", "ceo"]},
                query_intent=_intent(
                    query="Recommend stocks",
                    ticker="AMZN",
                    company_name="Amazon",
                ),
                query_analysis=analysis,
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Workspace(session_id="S-TEST", base_dir=Path(tmpdir))
            workspace.prepare()
            workspace.set_round(1)
            asyncio.run(
                aggregation.aggregate(
                    "Recommend stocks",
                    plan,
                    execution,
                    workspace,
                )
            )

        self.assertGreaterEqual(len(client.prompts), 3)
        non_root_prompt = client.prompts[0]
        root_prompt = client.prompts[-1]
        self.assertIn("[SCOPED_DOMAINS]\ndcf", non_root_prompt)
        self.assertNotIn("module=ceo name=CEO·리더십 분석", non_root_prompt)
        self.assertIn("--- source: report:T-LEAF-1 ---", non_root_prompt)
        self.assertIn("## source: leaf1.md", non_root_prompt)
        self.assertIn("[SOURCES]\n- https://example.com/dcf", non_root_prompt)
        self.assertIn("[ASPECT_FACTS]", root_prompt)
        self.assertIn("discount_rate", root_prompt)
        self.assertIn("TAIL-MARKER", root_prompt)
        self.assertIn("--- source: report:T-MERGE-1 ---", root_prompt)
        self.assertIn("child merge report를 1차 사실 원장으로 사용", root_prompt)
        self.assertIn("### [DOMAIN:dcf] scoped section", root_prompt)
        self.assertNotIn("--- source: leaf1.md ---", root_prompt)

    def test_root_prompt_filters_leaf_domain_evidence_and_compacts_module_summaries(self) -> None:
        loader = DomainLoader()
        _, modules = loader.load()
        analysis = replace(_analysis(), intent_tags=["single_subject"])
        huge_summary = ("module summary " * 200) + "TAIL-END"
        plan = Plan(
            query="Analyze Amazon",
            analysis=analysis,
            root_task_id="T-ROOT",
            tasks=[
                Task(
                    id="T-LEAF-1",
                    task_type="leaf",
                    query_unit_ids=[0],
                    tool=ToolCall(name="sec_tool", args={"ticker": "AMZN"}),
                    domain_id="dcf",
                    output="/execution/outputs/T-LEAF-1/result.md",
                    description="Leaf valuation",
                ),
                Task(
                    id="T-MERGE-1",
                    task_type="merge",
                    query_unit_ids=[0],
                    deps=["T-LEAF-1"],
                    description="Merged valuation",
                ),
                Task(
                    id="T-MOD-1",
                    task_type="module",
                    query_unit_ids=[0],
                    deps=["T-MERGE-1"],
                    tool=ToolCall(name="domain_tool", args={"query": "valuation"}),
                    domain_id="dcf",
                    output="/execution/outputs/T-MOD-1/result.md",
                    description="DCF module",
                ),
                Task(
                    id="T-ROOT",
                    task_type="merge",
                    query_unit_ids=[0],
                    deps=["T-MERGE-1", "T-MOD-1"],
                    description="Root synthesis",
                ),
            ],
        )
        execution = ExecutionResult(
            completed_leaf_task_ids=["T-LEAF-1"],
            artifacts=[
                ExecutionArtifact(
                    task_id="T-LEAF-1",
                    path="leaf1.md",
                    content="leaf1",
                    raw_result={
                        "findings": "### [ASPECT:discount_rate] 할인율과 자본비용\n- wacc: 10%",
                    },
                    domain_id="dcf",
                    domain_summary="Leaf valuation evidence",
                    domain_payload={"raw": "LEAF-PAYLOAD"},
                ),
                ExecutionArtifact(
                    task_id="T-MOD-1",
                    path="mod1.md",
                    content="mod1",
                    raw_result={"findings": huge_summary},
                    domain_id="dcf",
                    domain_summary=huge_summary,
                    domain_payload={"raw": "MODULE-PAYLOAD"},
                ),
            ],
        )
        client = _CaptureSynthesisClient()
        aggregation = Aggregation(client=client)
        aggregation.bind_domain_context(
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

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Workspace(session_id="S-TEST", base_dir=Path(tmpdir))
            workspace.prepare()
            workspace.set_round(1)
            asyncio.run(
                aggregation.aggregate(
                    "Analyze Amazon",
                    plan,
                    execution,
                    workspace,
                )
            )

        root_prompt = client.prompts[-1]
        self.assertIn("[DOMAIN_EVIDENCE_OVERVIEW]", root_prompt)
        self.assertIn("module=dcf name=DCF 밸류에이션", root_prompt)
        self.assertIn("evidence#1.task_id: T-MOD-1", root_prompt)
        self.assertNotIn("LEAF-PAYLOAD", root_prompt)
        self.assertNotIn("MODULE-PAYLOAD", root_prompt)
        self.assertNotIn("TAIL-END", root_prompt)


class DomainEvidenceTests(unittest.TestCase):
    def test_generic_domain_artifact_fields_keep_raw_payload(self) -> None:
        output = build_domain_artifact_fields(
            tool_name="domain_tool",
            raw_result={
                "company_name": "Amazon",
                "assumptions": {"discount_rate": 0.1},
                "calculation": {
                    "output": (
                        "{'enterprise_value': 123.456, 'pv_explicit': 45.6, "
                        "'terminal_value': 100.0, 'terminal_pv': 77.856}"
                    )
                },
                "findings": "DCF summary",
            },
            metadata={"tool_type": "domain", "domain": "dcf"},
        )

        self.assertEqual(output["domain_id"], "dcf")
        self.assertEqual(output["domain_summary"], "DCF summary")
        self.assertEqual(output["domain_key_values"], {})
        self.assertEqual(
            output["domain_payload"]["raw_result"]["company_name"],
            "Amazon",
        )

    def test_generic_domain_artifact_fields_fall_back_to_task_domain_id(self) -> None:
        output = build_domain_artifact_fields(
            tool_name="sec_tool",
            raw_result={"summary": "Risk transmission summary"},
            metadata={},
            fallback_domain_id="risk_transmission",
        )

        self.assertEqual(output["domain_id"], "risk_transmission")
        self.assertEqual(output["domain_summary"], "Risk transmission summary")

    def test_executor_preserves_generic_domain_evidence_for_module_task(self) -> None:
        analysis = QueryAnalysis(
            domain_ids=["risk_transmission"],
            entities={"amazon": "Amazon"},
            units=[
                QueryUnit(
                    id="Q-001",
                    objective="Analyze transmission path",
                    retrieval_query="Analyze transmission path",
                    domain_ids=["risk_transmission"],
                    entity_ids=["amazon"],
                    time_scope="2021-01-01 to 2026-03-06",
                )
            ],
            requirements=[],
            rationale="One-unit analysis.",
        )
        plan = Plan(
            query="module evidence test",
            analysis=analysis,
            root_task_id="T-ROOT",
            tasks=[
                Task(
                    id="T-MOD-1",
                    task_type="module",
                    query_unit_ids=[0],
                    deps=[],
                    tool=ToolCall(name="fake_generic_domain_tool", args={"query": "module"}),
                    domain_id="risk_transmission",
                    output="/execution/outputs/T-MOD-1/result.md",
                    description="Generic domain task",
                ),
                Task(
                    id="T-ROOT",
                    task_type="merge",
                    query_unit_ids=[0],
                    deps=["T-MOD-1"],
                    description="Root",
                ),
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Workspace(session_id="S-TEST", base_dir=Path(tmpdir))
            workspace.prepare()
            workspace.set_round(1)
            executor = Executor()
            executor._tool_cache["fake_generic_domain_tool"] = _FakeGenericDomainTool()
            result = asyncio.run(executor.execute("module evidence test", plan, workspace))

        self.assertEqual(result.completed_leaf_task_ids, [])
        self.assertEqual(result.artifacts[0].task_id, "T-MOD-1")
        self.assertEqual(result.artifacts[0].domain_id, "risk_transmission")

    def test_executor_persists_tool_metadata_on_artifacts_and_meta_json(self) -> None:
        analysis = QueryAnalysis(
            domain_ids=[],
            entities={},
            units=[
                QueryUnit(
                    id="Q-001",
                    objective="Inspect retrieval quality",
                    retrieval_query="Inspect retrieval quality",
                    domain_ids=[],
                    entity_ids=[],
                    time_scope="2021-01-01 to 2026-03-06",
                )
            ],
            requirements=[],
            rationale="One-unit analysis.",
        )
        plan = Plan(
            query="thin retrieval metadata",
            analysis=analysis,
            root_task_id="T-ROOT",
            tasks=[
                Task(
                    id="T-LEAF-1",
                    task_type="leaf",
                    query_unit_ids=[0],
                    tool=ToolCall(name="fake_thin_tool", args={"query": "thin"}),
                    output="/execution/outputs/T-LEAF-1/result.md",
                    description="Thin retrieval test",
                ),
                Task(
                    id="T-ROOT",
                    task_type="merge",
                    query_unit_ids=[0],
                    deps=["T-LEAF-1"],
                    description="Root",
                ),
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Workspace(session_id="S-TEST", base_dir=Path(tmpdir))
            workspace.prepare()
            workspace.set_round(1)
            executor = Executor()
            executor._tool_cache["fake_thin_tool"] = _ThinRetrievalTool()
            result = asyncio.run(executor.execute("thin retrieval metadata", plan, workspace))
            meta_path = (
                workspace.session_dir
                / "execution"
                / "round-01"
                / "outputs"
                / "T-LEAF-1"
                / "result.md.meta.json"
            )
            meta_payload = json.loads(meta_path.read_text(encoding="utf-8"))
            json_path = (
                workspace.session_dir
                / "execution"
                / "round-01"
                / "outputs"
                / "T-LEAF-1"
                / "result.json"
            )
            json_payload = json.loads(json_path.read_text(encoding="utf-8"))

        self.assertEqual(result.artifacts[0].tool_metadata["selected_count"], 0)
        self.assertEqual(meta_payload["retrieval"]["selected_count"], 0)
        self.assertEqual(json_payload["task_id"], "T-LEAF-1")
        self.assertEqual(json_payload["tool_name"], "fake_thin_tool")
        self.assertEqual(json_payload["tool_metadata"]["selected_count"], 0)


class ReviewerTests(unittest.TestCase):
    def test_reviewer_forces_fallback_for_thin_retrieval(self) -> None:
        analysis = QueryAnalysis(
            domain_ids=[],
            entities={},
            units=[
                QueryUnit(
                    id="Q-001",
                    objective="Inspect retrieval quality",
                    retrieval_query="Inspect retrieval quality",
                    domain_ids=[],
                    entity_ids=[],
                    time_scope="2021-01-01 to 2026-03-06",
                )
            ],
            requirements=[],
            rationale="One-unit analysis.",
        )
        plan = Plan(
            query="thin retrieval fallback",
            analysis=analysis,
            root_task_id="T-ROOT",
            tasks=[
                Task(
                    id="T-LEAF-1",
                    task_type="leaf",
                    query_unit_ids=[0],
                    tool=ToolCall(name="web_search_tool", args={"query": "thin"}),
                    output="/execution/outputs/T-LEAF-1/result.md",
                    description="Thin retrieval test",
                ),
                Task(
                    id="T-ROOT",
                    task_type="merge",
                    query_unit_ids=[0],
                    deps=["T-LEAF-1"],
                    description="Root",
                ),
            ],
        )
        execution = ExecutionResult(
            completed_leaf_task_ids=["T-LEAF-1"],
            artifacts=[
                ExecutionArtifact(
                    task_id="T-LEAF-1",
                    path="leaf1.md",
                    content="leaf1",
                    raw_result={"findings": "No chunks selected"},
                    tool_metadata={"selected_count": 0},
                )
            ],
        )
        aggregation = AggregationResult(
            final_markdown="# Final",
            aggregated_query_unit_ids=[0],
            final_included_query_unit_ids=[0],
        )
        from valuator.core.reviewer.service import Reviewer

        reviewer = Reviewer(client=_ReviewerClient())

        result = asyncio.run(reviewer.review(plan, execution, aggregation))

        self.assertEqual(result.status, "revise")
        self.assertEqual(result.actions[0]["node"], 0)
        self.assertEqual(result.coverage_feedback["signals"]["thin_retrieval"], 1)


class EngineFinalMarkdownTests(unittest.TestCase):
    def test_engine_keeps_final_markdown_free_of_forced_query_breakdown(self) -> None:
        analysis = QueryAnalysis(
            domain_ids=["dcf"],
            entities={"amazon": "Amazon"},
            units=[
                QueryUnit(
                    id="Q-001",
                    objective="Analyze Amazon valuation",
                    retrieval_query="Amazon valuation drivers and filings",
                    domain_ids=["dcf"],
                    entity_ids=["amazon"],
                    time_scope="2021-01-01 to 2026-03-06",
                )
            ],
            requirements=[
                QueryRequirement(
                    id="R-001",
                    acceptance="Explain the valuation conclusion.",
                    unit_ids=[0],
                    domain_ids=["dcf"],
                    entity_ids=["amazon"],
                    provenance="Derived from user query.",
                )
            ],
            rationale="One-step analysis.",
        )
        plan = Plan(
            query="Analyze Amazon valuation",
            analysis=analysis,
            root_task_id="T-ROOT",
            tasks=[
                Task(
                    id="T-LEAF-1",
                    task_type="leaf",
                    query_unit_ids=[0],
                    tool=ToolCall(name="web_search_tool", args={"query": "Amazon valuation"}),
                    output="/execution/outputs/T-LEAF-1/result.md",
                    description="Analyze Amazon valuation",
                ),
                Task(
                    id="T-ROOT",
                    task_type="merge",
                    query_unit_ids=[0],
                    deps=["T-LEAF-1"],
                    description="Final synthesis",
                ),
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Workspace(session_id="S-TEST", base_dir=Path(tmpdir))
            engine = Engine(
                workspace=workspace,
                planner=_NoopPlanner(),
                executor=_SingleLeafExecutor(),
                aggregator=_StaticAggregator(),
                reviewer=_PassReviewer(),
                max_rounds=1,
            )

            result = asyncio.run(engine.run_with_plan(plan.query, plan))
            final_text = Path(result["final_path"]).read_text(encoding="utf-8")
            trace_text = (
                workspace.session_dir / "output" / "final.trace.json"
            ).read_text(encoding="utf-8")
            trace_payload = json.loads(trace_text)

        self.assertEqual(final_text, "# Final\n\n[CONTRACT_COVERAGE] R-001\n")
        self.assertNotIn("## Query 분석 요약", final_text)
        self.assertEqual(trace_payload["root_task_id"], "T-ROOT")
        self.assertEqual(trace_payload["source_reports"], ["T-LEAF-1"])

    def test_engine_stops_when_replan_returns_same_plan(self) -> None:
        analysis = QueryAnalysis(
            domain_ids=["dcf"],
            entities={"amazon": "Amazon"},
            units=[
                QueryUnit(
                    id="Q-001",
                    objective="Analyze Amazon valuation",
                    retrieval_query="Amazon valuation drivers and filings",
                    domain_ids=["dcf"],
                    entity_ids=["amazon"],
                    time_scope="2021-01-01 to 2026-03-06",
                )
            ],
            requirements=[
                QueryRequirement(
                    id="R-001",
                    acceptance="Explain the valuation conclusion.",
                    unit_ids=[0],
                    domain_ids=["dcf"],
                    entity_ids=["amazon"],
                    provenance="Derived from user query.",
                )
            ],
            rationale="One-step analysis.",
        )
        plan = Plan(
            query="Analyze Amazon valuation",
            analysis=analysis,
            root_task_id="T-ROOT",
            tasks=[
                Task(
                    id="T-LEAF-1",
                    task_type="leaf",
                    query_unit_ids=[0],
                    tool=ToolCall(
                        name="web_search_tool",
                        args={"query": "Amazon valuation"},
                    ),
                    output="/execution/outputs/T-LEAF-1/result.md",
                    description="Analyze Amazon valuation",
                ),
                Task(
                    id="T-ROOT",
                    task_type="merge",
                    query_unit_ids=[0],
                    deps=["T-LEAF-1"],
                    description="Final synthesis",
                ),
            ],
        )
        planner = _SamePlanPlanner(plan)
        reviewer = _ReviseReviewer()

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Workspace(session_id="S-TEST", base_dir=Path(tmpdir))
            engine = Engine(
                workspace=workspace,
                planner=planner,
                executor=_SingleLeafExecutor(),
                aggregator=_StaticAggregator(),
                reviewer=reviewer,
                max_rounds=3,
            )

            result = asyncio.run(engine.run(plan.query))

        self.assertEqual(result["status"], "revise")
        self.assertEqual(planner.replan_calls, 1)
        self.assertEqual(reviewer.calls, 1)

    def test_engine_runs_legacy_single_unit_plan_when_domain_arch_is_disabled(self) -> None:
        planner = Planner(client=_PlannerClient())

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Workspace(session_id="S-TEST", base_dir=Path(tmpdir))
            engine = Engine(
                workspace=workspace,
                planner=planner,
                executor=_SingleLeafExecutor(),
                aggregator=_StaticAggregator(),
                reviewer=_PassReviewer(),
                max_rounds=1,
            )

            with patch(
                "valuator.core.orchestrator.engine.config",
                replace(runtime_config, domain_arch_enabled=False),
            ):
                result = asyncio.run(engine.run("Analyze Amazon valuation"))

            plan_payload = json.loads(
                (workspace.session_dir / "plan" / "active" / "decomposition.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(plan_payload["analysis"]["domain_ids"], [])
        self.assertEqual(len(plan_payload["analysis"]["units"]), 1)
        self.assertEqual(plan_payload["analysis"]["units"][0]["objective"], "Analyze Amazon valuation")
        self.assertEqual(
            plan_payload["analysis"]["requirements"][0]["unit_ids"],
            [0],
        )


if __name__ == "__main__":
    unittest.main()
