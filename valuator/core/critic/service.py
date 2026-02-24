from __future__ import annotations

from typing import Any

from ..contracts.plan import Plan


class Review:
    def __init__(self) -> None:
        pass

    async def review(
        self,
        plan: Plan,
        execution: dict,
        aggregation: dict,
    ) -> dict[str, Any]:
        required_units = set(range(len(plan.query_units)))
        aggregated_units = self._normalized_int_set(
            aggregation.get("aggregated_query_unit_ids", []),
            upper_bound=len(plan.query_units),
        )
        covered_units = required_units & aggregated_units

        query_coverage = 1.0
        if required_units:
            query_coverage = len(covered_units) / len(required_units)

        execution_leaves = self._normalized_str_set(execution.get("leaf_completed_tasks", []))
        aggregated_leaves = self._normalized_str_set(aggregation.get("aggregated_leaf_task_ids", []))
        if execution_leaves:
            execution_coverage = len(execution_leaves & aggregated_leaves) / len(execution_leaves)
        else:
            execution_coverage = 1.0

        missing_query_units = sorted(required_units - covered_units)
        missing_execution_tasks = sorted(execution_leaves - aggregated_leaves)

        actions: list[dict[str, Any]] = []
        if missing_query_units:
            actions.append(
                {"type": "add_tasks_for_query_units", "values": missing_query_units}
            )
        if missing_execution_tasks:
            actions.append(
                {
                    "type": "include_execution_outputs_in_aggregation",
                    "values": missing_execution_tasks,
                }
            )

        status = "pass"
        failure_reasons: list[str] = []
        if query_coverage < 1.0:
            status = "fail"
            failure_reasons.append("query coverage is incomplete")
        if execution_coverage < 1.0:
            status = "fail"
            failure_reasons.append("execution coverage is incomplete in aggregation")
        if aggregation.get("root_report") is None:
            status = "fail"
            failure_reasons.append("aggregation did not produce root report")

        return {
            "query_coverage": round(query_coverage, 3),
            "execution_coverage": round(execution_coverage, 3),
            "missing_query_units": missing_query_units,
            "missing_execution_tasks": missing_execution_tasks,
            "status": status,
            "failure_reason": "; ".join(failure_reasons),
            "actions": actions,
            "round": 0,
        }

    def _normalized_int_set(self, value: Any, upper_bound: int) -> set[int]:
        if not isinstance(value, list):
            return set()
        normalized: set[int] = set()
        for item in value:
            if not isinstance(item, int):
                continue
            if item < 0:
                continue
            if item >= upper_bound:
                continue
            normalized.add(item)
        return normalized

    def _normalized_str_set(self, value: Any) -> set[str]:
        if not isinstance(value, list):
            return set()
        normalized: set[str] = set()
        for item in value:
            text = str(item).strip()
            if text:
                normalized.add(text)
        return normalized
