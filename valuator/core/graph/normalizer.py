"""Plan graph normalization utilities."""

from __future__ import annotations

from ..contracts.plan import Plan, Task
from .validator import validate_plan_graph


def ensure_recursive_graph(
    plan: Plan,
    allowed_tools: set[str] | None = None,
) -> Plan:
    """Normalize task types and guarantee a single-root DAG."""
    if not plan.tasks:
        raise ValueError("plan must include at least one task")

    normalized_tasks: list[Task] = []
    for task in plan.tasks:
        task_type = task.task_type
        if task_type == "leaf" and task.deps:
            task_type = "merge"

        tool = task.tool
        output = task.output
        query_unit_ids = list(task.query_unit_ids)
        if task_type == "merge":
            tool = None
            output = ""
            query_unit_ids = []

        normalized_tasks.append(
            task.model_copy(
                update={
                    "task_type": task_type,
                    "tool": tool,
                    "output": output,
                    "query_unit_ids": query_unit_ids,
                }
            )
        )

    normalized = plan.model_copy(update={"tasks": normalized_tasks})
    task_ids = {t.id for t in normalized.tasks}

    if normalized.root_task_id and normalized.root_task_id in task_ids:
        validate_plan_graph(normalized, allowed_tools)
        return normalized

    sinks = _sink_task_ids(normalized.tasks)
    if len(sinks) == 1:
        normalized = normalized.model_copy(update={"root_task_id": sinks[0]})
        validate_plan_graph(normalized, allowed_tools)
        return normalized

    root_id = _next_virtual_root_id(task_ids)
    root_task = Task(
        id=root_id,
        task_type="merge",
        deps=sinks,
        description="Virtual root synthesized for flat plan",
        merge_instruction="Merge child outputs recursively into one final narrative.",
    )
    upgraded = normalized.model_copy(
        update={
            "root_task_id": root_id,
            "tasks": [*normalized.tasks, root_task],
        }
    )
    validate_plan_graph(upgraded, allowed_tools)
    return upgraded


def _next_virtual_root_id(task_ids: set[str]) -> str:
    if "T-ROOT" not in task_ids:
        return "T-ROOT"
    suffix = 1
    while True:
        candidate = f"T-ROOT-{suffix}"
        if candidate not in task_ids:
            return candidate
        suffix += 1


def _sink_task_ids(tasks: list[Task]) -> list[str]:
    task_ids = {task.id for task in tasks}
    referenced = {dep for task in tasks for dep in task.deps if dep in task_ids}
    sinks = sorted(task_ids - referenced)
    if not sinks:
        raise ValueError("cannot synthesize root without sink tasks")
    return sinks
