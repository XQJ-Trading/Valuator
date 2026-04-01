from __future__ import annotations

import json
from typing import Any

from domain.query import QueryAnalysis, QueryUnit, summarize_temporal_contract
from valuator.tools.base import ToolRegistry

from ..context import TaskContext, TaskSummary
from ..scheduler import Scheduler
from ..shared_state import SharedState
from ..task import Task
from ..types import TaskState, ToolRequest


def build_task_context(
    *,
    task: Task,
    query: str,
    scheduler: Scheduler,
    analysis: QueryAnalysis,
    shared: SharedState,
    tools: ToolRegistry,
) -> TaskContext:
    query_units = query_units_for_task(task=task, analysis=analysis)
    return TaskContext(
        task_id=task.id,
        description=task.description,
        step_count=task.step_count,
        as_of_utc=analysis.as_of_utc,
        tool_results=list(task.tool_results),
        child_outputs=dict(task.child_outputs),
        current_children=[
            TaskSummary(
                id=child.id,
                description=child.description,
                state=child.state,
                output=child.completion_payload() if child.state is TaskState.DONE else None,
            )
            for child in task.children()
        ],
        ancestry=build_ancestry(task=task, scheduler=scheduler),
        siblings=build_siblings(task=task, scheduler=scheduler),
        shared=shared.view(),
        query=query,
        query_analysis=analysis,
        query_units=query_units,
        available_tools=analysis.allowed_tools or registered_tools(tools),
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
                output=parent.completion_payload() if parent.state is TaskState.DONE else None,
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
            output=sibling.completion_payload() if sibling.state is TaskState.DONE else None,
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


def enrich_tool_request(*, tool_request: Any, ctx: TaskContext) -> ToolRequest:
    args = dict(tool_request.args)
    temporal = summarize_temporal_contract(
        as_of_utc=ctx.as_of_utc,
        units=ctx.query_units,
    )
    if tool_request.tool_name in {"web_search_tool", "domain_tool"}:
        for key in ("as_of_utc", "time_scope", "target_start", "target_end"):
            value = getattr(temporal, key)
            if value:
                args.setdefault(key, value)
    if tool_request.tool_name == "domain_tool":
        context = str(args.get("context") or "").strip()
        if not context:
            context = domain_context(ctx)
            if context:
                args["context"] = context
        args["grounding_mode"] = "grounded_required" if context else "synthesis_only"

    return ToolRequest(tool_name=tool_request.tool_name, args=args)


def domain_context(ctx: TaskContext) -> str:
    if not ctx.shared.facts:
        return ""
    temporal = summarize_temporal_contract(
        as_of_utc=ctx.as_of_utc,
        units=ctx.query_units,
    )
    lines = [
        "[GROUNDING_FACTS]",
        f"as_of_utc={ctx.as_of_utc or '(unknown)'}",
    ]
    if temporal.time_scope:
        lines.append(f"time_scope={temporal.time_scope}")
    if temporal.target_start or temporal.target_end:
        lines.append(
            f"target_period={temporal.target_start or '(open)'}..{temporal.target_end or '(open)'}"
        )
    for key, fact in ctx.shared.facts.items():
        meta = [f"grounded={fact.grounded}"]
        if fact.time_scope:
            meta.append(f"time_scope={fact.time_scope}")
        if fact.target_start or fact.target_end:
            meta.append(
                "target=" f"{fact.target_start or '(open)'}..{fact.target_end or '(open)'}"
            )
        if fact.source_urls:
            meta.append(f"sources={len(fact.source_urls)}")
        value = json.dumps(fact.value, ensure_ascii=False, default=str)
        if len(value) > 400:
            value = value[:397] + "..."
        lines.append(f"- {key} [{', '.join(meta)}]: {value}")
    return "\n".join(lines)
