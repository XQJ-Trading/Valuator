"""Plan graph validation utilities."""

from __future__ import annotations

from ..contracts.plan import Plan, Task


def validate_plan_graph(
    plan: Plan,
) -> None:
    """Run minimal structural checks required to traverse the graph safely."""
    if not plan.tasks:
        raise ValueError("plan must include tasks")

    unit_count = len(plan.query_units)
    task_ids: set[str] = set()
    task_map: dict[str, Task] = {}
    for task in plan.tasks:
        if task.id in task_ids:
            raise ValueError(f"duplicate task id: {task.id}")
        task_ids.add(task.id)
        task_map[task.id] = task

    root_task_id = plan.root_task_id
    if not root_task_id:
        raise ValueError("root_task_id is required")
    if root_task_id not in task_ids:
        raise ValueError(f"root_task_id not found: {root_task_id}")
    if task_map[root_task_id].task_type != "merge":
        raise ValueError(f"root_task_id must point to a merge task: {root_task_id}")

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
            if not task.query_unit_ids:
                raise ValueError(f"leaf task missing query_unit_ids: {task.id}")
            for unit_id in task.query_unit_ids:
                if unit_id < 0 or unit_id >= unit_count:
                    raise ValueError(
                        f"leaf task has invalid query_unit_id {unit_id}: {task.id}"
                    )
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

    state: dict[str, int] = {}

    def _visit(task_id: str) -> None:
        current = state.get(task_id, 0)
        if current == 1:
            raise ValueError("invalid task graph: cycle detected")
        if current == 2:
            return

        state[task_id] = 1
        task = task_map[task_id]
        for dep in task.deps:
            _visit(dep)
        state[task_id] = 2

    for task_id in task_ids:
        _visit(task_id)
