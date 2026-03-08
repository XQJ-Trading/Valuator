from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from hashlib import sha256
from typing import Any, Awaitable, Callable

from ...domain import DomainModuleContext
from ...domain.ir import build_domain_artifact_fields
from ...tools.balance_sheet_extraction_tool import BalanceSheetExtractionTool
from ...tools.ceo_analysis_tool import CEOAnalysisTool
from ...tools.code_execute_tool import ExecuteCodeTool
from ...tools.dcf_pipeline_tool import DCFPipelineTool
from ...tools.sec_tool import SECTool
from ...tools.base import ObservationData, ToolResult
from ...tools.specs import TOOL_SPECS
from ...tools.web_search_tool import PerplexitySearchTool
from ...tools.yfinance_tool import YFinanceBalanceSheetTool
from ..contracts.plan import ExecutionArtifact, ExecutionResult, Plan, Task, TaskReport
from ..workspace.service import Workspace

_TOOL_CLASSES: dict[str, type[Any]] = {
    "web_search_tool": PerplexitySearchTool,
    "sec_tool": SECTool,
    "yfinance_balance_sheet": YFinanceBalanceSheetTool,
    "code_execute_tool": ExecuteCodeTool,
    "ceo_analysis_tool": CEOAnalysisTool,
    "dcf_pipeline_tool": DCFPipelineTool,
    "balance_sheet_extraction_tool": BalanceSheetExtractionTool,
}
_EXECUTOR_LEAF_CONCURRENCY = 4
_EXECUTABLE_TASK_TYPES = frozenset({"leaf", "module"})


class Executor:
    def __init__(self) -> None:
        if set(_TOOL_CLASSES) != set(TOOL_SPECS):
            raise ValueError("planner/executor tool keys mismatch")
        self._tool_cache: dict[str, Any] = {}
        self._usage_writer: Any | None = None
        self._domain_context: DomainModuleContext | None = None

    def bind_domain_context(
        self,
        domain_context: DomainModuleContext | None,
    ) -> None:
        self._domain_context = domain_context

    async def execute(
        self,
        query: str,
        plan: Plan,
        workspace: Workspace,
        usage_writer: Any | None = None,
        on_leaf_start: Callable[[Task], Awaitable[None]] | None = None,
        on_leaf_complete: Callable[[Task, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> ExecutionResult:
        _ = query
        self._usage_writer = usage_writer
        task_map = {task.id: task for task in plan.tasks}
        executable_tasks = {
            task.id: task
            for task in plan.tasks
            if task.task_type in _EXECUTABLE_TASK_TYPES
        }
        if not executable_tasks:
            self._usage_writer = None
            return ExecutionResult()

        dependency_cache: dict[str, set[str]] = {}
        required_dependencies = {
            task_id: self._required_executable_dependencies(
                task_id=task_id,
                task_map=task_map,
                cache=dependency_cache,
            )
            for task_id in executable_tasks
        }
        sem = asyncio.Semaphore(_EXECUTOR_LEAF_CONCURRENCY)
        completed: dict[str, ExecutionArtifact] = {}
        results: list[ExecutionArtifact] = []
        pending = dict(executable_tasks)

        try:
            while pending:
                ready = [
                    task
                    for task_id, task in pending.items()
                    if required_dependencies[task_id].issubset(completed)
                ]
                if not ready:
                    raise ValueError("executable task graph has unresolved dependencies")

                batch_results = await self._execute_task_batch(
                    tasks=ready,
                    task_map=task_map,
                    completed=completed,
                    reports=None,
                    workspace=workspace,
                    semaphore=sem,
                    on_leaf_start=on_leaf_start,
                    on_leaf_complete=on_leaf_complete,
                )
                for artifact in batch_results:
                    results.append(artifact)
                    completed[artifact.task_id] = artifact
                    pending.pop(artifact.task_id, None)

            return ExecutionResult(
                completed_leaf_task_ids=[
                    artifact.task_id
                    for artifact in results
                    if executable_tasks[artifact.task_id].task_type == "leaf"
                ],
                artifacts=results,
            )
        finally:
            self._usage_writer = None

    async def execute_batch(
        self,
        *,
        plan: Plan,
        task_ids: list[str],
        workspace: Workspace,
        usage_writer: Any | None = None,
        on_leaf_start: Callable[[Task], Awaitable[None]] | None = None,
        on_leaf_complete: Callable[[Task, dict[str, Any]], Awaitable[None]] | None = None,
        dependency_reports: dict[str, TaskReport] | None = None,
    ) -> list[ExecutionArtifact]:
        if not task_ids:
            return []

        self._usage_writer = usage_writer
        task_map = {task.id: task for task in plan.tasks}
        tasks = [task_map[task_id] for task_id in task_ids]
        sem = asyncio.Semaphore(_EXECUTOR_LEAF_CONCURRENCY)

        try:
            return await self._execute_task_batch(
                tasks=tasks,
                task_map=task_map,
                completed={},
                reports=dependency_reports,
                workspace=workspace,
                semaphore=sem,
                on_leaf_start=on_leaf_start,
                on_leaf_complete=on_leaf_complete,
            )
        finally:
            self._usage_writer = None

    async def _execute_task_batch(
        self,
        *,
        tasks: list[Task],
        task_map: dict[str, Task],
        completed: dict[str, ExecutionArtifact],
        reports: dict[str, TaskReport] | None,
        workspace: Workspace,
        semaphore: asyncio.Semaphore,
        on_leaf_start: Callable[[Task], Awaitable[None]] | None,
        on_leaf_complete: Callable[[Task, dict[str, Any]], Awaitable[None]] | None,
    ) -> list[ExecutionArtifact]:
        async def _run(task: Task) -> ExecutionArtifact:
            async with semaphore:
                if on_leaf_start is not None:
                    await on_leaf_start(task)
                artifact = await self._execute_one_task(
                    task=task,
                    task_map=task_map,
                    completed=completed,
                    reports=reports,
                    workspace=workspace,
                )
                if on_leaf_complete is not None:
                    await on_leaf_complete(task, asdict(artifact))
                return artifact

        return list(await asyncio.gather(*[_run(task) for task in tasks]))

    async def _execute_one_task(
        self,
        *,
        task: Task,
        task_map: dict[str, Task],
        completed: dict[str, ExecutionArtifact],
        reports: dict[str, TaskReport] | None,
        workspace: Workspace,
    ) -> ExecutionArtifact:
        tool_name = task.tool.name
        tool_args = self._tool_args_for_task(
            task=task,
            task_map=task_map,
            completed=completed,
            reports=reports,
        )
        if self._domain_context is not None and self._domain_context.module_ids:
            allowed: set[str] = set()
            for module_id in self._domain_context.module_ids:
                module = self._domain_context.modules.get(module_id)
                if module is None:
                    continue
                for name in module.tools:
                    allowed.add(name)
            if allowed and tool_name not in allowed:
                raise ValueError(
                    f"tool '{tool_name}' is not allowed for current domain context"
                )
        args_hash = self._hash_args(tool_args)
        cached = workspace.find_cached_output(tool_name, args_hash)
        domain_fields: dict[str, Any] = {}
        if cached is not None:
            content = cached
            raw_result = self._extract_raw_result_from_markdown(cached)
            domain_fields = build_domain_artifact_fields(
                tool_name=tool_name,
                raw_result=raw_result,
                metadata={},
                fallback_domain_id=task.domain_id.strip(),
            )
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
                domain_fields = build_domain_artifact_fields(
                    tool_name=tool_name,
                    raw_result=raw_result,
                    metadata=result.metadata or {},
                    fallback_domain_id=task.domain_id.strip(),
                )

        leaf_output_path = workspace.leaf_output_path(task.id)
        workspace.write_leaf_output(task.id, content)
        workspace.write_output_metadata(
            leaf_output_path,
            {
                "tool": tool_name,
                "args_hash": args_hash,
            },
        )
        return ExecutionArtifact(
            task_id=task.id,
            path=leaf_output_path,
            content=content,
            raw_result=raw_result,
            domain_id=str(domain_fields.get("domain_id") or ""),
            domain_summary=str(domain_fields.get("domain_summary") or ""),
            domain_key_values=dict(domain_fields.get("domain_key_values") or {}),
            domain_payload=dict(domain_fields.get("domain_payload") or {}),
        )

    def _tool_args_for_task(
        self,
        *,
        task: Task,
        task_map: dict[str, Task],
        completed: dict[str, ExecutionArtifact],
        reports: dict[str, TaskReport] | None,
    ) -> dict[str, Any]:
        tool_args = dict(task.tool.args)
        if task.task_type != "module":
            return tool_args

        context = self._dependency_context(
            task=task,
            task_map=task_map,
            completed=completed,
            reports=reports,
        )
        if not context:
            return tool_args

        if task.tool.name == "balance_sheet_extraction_tool":
            tool_args["summary"] = context
            return tool_args

        tool_args["context"] = context
        return tool_args

    def _required_executable_dependencies(
        self,
        *,
        task_id: str,
        task_map: dict[str, Task],
        cache: dict[str, set[str]],
    ) -> set[str]:
        cached = cache.get(task_id)
        if cached is not None:
            return cached

        task = task_map[task_id]
        required: set[str] = set()
        for dep_id in task.deps:
            dep = task_map[dep_id]
            if dep.task_type in _EXECUTABLE_TASK_TYPES:
                required.add(dep_id)
                continue
            required.update(
                self._required_executable_dependencies(
                    task_id=dep_id,
                    task_map=task_map,
                    cache=cache,
                )
            )
        cache[task_id] = required
        return required

    def _dependency_context(
        self,
        *,
        task: Task,
        task_map: dict[str, Task],
        completed: dict[str, ExecutionArtifact],
        reports: dict[str, TaskReport] | None,
    ) -> str:
        if not task.deps:
            return ""

        lines: list[str] = []
        for dep_id in task.deps:
            self._append_dependency_context(
                task_id=dep_id,
                task_map=task_map,
                completed=completed,
                reports=reports,
                lines=lines,
            )
        return "\n\n".join(lines)

    def _append_dependency_context(
        self,
        *,
        task_id: str,
        task_map: dict[str, Task],
        completed: dict[str, ExecutionArtifact],
        reports: dict[str, TaskReport] | None,
        lines: list[str],
    ) -> None:
        if reports is not None:
            report = reports.get(task_id)
            if report is not None:
                markdown = report.markdown.strip()
                if markdown:
                    lines.append(f"--- task: {task_id} ---")
                    lines.append(markdown)
                    return

        task = task_map[task_id]
        if task.task_type in _EXECUTABLE_TASK_TYPES:
            result = completed[task_id]
            lines.append(f"--- task: {task_id} ---")
            lines.append(result.content.strip())
            return

        for dep_id in task.deps:
            self._append_dependency_context(
                task_id=dep_id,
                task_map=task_map,
                completed=completed,
                reports=reports,
                lines=lines,
            )

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
        payload = (
            dict(payload) if isinstance(payload, dict) else {"result": payload}
        )
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
