from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from valuator.core.task import Task
from valuator.utils.time_utils import kst_isoformat

from .trace import task_rel_path


@dataclass(frozen=True)
class TaskTreeSnapshot:
    tree: dict[str, Any]
    plan_tasks: dict[str, dict[str, Any]]
    task_payloads: dict[str, dict[str, Any]]
    tree_markdown: str


def build_task_tree_snapshot(
    root_task: Task,
    *,
    root_task_id: str,
    unit_count: int,
    session_dir: Path,
    tasks_dir: Path,
    task_created_at: dict[str, str],
    task_artifacts: dict[str, dict[str, str | None]],
) -> TaskTreeSnapshot:
    plan_tasks: dict[str, dict[str, Any]] = {}
    task_payloads: dict[str, dict[str, Any]] = {}

    def build(task: Task) -> dict[str, Any]:
        created_at = task_created_at.setdefault(task.id, kst_isoformat())
        task_dir = tasks_dir / task_rel_path(task.id)
        children = task.children()
        task_type = "merge" if task.id == root_task_id or children else "leaf"
        query_unit_ids = list(task.query_unit_ids)
        if not query_unit_ids:
            query_unit_ids = (
                list(range(unit_count))
                if task.id == root_task_id
                else [0] if task_type == "leaf" and unit_count == 1 else []
            )

        tool = None
        if task_type == "leaf":
            if task.last_tool_request is not None:
                tool = {
                    "name": task.last_tool_request.tool_name,
                    "args": dict(task.last_tool_request.args),
                }
            elif task.execution_tool.strip():
                tool = {"name": task.execution_tool.strip(), "args": {}}
            elif task.tool_hint.strip():
                tool = {"name": task.tool_hint.strip(), "args": {}}

        artifacts = task_artifacts.setdefault(
            task.id,
            {
                "execution_result_path": None,
                "execution_meta_path": None,
                "aggregation_report_path": None,
                "aggregation_raw_results_path": None,
                "final_output_path": None,
            },
        )
        plan_tasks[task.id] = {
            "id": task.id,
            "task_type": task_type,
            "query_unit_ids": query_unit_ids,
            "deps": [child.id for child in children] if task_type == "merge" else [],
            "tool": tool,
            "output": "execution/result.md" if task_type == "leaf" else "",
            "description": task.description,
            "task_name": task.task_name,
            "execution_tool": task.execution_tool,
            "merge_instruction": "",
        }
        task_payloads[task.id] = {
            "task_id": task.id,
            "parent_id": task.parent_id,
            "description": task.description,
            "task_name": task.task_name,
            "execution_tool": task.execution_tool,
            "work_phase": task.work_phase.value,
            "state": task.state.value,
            "error": task.error,
            "created_at": created_at,
            "updated_at": kst_isoformat(),
            "task_type": task_type,
            "query_unit_ids": query_unit_ids,
            "deps": list(plan_tasks[task.id]["deps"]),
            "tool": tool,
            "output": plan_tasks[task.id]["output"],
            "merge_instruction": "",
            "children": [child.id for child in children],
            "artifacts": artifacts,
        }
        children_payload = [build(child) for child in children]
        return {
            "task_id": task.id,
            "description": task.description,
            "state": task.state.value,
            "path": str(task_dir.relative_to(session_dir)),
            "children": children_payload,
        }

    return TaskTreeSnapshot(
        tree=build(root_task),
        plan_tasks=plan_tasks,
        task_payloads=task_payloads,
        tree_markdown=render_tree_markdown(root_task),
    )


def render_tree_markdown(task: Task, depth: int = 0) -> str:
    indent = "  " * depth
    children = task.children()
    leaf_tool = task.execution_tool.strip() or task.tool_hint.strip()
    kind = f"leaf: {leaf_tool}" if not children and leaf_tool else ""
    suffix = f" ({kind})" if kind else ""
    name_snippet = (
        f" `{task.task_name.strip()}`" if str(task.task_name or "").strip() else ""
    )
    line = (
        f"{indent}- **{task.id}**{name_snippet} [{task.state.value}] "
        f"{task.description}{suffix}"
    )
    lines = [line]
    for child in children:
        lines.append(render_tree_markdown(child, depth + 1))
    return "\n".join(lines)
