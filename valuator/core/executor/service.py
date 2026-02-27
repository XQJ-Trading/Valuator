from __future__ import annotations

import asyncio
import json
from hashlib import sha256
from typing import Any, Awaitable, Callable

from ...tools.code_execute_tool import ExecuteCodeTool
from ...tools.sec_tool import SECTool
from ...tools.base import ObservationData, ToolResult
from ...tools.web_search_tool import PerplexitySearchTool
from ...tools.yfinance_tool import YFinanceBalanceSheetTool
from ..contracts.plan import Plan, Task
from ..planner.service import _TOOL_ARGS
from ..workspace.service import Workspace

_TOOL_CLASSES: dict[str, type[Any]] = {
    "web_search_tool": PerplexitySearchTool,
    "sec_tool": SECTool,
    "yfinance_balance_sheet": YFinanceBalanceSheetTool,
    "code_execute_tool": ExecuteCodeTool,
}
_EXECUTOR_LEAF_CONCURRENCY = 4


class Executor:
    def __init__(self) -> None:
        if set(_TOOL_CLASSES) != set(_TOOL_ARGS):
            raise ValueError("planner/executor tool keys mismatch")
        self._tool_cache: dict[str, Any] = {}
        self._usage_writer: Any | None = None

    async def execute(
        self,
        query: str,
        plan: Plan,
        workspace: Workspace,
        usage_writer: Any | None = None,
        on_leaf_start: Callable[[Task], Awaitable[None]] | None = None,
        on_leaf_complete: Callable[[Task, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        _ = query
        self._usage_writer = usage_writer
        leaf_tasks = [task for task in plan.tasks if task.task_type == "leaf"]
        if not leaf_tasks:
            self._usage_writer = None
            return {"leaf_completed_tasks": [], "artifacts": []}

        sem = asyncio.Semaphore(_EXECUTOR_LEAF_CONCURRENCY)

        async def _run(task: Task) -> dict[str, Any]:
            async with sem:
                if on_leaf_start is not None:
                    await on_leaf_start(task)
                result = await self._execute_one_leaf(task, workspace)
                if on_leaf_complete is not None:
                    await on_leaf_complete(task, result)
                return result

        try:
            results = await asyncio.gather(*[_run(task) for task in leaf_tasks])
            return {
                "leaf_completed_tasks": [row["task_id"] for row in results],
                "artifacts": results,
            }
        finally:
            self._usage_writer = None

    async def _execute_one_leaf(self, task: Task, workspace: Workspace) -> dict[str, Any]:
        tool_name = task.tool.name
        tool_args = dict(task.tool.args)
        args_hash = self._hash_args(tool_args)
        cached = workspace.find_cached_output(tool_name, args_hash)
        if cached is not None:
            content = cached
            raw_result = self._extract_raw_result_from_markdown(cached)
        else:
            result = await self._get_tool(tool_name).execute(**tool_args)
            if not result.success:
                fallback = await self._run_failure_fallback(
                    task=task,
                    tool_name=tool_name,
                    failure=result,
                )
                if fallback is None:
                    raise ValueError(result.error or "tool returned failure")
                content, raw_result = fallback
            else:
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
                raw_result = payload

        leaf_output_path = workspace.leaf_output_path(task.id)
        workspace.write_leaf_output(task.id, content)
        workspace.write_output_metadata(
            leaf_output_path,
            {
                "tool": tool_name,
                "args_hash": args_hash,
            },
        )
        return {
            "task_id": task.id,
            "path": leaf_output_path,
            "content": content,
            "raw_result": raw_result,
        }

    async def _run_failure_fallback(
        self,
        *,
        task: Task,
        tool_name: str,
        failure: ToolResult,
    ) -> tuple[str, Any] | None:
        fallback = failure.metadata.get("fallback")
        if fallback is None:
            return None
        fallback_tool_name = fallback.get("tool_name", "").strip()
        if not fallback_tool_name:
            raise ValueError("fallback.tool_name is required")
        fallback_tool_args = dict(fallback.get("tool_args") or {})
        if fallback_tool_name not in _TOOL_CLASSES:
            raise ValueError(f"unsupported fallback tool: {fallback_tool_name}")

        fallback_tool = self._get_tool(fallback_tool_name)
        fallback_result = await fallback_tool.execute(**fallback_tool_args)
        if not fallback_result.success:
            raise ValueError(fallback_result.error or "tool returned failure")

        payload = fallback_result.result
        if isinstance(payload, ObservationData):
            payload = payload.data
        if isinstance(payload, dict):
            payload = dict(payload)
        else:
            payload = {"result": payload}
        payload["fallback_from"] = tool_name
        payload["fallback_reason"] = failure.error or ""
        error_code = (failure.metadata.get("error_code") or "").strip()
        if error_code:
            payload["fallback_error_code"] = error_code

        content = self._render_tool_markdown(
            task_id=task.id,
            tool_name=fallback_tool_name,
            tool_args=fallback_tool_args,
            payload=payload,
            metadata=fallback_result.metadata,
        )
        return content, payload

    def _get_tool(self, tool_name: str) -> Any:
        cached = self._tool_cache.get(tool_name)
        if cached is not None:
            cached.bind_usage_writer(self._usage_writer)
            return cached

        try:
            tool_class = _TOOL_CLASSES[tool_name]
        except KeyError as exc:
            raise RuntimeError(f"executor tool registry mismatch: {tool_name}") from exc
        tool = tool_class()
        self._tool_cache[tool_name] = tool
        tool.bind_usage_writer(self._usage_writer)
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
        findings = self._extract_findings(payload=payload)
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

    def _extract_findings(self, *, payload: Any) -> str:
        if isinstance(payload, dict):
            summary = payload.get("summary")
            if isinstance(summary, str) and summary.strip():
                return summary.strip()
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
