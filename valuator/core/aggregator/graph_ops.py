from __future__ import annotations

from ..contracts.plan import Plan, Task


def post_order_tasks(plan: Plan) -> list[str]:
    task_map = {task.id: task for task in plan.tasks}
    visited: set[str] = set()
    order: list[str] = []

    def visit(task_id: str) -> None:
        if task_id in visited:
            return
        for dep in sorted(task_map[task_id].deps):
            visit(dep)
        visited.add(task_id)
        order.append(task_id)

    for task_id in sorted(task_map):
        visit(task_id)
    return order


def descendant_leaf_task_ids(root_task_id: str, task_map: dict[str, Task]) -> set[str]:
    cache: dict[str, set[str]] = {}

    def collect(task_id: str) -> set[str]:
        if task_id in cache:
            return cache[task_id]
        task = task_map[task_id]
        if task.task_type == "leaf":
            cache[task_id] = {task_id}
            return cache[task_id]

        leaf_ids: set[str] = set()
        for dep in task.deps:
            leaf_ids.update(collect(dep))
        cache[task_id] = leaf_ids
        return leaf_ids

    return collect(root_task_id)


def descendant_artifact_task_ids(root_task_id: str, task_map: dict[str, Task]) -> set[str]:
    cache: dict[str, set[str]] = {}

    def collect(task_id: str) -> set[str]:
        if task_id in cache:
            return cache[task_id]
        task = task_map[task_id]
        if task.task_type != "merge":
            cache[task_id] = {task_id}
            return cache[task_id]

        artifact_ids: set[str] = set()
        for dep in task.deps:
            artifact_ids.update(collect(dep))
        cache[task_id] = artifact_ids
        return artifact_ids

    return collect(root_task_id)
