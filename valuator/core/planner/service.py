from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any

from ...models.gemini_direct import GeminiClient
from ...utils.config import config
from ..contracts.plan import Plan, Task, ToolCall
from ..contracts.requirement import PlanContract, RequirementItem
from ..graph.validator import validate_plan_graph

_SYSTEM_PROMPT = (
    "Return concise JSON only. No markdown. "
    "Do not include any keys except the requested schema."
)
_TOOL_ENUM = (
    "web_search_tool",
    "sec_tool",
    "yfinance_balance_sheet",
    "code_execute_tool",
)
_TOOL_REQUIRED_ARGS: dict[str, tuple[str, ...]] = {
    "web_search_tool": ("query",),
    "sec_tool": ("ticker", "year", "query"),
    "yfinance_balance_sheet": ("ticker",),
    "code_execute_tool": ("code",),
}
_TOOL_ALLOWED_ARGS: dict[str, tuple[str, ...]] = {
    "web_search_tool": ("query",),
    "sec_tool": ("ticker", "year", "query"),
    "yfinance_balance_sheet": ("ticker", "year"),
    "code_execute_tool": ("code",),
}
_YEAR_MIN = 1900
_YEAR_MAX = 2100
_LEAF_BUILD_CONCURRENCY = 4


class Planner:
    def __init__(
        self,
        client: GeminiClient | None = None,
    ) -> None:
        self.client = client or GeminiClient(config.agent_model)

    async def plan(self, query: str) -> Plan:
        if not query or not query.strip():
            raise ValueError("query is required")

        reference_date = date.today()
        query_units = await self._plan_decomposition(
            query, reference_date=reference_date
        )
        contract = self._compile_contract(query_units)
        contract = self._pre_review_contract(query_units, contract)
        tasks = await self._build_leaf_tasks(
            query, query_units, reference_date=reference_date
        )
        root_id = "T-ROOT"
        tasks.append(
            Task(
                id=root_id,
                task_type="merge",
                deps=[task.id for task in tasks],
                description="Final report synthesis",
                merge_instruction=(
                    "Combine all child analyses into a single coherent investment report. "
                    "Use absolute time anchors (for example, 2025Q3, 2026-01-08) instead of relative phrases. "
                    "Preserve quantitative facts, explain risk transmission to P&L/FCF, "
                    "and conclude with trigger-based portfolio actions."
                ),
            )
        )

        plan = Plan(
            query=query,
            query_units=query_units,
            contract=contract,
            root_task_id=root_id,
            tasks=tasks,
        )
        validate_plan_graph(plan)
        return plan

    async def replan(self, current_plan: Plan, review: dict[str, Any]) -> Plan:
        action_map = self._action_reasons_by_unit(
            actions=review.get("actions"),
            unit_count=len(current_plan.query_units),
        )
        if not action_map:
            return current_plan

        item_map = self._contract_items_by_unit(current_plan.contract)
        next_leaf_num = self._next_leaf_number(current_plan.tasks)
        batch_specs: list[dict[str, Any]] = []
        for offset, idx in enumerate(sorted(action_map)):
            batch_specs.append(
                {
                    "query": current_plan.query,
                    "unit": self._focused_unit_text(
                        unit=current_plan.query_units[idx],
                        items=item_map.get(idx, []),
                        reasons=action_map[idx],
                    ),
                    "query_unit_id": idx,
                    "description": f"Refreshed unit #{idx + 1} (action-targeted)",
                    "next_leaf_num": next_leaf_num + offset,
                    "reference_date": None,
                }
            )

        new_tasks = await self._build_leaf_tasks_batch(batch_specs)

        if not new_tasks:
            return current_plan

        task_map = {task.id: task for task in current_plan.tasks}
        root_id = current_plan.root_task_id
        if not root_id or root_id not in task_map:
            raise ValueError("current plan has invalid root_task_id")

        root = task_map[root_id]
        merged_root = root.model_copy(
            update={"deps": [*root.deps, *[t.id for t in new_tasks]]}
        )
        merged_tasks = [task for task in current_plan.tasks if task.id != root_id]
        merged_tasks.extend(new_tasks)
        merged_tasks.append(merged_root)

        next_plan = current_plan.model_copy(update={"tasks": merged_tasks})
        validate_plan_graph(next_plan)
        return next_plan

    async def _plan_decomposition(
        self, query: str, *, reference_date: date
    ) -> list[str]:
        latest_year = self._latest_year_for_date(reference_date)
        prompt = (
            "Plan decomposition for the user query.\n"
            "Return JSON object with one key: units (string array).\n\n"
            "Rules:\n"
            "- Each unit must be executable as a concrete retrieval query.\n"
            "- Split broad scopes into atomic units; do not combine multiple primary asks in one unit.\n"
            "- Do not output duplicate or overlapping units.\n"
            "- Do not output meta instructions (for example: analyze deeply, summarize broadly).\n"
            f"- Convert relative time phrases into absolute years ending at {latest_year} (reference = search time; recency first).\n"
            "- For time-series asks (예: 최근 5개년), include explicit absolute years in units.\n"
            "- Prioritize coverage across key analysis axes implied by the query.\n\n"
            f"[REFERENCE_DATE]\n{reference_date.isoformat()}\n\n"
            f"[LATEST_YEAR]\n{latest_year}\n\n"
            f"[QUERY]\n{query}\n"
        )
        raw = await self.client.generate(
            prompt=prompt,
            system_prompt=_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["units"],
                "properties": {
                    "units": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {"type": "string"},
                    },
                },
            },
        )
        data = self._parse_json(raw)
        units_raw = data.get("units")

        if not isinstance(units_raw, list):
            raise ValueError("planner decomposition units must be a list")
        units = [
            unit.strip() for unit in units_raw if isinstance(unit, str) and unit.strip()
        ]
        units = list(dict.fromkeys(units))
        if not units:
            raise ValueError("planner decomposition returned no usable units")

        return units

    async def _build_leaf_tasks(
        self,
        query: str,
        query_units: list[str],
        *,
        reference_date: date,
    ) -> list[Task]:
        batch_specs: list[dict[str, Any]] = []
        for idx, unit in enumerate(query_units):
            batch_specs.append(
                {
                    "query": query,
                    "unit": unit,
                    "query_unit_id": idx,
                    "description": unit,
                    "next_leaf_num": idx + 1,
                    "reference_date": reference_date,
                }
            )
        return await self._build_leaf_tasks_batch(batch_specs)

    async def _build_leaf_tasks_batch(
        self,
        batch_specs: list[dict[str, Any]],
    ) -> list[Task]:
        if not batch_specs:
            return []

        sem = asyncio.Semaphore(_LEAF_BUILD_CONCURRENCY)

        async def _run(spec: dict[str, Any]) -> tuple[list[Task], int]:
            async with sem:
                return await self._build_leaf_tasks_for_unit(
                    query=str(spec["query"]),
                    unit=str(spec["unit"]),
                    query_unit_id=int(spec["query_unit_id"]),
                    description=str(spec["description"]),
                    next_leaf_num=int(spec["next_leaf_num"]),
                    reference_date=spec.get("reference_date"),
                )

        results = await asyncio.gather(*[_run(spec) for spec in batch_specs])
        tasks: list[Task] = []
        for built_tasks, _ in results:
            tasks.extend(built_tasks)
        return tasks

    async def _build_leaf_tasks_for_unit(
        self,
        *,
        query: str,
        unit: str,
        query_unit_id: int,
        description: str,
        next_leaf_num: int,
        reference_date: date | None = None,
    ) -> tuple[list[Task], int]:
        ref = reference_date or date.today()
        tool = await self._select_tool_for_unit(
            query=query, unit=unit, reference_date=ref
        )
        task_id = self._leaf_id(next_leaf_num)
        return (
            [
                Task(
                    id=task_id,
                    task_type="leaf",
                    query_unit_ids=[query_unit_id],
                    tool=tool,
                    output=f"/execution/outputs/{task_id}/result.md",
                    description=description,
                )
            ],
            next_leaf_num + 1,
        )

    async def _select_tool_for_unit(
        self,
        *,
        query: str,
        unit: str,
        reference_date: date | None = None,
    ) -> ToolCall:
        ref = reference_date or date.today()
        latest_year = self._latest_year_for_date(ref)
        prompt = (
            "Select exactly one tool and concrete arguments for this query unit.\n"
            "Return only a valid tool contract.\n"
            "For sec_tool and yfinance_balance_sheet use LATEST_YEAR when year is required or relevant (recency first).\n\n"
            f"[REFERENCE_DATE]\n{ref.isoformat()}\n\n"
            f"[LATEST_YEAR]\n{latest_year}\n\n"
            f"[QUERY]\n{query}\n\n"
            f"[QUERY_UNIT]\n{unit}\n\n"
            "[TOOLS]\n"
            "- web_search_tool args: {query:string}\n"
            "- sec_tool args: {ticker:string, year:int, query:string}\n"
            "- yfinance_balance_sheet args: {ticker:string, year?:string}\n"
            "- code_execute_tool args: {code:string}\n"
        )
        raw = await self.client.generate(
            prompt=prompt,
            system_prompt=_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["tool_name", "tool_args"],
                "properties": {
                    "tool_name": {"type": "string", "enum": list(_TOOL_ENUM)},
                    "tool_args": {"type": "object"},
                },
            },
        )
        data = self._parse_json(raw)
        name = str(data.get("tool_name", "")).strip()
        args = data.get("tool_args")
        if not isinstance(args, dict):
            raise ValueError("tool_args must be an object")
        self._validate_selected_tool(name=name, args=args)
        return ToolCall(name=name, args=args)

    def _validate_selected_tool(self, *, name: str, args: dict[str, Any]) -> None:
        if name not in _TOOL_ENUM:
            raise ValueError(f"invalid tool selected: {name}")
        required = _TOOL_REQUIRED_ARGS.get(name, ())
        missing = [key for key in required if key not in args]
        if missing:
            raise ValueError(f"missing required args for {name}: {missing}")
        allowed = _TOOL_ALLOWED_ARGS.get(name, ())
        unknown = [key for key in args if key not in allowed]
        if unknown:
            raise ValueError(f"unknown args for {name}: {unknown}")

    def _next_leaf_number(self, tasks: list[Task]) -> int:
        max_num = 0
        for task in tasks:
            if not task.id.startswith("T-LEAF-"):
                continue
            suffix = task.id.removeprefix("T-LEAF-")
            if suffix.isdigit():
                max_num = max(max_num, int(suffix))
        return max_num + 1

    def _leaf_id(self, number: int) -> str:
        return f"T-LEAF-{number}"

    def _latest_year_for_date(self, d: date) -> int:
        return max(_YEAR_MIN, min(_YEAR_MAX, d.year))

    def _parse_json(self, raw: str) -> dict[str, Any]:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("planner response must be JSON object")
        return data

    def _compile_contract(self, query_units: list[str]) -> PlanContract:
        items: list[RequirementItem] = []
        for unit_id, unit in enumerate(query_units):
            items.append(
                RequirementItem(
                    id=f"R-{unit_id + 1:03d}",
                    unit_id=unit_id,
                    requirement_type="query_unit",
                    acceptance=unit,
                    required=True,
                )
            )
        return PlanContract(
            items=items,
            rationale="Query units mapped 1:1 to required contract items.",
        )

    def _pre_review_contract(
        self,
        query_units: list[str],
        contract: PlanContract,
    ) -> PlanContract:
        required_unit_ids = {idx for idx in range(len(query_units))}
        covered_unit_ids = {item.unit_id for item in contract.items if item.required}
        if covered_unit_ids == required_unit_ids:
            return contract
        return self._compile_contract(query_units)

    def _action_reasons_by_unit(
        self,
        *,
        actions: Any,
        unit_count: int,
    ) -> dict[int, list[str]]:
        if not isinstance(actions, list):
            raise ValueError("review.actions must be a list of {'node': int, 'reason': str}")
        reason_map: dict[int, list[str]] = {}
        for action in actions:
            if not isinstance(action, dict):
                raise ValueError("review.actions must be a list of {'node': int, 'reason': str}")
            node = action.get("node")
            reason = action.get("reason")
            if (
                not isinstance(node, int)
                or isinstance(node, bool)
                or node < 0
                or node >= unit_count
                or not isinstance(reason, str)
                or not reason.strip()
            ):
                raise ValueError("review.actions must be a list of {'node': int, 'reason': str}")
            reason_map.setdefault(node, []).append(reason.strip())
        normalized: dict[int, list[str]] = {}
        for node, reasons in reason_map.items():
            dedup = list(dict.fromkeys(reasons))
            if dedup:
                normalized[node] = dedup
        return normalized

    def _contract_items_by_unit(
        self,
        contract: PlanContract | None,
    ) -> dict[int, list[RequirementItem]]:
        if contract is None:
            return {}
        by_unit: dict[int, list[RequirementItem]] = {}
        for item in contract.items:
            by_unit.setdefault(item.unit_id, []).append(item)
        return by_unit

    def _focused_unit_text(
        self,
        *,
        unit: str,
        items: list[RequirementItem],
        reasons: list[str],
    ) -> str:
        chunks: list[str] = [unit]
        if items:
            lines = [f"- [{item.id}] {item.acceptance}" for item in items]
            requirement_block = "\n".join(lines)
            chunks.append(f"[REQUIREMENTS TO FILL]\n{requirement_block}")
        if reasons:
            reason_lines: list[str] = []
            seen: set[str] = set()
            for reason in reasons:
                text = reason.strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                reason_lines.append(f"- {text}")
            if reason_lines:
                chunks.append("[REVIEW_GAPS]\n" + "\n".join(reason_lines))
        return "\n\n".join(chunks)
