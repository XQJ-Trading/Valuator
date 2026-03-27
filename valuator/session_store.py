from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from valuator.tools.base import ToolResult
from valuator.utils.config import ROOT_DIR
from valuator.utils.session_trace import SessionTraceWriter, task_rel_path, utc_isoformat

from .core.task import Task

CURRENT_ROUND = 1


def valuator_sessions_root() -> Path:
    return ROOT_DIR / "valuator" / "sessions"


def round_dir_name(round_number: int) -> str:
    return f"round-{round_number:02d}"


class ValuatorSessionStore:
    def __init__(
        self,
        *,
        session_id: str,
        query: str,
        model: str,
        created_at: datetime | str,
        context: dict[str, Any] | None = None,
        root_dir: Path | None = None,
    ) -> None:
        self.session_id = session_id
        self.query = query
        self.model = model
        self.created_at = utc_isoformat(created_at)
        self.effective_query = query
        self.current_round = CURRENT_ROUND
        self.round_dir = round_dir_name(self.current_round)
        self.root_dir = (root_dir or valuator_sessions_root()).resolve()
        self.session_dir = self.root_dir / session_id
        self.input_dir = self.session_dir / "input"
        self.plan_active_dir = self.session_dir / "plan" / "active"
        self.plan_round_dir = self.session_dir / "plan" / self.round_dir
        self.tasks_dir = self.session_dir / "tasks"
        self.diagnostics_dir = self.session_dir / "diagnostics"
        self.review_dir = self.session_dir / "review"
        self.review_history_path = self.review_dir / "history" / f"{self.round_dir}.json"
        self.output_dir = self.session_dir / "output"
        self._lock = threading.RLock()
        self._analysis_payload: dict[str, Any] | None = None
        self._root_task_id: str | None = None
        self._task_created_at: dict[str, str] = {}
        self._task_artifacts: dict[str, dict[str, str | None]] = {}
        self._plan_tasks: dict[str, dict[str, Any]] = {}
        self.trace_writer = SessionTraceWriter(
            session_id=session_id,
            query=query,
            model=model,
            created_at=created_at,
            session_dir=self.session_dir,
            tasks_dir=self.tasks_dir,
            diagnostics_dir=self.diagnostics_dir,
            session_metadata_callback=self._merge_trace_fields,
        )
        self._session_payload: dict[str, Any] = {
            "session_id": session_id,
            "query": query,
            "effective_query": query,
            "status": "running",
            "created_at": self.created_at,
            "updated_at": self.created_at,
            "model": model,
            "root_task_id": None,
            "current_round": self.current_round,
            "event_count": 0,
            "step_count": 0,
            "llm_call_count": 0,
            "paths": {
                "session": "session.json",
                "timeline": "timeline.jsonl",
                "input": "input",
                "plan": "plan",
                "tasks": "tasks",
                "review": "review",
                "output": "output",
                "diagnostics": "diagnostics",
                "llm_usage": "diagnostics/llm_usage.jsonl",
            },
        }

        for path in (
            self.input_dir,
            self.plan_active_dir,
            self.plan_round_dir,
            self.tasks_dir,
            self.diagnostics_dir,
            self.review_dir / "history",
            self.output_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

        self._write_text(self.input_dir / "user_input.md", query.strip() + "\n")
        self._write_json(self.input_dir / "request_context.json", context or {})
        self.write_review(status="running")
        self._write_session()

    def update_trace_query(self, query: str) -> None:
        with self._lock:
            self.effective_query = query
            self._session_payload["effective_query"] = query
            self._session_payload["updated_at"] = utc_isoformat()
            self._write_session()

    def write_plan(self, *, effective_query: str, analysis: Any, root_task: Task) -> None:
        with self._lock:
            self.effective_query = effective_query
            self._analysis_payload = asdict(analysis)
            self._root_task_id = root_task.id
            self._session_payload["effective_query"] = effective_query
            self._session_payload["root_task_id"] = root_task.id
            self._session_payload["updated_at"] = utc_isoformat()
            self._write_session()
            self.sync_task_tree(root_task)

    def sync_task_tree(self, root_task: Task) -> None:
        with self._lock:
            self._root_task_id = root_task.id
            self._session_payload["root_task_id"] = root_task.id
            self._plan_tasks.clear()

            unit_count = 0
            default_domain_id = ""
            if self._analysis_payload is not None:
                unit_count = len(self._analysis_payload.get("units", []))
                domain_ids = self._analysis_payload.get("domain_ids", [])
                if domain_ids:
                    default_domain_id = domain_ids[0]

            tree = self._write_task_tree(
                root_task,
                unit_count=unit_count,
                default_domain_id=default_domain_id,
            )
            self._write_json(self.plan_active_dir / "task_tree.json", tree)
            self._write_text(
                self.plan_active_dir / "task_tree.md",
                f"# Task Tree\n\n{self._render_tree_md(root_task)}\n",
            )

            # The server seeds the root task before query analysis exists.
            if self._analysis_payload is not None:
                decomposition = {
                    "query": self.query,
                    "effective_query": self.effective_query,
                    "analysis": self._analysis_payload,
                    "tasks": list(self._plan_tasks.values()),
                    "root_task_id": self._root_task_id,
                }
                self._write_json(self.plan_active_dir / "decomposition.json", decomposition)
                self._write_json(self.plan_round_dir / "decomposition.json", decomposition)

            self._session_payload["updated_at"] = utc_isoformat()
            self._write_session()

    def save_decomposition_snapshot(self, task: Task, children: list[Task]) -> None:
        snapshot_dir = self.plan_active_dir / "snapshots" / task_rel_path(task.id)
        lines = [f"# {task.id}\n", f"{task.description}\n", "## Children\n"]
        for child in children:
            hint = f" (`{child.tool_hint}`)" if child.tool_hint.strip() else ""
            lines.append(f"- **{child.id}**{hint}: {child.description}")
        self._write_text(snapshot_dir / "decomposition.md", "\n".join(lines) + "\n")

    def write_execution_result(
        self,
        *,
        task_id: str,
        tool_name: str,
        args: dict[str, Any],
        result: ToolResult,
        started_at: str,
        duration_ms: float,
    ) -> None:
        with self._lock:
            plan_task = self._plan_tasks[task_id]
            task_dir = self._task_dir(task_id) / "execution"
            os.makedirs(task_dir, exist_ok=True)
            result_path = task_dir / "result.md"
            result_json_path = task_dir / "result.json"
            meta_path = task_dir / "result.md.meta.json"

            domain_summary = ""
            if isinstance(result.result, dict):
                for key in ("domain_summary", "summary", "findings", "result", "content"):
                    candidate = result.result.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        domain_summary = candidate.strip()
                        break
            elif isinstance(result.result, str) and result.result.strip():
                domain_summary = result.result.strip()

            self._write_text(result_path, self._artifact_text(result.result, result.error))
            self._write_json(
                result_json_path,
                {
                    "task_id": task_id,
                    "task_type": plan_task["task_type"],
                    "query_unit_ids": list(plan_task["query_unit_ids"]),
                    "tool_name": tool_name,
                    "domain_id": plan_task["domain_id"],
                    "domain_summary": domain_summary,
                    "domain_key_values": {},
                    "tool_metadata": result.metadata,
                    "raw_result": result.result,
                },
            )
            self._write_json(
                meta_path,
                {
                    "tool": tool_name,
                    "args_hash": self._args_hash(args),
                    "args": args,
                    "success": result.success,
                    "error": result.error,
                    "retrieval": result.metadata,
                    "started_at": started_at,
                    "duration_ms": round(duration_ms, 3),
                },
            )

            artifacts = self._artifacts_for(task_id)
            artifacts["execution_result_path"] = self._task_rel(task_id, result_path)
            artifacts["execution_meta_path"] = self._task_rel(task_id, meta_path)
            self._session_payload["updated_at"] = utc_isoformat()
            self._write_session()

    def write_aggregation_report(self, *, task_id: str, output: Any) -> None:
        with self._lock:
            plan_task = self._plan_tasks[task_id]
            task_dir = self._task_dir(task_id) / "aggregation"
            os.makedirs(task_dir, exist_ok=True)
            report_path = task_dir / "report.md"
            ledger_path = task_dir / "ledger.json"
            source_reports = list(plan_task["deps"]) if plan_task["task_type"] == "merge" else []
            child_results = self._collect_child_results(source_reports)
            sources = (
                [f"report:{child_id}" for child_id in source_reports]
                if plan_task["task_type"] == "merge"
                else [self._artifacts_for(task_id)["execution_result_path"] or "execution/result.md"]
            )

            lines = [f"# {task_id}", ""]
            if len(sources) == 1:
                lines.extend([f"## source: {sources[0]}", ""])
            elif sources:
                lines.extend(["## sources", ""])
                lines.extend(f"- {entry}" for entry in sources)
                lines.append("")
            if child_results:
                lines.extend(["## child results", ""])
                for child in child_results:
                    lines.append(f"### {child['task_id']}")
                    lines.append("")
                    summary = str(child.get("summary") or "").strip()
                    if summary:
                        lines.append(summary)
                    else:
                        lines.append("(child result is empty)")
                    lines.append("")
            lines.append(self._artifact_text(output, None).strip())
            self._write_text(report_path, "\n".join(lines).strip() + "\n")

            if isinstance(output, dict):
                facts = output.get("facts") if isinstance(output.get("facts"), dict) else output
            elif isinstance(output, str) and output.strip():
                facts = {"summary": output.strip()}
            else:
                result_payload = self._read_json_if_exists(
                    self._task_dir(task_id) / "execution" / "result.json"
                )
                if result_payload is not None:
                    facts = result_payload.get("raw_result") or {}
                elif child_results:
                    facts = {
                        "children": [
                            {
                                "task_id": child["task_id"],
                                "summary": child.get("summary"),
                                "result": child.get("result"),
                            }
                            for child in child_results
                        ]
                    }
                else:
                    facts = {}

            domain_ids: list[str] = []
            if self._analysis_payload is not None:
                domain_ids = list(self._analysis_payload.get("domain_ids", []))

            self._write_json(
                ledger_path,
                {
                    "task_id": task_id,
                    "task_type": plan_task["task_type"],
                    "query_unit_ids": list(plan_task["query_unit_ids"]),
                    "domain_ids": domain_ids,
                    "sources": sources,
                    "source_reports": source_reports,
                    "child_results": child_results,
                    "facts": facts,
                    "aspect_facts": [],
                    "uncovered_aspects": [],
                },
            )

            artifacts = self._artifacts_for(task_id)
            artifacts["aggregation_report_path"] = self._task_rel(task_id, report_path)
            self._session_payload["updated_at"] = utc_isoformat()
            self._write_session()

    def write_final_output(self, content: str, root_task: Task | None = None) -> None:
        with self._lock:
            if self._root_task_id is None:
                raise RuntimeError("root task id is not set")

            requirements: list[dict[str, Any]] = []
            domain_ids: list[str] = []
            if self._analysis_payload is not None:
                requirements = list(self._analysis_payload.get("requirements", []))
                domain_ids = list(self._analysis_payload.get("domain_ids", []))

            final_path = self.output_dir / "final.md"
            meta_path = self.output_dir / "final.md.meta.json"
            trace_path = self.output_dir / "final.trace.json"
            source_reports = self._collect_all_task_ids()

            self._write_text(final_path, content.strip() + "\n")
            self._write_json(
                meta_path,
                {
                    "session_id": self.session_id,
                    "root_task_id": self._root_task_id,
                    "model": self.model,
                    "updated_at": utc_isoformat(),
                },
            )
            self._write_json(
                trace_path,
                {
                    "root_task_id": self._root_task_id,
                    "source_reports": source_reports,
                    "source_materials": [f"report:{task_id}" for task_id in source_reports],
                    "covered_requirement_ids": [item["id"] for item in requirements],
                    "missing_requirement_ids": [],
                    "domain_coverage": {
                        "final_ids": domain_ids,
                        "evidence_ids": domain_ids,
                    },
                    "aspect_coverage": {},
                },
            )

            self._artifacts_for(self._root_task_id)["final_output_path"] = self._task_rel(
                self._root_task_id,
                final_path,
            )
            if root_task is not None:
                self._write_text(
                    self.output_dir / "final.trace.md",
                    f"# Final Trace\n\n{self._render_tree_md(root_task)}\n",
                )
            self._session_payload["updated_at"] = utc_isoformat()
            self._write_session()

    def write_review(
        self,
        *,
        status: str,
        actions: list[Any] | None = None,
        coverage_feedback: dict[str, Any] | None = None,
        quant_axes: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "status": status,
            "round": self.current_round,
            "actions": actions or [],
            "coverage_feedback": coverage_feedback or {},
            "now_utc": utc_isoformat(),
            "quant_axes": quant_axes or {},
        }
        self._write_json(self.review_dir / "latest.json", payload)
        self._write_json(self.review_history_path, payload)

    def update_session(
        self,
        *,
        status: str,
        error: str | None = None,
        updated_at: datetime | str | None = None,
    ) -> None:
        with self._lock:
            self._session_payload["status"] = status
            self._session_payload["updated_at"] = utc_isoformat(updated_at)
            if error:
                self._session_payload["error"] = error
            else:
                self._session_payload.pop("error", None)
            self._write_session()

    def _write_task_tree(
        self,
        task: Task,
        *,
        unit_count: int,
        default_domain_id: str,
    ) -> dict[str, Any]:
        created_at = self._task_created_at.setdefault(task.id, utc_isoformat())
        task_dir = self._task_dir(task.id)
        children = task.children()
        task_type = "merge" if task.id == self._root_task_id or children else "leaf"
        query_unit_ids = (
            list(range(unit_count))
            if task.id == self._root_task_id
            else [0] if task_type == "leaf" and unit_count == 1 else []
        )
        tool = None
        if task_type == "leaf":
            if task.last_tool_request is not None:
                tool = {
                    "name": task.last_tool_request.tool_name,
                    "args": dict(task.last_tool_request.args),
                }
            elif task.tool_hint.strip():
                tool = {"name": task.tool_hint.strip(), "args": {}}

        plan_task = {
            "id": task.id,
            "task_type": task_type,
            "query_unit_ids": query_unit_ids,
            "deps": [child.id for child in children] if task_type == "merge" else [],
            "tool": tool,
            "domain_id": default_domain_id,
            "output": "execution/result.md" if task_type == "leaf" else "",
            "description": task.description,
            "merge_instruction": "",
        }
        self._plan_tasks[task.id] = plan_task

        payload = {
            "task_id": task.id,
            "parent_id": task.parent_id,
            "description": task.description,
            "state": task.state.value,
            "created_at": created_at,
            "updated_at": utc_isoformat(),
            "task_type": task_type,
            "query_unit_ids": query_unit_ids,
            "deps": list(plan_task["deps"]),
            "tool": tool,
            "domain_id": default_domain_id,
            "output": plan_task["output"],
            "merge_instruction": "",
            "children": [child.id for child in children],
            "artifacts": self._artifacts_for(task.id),
        }
        self._write_json(task_dir / "task.json", payload)

        children_payload = [
            self._write_task_tree(
                child,
                unit_count=unit_count,
                default_domain_id=default_domain_id,
            )
            for child in children
        ]
        return {
            "task_id": task.id,
            "description": task.description,
            "state": task.state.value,
            "path": self._rel(task_dir),
            "children": children_payload,
        }

    def _collect_all_task_ids(self) -> list[str]:
        return [
            task_id
            for task_id in self._plan_tasks
            if task_id != self._root_task_id
        ]

    def _artifacts_for(self, task_id: str) -> dict[str, str | None]:
        return self._task_artifacts.setdefault(
            task_id,
            {
                "execution_result_path": None,
                "execution_meta_path": None,
                "aggregation_report_path": None,
                "final_output_path": None,
            },
        )

    def _merge_trace_fields(self, fields: Mapping[str, Any]) -> None:
        with self._lock:
            self._session_payload.update(fields)
            self._session_payload["updated_at"] = utc_isoformat(
                fields.get("updated_at") if "updated_at" in fields else None
            )
            self._write_session()

    def _task_dir(self, task_id: str) -> Path:
        return self.tasks_dir / task_rel_path(task_id)

    def _task_rel(self, task_id: str, path: Path) -> str:
        return os.path.relpath(path, start=self._task_dir(task_id))

    def _write_session(self) -> None:
        self._write_json(self.session_dir / "session.json", self._session_payload)

    def _rel(self, path: Path) -> str:
        return str(path.relative_to(self.session_dir))

    @staticmethod
    def _args_hash(args: dict[str, Any]) -> str:
        text = json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _artifact_text(value: Any, error: str | None) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip() + "\n"
        if isinstance(value, dict):
            for key in ("markdown", "report", "content", "findings", "result"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip() + "\n"
        if error:
            return error.strip() + "\n"
        return json.dumps(value, ensure_ascii=False, indent=2, default=str).strip() + "\n"

    def _collect_child_results(self, child_task_ids: list[str]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for child_task_id in child_task_ids:
            execution_payload = self._read_json_if_exists(
                self._task_dir(child_task_id) / "execution" / "result.json"
            )
            if execution_payload is not None:
                raw_result = execution_payload.get("raw_result")
                summary = execution_payload.get("domain_summary")
                if not isinstance(summary, str) or not summary.strip():
                    summary = self._artifact_text(raw_result, None).strip()
                records.append(
                    {
                        "task_id": child_task_id,
                        "summary": summary,
                        "result": raw_result,
                    }
                )
                continue

            ledger_payload = self._read_json_if_exists(
                self._task_dir(child_task_id) / "aggregation" / "ledger.json"
            )
            if ledger_payload is not None:
                facts = ledger_payload.get("facts")
                summary = ""
                if isinstance(facts, dict):
                    candidate = facts.get("summary")
                    if isinstance(candidate, str):
                        summary = candidate.strip()
                if not summary:
                    summary = self._artifact_text(facts, None).strip()
                records.append(
                    {
                        "task_id": child_task_id,
                        "summary": summary,
                        "result": facts,
                    }
                )
                continue

            records.append(
                {
                    "task_id": child_task_id,
                    "summary": "",
                    "result": None,
                }
            )
        return records

    @staticmethod
    def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _render_tree_md(task: Task, depth: int = 0) -> str:
        indent = "  " * depth
        children = task.children()
        kind = f"leaf: {task.tool_hint}" if not children and task.tool_hint.strip() else ""
        suffix = f" ({kind})" if kind else ""
        line = f"{indent}- **{task.id}** [{task.state.value}] {task.description}{suffix}"
        lines = [line]
        for child in children:
            lines.append(ValuatorSessionStore._render_tree_md(child, depth + 1))
        return "\n".join(lines)
