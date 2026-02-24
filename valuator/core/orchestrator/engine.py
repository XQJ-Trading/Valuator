from __future__ import annotations

from pathlib import Path
from typing import Any

from ...models.gemini_direct import GeminiClient
from ...utils.config import config
from ..aggregator.service import Aggregation
from ..contracts.plan import Plan
from ..critic.service import Review
from ..executor.service import Executor
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
        executor = Executor(client=client)
        aggregator = Aggregation(client=client)
        reviewer = Review()
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
        self.workspace.write_user_input(query)

        plan = await self.planner.plan(query)
        final_path: Path | None = None
        review_path: Path | None = None
        latest_review: dict[str, Any] = {}

        for round_idx in range(1, self.max_rounds + 1):
            self.workspace.set_round(round_idx)
            self.workspace.write_plan(plan)
            self.workspace.write_strategy(plan.analysis_strategy)

            execution = await self.executor.execute(query, plan, self.workspace)
            aggregation = await self.aggregator.aggregate(
                query,
                plan,
                execution,
                self.workspace,
            )

            final_path = self.workspace.write_final(aggregation["final_markdown"])
            review = await self.reviewer.review(plan, execution, aggregation)
            review["round"] = round_idx
            review_path = self.workspace.write_review(review)
            latest_review = review

            if review.get("status") == "pass":
                break
            if round_idx >= self.max_rounds:
                break
            plan = await self.planner.replan(query, plan, review)

        if final_path is None or review_path is None:
            raise RuntimeError("engine did not produce final artifacts")

        return {
            "session_id": self.workspace.session_id,
            "query_coverage": float(latest_review.get("query_coverage", 0.0)),
            "execution_coverage": float(latest_review.get("execution_coverage", 0.0)),
            "status": str(latest_review.get("status", "fail")),
            "final_path": str(final_path),
            "review_path": str(review_path),
        }

    async def run_with_plan(self, query: str, plan: Plan) -> dict[str, Any]:
        if not query or not query.strip():
            raise ValueError("query is required")
        self.workspace.prepare()
        self.workspace.write_user_input(query)
        self.workspace.set_round(1)
        self.workspace.write_plan(plan)
        self.workspace.write_strategy(plan.analysis_strategy)
        execution = await self.executor.execute(query, plan, self.workspace)
        aggregation = await self.aggregator.aggregate(
            query,
            plan,
            execution,
            self.workspace,
        )
        final_path = self.workspace.write_final(aggregation["final_markdown"])
        review = await self.reviewer.review(plan, execution, aggregation)
        review["round"] = 1
        review_path = self.workspace.write_review(review)
        return {
            "session_id": self.workspace.session_id,
            "query_coverage": float(review.get("query_coverage", 0.0)),
            "execution_coverage": float(review.get("execution_coverage", 0.0)),
            "status": str(review.get("status", "fail")),
            "final_path": str(final_path),
            "review_path": str(review_path),
        }
