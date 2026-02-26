"""Reviewer service: LLM-first with fail-fast validation."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from ...models.gemini_direct import GeminiClient
from ...utils.config import config
from ..contracts.plan import Plan
from ..contracts.requirement import evaluate_contract

from .prompts import (
    REVIEWER_SYSTEM,
    build_reviewer_response_json_schema,
    build_reviewer_user_prompt,
)


class Reviewer:
    def __init__(self, client: GeminiClient | None = None) -> None:
        self.client = client or GeminiClient(config.agent_model)

    async def review(
        self, plan: Plan, execution: dict, aggregation: dict
    ) -> dict[str, Any]:
        facts = self._collect_gap_facts(plan, execution, aggregation)
        reason_map = self._collect_action_reasons(facts)
        candidate_actions = [
            {
                "node": node,
                "gaps": sorted(r.strip() for r in reason_map[node] if r.strip()),
            }
            for node in sorted(reason_map)
        ]
        signals = {
            "missing_mapping": len(facts.get("units_without_leaf_mapping", [])),
            "missing_leaf": len(facts.get("missing_leaf_task_ids", [])),
            "missing_contract": len(facts.get("missing_contract_items", [])),
            "final_empty": bool(facts.get("final_empty", False)),
            "action_nodes_total": len(reason_map),
        }

        user_prompt = build_reviewer_user_prompt(
            query=plan.query,
            query_units=plan.query_units or [],
            candidate_actions=candidate_actions,
            diagnostics={"signals": signals},
        )
        unit_count = len(plan.query_units)
        response_schema = build_reviewer_response_json_schema(
            max_node=max(unit_count - 1, 0)
        )

        try:
            raw = await self.client.generate(
                prompt=user_prompt,
                system_prompt=REVIEWER_SYSTEM,
                response_mime_type="application/json",
                response_json_schema=response_schema,
            )
            data = json.loads(raw.strip())
            if not isinstance(data, dict):
                raise ValueError("reviewer response must be a JSON object")
            actions = self._require_actions(data.get("actions"), unit_count)
            self_assessment = self._require_self_assessment(data.get("self_assessment"))
        except Exception as exc:
            raise ValueError(f"invalid reviewer response: {exc}") from exc

        coverage_feedback = self._build_coverage_feedback(
            signals=signals,
            self_assessment=self_assessment,
        )
        return {"actions": actions, "coverage_feedback": coverage_feedback}

    def _collect_gap_facts(
        self, plan: Plan, execution: dict, aggregation: dict
    ) -> dict[str, Any]:
        unit_count = len(plan.query_units)
        final_markdown = self._final_markdown(aggregation)
        missing_contract_items = self._missing_contract_items(
            plan=plan,
            aggregation=aggregation,
            final_markdown=final_markdown,
        )
        item_map = (
            {item.id: item for item in plan.contract.items} if plan.contract else {}
        )
        leaf_tasks = {task.id: task for task in plan.tasks if task.task_type == "leaf"}

        completed_leaf_ids = {
            task_id
            for task_id in (execution.get("leaf_completed_tasks") or [])
            if isinstance(task_id, str)
        }
        planned_leaf_ids = sorted(leaf_tasks)
        missing_leaf_task_ids = sorted(set(planned_leaf_ids) - completed_leaf_ids)

        mapped_units: set[int] = set()
        for task in leaf_tasks.values():
            for node in self._normalize_nodes(task.query_unit_ids, unit_count):
                mapped_units.add(node)

        units_without_leaf_mapping = sorted(
            node for node in range(unit_count) if node not in mapped_units
        )

        return {
            "unit_count": unit_count,
            "final_empty": not final_markdown.strip(),
            "missing_contract_items": missing_contract_items,
            "item_map": item_map,
            "leaf_tasks": leaf_tasks,
            "missing_leaf_task_ids": missing_leaf_task_ids,
            "units_without_leaf_mapping": units_without_leaf_mapping,
        }

    def _collect_action_reasons(self, facts: dict[str, Any]) -> dict[int, set[str]]:
        """Collect deterministic hints for LLM prompt only."""
        unit_count = int(facts.get("unit_count", 0))
        if unit_count <= 0:
            return {}

        reason_map: dict[int, set[str]] = defaultdict(set)

        item_map = facts.get("item_map", {})
        for item_id in facts.get("missing_contract_items", []):
            item = item_map.get(item_id)
            if item is None or item.unit_id < 0 or item.unit_id >= unit_count:
                continue
            reason_map[item.unit_id].add(
                f"계약 항목 {item.id}({item.acceptance})이 최종 보고서에서 충족되지 않았습니다."
            )

        for node in facts.get("units_without_leaf_mapping", []):
            if isinstance(node, int):
                reason_map[node].add(
                    "query unit에 매핑된 leaf task가 없어 분해 결과를 실행할 수 없습니다."
                )

        leaf_tasks = facts.get("leaf_tasks", {})
        for task_id in facts.get("missing_leaf_task_ids", []):
            task = leaf_tasks.get(task_id)
            if task is None:
                continue
            for node in self._normalize_nodes(task.query_unit_ids, unit_count):
                reason_map[node].add(
                    f"leaf task {task_id}가 실행되지 않아 해당 단위의 근거 데이터가 부족합니다."
                )

        if bool(facts.get("final_empty", False)):
            for node in range(unit_count):
                reason_map[node].add(
                    "최종 보고서가 비어 있어 해당 단위의 분석 결과를 확인할 수 없습니다."
                )

        return {node: values for node, values in reason_map.items() if values}

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

    def _require_actions(self, value: Any, unit_count: int) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise ValueError("actions must be list")
        actions: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("each action must be object")
            node = item.get("node")
            reason = item.get("reason")
            if (
                not isinstance(node, int)
                or isinstance(node, bool)
                or node < 0
                or node >= unit_count
            ):
                raise ValueError(f"invalid action node: {node}")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("action reason must be non-empty string")
            actions.append({"node": node, "reason": reason.strip()})
        return actions

    def _require_self_assessment(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("self_assessment must be object")

        normalized: dict[str, Any] = {}
        for axis in ("decomposition", "execution", "propagation"):
            axis_value = value.get(axis)
            if not isinstance(axis_value, dict):
                raise ValueError(f"self_assessment.{axis} must be object")
            verdict = axis_value.get("verdict")
            reason = axis_value.get("reason")
            if verdict not in {"pass", "revise", "fail"}:
                raise ValueError(f"invalid verdict for {axis}: {verdict}")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"self_assessment.{axis}.reason must be non-empty")
            normalized[axis] = {"verdict": verdict, "reason": reason.strip()}

        overall = value.get("overall")
        if not isinstance(overall, str) or not overall.strip():
            raise ValueError("self_assessment.overall must be non-empty string")
        normalized["overall"] = overall.strip()
        return normalized

    def _final_markdown(self, aggregation: dict) -> str:
        final = aggregation.get("final_markdown")
        if isinstance(final, str):
            return final
        root = aggregation.get("root_report")
        if isinstance(root, dict) and isinstance(root.get("markdown"), str):
            return root["markdown"]
        return ""

    def _missing_contract_items(
        self, plan: Plan, aggregation: dict, final_markdown: str
    ) -> list[str]:
        from_agg = aggregation.get("missing_contract_items")
        if isinstance(from_agg, list):
            return [item for item in from_agg if isinstance(item, str)]
        return evaluate_contract(plan.contract, final_markdown)

    def _normalize_nodes(self, nodes: Any, unit_count: int) -> list[int]:
        if not isinstance(nodes, list):
            return []
        return sorted(
            {
                int(node)
                for node in nodes
                if isinstance(node, int)
                and not isinstance(node, bool)
                and 0 <= node < unit_count
            }
        )


# Backward compatibility: engine and callers use Review
Review = Reviewer
