from __future__ import annotations

from ..contracts.plan import Plan, Task


def post_order_tasks(plan: Plan) -> list[str]:
    task_map = {task.id: task for task in plan.tasks}
    state: dict[str, int] = {}
    order: list[str] = []

    def visit(task_id: str) -> None:
        current = state.get(task_id, 0)
        if current == 1:
            raise ValueError("invalid task graph: cycle detected")
        if current == 2:
            return
        state[task_id] = 1
        for dep in sorted(task_map[task_id].deps):
            if dep not in task_map:
                raise ValueError(f"invalid task graph: missing dependency {dep}")
            visit(dep)
        state[task_id] = 2
        order.append(task_id)

    for task_id in sorted(task_map):
        visit(task_id)
    return order


def infer_root_task_id(tasks: list[Task]) -> str:
    task_ids = {task.id for task in tasks}
    deps = {dep for task in tasks for dep in task.deps}
    sinks = sorted(task_ids - deps)
    if len(sinks) != 1:
        raise ValueError("cannot infer single root task")
    return sinks[0]


def descendant_leaf_artifacts(
    task_id: str,
    task_map: dict[str, Task],
    leaf_artifacts: dict[str, list[dict[str, str]]],
    cache: dict[str, list[dict[str, str]]],
) -> list[dict[str, str]]:
    if task_id in cache:
        return cache[task_id]

    task = task_map[task_id]
    if task.task_type == "leaf":
        result = [
            {"source": artifact["path"], "content": artifact["content"]}
            for artifact in leaf_artifacts.get(task_id, [])
        ]
        cache[task_id] = result
        return result

    result: list[dict[str, str]] = []
    seen_sources: set[str] = set()
    for dep in task.deps:
        for item in descendant_leaf_artifacts(dep, task_map, leaf_artifacts, cache):
            if item["source"] in seen_sources:
                continue
            result.append(item)
            seen_sources.add(item["source"])

    cache[task_id] = result
    return result


def descendant_leaf_task_ids(root_task_id: str, task_map: dict[str, Task]) -> set[str]:
    cache: dict[str, set[str]] = {}

    def collect(task_id: str) -> set[str]:
        if task_id in cache:
            return cache[task_id]
        if task_id not in task_map:
            raise ValueError(f"invalid task graph: missing task {task_id}")

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
