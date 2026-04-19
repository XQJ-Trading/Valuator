from __future__ import annotations

from typing import Any

from domain.query import QueryAnalysis, QueryUnit, summarize_temporal_contract
from valuator.evidence import SqliteEvidenceStore
from valuator.tools.base import ToolRegistry

from ..context import TaskContext, TaskSummary
from ..scheduler import Scheduler
from ..shared_state import SharedState
from ..task import ComplexTask, Task
from ..types import TaskState, TaskWorkPhase, ToolRequest


def _fact_keys_from_child_completion_payload(payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    if payload.get("status") == "facts_only" and isinstance(payload.get("facts"), dict):
        return set(payload["facts"].keys())
    return set()


def _task_scoped_evidence(
    *,
    task: Task,
    scheduler: Scheduler,
    evidence_rows: list[Any],
) -> list[Any]:
    if not evidence_rows or task.parent_id is None:
        return evidence_rows

    related_task_ids = {task.id}
    parent_id = task.parent_id
    while parent_id:
        related_task_ids.add(parent_id)
        parent = scheduler.get_task(parent_id)
        if parent is None:
            break
        parent_id = parent.parent_id

    descendant_prefix = f"{task.id}."
    scoped: list[Any] = []
    for row in evidence_rows:
        row_task_id = getattr(row, "task_id", "") or ""
        if not row_task_id:
            scoped.append(row)
            continue
        if row_task_id in related_task_ids or row_task_id.startswith(descendant_prefix):
            scoped.append(row)
    return scoped


def build_task_context(
    *,
    task: Task,
    query: str,
    scheduler: Scheduler,
    analysis: QueryAnalysis,
    shared: SharedState,
    tools: ToolRegistry,
    evidence_store: SqliteEvidenceStore | None = None,
    evidence_session_id: str = "",
) -> TaskContext:
    query_units = query_units_for_task(task=task, analysis=analysis)
    evidence_rows = (
        evidence_store.list_for_session(evidence_session_id)
        if evidence_store is not None and evidence_session_id
        else []
    )
    include_fact_keys: frozenset[str] | None = None
    if (
        isinstance(task, ComplexTask)
        and task.work_phase is TaskWorkPhase.SYNTHESIZE
        and task.child_outputs
    ):
        from_child: set[str] = set()
        for payload in task.child_outputs.values():
            from_child |= _fact_keys_from_child_completion_payload(payload)
        if from_child:
            relevant = shared.relevant_fact_keys_for(
                task_id=task.id,
                query_unit_ids=task.query_unit_ids,
            )
            include_fact_keys = frozenset(relevant - from_child)
    return TaskContext(
        task_id=task.id,
        description=task.description,
        step_count=task.step_count,
        as_of_kst=analysis.as_of_kst,
        tool_results=list(task.tool_results),
        child_outputs=dict(task.child_outputs),
        current_children=[
            TaskSummary(
                id=child.id,
                description=child.description,
                state=child.state,
                output=(
                    child.completion_payload()
                    if (
                        child.state is TaskState.DONE
                        and child.id not in task.child_outputs
                    )
                    else None
                ),
            )
            for child in task.children()
        ],
        ancestry=build_ancestry(task=task, scheduler=scheduler),
        siblings=build_siblings(task=task, scheduler=scheduler),
        shared=shared.view_for(
            task_id=task.id,
            query_unit_ids=task.query_unit_ids,
            include_fact_keys=include_fact_keys,
        ),
        query=query,
        query_analysis=analysis,
        query_units=query_units,
        available_tools=analysis.allowed_tools or registered_tools(tools),
        evidence=_task_scoped_evidence(
            task=task,
            scheduler=scheduler,
            evidence_rows=evidence_rows,
        ),
    )


def build_ancestry(*, task: Task, scheduler: Scheduler) -> list[TaskSummary]:
    ancestry: list[TaskSummary] = []
    parent_id = task.parent_id
    while parent_id:
        parent = scheduler.get_task(parent_id)
        if parent is None:
            break
        ancestry.append(
            TaskSummary(
                id=parent.id,
                description=parent.description,
                state=parent.state,
                output=(
                    parent.completion_payload()
                    if parent.state is TaskState.DONE
                    else None
                ),
            )
        )
        parent_id = parent.parent_id
    return ancestry


def build_siblings(*, task: Task, scheduler: Scheduler) -> dict[str, TaskSummary]:
    if not task.parent_id:
        return {}
    parent = scheduler.get_task(task.parent_id)
    if parent is None:
        return {}
    return {
        sibling.id: TaskSummary(
            id=sibling.id,
            description=sibling.description,
            state=sibling.state,
            output=(
                sibling.completion_payload()
                if sibling.state is TaskState.DONE
                else None
            ),
        )
        for sibling in parent.children()
        if sibling.id != task.id
    }


def registered_tools(tools: ToolRegistry) -> list[str]:
    return sorted(
        str(tool_info["name"])
        for tool_info in tools.list_tools()
        if isinstance(tool_info, dict) and "name" in tool_info
    )


def query_units_for_task(*, task: Task, analysis: QueryAnalysis) -> list[QueryUnit]:
    if not analysis.units:
        return []
    if task.query_unit_ids:
        return [
            analysis.units[index]
            for index in task.query_unit_ids
            if 0 <= index < len(analysis.units)
        ]
    if len(analysis.units) == 1:
        return [analysis.units[0]]
    return []


# Tools whose args receive temporal fields here must match evidence lookup/record keys
# (same dict passed to stable_args_hash after this enrichment).
_TEMPORAL_ENRICH_TOOLS = frozenset({"web_search_tool"})


def enrich_tool_request(*, tool_request: Any, ctx: TaskContext) -> ToolRequest:
    args = dict(tool_request.args)
    temporal = summarize_temporal_contract(
        as_of_kst=ctx.as_of_kst,
        units=ctx.query_units,
    )
    if tool_request.tool_name in _TEMPORAL_ENRICH_TOOLS:
        for key in ("as_of_kst", "time_scope", "target_start", "target_end"):
            value = getattr(temporal, key)
            if value:
                args.setdefault(key, value)

    return ToolRequest(tool_name=tool_request.tool_name, args=args)
