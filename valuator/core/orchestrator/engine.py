from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...models.gemini_direct import GeminiClient
from ...utils.config import config
from ..aggregator.service import Aggregation
from ..contracts.plan import Plan
from ..llm_usage import LLMUsageWriter
from ..reviewer.service import Review
from ..executor.service import Executor
from ..graph.validator import validate_plan_graph
from ..planner.service import Planner
from ..workspace.service import Workspace


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

    async def run(self, query: str) -> dict[str, Any]:
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
            final_path: Path | None = None
            review_path: Path | None = None
            latest_review: dict[str, Any] | None = None

            for round_idx in range(1, self.max_rounds + 1):
                review_payload, final_path, review_path = await self._run_round(
                    query=query,
                    plan=plan,
                    round_idx=round_idx,
                    usage_writer=usage_writer,
                )
                status = review_payload["status"]
                latest_review = review_payload

                if status == "pass":
                    break
                if round_idx >= self.max_rounds:
                    break
                plan = await self.planner.replan(plan, review_payload)

            if final_path is None or review_path is None or latest_review is None:
                raise RuntimeError("engine did not produce final artifacts")

            return {
                "session_id": self.workspace.session_id,
                "coverage_feedback": latest_review["coverage_feedback"],
                "status": latest_review["status"],
                "final_path": str(final_path),
                "review_path": str(review_path),
            }
        finally:
            self.planner.bind_usage_writer(None)
            self.aggregator.bind_usage_writer(None)
            self.reviewer.bind_usage_writer(None)
            usage_writer.append_total()

    async def run_with_plan(self, query: str, plan: Plan) -> dict[str, Any]:
        if not query or not query.strip():
            raise ValueError("query is required")
        validate_plan_graph(plan)
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
            review_payload, final_path, review_path = await self._run_round(
                query,
                plan,
                round_idx=1,
                usage_writer=usage_writer,
            )
            return {
                "session_id": self.workspace.session_id,
                "coverage_feedback": review_payload["coverage_feedback"],
                "status": review_payload["status"],
                "final_path": str(final_path),
                "review_path": str(review_path),
            }
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
    ) -> tuple[dict[str, Any], Path, Path]:
        self.workspace.set_round(round_idx)
        self.workspace.write_plan(plan)
        execution = await self.executor.execute(
            query,
            plan,
            self.workspace,
            usage_writer=usage_writer,
        )
        aggregation = await self.aggregator.aggregate(
            query,
            plan,
            execution,
            self.workspace,
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
