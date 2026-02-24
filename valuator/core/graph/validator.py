"""Plan graph validation utilities."""

from __future__ import annotations

from collections import defaultdict

from ..contracts.plan import Plan, Task


def validate_plan_graph(
    plan: Plan,
    allowed_tools: set[str] | None = None,
) -> None:
    """Raise ValueError if the plan graph is structurally invalid."""
    if not plan.tasks:
        raise ValueError("plan must include tasks")

    task_ids: set[str] = set()
    for task in plan.tasks:
        if task.id in task_ids:
            raise ValueError(f"duplicate task id: {task.id}")
        task_ids.add(task.id)

    if not plan.root_task_id:
        raise ValueError("plan must define root_task_id")
    if plan.root_task_id not in task_ids:
        raise ValueError(f"root_task_id not found: {plan.root_task_id}")

    task_map = {task.id: task for task in plan.tasks}
    root = task_map[plan.root_task_id]
    if root.task_type != "merge":
        raise ValueError(f"root_task_id must point to a merge task: {plan.root_task_id}")

    for task in plan.tasks:
        if len(task.deps) != len(set(task.deps)):
            raise ValueError(f"duplicate deps in task {task.id}")
        for dep in task.deps:
            if dep == task.id:
                raise ValueError(f"self dependency is not allowed: {task.id}")
            if dep not in task_map:
                raise ValueError(f"missing dependency {dep} in task {task.id}")

        if task.task_type == "merge" and not task.deps:
            raise ValueError(f"merge task must declare deps: {task.id}")

        if task.task_type == "leaf":
            if not task.tool:
                raise ValueError(f"leaf task must define tool: {task.id}")
            if allowed_tools and task.tool.name not in allowed_tools:
                raise ValueError(
                    f"unsupported leaf tool '{task.tool.name}' for task {task.id}"
                )
            if not task.output:
                raise ValueError(f"leaf task must define output: {task.id}")
        else:
            if task.tool is not None:
                raise ValueError(f"merge task must not define tool: {task.id}")
            if task.output:
                raise ValueError(f"merge task must not define output: {task.id}")

    _validate_cycle_free(plan.tasks)
    _validate_root_reachability(plan.tasks, plan.root_task_id)


def _validate_cycle_free(tasks: list[Task]) -> None:
    task_map = {task.id: task for task in tasks}
    state: dict[str, int] = {}

    def visit(task_id: str) -> None:
        current = state.get(task_id, 0)
        if current == 1:
            raise ValueError("invalid plan graph: cycle detected")
        if current == 2:
            return
        state[task_id] = 1
        for dep in task_map[task_id].deps:
            visit(dep)
        state[task_id] = 2

    for task_id in sorted(task_map):
        visit(task_id)


def _validate_root_reachability(tasks: list[Task], root_task_id: str) -> None:
    deps_by_task: dict[str, list[str]] = defaultdict(list)
    for task in tasks:
        for dep in task.deps:
            deps_by_task[task.id].append(dep)

    visited: set[str] = set()
    stack = [root_task_id]
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        stack.extend(deps_by_task.get(current, []))

    all_ids = {task.id for task in tasks}
    missing = sorted(all_ids - visited)
    if missing:
        raise ValueError(
            "every task must contribute to root; unreachable tasks: "
            + ", ".join(missing)
        )
