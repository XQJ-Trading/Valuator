from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Any

from ...models.gemini_direct import GeminiClient
from ...utils.config import config
from ..contracts.plan import Plan, Task, ToolCall
from ..contracts.requirement import PlanContract, RequirementItem

_SYSTEM_PROMPT = (
    "Return concise JSON only. No markdown. "
    "Do not include any keys except the requested schema."
)
_TOOL_ARGS: dict[str, dict[str, tuple[str, ...]]] = {
    "web_search_tool": {"required": ("query",), "optional": ()},
    "sec_tool": {"required": ("ticker", "year", "query"), "optional": ()},
    "yfinance_balance_sheet": {"required": ("ticker",), "optional": ("year",)},
    "code_execute_tool": {"required": ("code",), "optional": ()},
}
_TOOL_CAPABILITY = {
    "web_search_tool": "current news/facts/sources",
    "sec_tool": "10-K filings and disclosures",
    "yfinance_balance_sheet": "financial statements plus valuation/pricing coordinates (market_cap, price, PE, PBR)",
    "code_execute_tool": "deterministic calculations",
}
_LEAF_BUILD_CONCURRENCY = 4


class Planner:
    def __init__(
        self,
        client: GeminiClient | None = None,
    ) -> None:
        self.client = client or GeminiClient(config.agent_model)
        self._now_utc: datetime | None = None

    def bind_now_utc(self, now_utc: datetime) -> None:
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        self._now_utc = now_utc.astimezone(timezone.utc)

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        self.client.bind_usage_writer(usage_writer)

    async def plan(self, query: str) -> Plan:
        if not query or not query.strip():
            raise ValueError("query is required")

        reference_date = self._reference_date()
        query_units = await self._plan_decomposition(
            query, reference_date=reference_date
        )
        contract = self._compile_contract(query_units)
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
        reference_date = self._reference_date()
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
                    "reference_date": reference_date,
                }
            )

        new_tasks = await self._build_leaf_tasks_batch(batch_specs)

        if not new_tasks:
            return current_plan

        task_map = {task.id: task for task in current_plan.tasks}
        root_id = current_plan.root_task_id
        root = task_map[root_id]
        merged_root = root.model_copy(
            update={"deps": [*root.deps, *[t.id for t in new_tasks]]}
        )
        merged_tasks = [task for task in current_plan.tasks if task.id != root_id]
        merged_tasks.extend(new_tasks)
        merged_tasks.append(merged_root)

        next_plan = current_plan.model_copy(update={"tasks": merged_tasks})
        return next_plan

    async def _plan_decomposition(
        self, query: str, *, reference_date: date
    ) -> list[str]:
        latest_year = reference_date.year
        prompt = (
            "Plan decomposition for the user query.\n"
            "Return JSON object with one key: units (string array).\n\n"
            "Rules:\n"
            "- Each unit must be executable as a concrete retrieval query.\n"
            "- Split broad scopes into atomic units; do not combine multiple primary asks in one unit.\n"
            "- Do not output duplicate or overlapping units.\n"
            "- Do not output meta instructions (for example: analyze deeply, summarize broadly).\n"
            "- Preserve explicitly named entities/tickers from QUERY; do not substitute different companies/themes.\n"
            f"- Convert relative time phrases into absolute years ending at {latest_year} (reference = search time; recency first).\n"
            "- For time-series asks (예: 최근 5개년), include explicit absolute years in units.\n"
            "- Prioritize coverage across key analysis axes implied by the query.\n\n"
            f"[REFERENCE_DATE]\n{reference_date.isoformat()}\n\n"
            f"[LATEST_YEAR]\n{latest_year}\n\n"
            f"[QUERY]\n{query}\n"
        )
        data = await self.client.generate_json(
            prompt=prompt,
            system_prompt=_SYSTEM_PROMPT,
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
            trace_method="planner._plan_decomposition",
        )
        units = [unit.strip() for unit in data["units"] if unit.strip()]
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

        async def _run(spec: dict[str, Any]) -> Task:
            async with sem:
                tool = await self._select_tool_for_unit(
                    query=spec["query"],
                    unit=spec["unit"],
                    reference_date=spec.get("reference_date"),
                )
                task_id = self._leaf_id(spec["next_leaf_num"])
                return Task(
                    id=task_id,
                    task_type="leaf",
                    query_unit_ids=[spec["query_unit_id"]],
                    tool=tool,
                    output=f"/execution/outputs/{task_id}/result.md",
                    description=spec["description"],
                )

        return list(await asyncio.gather(*[_run(spec) for spec in batch_specs]))

    async def _select_tool_for_unit(
        self,
        *,
        query: str,
        unit: str,
        reference_date: date | None = None,
    ) -> ToolCall:
        ref = reference_date or self._reference_date()
        latest_year = ref.year
        def _args_text(spec: dict[str, tuple[str, ...]]) -> str:
            required = ", ".join(spec["required"])
            optional = ", ".join(f"{key}?" for key in spec["optional"])
            if required and optional:
                return f"{required}, {optional}"
            return required or optional or "-"

        tools_block = "\n".join(
            f"- {name} args: {{{_args_text(_TOOL_ARGS[name])}}}; use_for: {_TOOL_CAPABILITY[name]}"
            for name in _TOOL_ARGS
        )
        prompt = (
            "Select exactly one tool and concrete arguments for this query unit.\n"
            "Return only a valid tool contract.\n"
            "For sec_tool and yfinance_balance_sheet use LATEST_YEAR when year is required or relevant (recency first).\n\n"
            "Prefer preserving valuation/pricing coordinates (market cap, PER, PBR, price range) for equity analysis units.\n\n"
            f"[REFERENCE_DATE]\n{ref.isoformat()}\n\n"
            f"[LATEST_YEAR]\n{latest_year}\n\n"
            f"[QUERY]\n{query}\n\n"
            f"[QUERY_UNIT]\n{unit}\n\n"
            f"[TOOLS]\n{tools_block}\n"
        )
        data = await self.client.generate_json(
            prompt=prompt,
            system_prompt=_SYSTEM_PROMPT,
            response_json_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["tool_name", "tool_args"],
                "properties": {
                    "tool_name": {"type": "string", "enum": list(_TOOL_ARGS)},
                    "tool_args": {"type": "object"},
                },
            },
            trace_method="planner._select_tool_for_unit",
        )
        name = data["tool_name"].strip()
        args = data["tool_args"]
        self._check_tool_args(name=name, args=args)
        return ToolCall(name=name, args=args)

    def _check_tool_args(
        self,
        *,
        name: str,
        args: dict[str, Any],
    ) -> None:
        spec = _TOOL_ARGS.get(name)
        if spec is None:
            raise RuntimeError(f"planner tool registry mismatch: {name}")
        required = spec["required"]
        missing = [key for key in required if key not in args]
        if missing:
            raise ValueError(f"missing required args for {name}: {missing}")
        allowed = (*spec["required"], *spec["optional"])
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

    def _reference_date(self) -> date:
        if self._now_utc is not None:
            return self._now_utc.date()
        return date.today()

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

    def _action_reasons_by_unit(
        self,
        *,
        actions: Any,
        unit_count: int,
    ) -> dict[int, list[str]]:
        if not actions:
            return {}
        reason_map: dict[int, list[str]] = {}
        for action in actions:
            node = action["node"]
            reason = action["reason"].strip()
            if node < 0 or node >= unit_count or not reason:
                continue
            reason_map.setdefault(node, []).append(reason)
        return {
            node: list(dict.fromkeys(reasons))
            for node, reasons in reason_map.items()
            if reasons
        }

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
