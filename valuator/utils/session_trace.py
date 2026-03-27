from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from valuator.core.llm_usage import LLMUsageWriter, TokenUsage


def utc_isoformat(value: datetime | str | None = None) -> str:
    if isinstance(value, str):
        if value.endswith("Z"):
            return value
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        return utc_isoformat(parsed)

    if value is None:
        value = datetime.now(timezone.utc)
    elif value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def compact_utc_timestamp(value: datetime | str | None = None) -> str:
    text = utc_isoformat(value)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed.strftime("%Y%m%d_%H%M%S_%f")


def task_rel_path(task_id: str) -> Path:
    parts = task_id.split(".")
    if not parts:
        return Path(task_id)
    path = Path(parts[0])
    for index in range(1, len(parts)):
        path /= ".".join(parts[: index + 1])
    return path


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
        usage: TokenUsage | Mapping[str, int] | None,
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
                **self._json_ready(dict(event)),
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
                "input": self._json_ready(input_payload),
                "result": self._json_ready(result_payload),
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
        wait_for_facts: list[str] | None = None,
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

            self._ensure_task_dir(task_dir, task_id, input_payload=input_payload)
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
                "tool_args": self._json_ready(tool_args),
                "tool_success": tool_success,
                "children_created": children_created,
                "wait_for": wait_for,
                "wait_for_facts": wait_for_facts,
                "input": self._json_ready(input_payload),
                "result": self._json_ready(result_payload),
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
                    "summary": self._timeline_summary(record),
                },
            )
            self._write_task_markdown(task_dir, task_id)
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
                self._ensure_task_dir(task_dir, task_id)
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

    def task_dir(self, task_id: str) -> Path:
        return self._task_dir(task_id)

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

    def _write_task_markdown(self, task_dir: Path, task_id: str) -> None:
        steps_path = task_dir / "steps.jsonl"
        rows = [
            json.loads(line)
            for line in steps_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        task_payload = self._read_json(task_dir / "task.json") or {}
        description = str(task_payload.get("description") or "").strip()
        state = str(task_payload.get("state") or "running").strip()
        title = f"{task_id}: {description}" if description else task_id
        step_ids = sorted(
            {
                int(row["seq"])
                for row in rows
                if isinstance(row.get("seq"), int) and int(row["seq"]) > 0
            }
        )
        lines = [
            f"# {title}",
            f"State: {state} | Steps: {len(step_ids)}",
            "",
        ]
        for row in rows:
            lines.extend(self._task_markdown_block(row))
            lines.append("")
        (task_dir / "task.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _task_markdown_block(self, row: Mapping[str, Any]) -> list[str]:
        seq = row.get("seq", "?")
        phase = str(row.get("phase") or "")
        action = str(row.get("action") or "").strip()
        lines = [
            f"## Step {seq} [{self._display_time(row.get('timestamp'))}] {phase}",
        ]
        if phase == "decision":
            if action == "execute" and row.get("tool_name"):
                lines.append(f"**action**: execute({row['tool_name']})")
                if row.get("tool_args") is not None:
                    lines.append(
                        f"  args: {json.dumps(row['tool_args'], ensure_ascii=False, default=str)}"
                    )
            elif action == "decompose":
                lines.append("**action**: decompose")
                child_lines = self._child_markdown_lines(row)
                if child_lines:
                    lines.extend(child_lines)
            else:
                lines.append(f"**action**: {action or 'unknown'}")
            if row.get("reason"):
                lines.append(f"  reason: {row['reason']}")
        elif phase == "tool_result":
            result_label = "success" if bool(row.get("tool_success")) else "failed"
            duration_ms = row.get("duration_ms")
            duration_text = ""
            if isinstance(duration_ms, (int, float)):
                duration_text = f" ({int(round(duration_ms))}ms)"
            lines.append(f"**result**: {result_label}{duration_text}")
            preview = self._result_preview(row)
            if preview:
                lines.append(f"  {preview}")
        elif phase == "task_result":
            lines.append(f"**task**: {row.get('status', 'unknown')}")
            preview = self._result_preview(row)
            if preview:
                lines.append(f"  {preview}")
        else:
            if action:
                lines.append(f"**action**: {action}")
            if row.get("summary"):
                lines.append(f"  {row['summary']}")
        if row.get("error"):
            lines.append(f"  error: {row['error']}")
        return lines

    def _child_markdown_lines(self, row: Mapping[str, Any]) -> list[str]:
        result = row.get("result")
        if not isinstance(result, Mapping):
            children = row.get("children_created")
            if isinstance(children, list):
                return [f"  - {child}" for child in children]
            return []
        payload_children = result.get("children")
        if not isinstance(payload_children, list):
            children = row.get("children_created")
            if isinstance(children, list):
                return [f"  - {child}" for child in children]
            return []
        lines: list[str] = []
        for item in payload_children:
            if not isinstance(item, Mapping):
                continue
            child_id = str(item.get("id") or "").strip()
            description = str(item.get("description") or "").strip()
            if child_id and description:
                lines.append(f'  - {child_id}: "{description}"')
            elif child_id:
                lines.append(f"  - {child_id}")
        return lines

    def _result_preview(self, row: Mapping[str, Any]) -> str:
        for key in ("summary",):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        result = row.get("result")
        if isinstance(result, Mapping):
            for key in ("output", "result", "findings", "content", "error"):
                value = result.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, Mapping):
                    for nested_key in ("findings", "summary", "content", "result"):
                        nested_value = value.get(nested_key)
                        if isinstance(nested_value, str) and nested_value.strip():
                            return nested_value.strip()
        if isinstance(result, str) and result.strip():
            return result.strip()
        return ""

    def _timeline_summary(self, row: Mapping[str, Any]) -> str:
        summary = str(row.get("summary") or "").strip()
        if summary:
            return summary
        phase = str(row.get("phase") or "")
        action = str(row.get("action") or "")
        if phase == "decision":
            if action == "execute" and row.get("tool_name"):
                return f"execute({row['tool_name']})"
            if action == "decompose":
                children = row.get("children_created") or []
                return f"decompose[{len(children)}]"
            return action or "decision"
        if phase == "tool_result":
            tool_name = str(row.get("tool_name") or "tool")
            status = "success" if bool(row.get("tool_success")) else "failed"
            return f"{tool_name} {status}"
        if phase == "task_result":
            return f"task {row.get('status', 'unknown')}"
        return phase or "step"

    def _ensure_task_dir(
        self,
        task_dir: Path,
        task_id: str,
        *,
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
        if isinstance(input_payload, Mapping):
            task_payload = input_payload.get("task")
            if isinstance(task_payload, Mapping):
                raw_description = task_payload.get("description")
                if isinstance(raw_description, str):
                    description = raw_description
        self._write_json(
            task_json_path,
            {
                "task_id": task_id,
                "parent_id": None,
                "description": description,
                "state": "running",
                "children": [],
                "artifacts": {
                    "execution_result_path": None,
                    "execution_meta_path": None,
                    "aggregation_report_path": None,
                    "final_output_path": None,
                },
            },
        )

    def _relative_path(self, path: Path) -> str:
        return str(path.relative_to(self.session_dir))

    @classmethod
    def _json_ready(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Enum):
            return cls._json_ready(value.value)
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, Mapping):
            return {str(key): cls._json_ready(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._json_ready(item) for item in value]
        if is_dataclass(value):
            return cls._json_ready(asdict(value))
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return cls._json_ready(model_dump())
        if hasattr(value, "__dict__"):
            return {
                str(key): cls._json_ready(item)
                for key, item in vars(value).items()
                if not key.startswith("_")
            }
        return str(value)

    @staticmethod
    def _display_time(value: Any) -> str:
        timestamp = utc_isoformat(value)
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return timestamp
        return parsed.strftime("%H:%M:%SZ")

    @staticmethod
    def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file_obj:
            file_obj.write(json.dumps(payload, ensure_ascii=False) + "\n")

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
