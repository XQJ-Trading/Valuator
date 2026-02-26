from __future__ import annotations

import asyncio
import json
from hashlib import sha256
from typing import Any

from ...tools.base import ObservationData, ToolResult
from ..contracts.plan import Plan, Task
from ..workspace.service import Workspace

_DEFAULT_ALLOWED_TOOLS: set[str] = {
    "web_search_tool",
    "sec_tool",
    "yfinance_balance_sheet",
    "code_execute_tool",
}
_EXECUTOR_LEAF_CONCURRENCY = 4


class Executor:
    def __init__(self) -> None:
        self.allowed_tools = set(_DEFAULT_ALLOWED_TOOLS)
        self._tool_cache: dict[str, Any] = {}

    async def execute(self, query: str, plan: Plan, workspace: Workspace) -> dict[str, Any]:
        _ = query
        leaf_tasks = [task for task in plan.tasks if task.task_type == "leaf"]
        if not leaf_tasks:
            return {"leaf_completed_tasks": [], "artifacts": []}

        sem = asyncio.Semaphore(_EXECUTOR_LEAF_CONCURRENCY)

        async def _run(task: Task) -> dict[str, Any]:
            async with sem:
                return await self._execute_one_leaf(task, workspace)

        results = await asyncio.gather(*[_run(task) for task in leaf_tasks])
        return {
            "leaf_completed_tasks": [row["task_id"] for row in results],
            "artifacts": results,
        }

    async def _execute_one_leaf(self, task: Task, workspace: Workspace) -> dict[str, Any]:
        if not task.tool:
            raise ValueError(f"leaf task missing tool: {task.id}")
        if not task.output:
            raise ValueError(f"leaf task missing output: {task.id}")

        tool_name = task.tool.name
        tool_args = dict(task.tool.args)
        if tool_name not in self.allowed_tools:
            raise ValueError(f"unsupported tool: {tool_name}")

        self._validate_tool_args(tool_name, tool_args)
        content, raw_result, used_tool, args_hash = await self._run_leaf_task(
            task=task,
            workspace=workspace,
            tool_name=tool_name,
            tool_args=tool_args,
        )

        workspace.write_output(task.output, content)
        workspace.write_output_metadata(
            task.output,
            {
                "tool": used_tool,
                "args_hash": args_hash,
            },
        )
        return {
            "task_id": task.id,
            "path": task.output,
            "content": content,
            "raw_result": raw_result,
        }

    async def _run_leaf_task(
        self,
        *,
        task: Task,
        workspace: Workspace,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> tuple[str, Any, str, str]:
        args_hash = self._hash_args(tool_args)
        cached = workspace.find_cached_output(tool_name, args_hash)
        if cached is not None:
            return cached, self._extract_raw_result_from_markdown(cached), tool_name, args_hash

        content, raw_result = await self._run_tool_task(task, tool_name, tool_args)
        return content, raw_result, tool_name, args_hash

    async def _run_tool_task(
        self,
        task: Task,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> tuple[str, Any]:
        tool = self._get_tool(tool_name)
        result = await tool.execute(**tool_args)
        if not isinstance(result, ToolResult):
            raise ValueError("tool must return ToolResult")
        if not result.success:
            raise ValueError(result.error or "tool returned failure")

        payload = result.result
        if isinstance(payload, ObservationData):
            payload = payload.data
        content = self._render_tool_markdown(
            task_id=task.id,
            tool_name=tool_name,
            tool_args=tool_args,
            payload=payload,
            metadata=result.metadata,
        )
        return content, payload

    def _validate_tool_args(self, tool_name: str, tool_args: dict[str, Any]) -> None:
        tool = self._get_tool(tool_name)
        schema = tool.get_schema()

        params: dict[str, Any] | None = None
        if isinstance(schema, dict):
            if schema.get("type") == "function":
                fn = schema.get("function")
                if isinstance(fn, dict):
                    raw_params = fn.get("parameters")
                    if isinstance(raw_params, dict):
                        params = raw_params
            elif isinstance(schema.get("parameters"), dict):
                params = schema.get("parameters")
        if not params:
            return

        properties = params.get("properties", {})
        required = params.get("required", [])
        additional = params.get("additionalProperties", True)

        if isinstance(required, list):
            missing = [key for key in required if key not in tool_args]
            if missing:
                raise ValueError(f"missing required args for {tool_name}: {missing}")

        if additional is False and isinstance(properties, dict):
            unknown = [key for key in tool_args if key not in properties]
            if unknown:
                raise ValueError(f"unknown args for {tool_name}: {unknown}")

        if not isinstance(properties, dict):
            return
        for key, value in tool_args.items():
            spec = properties.get(key)
            if not isinstance(spec, dict):
                continue
            expected = spec.get("type")
            if not expected:
                continue
            if not self._value_matches_type(value, expected):
                raise ValueError(
                    f"invalid arg type for {tool_name}.{key}: expected {expected}, got {type(value).__name__}"
                )

    def _value_matches_type(self, value: Any, expected: Any) -> bool:
        expected_types = expected if isinstance(expected, list) else [expected]
        for item in expected_types:
            if item == "null" and value is None:
                return True
            if item == "string" and isinstance(value, str):
                return True
            if item == "integer" and isinstance(value, int) and not isinstance(value, bool):
                return True
            if item == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
                return True
            if item == "boolean" and isinstance(value, bool):
                return True
            if item == "array" and isinstance(value, list):
                return True
            if item == "object" and isinstance(value, dict):
                return True
        return False

    def _get_tool(self, tool_name: str) -> Any:
        cached = self._tool_cache.get(tool_name)
        if cached is not None:
            return cached

        if tool_name == "web_search_tool":
            from ...tools.web_search_tool import PerplexitySearchTool

            tool = PerplexitySearchTool()
        elif tool_name == "sec_tool":
            from ...tools.sec_tool import SECTool

            tool = SECTool()
        elif tool_name == "yfinance_balance_sheet":
            from ...tools.yfinance_tool import YFinanceBalanceSheetTool

            tool = YFinanceBalanceSheetTool()
        elif tool_name == "code_execute_tool":
            from ...tools.code_execute_tool import ExecuteCodeTool

            tool = ExecuteCodeTool()
        else:
            raise ValueError(f"unknown tool: {tool_name}")

        self._tool_cache[tool_name] = tool
        return tool

    def _hash_args(self, args: dict[str, Any]) -> str:
        encoded = json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)
        return sha256(encoded.encode("utf-8")).hexdigest()

    def _render_tool_markdown(
        self,
        *,
        task_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        payload: Any,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        _ = tool_args, metadata
        lines = [f"# {task_id}", "", f"- tool: `{tool_name}`", ""]

        lines.append("## findings")
        findings = self._extract_findings(tool_name=tool_name, payload=payload)
        if findings:
            lines.append(findings)
        else:
            lines.append("- no findings extracted from tool output")
        lines.append("")

        lines.append("## raw_result")
        lines.append("```json")
        lines.append(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        lines.append("```")

        return "\n".join(lines).strip() + "\n"

    def _extract_findings(self, *, tool_name: str, payload: Any) -> str:
        if tool_name == "web_search_tool":
            return payload["answer"].strip()
        if tool_name == "sec_tool":
            extracts = payload["extracts"]
            findings = "\n\n".join(item.strip() for item in extracts if item.strip())
            if findings:
                return findings
            return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)

    def _extract_raw_result_from_markdown(self, content: str) -> Any:
        marker = "## raw_result"
        marker_idx = content.find(marker)
        if marker_idx < 0:
            return None
        fence_start = content.find("```json", marker_idx)
        if fence_start < 0:
            return None
        body_start = content.find("\n", fence_start)
        if body_start < 0:
            return None
        body_start += 1
        fence_end = content.find("```", body_start)
        if fence_end < 0:
            return None
        raw_json = content[body_start:fence_end].strip()
        if not raw_json:
            return None
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError:
            return None
