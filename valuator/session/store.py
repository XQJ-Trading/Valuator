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

from valuator.core.task import Task
from valuator.core.types import ToolResult
from valuator.utils.config import ROOT_DIR
from valuator.utils.time_utils import kst_isoformat

from .browse_tree import build_browse_tree
from .citation_links import (
    apply_citation_links_to_tool_payload,
    strip_lenticular_source_refs_from_tool_payload,
)
from .markdown import (
    render_final_markdown,
    strip_markdown_title,
)
from .report_artifacts import artifact_text, load_report_source, render_aggregation_report
from .task_tree import build_task_tree_snapshot, render_tree_markdown
from .trace import SessionTraceWriter, task_rel_path

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
        self.created_at = kst_isoformat(created_at)
        self.effective_query = query
        self.current_round = CURRENT_ROUND
        self.round_dir = round_dir_name(self.current_round)
        self.root_dir = (root_dir or valuator_sessions_root()).resolve()
        self.session_dir = self.root_dir / session_id
        self.input_dir = self.session_dir / "input"
        self.plan_active_dir = self.session_dir / "plan" / "active"
        self.plan_round_dir = self.session_dir / "plan" / self.round_dir
        self.tasks_dir = self.session_dir / "tasks"
        self.trace_dir = self.session_dir / "trace"
        self.review_dir = self.session_dir / "review"
        self.review_history_path = (
            self.review_dir / "history" / f"{self.round_dir}.json"
        )
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
            trace_dir=self.trace_dir,
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
                "trace": "trace",
                "llm_usage": "trace/llm_usage.jsonl",
                "debug_steps": "debug/steps",
            },
        }

        for path in (
            self.input_dir,
            self.plan_active_dir,
            self.plan_round_dir,
            self.tasks_dir,
            self.trace_dir,
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
            self._session_payload["updated_at"] = kst_isoformat()
            self._write_session()

    def write_plan(
        self, *, effective_query: str, analysis: Any, root_task: Task
    ) -> None:
        with self._lock:
            self.effective_query = effective_query
            self._analysis_payload = asdict(analysis)
            self._root_task_id = root_task.id
            self._session_payload["effective_query"] = effective_query
            self._session_payload["root_task_id"] = root_task.id
            self._session_payload["updated_at"] = kst_isoformat()
            self._write_session()
            self.sync_task_tree(root_task)

    def sync_task_tree(self, root_task: Task) -> None:
        with self._lock:
            self._root_task_id = root_task.id
            self._session_payload["root_task_id"] = root_task.id

            unit_count = 0
            if self._analysis_payload is not None:
                unit_count = len(self._analysis_payload.get("units", []))

            snapshot = build_task_tree_snapshot(
                root_task,
                root_task_id=root_task.id,
                unit_count=unit_count,
                session_dir=self.session_dir,
                tasks_dir=self.tasks_dir,
                task_created_at=self._task_created_at,
                task_artifacts=self._task_artifacts,
            )
            self._plan_tasks = snapshot.plan_tasks
            for task_id, payload in snapshot.task_payloads.items():
                self._write_json(self._task_dir(task_id) / "task.json", payload)
            self._write_json(self.plan_active_dir / "task_tree.json", snapshot.tree)
            self._write_text(
                self.plan_active_dir / "task_tree.md",
                f"# Task Tree\n\n{snapshot.tree_markdown}\n",
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
                self._write_json(
                    self.plan_active_dir / "decomposition.json", decomposition
                )
                self._write_json(
                    self.plan_round_dir / "decomposition.json", decomposition
                )

            self._session_payload["updated_at"] = kst_isoformat()
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
    ) -> dict[str, str]:
        with self._lock:
            plan_task = self._plan_tasks[task_id]
            task_dir = self._task_dir(task_id) / "execution"
            os.makedirs(task_dir, exist_ok=True)
            result_path = task_dir / "result.md"
            result_json_path = task_dir / "result.json"
            meta_path = task_dir / "result.md.meta.json"

            display_payload = (
                apply_citation_links_to_tool_payload(result.result, result.metadata)
                if result.success
                else result.result
            )
            source_ref: list[str] = []
            if result.success:
                display_payload, source_ref = (
                    strip_lenticular_source_refs_from_tool_payload(display_payload)
                )

            domain_summary = ""
            if isinstance(display_payload, dict):
                for key in (
                    "domain_summary",
                    "summary",
                    "findings",
                    "result",
                    "content",
                ):
                    candidate = display_payload.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        domain_summary = candidate.strip()
                        break
            elif isinstance(display_payload, str) and display_payload.strip():
                domain_summary = display_payload.strip()

            self._write_text(
                result_path, artifact_text(display_payload, result.error)
            )
            self._write_json(
                result_json_path,
                {
                    "task_id": task_id,
                    "task_type": plan_task["task_type"],
                    "query_unit_ids": list(plan_task["query_unit_ids"]),
                    "tool_name": tool_name,
                    "domain_summary": domain_summary,
                    "domain_key_values": {},
                    "tool_metadata": result.metadata,
                    "raw_result": result.result,
                },
            )
            retrieval_meta = dict(result.metadata)
            if source_ref:
                retrieval_meta["source_ref"] = source_ref

            self._write_json(
                meta_path,
                {
                    "tool": tool_name,
                    "args_hash": self._args_hash(args),
                    "args": args,
                    "success": result.success,
                    "error": result.error,
                    "retrieval": retrieval_meta,
                    "started_at": started_at,
                    "duration_ms": round(duration_ms, 3),
                },
            )

            artifacts = self._artifacts_for(task_id)
            artifact_refs = {
                "execution_result_path": self._task_rel(task_id, result_path),
                "execution_meta_path": self._task_rel(task_id, meta_path),
            }
            artifacts.update(artifact_refs)
            self._session_payload["updated_at"] = kst_isoformat()
            self._write_session()
            return artifact_refs

    def write_aggregation_report(
        self,
        *,
        task_id: str,
        output: Any,
    ) -> dict[str, str]:
        with self._lock:
            plan_task = self._plan_tasks[task_id]
            task_dir = self._task_dir(task_id) / "aggregation"
            os.makedirs(task_dir, exist_ok=True)
            report_path = task_dir / "report.md"
            raw_results_path = task_dir / "raw_results.json"
            source_reports = (
                list(plan_task["deps"]) if plan_task["task_type"] == "merge" else []
            )
            child_sources = [
                load_report_source(
                    task_id=child_task_id,
                    task_dir=self._task_dir(child_task_id),
                    task_name=str(
                        self._plan_tasks.get(child_task_id, {}).get("task_name")
                        or child_task_id
                    ).replace("_", " "),
                    rel=self._rel,
                )
                for child_task_id in source_reports
            ]
            current_source = load_report_source(
                task_id=task_id,
                task_dir=self._task_dir(task_id),
                task_name=str(plan_task.get("task_name") or task_id).replace("_", " "),
                rel=self._rel,
            )

            title = str(plan_task.get("task_name") or task_id).replace("_", " ")
            report_markdown, facts = render_aggregation_report(
                title=title,
                output=output,
                child_sources=child_sources,
                current_source=current_source,
            )
            self._write_text(report_path, report_markdown)

            self._write_json(
                raw_results_path,
                {
                    "task_id": task_id,
                    "task_type": plan_task["task_type"],
                    "query_unit_ids": list(plan_task["query_unit_ids"]),
                    "source_task_ids": source_reports,
                    "child_results": [
                        {
                            "task_id": child.task_id,
                            "title": child.title,
                            "source_type": child.source_type,
                            "report_path": child.report_path,
                            "raw_results_path": child.raw_path,
                            "raw_result": child.raw_result,
                        }
                        for child in child_sources
                    ],
                    "output": output,
                    "facts": facts,
                },
            )

            artifacts = self._artifacts_for(task_id)
            artifact_refs = {
                "aggregation_report_path": self._task_rel(task_id, report_path),
                "aggregation_raw_results_path": self._task_rel(
                    task_id, raw_results_path
                ),
            }
            artifacts.update(artifact_refs)
            self._session_payload["updated_at"] = kst_isoformat()
            self._write_session()
            return artifact_refs

    def final_output_markdown(self, output: Any) -> str:
        with self._lock:
            report_body = ""
            if self._root_task_id is not None:
                report_path = (
                    self._task_dir(self._root_task_id) / "aggregation" / "report.md"
                )
                if report_path.exists():
                    report_body = strip_markdown_title(
                        report_path.read_text(encoding="utf-8")
                    )
        return render_final_markdown(output, report_body=report_body)

    def write_final_output(self, content: Any, root_task: Task | None = None) -> None:
        with self._lock:
            if self._root_task_id is None:
                raise RuntimeError("root task id is not set")

            requirements: list[dict[str, Any]] = []
            if self._analysis_payload is not None:
                requirements = list(self._analysis_payload.get("requirements", []))

            final_path = self.output_dir / "final.md"
            meta_path = self.output_dir / "final.md.meta.json"
            trace_path = self.output_dir / "final.trace.json"
            source_reports = self._collect_all_task_ids()
            final_markdown = self.final_output_markdown(content)

            self._write_text(final_path, final_markdown.strip() + "\n")
            self._write_json(
                meta_path,
                {
                    "session_id": self.session_id,
                    "root_task_id": self._root_task_id,
                    "model": self.model,
                    "updated_at": kst_isoformat(),
                },
            )
            self._write_json(
                trace_path,
                {
                    "root_task_id": self._root_task_id,
                    "source_reports": source_reports,
                    "source_materials": [
                        f"report:{task_id}" for task_id in source_reports
                    ],
                    "covered_requirement_ids": [item["id"] for item in requirements],
                    "missing_requirement_ids": [],
                    "aspect_coverage": {},
                },
            )

            self._artifacts_for(self._root_task_id)["final_output_path"] = (
                self._task_rel(
                    self._root_task_id,
                    final_path,
                )
            )
            if root_task is not None:
                self._write_text(
                    self.output_dir / "final.trace.md",
                    f"# Final Trace\n\n{render_tree_markdown(root_task)}\n",
                )
            self._session_payload["updated_at"] = kst_isoformat()
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
            "now_kst": kst_isoformat(),
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
            self._session_payload["updated_at"] = kst_isoformat(updated_at)
            if error:
                self._session_payload["error"] = error
            else:
                self._session_payload.pop("error", None)
            self._write_session()

    def build_browse_tree(self) -> None:
        with self._lock:
            if not build_browse_tree(
                session_dir=self.session_dir,
                tasks_dir=self.tasks_dir,
                root_task_id=self._root_task_id,
            ):
                return
            self._session_payload["updated_at"] = kst_isoformat()
            self._write_session()

    def _collect_all_task_ids(self) -> list[str]:
        return [
            task_id for task_id in self._plan_tasks if task_id != self._root_task_id
        ]

    def _artifacts_for(self, task_id: str) -> dict[str, str | None]:
        return self._task_artifacts.setdefault(
            task_id,
            {
                "execution_result_path": None,
                "execution_meta_path": None,
                "aggregation_report_path": None,
                "aggregation_raw_results_path": None,
                "final_output_path": None,
            },
        )

    def _merge_trace_fields(self, fields: Mapping[str, Any]) -> None:
        with self._lock:
            self._session_payload.update(fields)
            self._session_payload["updated_at"] = kst_isoformat(
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
