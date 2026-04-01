from __future__ import annotations

from dataclasses import asdict
from typing import Any

from valuator.utils.time_utils import utc_isoformat

from ..context import TaskContext, TaskSummary
from ..task import Task
from ..types import Action, TaskDecision


def log_step_decision(
    writer: Any | None,
    *,
    task: Task,
    task_seq: int,
    ctx: TaskContext,
    status: str,
    started_at: str,
    duration_ms: float,
    decision: TaskDecision | None = None,
    error: str | None = None,
) -> None:
    if writer is None:
        return

    if decision is None:
        result_payload: dict[str, Any] = {"error": error}
    else:
        result_payload = decision_payload(decision)
        if error is not None:
            result_payload["error"] = error

    if decision is None:
        summary = error or "step decision failed"
    else:
        summary = f"action={decision.action.value}"
        if error is not None:
            summary = f"{summary} error={error}"

    children_created = None
    if decision is not None and decision.action is Action.DECOMPOSE:
        children_created = [child["id"] for child in planned_child_records(task, decision)]
        result_payload["children"] = planned_child_records(task, decision)

    tool_name = None
    tool_args = None
    if decision is not None and decision.tool_request is not None:
        tool_name = decision.tool_request.tool_name
        tool_args = decision.tool_request.args

    writer.write_task_step(
        task_id=task.id,
        task_seq=task_seq,
        phase="decision",
        status=status,
        action=decision.action.value if decision is not None else None,
        summary=summary,
        started_at=started_at,
        duration_ms=round(duration_ms, 3),
        tool_name=tool_name,
        tool_args=tool_args,
        children_created=children_created,
        wait_for=list(decision.wait_for) if decision is not None else None,
        input_payload=decision_input_payload(task, ctx),
        result_payload=result_payload,
        error=error,
    )


def log_tool_execution(
    writer: Any | None,
    *,
    task_id: str,
    task_seq: int,
    tool_name: str,
    args: dict[str, Any],
    result: Any,
    started_at: str,
    duration_ms: float,
) -> None:
    if writer is None:
        return

    writer.write_task_step(
        task_id=task_id,
        task_seq=task_seq,
        phase="tool_result",
        status="success" if bool(result.success) else "failed",
        action=Action.EXECUTE.value,
        summary=f"tool={tool_name} success={bool(result.success)}",
        started_at=started_at,
        duration_ms=round(duration_ms, 3),
        tool_name=tool_name,
        tool_args=args,
        tool_success=bool(result.success),
        input_payload={"tool_name": tool_name, "args": args},
        result_payload=result.model_dump(),
        error=result.error,
    )


def log_task_result(
    writer: Any | None,
    task: Task,
    *,
    task_seq: int,
    action: str | None,
    status: str,
    output: Any = None,
    error: str | None = None,
) -> None:
    if writer is None:
        return

    summary = task.state.value
    if error:
        summary = error

    writer.write_task_step(
        task_id=task.id,
        task_seq=task_seq,
        phase="task_result",
        status=status,
        action=action,
        summary=summary,
        started_at=utc_isoformat(),
        duration_ms=0.0,
        input_payload=task_runtime_payload(task),
        result_payload={
            "state": task.state.value,
            "output": output,
            "error": error,
        },
        error=error,
    )


def decision_input_payload(task: Task, ctx: TaskContext) -> dict[str, Any]:
    return {
        "task": task_runtime_payload(task),
        "context": {
            "query": ctx.query,
            "available_tools": list(ctx.available_tools),
            "tool_results": [result.model_dump() for result in ctx.tool_results],
            "child_outputs": dict(ctx.child_outputs),
            "ancestry": [task_summary_payload(item) for item in ctx.ancestry],
            "siblings": {
                task_id: task_summary_payload(summary) for task_id, summary in ctx.siblings.items()
            },
            "shared": {
                "facts": {key: asdict(fact) for key, fact in ctx.shared.facts.items()},
                "conflicts": [asdict(conflict) for conflict in ctx.shared.conflicts],
            },
        },
    }


def decision_payload(decision: TaskDecision) -> dict[str, Any]:
    payload = asdict(decision)
    payload["action"] = decision.action.value
    return payload


def task_runtime_payload(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "description": task.description,
        "state": task.state.value,
        "parent_id": task.parent_id,
        "step_count": task.step_count,
        "invalid_decision_count": task.invalid_decision_count,
        "tool_hint": task.tool_hint,
        "last_tool_request": (
            {
                "tool_name": task.last_tool_request.tool_name,
                "args": dict(task.last_tool_request.args),
            }
            if task.last_tool_request is not None
            else None
        ),
        "last_tool_success": task.last_tool_success,
        "last_invalid_error": task.last_invalid_error,
        "child_output_ids": sorted(task.child_outputs),
        "tool_result_count": len(task.tool_results),
    }


def task_summary_payload(summary: TaskSummary) -> dict[str, Any]:
    return {
        "id": summary.id,
        "description": summary.description,
        "state": summary.state.value,
        "output": summary.output,
    }


def planned_child_records(task: Task, decision: TaskDecision) -> list[dict[str, Any]]:
    start_index = len(task.children())
    return [
        {
            "id": f"{task.id}.{start_index + offset}",
            "description": child.description,
            "tool_hint": child.tool_hint,
        }
        for offset, child in enumerate(decision.children)
    ]
