"""Tests for planning, execution artifacts, and aggregation coverage."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

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
)
from valuator.domain.ir import build_domain_artifact_fields
from valuator.tools.base import ToolResult
from valuator.tools.specs import ToolSpec


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
            "dcf_pipeline_tool",
            "ceo_analysis_tool",
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


class _NoopPlanner:
    def bind_usage_writer(self, _usage_writer: object) -> None:
        return None

    def bind_now_utc(self, _now_utc: object) -> None:
        return None


class _SamePlanPlanner(_NoopPlanner):
    def __init__(self, plan: Plan | None = None) -> None:
        self.plan_to_return = plan
        self.replan_calls = 0

    async def plan(self, _query: str) -> Plan:
        if self.plan_to_return is None:
            raise AssertionError("plan_to_return is required")
        return self.plan_to_return

    async def replan(self, current_plan: Plan, _review: ReviewResult) -> Plan:
        self.replan_calls += 1
        return current_plan


class _SingleLeafExecutor:
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

    async def build_task_report(self, **kwargs: object) -> TaskReport:
        task_id = str(kwargs["task_id"])
        return TaskReport(task_id=task_id, markdown=f"# Report for {task_id}")

    def finalize_aggregation(self, **_kwargs: object) -> AggregationResult:
        return AggregationResult(
            final_markdown="# Final\n\n[CONTRACT_COVERAGE] R-001",
            aggregated_query_unit_ids=[0],
            final_included_query_unit_ids=[0],
            covered_requirement_ids=["R-001"],
        )


class _PassReviewer:
    def bind_usage_writer(self, _usage_writer: object) -> None:
        return None

    def bind_now_utc(self, _now_utc: object) -> None:
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


class PlannerTests(unittest.TestCase):
    def test_planner_builds_tasks_from_canonical_query_analysis(self) -> None:
        loader = DomainLoader()
        _, modules = loader.load()
        planner = Planner(client=_PlannerClient())
        planner.bind_domain_context(
            DomainModuleContext(
                module_ids=["dcf", "ceo"],
                modules={module_id: modules[module_id] for module_id in ["dcf", "ceo"]},
                query_intent=QueryIntent(
                    query="Analyze Amazon as an investment",
                    ticker="AMZN",
                    market="USA",
                    company_names=["Amazon"],
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
        self.assertEqual(len(module_tasks), 2)
        self.assertEqual(len(merge_tasks), 3)
        self.assertEqual(sorted(task.domain_id for task in module_tasks), ["ceo", "dcf"])
        self.assertEqual(len(root_task.deps), 4)

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


class AggregationTests(unittest.TestCase):
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
                        "findings": "Valuation evidence",
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
                        "findings": "Governance evidence",
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
                query_intent=QueryIntent(
                    query="Recommend stocks",
                    company_names=["Amazon"],
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
        self.assertIn("--- source: leaf1.md ---", non_root_prompt)
        self.assertIn("[SOURCES]\n- https://example.com/dcf", non_root_prompt)
        self.assertIn("--- source: leaf1.md ---", root_prompt)


class DomainEvidenceTests(unittest.TestCase):
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
            with patch.dict(
                "valuator.core.executor.service._TOOL_CLASSES",
                {"fake_generic_domain_tool": _FakeGenericDomainTool},
                clear=False,
            ), patch.dict(
                "valuator.tools.specs.TOOL_SPECS",
                {
                    "fake_generic_domain_tool": ToolSpec(
                        name="fake_generic_domain_tool",
                        required=("query",),
                        capability="fake test tool",
                    )
                },
                clear=False,
            ):
                executor = Executor()
                result = asyncio.run(executor.execute("module evidence test", plan, workspace))

        self.assertEqual(result.completed_leaf_task_ids, [])
        self.assertEqual(result.artifacts[0].task_id, "T-MOD-1")
        self.assertEqual(result.artifacts[0].domain_id, "risk_transmission")


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

        self.assertEqual(final_text, "# Final\n\n[CONTRACT_COVERAGE] R-001\n")
        self.assertNotIn("## Query 분석 요약", final_text)

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


if __name__ == "__main__":
    unittest.main()
