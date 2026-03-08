from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from ...domain import (
    DomainLoader,
    DomainModuleContext,
    DomainRouter,
    QueryIntent,
)
from ...models.gemini_direct import GeminiClient
from ...utils.config import config
from ..aggregator.service import Aggregation
from ..contracts.plan import Plan, ReviewResult
from ..llm_usage import LLMUsageWriter
from ..reviewer.service import Review
from ..executor.service import Executor
from ..planner.service import Planner
from ..workspace.service import Workspace
from .state import RoundState


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
        domain_loader: DomainLoader | None = None,
        domain_router: DomainRouter | None = None,
    ) -> None:
        if max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")
        self.workspace = workspace
        self.planner = planner
        self.executor = executor
        self.aggregator = aggregator
        self.reviewer = reviewer
        self.max_rounds = max_rounds
        self._domain_loader = domain_loader
        self._domain_router = domain_router

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
        domain_loader: DomainLoader | None = None
        domain_router: DomainRouter | None = None
        if config.domain_arch_enabled:
            domain_loader = DomainLoader()
            domain_router = DomainRouter()
        return cls(
            workspace=workspace,
            planner=planner,
            executor=executor,
            aggregator=aggregator,
            reviewer=reviewer,
            max_rounds=max_rounds,
            domain_loader=domain_loader,
            domain_router=domain_router,
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
        latest_review: ReviewResult | None = None

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
            status = review_payload.status
            latest_review = review_payload

            if status == "pass":
                break
            if round_idx >= max_rounds:
                break
            next_plan = await self.planner.replan(plan, review_payload)
            if next_plan == plan:
                break
            plan = next_plan

        if final_path is None or review_path is None or latest_review is None:
            raise RuntimeError("engine did not produce final artifacts")

        return {
            "session_id": self.workspace.session_id,
            "coverage_feedback": latest_review.coverage_feedback,
            "status": latest_review.status,
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
        if self._domain_router is not None:
            self._domain_router.bind_usage_writer(usage_writer)
        self.workspace.write_user_input(query)
        now_utc = datetime.now(timezone.utc)
        self.planner.bind_now_utc(now_utc)
        self.reviewer.bind_now_utc(now_utc)

        domain_context: DomainModuleContext | None = None
        if (
            config.domain_arch_enabled
            and self._domain_loader is not None
            and self._domain_router is not None
        ):
            index, modules = self._domain_loader.load()
            intent = QueryIntent(query=query)
            intent, analysis = await self._domain_router.analyze(intent, index, modules)
            selected_modules = {
                module_id: modules[module_id]
                for module_id in analysis.domain_ids
                if module_id in modules
            }
            domain_context = DomainModuleContext(
                module_ids=list(selected_modules),
                modules=selected_modules,
                query_intent=intent,
                query_analysis=analysis,
            )
            self.planner.bind_domain_context(domain_context)
            self.executor.bind_domain_context(domain_context)
            self.aggregator.bind_domain_context(domain_context)
            self.reviewer.bind_domain_context(domain_context)

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
            if self._domain_router is not None:
                self._domain_router.bind_usage_writer(None)
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
    ) -> tuple[ReviewResult, Path, Path]:
        self.workspace.set_round(round_idx)
        self.workspace.write_plan(plan)
        state = RoundState.from_plan(plan)

        while state.has_pending_tasks():
            progressed = await self._run_ready_executables(
                query=query,
                plan=plan,
                state=state,
                usage_writer=usage_writer,
                on_leaf_start=on_leaf_start,
                on_leaf_complete=on_leaf_complete,
                on_task_aggregated=on_task_aggregated,
            )
            while await self._run_ready_merges(
                query=query,
                plan=plan,
                state=state,
                on_task_aggregated=on_task_aggregated,
            ):
                progressed = True

            if not progressed:
                raise ValueError("task graph has unresolved phased dependencies")

        execution = state.execution_result()
        aggregation = self.aggregator.finalize_aggregation(
            plan=plan,
            task_map=state.task_map,
            artifact_materials=state.artifact_materials,
            artifact_index=state.artifact_index,
            reports=state.reports,
        )
        final_path = self.workspace.write_final(aggregation.final_markdown)
        review = await self.reviewer.review(plan, execution, aggregation)
        review_path = self.workspace.write_review(review)
        return review, final_path, review_path

    async def _run_ready_executables(
        self,
        *,
        query: str,
        plan: Plan,
        state: RoundState,
        usage_writer: LLMUsageWriter | None,
        on_leaf_start: LeafStartCallback | None,
        on_leaf_complete: LeafCompleteCallback | None,
        on_task_aggregated: TaskAggregatedCallback | None,
    ) -> bool:
        ready_task_ids = state.ready_executable_task_ids()
        if not ready_task_ids:
            return False

        artifacts = await self.executor.execute_batch(
            plan=plan,
            task_ids=ready_task_ids,
            workspace=self.workspace,
            usage_writer=usage_writer,
            on_leaf_start=on_leaf_start,
            on_leaf_complete=on_leaf_complete,
            dependency_reports=state.reports,
        )
        for artifact in artifacts:
            state.record_execution_artifact(artifact)
            await self._build_and_store_report(
                query=query,
                plan=plan,
                state=state,
                task_id=artifact.task_id,
                on_task_aggregated=on_task_aggregated,
            )
        return True

    async def _run_ready_merges(
        self,
        *,
        query: str,
        plan: Plan,
        state: RoundState,
        on_task_aggregated: TaskAggregatedCallback | None,
    ) -> bool:
        ready_task_ids = state.ready_merge_task_ids()
        if not ready_task_ids:
            return False

        for task_id in ready_task_ids:
            await self._build_and_store_report(
                query=query,
                plan=plan,
                state=state,
                task_id=task_id,
                on_task_aggregated=on_task_aggregated,
            )
        return True

    async def _build_and_store_report(
        self,
        *,
        query: str,
        plan: Plan,
        state: RoundState,
        task_id: str,
        on_task_aggregated: TaskAggregatedCallback | None,
    ) -> None:
        report = await self.aggregator.build_task_report(
            query=query,
            plan=plan,
            task_id=task_id,
            task_map=state.task_map,
            artifact_materials=state.artifact_materials,
            artifact_index=state.artifact_index,
            reports=state.reports,
        )
        state.record_task_report(report)
        self.workspace.write_aggregation_report(task_id, report.markdown)
        if on_task_aggregated is not None:
            await on_task_aggregated(
                state.task_map[task_id],
                state.completed_task_count,
                state.total_tasks,
            )
