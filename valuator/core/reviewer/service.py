"""Reviewer service: LLM-first with fail-fast validation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...models.gemini_direct import GeminiClient
from ...utils.config import config
from ..contracts.plan import Plan, Task
from ..contracts.requirement import evaluate_contract

from .prompts import (
    REVIEWER_SYSTEM,
    build_reviewer_response_json_schema,
    build_reviewer_user_prompt,
)


class Reviewer:
    def __init__(self, client: GeminiClient | None = None) -> None:
        self.client = client or GeminiClient(config.agent_model)
        self._now_utc_iso: str | None = None

    def bind_now_utc(self, now_utc: datetime) -> None:
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        self._now_utc_iso = now_utc.astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        self.client.bind_usage_writer(usage_writer)

    async def review(
        self, plan: Plan, execution: dict, aggregation: dict
    ) -> dict[str, Any]:
        final_markdown = aggregation.get("final_markdown", "")
        now_utc = self._now_utc_iso or self._current_now_utc_iso()
        unit_count = len(plan.query_units)
        from_agg = aggregation.get("missing_contract_items")
        if from_agg is None:
            missing_contract_items = evaluate_contract(plan.contract, final_markdown)
        else:
            missing_contract_items = from_agg

        item_map = {item.id: item for item in plan.contract.items} if plan.contract else {}
        leaf_tasks = {
            task.id: task for task in plan.tasks if task.task_type == "leaf"
        }
        completed_leaf_ids = set(execution.get("leaf_completed_tasks") or [])
        missing_leaf_task_ids = sorted(set(leaf_tasks) - completed_leaf_ids)
        mapped_units = {
            node
            for task in leaf_tasks.values()
            for node in task.query_unit_ids
        }
        units_without_leaf_mapping = [
            node for node in range(unit_count) if node not in mapped_units
        ]
        final_empty = not final_markdown.strip()

        candidate_nodes = self._candidate_action_nodes(
            unit_count=unit_count,
            missing_contract_items=missing_contract_items,
            item_map=item_map,
            leaf_tasks=leaf_tasks,
            missing_leaf_task_ids=missing_leaf_task_ids,
            units_without_leaf_mapping=units_without_leaf_mapping,
            final_empty=final_empty,
        )
        candidate_actions = [{"node": node} for node in candidate_nodes]
        signals = {
            "missing_mapping": len(units_without_leaf_mapping),
            "missing_leaf": len(missing_leaf_task_ids),
            "missing_contract": len(missing_contract_items),
            "final_empty": final_empty,
            "action_nodes_total": len(candidate_nodes),
        }
        aggregation_error = str(aggregation.get("aggregation_error") or "").strip()
        if aggregation_error:
            signals["aggregation_error"] = 1

        user_prompt = build_reviewer_user_prompt(
            query=plan.query,
            query_units=plan.query_units or [],
            candidate_actions=candidate_actions,
            diagnostics={
                "signals": signals,
                "missing_contract_items": missing_contract_items,
                "missing_leaf_task_ids": missing_leaf_task_ids,
                "units_without_leaf_mapping": units_without_leaf_mapping,
                "aggregation_error": aggregation_error,
            },
            final_markdown=final_markdown,
            now_utc=now_utc,
        )
        response_schema = build_reviewer_response_json_schema(
            max_node=max(unit_count - 1, 0)
        )

        data = await self.client.generate_json(
            prompt=user_prompt,
            system_prompt=REVIEWER_SYSTEM,
            response_json_schema=response_schema,
            trace_method="reviewer.review",
        )
        actions = self._collapse_actions(data["actions"], unit_count)
        self_assessment = data["self_assessment"]
        quant_axes = data["quant_axes"]

        coverage_feedback = self._build_coverage_feedback(
            signals=signals,
            self_assessment=self_assessment,
        )
        return {
            "actions": actions,
            "coverage_feedback": coverage_feedback,
            "now_utc": now_utc,
            "quant_axes": quant_axes,
        }

    def _candidate_action_nodes(
        self,
        *,
        unit_count: int,
        missing_contract_items: list[str],
        item_map: dict[str, Any],
        leaf_tasks: dict[str, Task],
        missing_leaf_task_ids: list[str],
        units_without_leaf_mapping: list[int],
        final_empty: bool,
    ) -> list[int]:
        if unit_count <= 0:
            return []

        nodes: set[int] = set()
        for item_id in missing_contract_items:
            item = item_map.get(item_id)
            if item is not None:
                nodes.add(item.unit_id)

        for node in units_without_leaf_mapping:
            nodes.add(node)

        for task_id in missing_leaf_task_ids:
            task = leaf_tasks[task_id]
            for node in task.query_unit_ids:
                nodes.add(node)

        if final_empty:
            return list(range(unit_count))
        return sorted(nodes)

    def _build_coverage_feedback(
        self, *, signals: dict[str, Any], self_assessment: dict[str, Any]
    ) -> dict[str, Any]:
        decomposition = self_assessment["decomposition"]["verdict"]
        execution = self_assessment["execution"]["verdict"]
        propagation = self_assessment["propagation"]["verdict"]
        summary = (
            f"decomposition={decomposition}, execution={execution}, propagation={propagation} | "
            f"missing_mapping={signals.get('missing_mapping', 0)}, "
            f"missing_leaf={signals.get('missing_leaf', 0)}, "
            f"missing_contract={signals.get('missing_contract', 0)}, "
            f"final_empty={signals.get('final_empty', False)}"
        )
        return {
            "summary": summary,
            "self_assessment": self_assessment,
            "signals": signals,
        }

    def _collapse_actions(
        self, actions_raw: list[dict[str, Any]], unit_count: int
    ) -> list[dict[str, Any]]:
        reason_by_node: dict[int, list[str]] = {}
        for action in actions_raw:
            node = action["node"]
            reason = action["reason"].strip()
            if node < 0 or node >= unit_count:
                continue
            if not reason:
                continue
            reason_by_node.setdefault(node, []).append(reason)
        return [
            {"node": node, "reason": " ".join(dict.fromkeys(reasons))}
            for node, reasons in sorted(reason_by_node.items())
            if reasons
        ]

    def _current_now_utc_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# Backward compatibility: engine and callers use Review
Review = Reviewer
