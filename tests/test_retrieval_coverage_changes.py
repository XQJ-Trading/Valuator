from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


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
sys.modules.setdefault("yaml", SimpleNamespace(safe_load=lambda _text: {}))

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
from valuator.core.reviewer.service import Reviewer
from valuator.core.workspace.service import Workspace
from valuator.domain.query import QueryAnalysis, QueryRequirement, QueryUnit
from valuator.tools.base import ToolResult


def _analysis() -> QueryAnalysis:
    return QueryAnalysis(
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
        requirements=[
            QueryRequirement(
                id="R-001",
                acceptance="Address retrieval quality directly.",
                unit_ids=[0],
                domain_ids=[],
                entity_ids=[],
                provenance="Derived from user query.",
            )
        ],
        allowed_tools=["web_search_tool"],
        rationale="Focused retrieval coverage test.",
    )


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


class _ThinRetrievalTool:
    def bind_usage_writer(self, _usage_writer: object) -> None:
        return None

    async def execute(self, **_kwargs: object) -> ToolResult:
        return ToolResult(
            success=True,
            result={"findings": "No chunks selected"},
            metadata={"selected_count": 0, "source": "test"},
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


class _NoopPlanner:
    def bind_usage_writer(self, _usage_writer: object) -> None:
        return None

    def bind_now_utc(self, _now_utc: object) -> None:
        return None

    def bind_domain_context(self, _domain_context: object) -> None:
        return None


class _CaptureReplanPlanner(_NoopPlanner):
    def __init__(self, plan: Plan) -> None:
        self.plan_to_return = plan
        self.replan_aggregations: list[AggregationResult | None] = []

    async def plan(self, _query: str) -> Plan:
        return self.plan_to_return

    async def replan(
        self,
        current_plan: Plan,
        _review: ReviewResult,
        aggregation: AggregationResult | None = None,
    ) -> Plan:
        self.replan_aggregations.append(aggregation)
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
    def __init__(self) -> None:
        self.result = AggregationResult(
            final_markdown="# Final\n\n[CONTRACT_COVERAGE] R-001",
            aggregated_query_unit_ids=[0],
            final_included_query_unit_ids=[0],
            covered_requirement_ids=["R-001"],
            aspect_coverage={"discount_rate": "uncovered"},
        )

    def bind_usage_writer(self, _usage_writer: object) -> None:
        return None

    def bind_domain_context(self, _domain_context: object) -> None:
        return None

    async def build_task_report(self, **kwargs: object) -> TaskReport:
        task_id = str(kwargs["task_id"])
        return TaskReport(task_id=task_id, markdown=f"# Report for {task_id}")

    def finalize_aggregation(self, **_kwargs: object) -> AggregationResult:
        return self.result


class _ReviseReviewer:
    def __init__(self) -> None:
        self.calls = 0

    def bind_usage_writer(self, _usage_writer: object) -> None:
        return None

    def bind_now_utc(self, _now_utc: object) -> None:
        return None

    def bind_domain_context(self, _domain_context: object) -> None:
        return None

    async def review(self, *_args: object, **_kwargs: object) -> ReviewResult:
        self.calls += 1
        return ReviewResult(
            status="revise",
            actions=[{"node": 0, "reason": "coverage gap"}],
        )


class PlannerCoverageTests(unittest.TestCase):
    def test_replan_includes_uncovered_aspect_coverage_hint(self) -> None:
        plan = Plan(
            query="Inspect retrieval quality",
            analysis=_analysis(),
            root_task_id="T-ROOT",
            tasks=[
                Task(
                    id="T-LEAF-1",
                    task_type="leaf",
                    query_unit_ids=[0],
                    tool=ToolCall(name="web_search_tool", args={"query": "base"}),
                    output="/execution/outputs/T-LEAF-1/result.md",
                    description="Inspect retrieval quality",
                    depth=2,
                ),
                Task(
                    id="T-MERGE-1",
                    task_type="merge",
                    query_unit_ids=[0],
                    deps=["T-LEAF-1"],
                    description="Unit merge",
                    depth=1,
                ),
                Task(
                    id="T-ROOT",
                    task_type="merge",
                    query_unit_ids=[0],
                    deps=["T-MERGE-1"],
                    description="Root",
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
        self.assertIn("[ASPECT_COVERAGE]", client.prompts[0])
        self.assertIn("- discount_rate", client.prompts[0])
        self.assertNotIn("- profitability", client.prompts[0])


class ExecutorMetadataTests(unittest.TestCase):
    def test_executor_persists_tool_metadata(self) -> None:
        plan = Plan(
            query="thin retrieval metadata",
            analysis=_analysis(),
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

        self.assertEqual(result.artifacts[0].tool_metadata["selected_count"], 0)
        self.assertEqual(meta_payload["retrieval"]["selected_count"], 0)


class ReviewerFallbackTests(unittest.TestCase):
    def test_reviewer_forces_fallback_for_thin_retrieval(self) -> None:
        plan = Plan(
            query="thin retrieval fallback",
            analysis=_analysis(),
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
            final_markdown="# Final\n\n[CONTRACT_COVERAGE] R-001",
            aggregated_query_unit_ids=[0],
            final_included_query_unit_ids=[0],
            covered_requirement_ids=["R-001"],
        )
        reviewer = Reviewer(client=_ReviewerClient())

        result = asyncio.run(reviewer.review(plan, execution, aggregation))

        self.assertEqual(result.status, "revise")
        self.assertEqual(result.actions[0]["node"], 0)
        self.assertEqual(result.coverage_feedback["signals"]["thin_retrieval"], 1)


class EngineWiringTests(unittest.TestCase):
    def test_engine_passes_aggregation_to_replan(self) -> None:
        plan = Plan(
            query="engine aggregation handoff",
            analysis=_analysis(),
            root_task_id="T-ROOT",
            tasks=[
                Task(
                    id="T-LEAF-1",
                    task_type="leaf",
                    query_unit_ids=[0],
                    tool=ToolCall(name="web_search_tool", args={"query": "base"}),
                    output="/execution/outputs/T-LEAF-1/result.md",
                    description="Inspect retrieval quality",
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
        planner = _CaptureReplanPlanner(plan)
        aggregator = _StaticAggregator()
        reviewer = _ReviseReviewer()

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Workspace(session_id="S-TEST", base_dir=Path(tmpdir))
            engine = Engine(
                workspace=workspace,
                planner=planner,
                executor=_SingleLeafExecutor(),
                aggregator=aggregator,
                reviewer=reviewer,
                max_rounds=2,
            )

            result = asyncio.run(engine.run(plan.query))

        self.assertEqual(result["status"], "revise")
        self.assertEqual(len(planner.replan_aggregations), 1)
        self.assertEqual(
            planner.replan_aggregations[0].aspect_coverage["discount_rate"],
            "uncovered",
        )


if __name__ == "__main__":
    unittest.main()
