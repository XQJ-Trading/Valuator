from __future__ import annotations

import json
import re
from typing import Any

from ...models.gemini_direct import GeminiClient
from ...utils.config import config
from ..contracts.plan import Plan, Task, ToolCall
from ..graph.normalizer import ensure_recursive_graph

_SYSTEM_PROMPT = (
    "Return concise JSON only. No markdown. "
    "Do not include any keys except the requested schema."
)


class Planner:
    def __init__(
        self,
        client: GeminiClient | None = None,
        allowed_tools: set[str] | None = None,
    ) -> None:
        self.client = client or GeminiClient(config.agent_model)
        self.allowed_tools = allowed_tools or {"research_llm"}

    async def plan(self, query: str) -> Plan:
        if not query or not query.strip():
            raise ValueError("query is required")

        query_units = await self._extract_query_units(query)
        if not query_units:
            query_units = [query.strip()]

        analysis_strategy = await self._build_analysis_strategy(query, query_units)
        tasks = self._build_leaf_tasks(query_units)
        root_id = "T-ROOT"
        tasks.append(
            Task(
                id=root_id,
                task_type="merge",
                deps=[task.id for task in tasks],
                description="Final report synthesis",
                merge_instruction=(
                    "Combine all child analyses into a single coherent investment report. "
                    "Preserve quantitative facts and clearly separate upside vs risk."
                ),
            )
        )

        plan = Plan(
            query=query,
            analysis_strategy=analysis_strategy,
            query_units=query_units,
            root_task_id=root_id,
            tasks=tasks,
        )
        return ensure_recursive_graph(plan, allowed_tools=self.allowed_tools)

    async def replan(self, query: str, current_plan: Plan, review: dict[str, Any]) -> Plan:
        actions = review.get("actions", [])
        if not isinstance(actions, list):
            return current_plan

        missing_units: list[int] = []
        for action in actions:
            if not isinstance(action, dict):
                continue
            if action.get("type") != "add_tasks_for_query_units":
                continue
            values = action.get("values", [])
            if isinstance(values, list):
                for value in values:
                    if isinstance(value, int):
                        missing_units.append(value)

        if not missing_units:
            return current_plan

        existing_covered_units: set[int] = set()
        for task in current_plan.tasks:
            existing_covered_units.update(task.query_unit_ids)

        new_tasks: list[Task] = []
        for idx in sorted(set(missing_units)):
            if idx < 0 or idx >= len(current_plan.query_units):
                continue
            if idx in existing_covered_units:
                continue
            task_id = self._next_leaf_id(current_plan.tasks + new_tasks)
            unit = current_plan.query_units[idx]
            new_tasks.append(
                Task(
                    id=task_id,
                    task_type="leaf",
                    query_unit_ids=[idx],
                    tool=ToolCall(
                        name="research_llm",
                        args={"focus": unit},
                    ),
                    output=f"/execution/outputs/{task_id}/result.md",
                    description=f"Replanned unit #{idx + 1}",
                )
            )

        if not new_tasks:
            return current_plan

        task_map = {task.id: task for task in current_plan.tasks}
        root_id = current_plan.root_task_id
        if not root_id or root_id not in task_map:
            return ensure_recursive_graph(
                current_plan.model_copy(update={"tasks": [*current_plan.tasks, *new_tasks]}),
                allowed_tools=self.allowed_tools,
            )

        root = task_map[root_id]
        merged_root = root.model_copy(update={"deps": [*root.deps, *[t.id for t in new_tasks]]})
        merged_tasks = [task for task in current_plan.tasks if task.id != root_id]
        merged_tasks.extend(new_tasks)
        merged_tasks.append(merged_root)

        next_plan = current_plan.model_copy(update={"tasks": merged_tasks})
        return ensure_recursive_graph(next_plan, allowed_tools=self.allowed_tools)

    async def _extract_query_units(self, query: str) -> list[str]:
        prompt = (
            "Split the user query into 3 to 6 executable analysis units.\n"
            "Return JSON object with a single key: units (string array).\n\n"
            f"[QUERY]\n{query}\n"
        )
        try:
            raw = await self.client.generate(
                prompt=prompt,
                system_prompt=_SYSTEM_PROMPT,
                response_mime_type="application/json",
            )
            data = self._parse_json(raw)
            units = data.get("units")
            if isinstance(units, list):
                normalized = [str(unit).strip() for unit in units if str(unit).strip()]
                if normalized:
                    return normalized[:6]
        except Exception:
            pass

        fallback = []
        for line in query.splitlines():
            line = line.strip()
            if not line:
                continue
            line = re.sub(r"^\d+[\.\)]\s*", "", line)
            line = re.sub(r"^[-*]\s*", "", line)
            if line:
                fallback.append(line)
        if not fallback:
            return [query.strip()]
        return fallback[:6]

    async def _build_analysis_strategy(self, query: str, units: list[str]) -> str:
        prompt = (
            "Write a short analysis strategy (max 4 lines) for this plan.\n"
            "Keep it concrete and focused on retrieval + synthesis.\n\n"
            f"[QUERY]\n{query}\n\n"
            f"[UNITS]\n{json.dumps(units, ensure_ascii=False)}"
        )
        try:
            raw = await self.client.generate(prompt=prompt)
            strategy = raw.strip()
            if strategy:
                return strategy
        except Exception:
            pass
        return "Decompose the query into retrieval-ready units, gather evidence per unit, then synthesize into one investment report."

    def _build_leaf_tasks(self, query_units: list[str]) -> list[Task]:
        tasks: list[Task] = []
        for idx, unit in enumerate(query_units):
            task_id = f"T-LEAF-{idx + 1}"
            tasks.append(
                Task(
                    id=task_id,
                    task_type="leaf",
                    query_unit_ids=[idx],
                    tool=ToolCall(name="research_llm", args={"focus": unit}),
                    output=f"/execution/outputs/{task_id}/result.md",
                    description=unit[:120],
                )
            )
        return tasks

    def _next_leaf_id(self, tasks: list[Task]) -> str:
        max_num = 0
        for task in tasks:
            if not task.id.startswith("T-LEAF-"):
                continue
            suffix = task.id.removeprefix("T-LEAF-")
            if suffix.isdigit():
                max_num = max(max_num, int(suffix))
        return f"T-LEAF-{max_num + 1}"

    def _parse_json(self, raw: str) -> dict[str, Any]:
        text = raw.strip()
        if "```" in text:
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else parts[0]
            text = re.sub(r"^json\s*", "", text.strip(), flags=re.IGNORECASE)
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("planner response must be JSON object")
        return data
