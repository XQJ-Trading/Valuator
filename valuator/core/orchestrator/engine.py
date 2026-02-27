from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from ...models.gemini_direct import GeminiClient
from ...utils.config import config
from ..aggregator.service import Aggregation
from ..contracts.plan import Plan
from ..contracts.requirement import evaluate_contract
from ..llm_usage import LLMUsageWriter
from ..reviewer.service import Review
from ..executor.service import Executor
from ..graph.validator import validate_plan_graph
from ..planner.service import Planner
from ..workspace.service import Workspace


LeafStartCallback = Callable[[Any], Awaitable[None]]
LeafCompleteCallback = Callable[[Any, dict[str, Any]], Awaitable[None]]
TaskAggregatedCallback = Callable[[Any, int, int], Awaitable[None]]


class Engine:
    def __init__(
        self,
        *,
        workspace: Workspace,
        planner: Planner,
        executor: Executor,
        aggregator: Aggregation,
        reviewer: Review,
        max_rounds: int,
    ) -> None:
        if max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")
        self.workspace = workspace
        self.planner = planner
        self.executor = executor
        self.aggregator = aggregator
        self.reviewer = reviewer
        self.max_rounds = max_rounds

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        max_rounds: int = 3,
        base_dir: Path | None = None,
        model: str | None = None,
    ) -> "Engine":
        client = GeminiClient(model or config.agent_model)
        workspace = Workspace(session_id=session_id, base_dir=base_dir)
        planner = Planner(client=client)
        executor = Executor()
        aggregator = Aggregation(client=client)
        reviewer = Review(client=client)
        return cls(
            workspace=workspace,
            planner=planner,
            executor=executor,
            aggregator=aggregator,
            reviewer=reviewer,
            max_rounds=max_rounds,
        )

    async def _execute_plan(
        self,
        *,
        query: str,
        plan: Plan,
        max_rounds: int,
        usage_writer: LLMUsageWriter | None,
        on_leaf_start: LeafStartCallback | None = None,
        on_leaf_complete: LeafCompleteCallback | None = None,
        on_task_aggregated: TaskAggregatedCallback | None = None,
    ) -> dict[str, Any]:
        final_path: Path | None = None
        review_path: Path | None = None
        latest_review: dict[str, Any] | None = None

        # Validate the initial plan once before starting rounds.
        validate_plan_graph(plan)

        for round_idx in range(1, max_rounds + 1):
            review_payload, final_path, review_path = await self._run_round(
                query=query,
                plan=plan,
                round_idx=round_idx,
                usage_writer=usage_writer,
                on_leaf_start=on_leaf_start,
                on_leaf_complete=on_leaf_complete,
                on_task_aggregated=on_task_aggregated,
            )
            status = review_payload["status"]
            latest_review = review_payload

            if status == "pass":
                break
            if round_idx >= max_rounds:
                break
            plan = await self.planner.replan(plan, review_payload)
            # Validate the replanned graph before the next round uses it.
            validate_plan_graph(plan)

        if final_path is None or review_path is None or latest_review is None:
            raise RuntimeError("engine did not produce final artifacts")

        return {
            "session_id": self.workspace.session_id,
            "coverage_feedback": latest_review["coverage_feedback"],
            "status": latest_review["status"],
            "final_path": str(final_path),
            "review_path": str(review_path),
        }

    async def run(
        self,
        query: str,
        *,
        on_leaf_start: LeafStartCallback | None = None,
        on_leaf_complete: LeafCompleteCallback | None = None,
        on_task_aggregated: TaskAggregatedCallback | None = None,
    ) -> dict[str, Any]:
        if not query or not query.strip():
            raise ValueError("query is required")

        self.workspace.prepare()
        usage_writer = LLMUsageWriter(
            self.workspace.session_dir / "output" / "llm_usage.jsonl",
            session_started_at=datetime.now(timezone.utc).isoformat().replace(
                "+00:00", "Z"
            ),
        )
        self.planner.bind_usage_writer(usage_writer)
        self.aggregator.bind_usage_writer(usage_writer)
        self.reviewer.bind_usage_writer(usage_writer)
        self.workspace.write_user_input(query)
        now_utc = datetime.now(timezone.utc)
        self.planner.bind_now_utc(now_utc)
        self.reviewer.bind_now_utc(now_utc)
        try:
            plan = await self.planner.plan(query)
            return await self._execute_plan(
                query=query,
                plan=plan,
                max_rounds=self.max_rounds,
                usage_writer=usage_writer,
                on_leaf_start=on_leaf_start,
                on_leaf_complete=on_leaf_complete,
                on_task_aggregated=on_task_aggregated,
            )
        finally:
            self.planner.bind_usage_writer(None)
            self.aggregator.bind_usage_writer(None)
            self.reviewer.bind_usage_writer(None)
            usage_writer.append_total()

    async def run_with_plan(self, query: str, plan: Plan) -> dict[str, Any]:
        if not query or not query.strip():
            raise ValueError("query is required")
        self.workspace.prepare()
        usage_writer = LLMUsageWriter(
            self.workspace.session_dir / "output" / "llm_usage.jsonl",
            session_started_at=datetime.now(timezone.utc).isoformat().replace(
                "+00:00", "Z"
            ),
        )
        self.planner.bind_usage_writer(usage_writer)
        self.aggregator.bind_usage_writer(usage_writer)
        self.reviewer.bind_usage_writer(usage_writer)
        self.workspace.write_user_input(query)
        now_utc = datetime.now(timezone.utc)
        self.planner.bind_now_utc(now_utc)
        self.reviewer.bind_now_utc(now_utc)
        try:
            return await self._execute_plan(
                query=query,
                plan=plan,
                max_rounds=1,
                usage_writer=usage_writer,
            )
        finally:
            self.planner.bind_usage_writer(None)
            self.aggregator.bind_usage_writer(None)
            self.reviewer.bind_usage_writer(None)
            usage_writer.append_total()

    async def _run_round(
        self,
        query: str,
        plan: Plan,
        *,
        round_idx: int,
        usage_writer: LLMUsageWriter | None = None,
        on_leaf_start: LeafStartCallback | None = None,
        on_leaf_complete: LeafCompleteCallback | None = None,
        on_task_aggregated: TaskAggregatedCallback | None = None,
    ) -> tuple[dict[str, Any], Path, Path]:
        self.workspace.set_round(round_idx)
        self.workspace.write_plan(plan)
        execution = await self.executor.execute(
            query,
            plan,
            self.workspace,
            usage_writer=usage_writer,
            on_leaf_start=on_leaf_start,
            on_leaf_complete=on_leaf_complete,
        )
        try:
            aggregation = await self.aggregator.aggregate(
                query,
                plan,
                execution,
                self.workspace,
                on_task_aggregated=on_task_aggregated,
            )
        except Exception as exc:
            aggregation = self._aggregation_failure_payload(
                plan=plan,
                execution=execution,
                error=exc,
            )
        final_path = self.workspace.write_final(aggregation["final_markdown"])
        review = await self.reviewer.review(plan, execution, aggregation)
        review_payload = {
            **review,
            "status": "pass" if not review["actions"] else "fail",
            "round": round_idx,
        }
        review_path = self.workspace.write_review(review_payload)
        return review_payload, final_path, review_path

    def _aggregation_failure_payload(
        self,
        *,
        plan: Plan,
        execution: dict[str, Any],
        error: Exception,
    ) -> dict[str, Any]:
        task_map = {task.id: task for task in plan.tasks}
        leaf_ids = sorted(
            task_id
            for task_id in set(execution.get("leaf_completed_tasks") or [])
            if task_id in task_map and task_map[task_id].task_type == "leaf"
        )
        aggregated_query_unit_ids = sorted(
            {
                unit_id
                for task_id in leaf_ids
                for unit_id in task_map[task_id].query_unit_ids
            }
        )
        return {
            "final_markdown": "",
            "root_task_id": plan.root_task_id,
            "aggregated_leaf_task_ids": leaf_ids,
            "aggregated_query_unit_ids": aggregated_query_unit_ids,
            "final_included_leaf_task_ids": leaf_ids,
            "final_included_query_unit_ids": aggregated_query_unit_ids,
            "missing_contract_items": evaluate_contract(plan.contract, ""),
            "aggregation_error": f"{type(error).__name__}: {error}",
        }
