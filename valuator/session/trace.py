from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from valuator.utils.json_ready import json_ready
from valuator.utils.llm_usage import LLMUsageWriter, TokenUsage
from valuator.utils.time_utils import compact_utc_timestamp, utc_isoformat

from .trace_markdown import timeline_summary, write_task_markdown


def task_rel_path(task_id: str) -> Path:
    parts = task_id.split(".")
    if not parts:
        return Path(task_id)
    path = Path(parts[0])
    for index in range(1, len(parts)):
        path /= ".".join(parts[: index + 1])
    return path


def ensure_task_dir(
    *,
    task_dir: Path,
    task_id: str,
    write_json,
    input_payload: Any = None,
) -> None:
    (task_dir / "llm_calls").mkdir(parents=True, exist_ok=True)
    steps_path = task_dir / "steps.jsonl"
    if not steps_path.exists():
        steps_path.write_text("", encoding="utf-8")
    task_json_path = task_dir / "task.json"
    if task_json_path.exists():
        return

    description = ""
    task_name = ""
    if isinstance(input_payload, Mapping):
        task_payload = input_payload.get("task")
        if isinstance(task_payload, Mapping):
            raw_description = task_payload.get("description")
            if isinstance(raw_description, str):
                description = raw_description
            raw_task_name = task_payload.get("task_name")
            if isinstance(raw_task_name, str):
                task_name = raw_task_name

    write_json(
        task_json_path,
        {
            "task_id": task_id,
            "parent_id": None,
            "description": description,
            "task_name": task_name,
            "state": "running",
            "children": [],
            "artifacts": {
                "execution_result_path": None,
                "execution_meta_path": None,
                "aggregation_report_path": None,
                "aggregation_raw_results_path": None,
                "final_output_path": None,
            },
        },
    )


class SessionTraceWriter:
    def __init__(
        self,
        *,
        session_id: str,
        query: str,
        model: str,
        created_at: datetime | str,
        base_dir: str | Path = "logs/gemini_low_level_request",
        session_dir_name: str | None = None,
        session_dir: str | Path | None = None,
        tasks_dir: str | Path | None = None,
        diagnostics_dir: str | Path | None = None,
        session_metadata_callback: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.session_id = session_id
        dir_name = session_dir_name or f"session_{session_id}"
        self.session_dir = (
            Path(session_dir).resolve()
            if session_dir is not None
            else (Path(base_dir) / dir_name).resolve()
        )
        self.tasks_dir = (
            Path(tasks_dir).resolve()
            if tasks_dir is not None
            else self.session_dir / "tasks"
        )
        self.diagnostics_dir = (
            Path(diagnostics_dir).resolve()
            if diagnostics_dir is not None
            else self.session_dir / "diagnostics"
        )
        self.output_dir = self.session_dir / "output"
        self.timeline_path = self.session_dir / "timeline.jsonl"
        self.events_path = self.diagnostics_dir / "events.jsonl"
        self.runtime_log_path = self.diagnostics_dir / "runtime.log"
        self.diagnostic_llm_calls_dir = self.diagnostics_dir / "llm_calls"
        self._lock = threading.RLock()
        self._session_metadata_callback = session_metadata_callback
        self._global_step_index = 0
        self._event_index = 0
        self._llm_call_index = 0
        self._task_llm_call_index: dict[str, int] = {}
        session_started_at = utc_isoformat(created_at)

        for path in (
            self.session_dir,
            self.tasks_dir,
            self.diagnostics_dir,
            self.diagnostic_llm_calls_dir,
            self.output_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.timeline_path.write_text("", encoding="utf-8")
        self.events_path.write_text("", encoding="utf-8")
        self.runtime_log_path.write_text("", encoding="utf-8")

        self._usage_writer = LLMUsageWriter(
            self.diagnostics_dir / "llm_usage.jsonl",
            session_started_at=session_started_at,
        )
        self._session_payload: dict[str, Any] = {
            "session_id": session_id,
            "query": query,
            "model": model,
            "created_at": session_started_at,
            "status": "running",
            "event_count": 0,
            "step_count": 0,
            "llm_call_count": 0,
            "paths": {
                "session": str(self.session_dir / "session.json"),
                "timeline": self._relative_path(self.timeline_path),
                "tasks": self._relative_path(self.tasks_dir),
                "output": self._relative_path(self.output_dir),
                "diagnostics": self._relative_path(self.diagnostics_dir),
                "events": self._relative_path(self.events_path),
                "llm_usage": self._relative_path(self.diagnostics_dir / "llm_usage.jsonl"),
                "runtime_log": self._relative_path(self.runtime_log_path),
            },
        }
        if self._session_metadata_callback is None:
            self._write_json(self.session_dir / "session.json", self._session_payload)

    def append_call(
        self,
        *,
        method: str,
        model: str,
        usage: TokenUsage,
        latency_seconds: float,
        started_at: str,
    ) -> None:
        self._usage_writer.append_call(
            method=method,
            model=model,
            usage=usage,
            latency_seconds=latency_seconds,
            started_at=started_at,
        )

    def append_total(self) -> None:
        self._usage_writer.append_total()

    def append_event(self, event: Mapping[str, Any]) -> None:
        with self._lock:
            self._event_index += 1
            payload = {
                "sequence": self._event_index,
                "timestamp": utc_isoformat(),
                **json_ready(dict(event)),
            }
            self._append_jsonl(self.events_path, payload)
            self._sync_session(event_count=self._event_index)

    def write_diagnostic_record(
        self,
        *,
        category: str,
        method: str,
        status: str,
        summary: str = "",
        started_at: str | None = None,
        duration_ms: float | None = None,
        input_payload: Any = None,
        result_payload: Any = None,
        error: str | None = None,
    ) -> None:
        self.append_event(
            {
                "type": "diagnostic_record",
                "category": category,
                "method": method,
                "status": status,
                "summary": summary,
                "started_at": utc_isoformat(started_at) if started_at else None,
                "duration_ms": round(duration_ms, 3) if duration_ms is not None else None,
                "input": json_ready(input_payload),
                "result": json_ready(result_payload),
                "error": error,
            }
        )

    def write_task_step(
        self,
        *,
        task_id: str,
        task_seq: int,
        phase: str,
        status: str,
        action: str | None = None,
        started_at: str | None = None,
        duration_ms: float | None = None,
        reason: str | None = None,
        summary: str = "",
        tool_name: str | None = None,
        tool_args: Mapping[str, Any] | None = None,
        tool_success: bool | None = None,
        children_created: list[str] | None = None,
        wait_for: list[str] | None = None,
        input_payload: Any = None,
        result_payload: Any = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            self._global_step_index += 1
            global_seq = self._global_step_index
            timestamp = utc_isoformat(started_at)
            task_dir = self._task_dir(task_id)
            steps_path = task_dir / "steps.jsonl"

            ensure_task_dir(
                task_dir=task_dir,
                task_id=task_id,
                write_json=self._write_json,
                input_payload=input_payload,
            )
            record = {
                "seq": task_seq,
                "global_seq": global_seq,
                "timestamp": timestamp,
                "phase": phase,
                "action": action,
                "status": status,
                "duration_ms": round(duration_ms, 3) if duration_ms is not None else None,
                "reason": reason,
                "summary": summary,
                "tool_name": tool_name,
                "tool_args": json_ready(tool_args),
                "tool_success": tool_success,
                "children_created": children_created,
                "wait_for": wait_for,
                "input": json_ready(input_payload),
                "result": json_ready(result_payload),
                "error": error,
            }
            self._append_jsonl(steps_path, record)
            self._append_jsonl(
                self.timeline_path,
                {
                    "global_seq": global_seq,
                    "task_id": task_id,
                    "task_seq": task_seq,
                    "timestamp": timestamp,
                    "phase": phase,
                    "action": action,
                    "summary": timeline_summary(record),
                },
            )
            write_task_markdown(task_dir=task_dir, task_id=task_id, read_json=self._read_json)
            self._sync_session(step_count=self._global_step_index)

    def log_llm_call(
        self,
        *,
        trace_method: str,
        model: str,
        prompt: str,
        system_prompt: str,
        response_mime_type: str | None,
        response_json_schema: dict[str, Any] | None,
        response_text: str | None,
        usage: Mapping[str, Any] | None,
        latency_ms: float,
        started_at: str,
        error: str | None = None,
    ) -> None:
        with self._lock:
            self._llm_call_index += 1
            task_id = self._task_id(trace_method)
            payload = {
                "session_id": self.session_id,
                "llm_call_index": self._llm_call_index,
                "started_at": started_at,
                "timestamp": compact_utc_timestamp(started_at),
                "trace_method": trace_method,
                "task_id": task_id,
                "model": model,
                "prompt": prompt,
                "system_prompt": system_prompt,
                "response_mime_type": response_mime_type,
                "response_json_schema": response_json_schema,
                "response_text": response_text,
                "usage": dict(usage or {}),
                "latency_ms": latency_ms,
                "error": error,
            }
            if task_id is None:
                path = self.diagnostic_llm_calls_dir / f"step_{self._llm_call_index:04d}.json"
            else:
                task_dir = self._task_dir(task_id)
                ensure_task_dir(task_dir=task_dir, task_id=task_id, write_json=self._write_json)
                task_index = self._task_llm_call_index.get(task_id, 0) + 1
                self._task_llm_call_index[task_id] = task_index
                path = task_dir / "llm_calls" / f"step_{task_index:02d}.json"
            self._write_json(path, payload)
            self._sync_session(llm_call_count=self._llm_call_index)

    def append_method_call(
        self,
        *,
        category: str,
        method: str,
        task_id: str | None = None,
        status: str,
        summary: str = "",
        started_at: str | None = None,
        finished_at: str | None = None,
        duration_ms: float | None = None,
        input_payload: Any = None,
        result_payload: Any = None,
        error: str | None = None,
    ) -> None:
        del finished_at
        if task_id is None:
            self.write_diagnostic_record(
                category=category,
                method=method,
                status=status,
                summary=summary,
                started_at=started_at,
                duration_ms=duration_ms,
                input_payload=input_payload,
                result_payload=result_payload,
                error=error,
            )
            return

        inferred_action = None
        if isinstance(result_payload, Mapping):
            action = result_payload.get("action")
            if isinstance(action, str):
                inferred_action = action
        inferred_task_seq = 0
        if isinstance(input_payload, Mapping):
            task_payload = input_payload.get("task")
            if isinstance(task_payload, Mapping):
                step_count = task_payload.get("step_count")
                if isinstance(step_count, int):
                    inferred_task_seq = step_count + 1
        if inferred_task_seq <= 0:
            inferred_task_seq = 1
        self.write_task_step(
            task_id=task_id,
            task_seq=inferred_task_seq,
            phase=category,
            status=status,
            action=inferred_action,
            started_at=started_at,
            duration_ms=duration_ms,
            summary=summary,
            input_payload=input_payload,
            result_payload=result_payload,
            error=error,
        )

    def update_session(self, **fields: Any) -> None:
        with self._lock:
            self._sync_session(**fields)

    def usage_summary(self) -> dict[str, Any]:
        w = self._usage_writer
        return {
            "total_tokens": w._usage_total.to_dict(),
            "total_latency_ms": round(w._latency_ms_total, 3),
            "total_cost_usd": round(w._cost_usd_total, 6),
        }

    def _task_dir(self, task_id: str) -> Path:
        return self.tasks_dir / task_rel_path(task_id)

    def _task_id(self, trace_method: str) -> str | None:
        for prefix in ("agent.step.", "agent.gate.critic."):
            if not trace_method.startswith(prefix):
                continue
            task_id = trace_method.removeprefix(prefix)
            if task_id.endswith(".error"):
                task_id = task_id[: -len(".error")]
            return task_id or None
        return None

    def _sync_session(self, **fields: Any) -> None:
        self._session_payload.update(fields)
        if self._session_metadata_callback is not None:
            self._session_metadata_callback(fields)
            return
        self._write_json(self.session_dir / "session.json", self._session_payload)

    def _relative_path(self, path: Path) -> str:
        return str(path.relative_to(self.session_dir))

    def task_dir(self, task_id: str) -> Path:
        return self._task_dir(task_id)

    @staticmethod
    def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file_obj:
            file_obj.write(json.dumps(payload, ensure_ascii=False) + "\n")
            file_obj.flush()

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file_obj:
            json.dump(payload, file_obj, ensure_ascii=False, indent=2)
            file_obj.write("\n")

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _safe_file_component(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
        return cleaned or "call"

