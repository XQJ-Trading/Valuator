from __future__ import annotations

from typing import Any

from ..contracts.plan import Task
from .graph_ops import descendant_leaf_artifacts


def extract_leaf_artifacts(execution: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    raw = execution.get("artifacts", [])
    by_task: dict[str, list[dict[str, str]]] = {}
    for item in raw:
        task_id = item.get("task_id", "").strip()
        path = item.get("path", "").strip()
        if not task_id or not path:
            continue
        by_task.setdefault(task_id, []).append(
            {
                "path": path,
                "content": item.get("content", ""),
            }
        )
    return by_task


def collect_materials(
    task: Task,
    task_map: dict[str, Task],
    leaf_artifacts: dict[str, list[dict[str, str]]],
    reports: dict[str, dict[str, Any]],
    descendant_cache: dict[str, list[dict[str, str]]],
) -> list[dict[str, str]]:
    _ = reports
    return list(
        descendant_leaf_artifacts(
            task.id, task_map, leaf_artifacts, descendant_cache
        )
    )


def query_unit_ids_for_leaf_tasks(
    leaf_task_ids: list[str],
    task_map: dict[str, Task],
) -> list[int]:
    query_units: set[int] = set()
    for task_id in leaf_task_ids:
        task = task_map.get(task_id)
        if not task:
            continue
        for unit_id in task.query_unit_ids:
            if unit_id >= 0:
                query_units.add(unit_id)
    return sorted(query_units)
