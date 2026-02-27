"""Plan graph validation utilities."""

from __future__ import annotations

from ..contracts.plan import Plan


def validate_plan_graph(
    plan: Plan,
) -> None:
    """Run minimal structural checks required to traverse the graph safely."""
    if not plan.tasks:
        raise ValueError("plan must include tasks")

    task_ids: set[str] = set()
    for task in plan.tasks:
        if task.id in task_ids:
            raise ValueError(f"duplicate task id: {task.id}")
        task_ids.add(task.id)

    if plan.root_task_id and plan.root_task_id not in task_ids:
        raise ValueError(f"root_task_id not found: {plan.root_task_id}")

    for task in plan.tasks:
        for dep in task.deps:
            if dep not in task_ids:
                raise ValueError(f"missing dependency {dep} in task {task.id}")

    for task in plan.tasks:
        if task.task_type == "leaf":
            if task.tool is None:
                raise ValueError(f"leaf task missing tool: {task.id}")
            if task.deps:
                raise ValueError(f"leaf task must not have deps: {task.id}")
            if not task.output.strip():
                raise ValueError(f"leaf task missing output path: {task.id}")
            continue

        if task.task_type == "merge":
            if task.tool is not None:
                raise ValueError(f"merge task must not include tool: {task.id}")
            if task.query_unit_ids:
                raise ValueError(f"merge task must not include query_unit_ids: {task.id}")
            if task.output.strip():
                raise ValueError(f"merge task must not include output: {task.id}")
