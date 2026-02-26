from __future__ import annotations

from pathlib import Path
from typing import Any

from ...models.gemini_direct import GeminiClient
from ...utils.config import config
from ..aggregator.service import Aggregation
from ..contracts.plan import Plan
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
        self.workspace.write_user_input(query)

        plan = await self.planner.plan(query)
        final_path: Path | None = None
        review_path: Path | None = None
        latest_review: dict[str, Any] = {}

        for round_idx in range(1, self.max_rounds + 1):
            self.workspace.set_round(round_idx)
            self.workspace.write_plan(plan)

            execution = await self.executor.execute(query, plan, self.workspace)
            aggregation = await self.aggregator.aggregate(
                query,
                plan,
                execution,
                self.workspace,
            )

            final_path = self.workspace.write_final(aggregation["final_markdown"])
            review = await self.reviewer.review(plan, execution, aggregation)
            review["actions"] = self._require_action_list(review.get("actions"))
            status = "pass" if not review["actions"] else "fail"
            review["status"] = status
            review["round"] = round_idx
            review_path = self.workspace.write_review(review)
            latest_review = review

            if status == "pass":
                break
            if round_idx >= self.max_rounds:
                break
            plan = await self.planner.replan(plan, review)

        if final_path is None or review_path is None:
            raise RuntimeError("engine did not produce final artifacts")

        return {
            "session_id": self.workspace.session_id,
            "coverage_feedback": latest_review.get("coverage_feedback", {}),
            "status": str(latest_review.get("status", "fail")),
            "final_path": str(final_path),
            "review_path": str(review_path),
        }

    async def run_with_plan(self, query: str, plan: Plan) -> dict[str, Any]:
        if not query or not query.strip():
            raise ValueError("query is required")
        validate_plan_graph(plan)
        self.workspace.prepare()
        self.workspace.write_user_input(query)
        self.workspace.set_round(1)
        self.workspace.write_plan(plan)
        execution = await self.executor.execute(query, plan, self.workspace)
        aggregation = await self.aggregator.aggregate(
            query,
            plan,
            execution,
            self.workspace,
        )
        final_path = self.workspace.write_final(aggregation["final_markdown"])
        review = await self.reviewer.review(plan, execution, aggregation)
        review["actions"] = self._require_action_list(review.get("actions"))
        review["status"] = "pass" if not review["actions"] else "fail"
        review["round"] = 1
        review_path = self.workspace.write_review(review)
        return {
            "session_id": self.workspace.session_id,
            "coverage_feedback": review.get("coverage_feedback", {}),
            "status": str(review.get("status", "fail")),
            "final_path": str(final_path),
            "review_path": str(review_path),
        }

    def _require_action_list(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise ValueError("review.actions must be list[{'node': int, 'reason': str}]")
        reason_by_node: dict[int, list[str]] = {}
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("review.actions must be list[{'node': int, 'reason': str}]")
            node = item.get("node")
            reason = item.get("reason")
            if (
                not isinstance(node, int)
                or isinstance(node, bool)
                or node < 0
                or not isinstance(reason, str)
                or not reason.strip()
            ):
                raise ValueError("review.actions must be list[{'node': int, 'reason': str}]")
            reason_by_node.setdefault(node, []).append(reason.strip())
        actions: list[dict[str, Any]] = []
        for node in sorted(reason_by_node):
            dedup = list(dict.fromkeys(reason_by_node[node]))
            actions.append({"node": node, "reason": " ".join(dedup)})
        return actions
