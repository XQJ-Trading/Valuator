from __future__ import annotations

from typing import Any

from ...models.gemini_direct import GeminiClient
from ...utils.config import config
from ..contracts.plan import Plan, Task
from ..workspace.service import Workspace


class Executor:
    def __init__(
        self,
        client: GeminiClient | None = None,
        allowed_tools: set[str] | None = None,
    ) -> None:
        self.client = client or GeminiClient(config.agent_model)
        self.allowed_tools = allowed_tools or {"research_llm"}

    async def execute(self, query: str, plan: Plan, workspace: Workspace) -> dict[str, Any]:
        artifacts: list[dict[str, str]] = []
        completed_leaves: list[str] = []

        for task in plan.tasks:
            if task.task_type != "leaf":
                continue
            if not task.tool:
                continue
            if task.tool.name not in self.allowed_tools:
                raise ValueError(f"unsupported tool: {task.tool.name}")
            if not task.output:
                raise ValueError(f"leaf task missing output: {task.id}")

            content = await self._run_leaf_task(query, task)

            workspace.write_output(task.output, content)
            artifacts.append({"task_id": task.id, "path": task.output, "content": content})
            completed_leaves.append(task.id)

        return {"leaf_completed_tasks": completed_leaves, "artifacts": artifacts}

    async def _run_leaf_task(self, query: str, task: Task) -> str:
        focus = ""
        if task.tool:
            focus = str(task.tool.args.get("focus", "")).strip()
        if not focus:
            focus = task.description.strip() or task.id

        prompt = (
            "You are a retrieval-focused financial analyst.\n"
            "Produce factual, concise research notes for the requested focus area.\n"
            "When unsure, explicitly state uncertainty.\n\n"
            f"[QUERY]\n{query}\n\n"
            f"[FOCUS]\n{focus}\n\n"
            "Output markdown with:\n"
            "1) key findings\n"
            "2) quantitative points\n"
            "3) risks and caveats"
        )
        try:
            content = await self.client.generate(prompt=prompt)
            text = content.strip()
            if text:
                return text + "\n"
        except Exception:
            pass

        fallback = (
            f"# {task.id}\n\n"
            f"- query: {query}\n"
            f"- focus: {focus}\n"
            "- note: live retrieval unavailable; generated fallback analysis artifact.\n"
        )
        return fallback
