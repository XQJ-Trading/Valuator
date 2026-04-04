from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .trace import task_rel_path


def _remove_browse_dir(path: Path) -> None:
    """Remove browse cache; tolerate races when another build deletes the same tree."""

    def _onerror(_func, _path, exc_info) -> None:
        err = exc_info[1]
        if isinstance(err, FileNotFoundError):
            return
        raise err

    try:
        shutil.rmtree(path, onerror=_onerror)
    except FileNotFoundError:
        pass


def build_browse_tree(
    *,
    session_dir: Path,
    tasks_dir: Path,
    root_task_id: str | None,
) -> bool:
    task_payloads: dict[str, dict[str, Any]] = {}
    for task_json_path in sorted(tasks_dir.rglob("task.json")):
        payload = _read_json_if_exists(task_json_path)
        if payload is None:
            continue
        task_id = str(payload.get("task_id") or "").strip()
        if task_id:
            task_payloads[task_id] = payload

    if not task_payloads:
        return False

    resolved_root_task_id = _browse_root_task_id(
        task_payloads=task_payloads,
        root_task_id=root_task_id,
    )
    if resolved_root_task_id is None:
        return False

    browse_dir = session_dir / "browse"
    if browse_dir.exists():
        _remove_browse_dir(browse_dir)
    browse_dir.mkdir(parents=True, exist_ok=True)
    _write_browse_node(
        task_id=resolved_root_task_id,
        task_payloads=task_payloads,
        parent_dir=browse_dir,
        sibling_names=set(),
        session_dir=session_dir,
        tasks_dir=tasks_dir,
    )
    return True


def _browse_root_task_id(
    *,
    task_payloads: dict[str, dict[str, Any]],
    root_task_id: str | None,
) -> str | None:
    if root_task_id and root_task_id in task_payloads:
        return root_task_id
    for task_id, payload in task_payloads.items():
        if payload.get("parent_id") is None:
            return task_id
    return None


def _write_browse_node(
    *,
    task_id: str,
    task_payloads: dict[str, dict[str, Any]],
    parent_dir: Path,
    sibling_names: set[str],
    session_dir: Path,
    tasks_dir: Path,
) -> None:
    payload = task_payloads[task_id]
    node_dir = parent_dir / _browse_dir_name(payload, sibling_names)
    node_dir.mkdir(parents=True, exist_ok=True)
    copied_files = _browse_markdown_files(
        task_id=task_id,
        payload=payload,
        node_dir=node_dir,
        session_dir=session_dir,
        tasks_dir=tasks_dir,
    )

    description = str(payload.get("description") or "").strip()
    lines = [
        f"# {node_dir.name.replace('_', ' ')}",
        "",
        f"- task_id: {str(payload.get('task_id') or '').strip()}",
        f"- state: {str(payload.get('state') or '').strip()}",
        f"- task_type: {str(payload.get('task_type') or '').strip()}",
        "",
    ]
    if description:
        lines.extend(["## Description", "", description, ""])
    tool = payload.get("tool")
    if isinstance(tool, Mapping) and tool.get("name"):
        lines.extend(["## Tool", "", f"- name: {tool['name']}"])
        args = tool.get("args")
        if isinstance(args, Mapping):
            for key, value in args.items():
                lines.append(f"- {key}: {value}")
        lines.append("")
    if copied_files:
        lines.extend(["## Files", ""])
        lines.extend(f"- {filename}" for filename in copied_files)
        lines.append("")
    (node_dir / "README.md").write_text(
        "\n".join(lines).rstrip() + "\n", encoding="utf-8"
    )

    child_names: set[str] = set()
    children = payload.get("children")
    if not isinstance(children, list):
        return
    for child_id in children:
        if not isinstance(child_id, str) or child_id not in task_payloads:
            continue
        _write_browse_node(
            task_id=child_id,
            task_payloads=task_payloads,
            parent_dir=node_dir,
            sibling_names=child_names,
            session_dir=session_dir,
            tasks_dir=tasks_dir,
        )


def _browse_markdown_files(
    *,
    task_id: str,
    payload: dict[str, Any],
    node_dir: Path,
    session_dir: Path,
    tasks_dir: Path,
) -> list[str]:
    copied_files: list[str] = []
    task_dir = tasks_dir / task_rel_path(task_id)
    sources: dict[str, Path] = {}

    report_source = _browse_report_source(task_dir)
    if report_source is not None:
        sources["report.md"] = report_source
    else:
        report_markdown = _browse_report_stub(payload)
        if report_markdown:
            (node_dir / "report.md").write_text(report_markdown, encoding="utf-8")
            copied_files.append("report.md")

    artifacts = payload.get("artifacts")
    if isinstance(artifacts, Mapping):
        relative_path = artifacts.get("final_output_path")
        if isinstance(relative_path, str) and relative_path.strip():
            final_md = _artifact_markdown_under_session(
                session_dir=session_dir,
                task_dir=task_dir,
                relative_path=relative_path.strip(),
            )
            if final_md is not None:
                sources["final.md"] = final_md

    for filename, source in sources.items():
        shutil.copy2(source, node_dir / filename)
        copied_files.append(filename)
    return copied_files


def _artifact_markdown_under_session(
    *,
    session_dir: Path,
    task_dir: Path,
    relative_path: str,
) -> Path | None:
    """Resolve artifact path only if it stays under the session directory."""
    root = session_dir.resolve()
    source = (task_dir / relative_path).resolve()
    try:
        source.relative_to(root)
    except ValueError:
        return None
    if source.is_file() and source.suffix.lower() == ".md":
        return source
    return None


def _browse_report_source(task_dir: Path) -> Path | None:
    aggregation_report = task_dir / "aggregation" / "report.md"
    if aggregation_report.exists() and aggregation_report.is_file():
        return aggregation_report

    execution_result = task_dir / "execution" / "result.md"
    if execution_result.exists() and execution_result.is_file():
        return execution_result
    return None


def _browse_report_stub(payload: dict[str, Any]) -> str:
    title = str(payload.get("task_name") or payload.get("task_id") or "task").replace(
        "_", " "
    )
    state = str(payload.get("state") or "").strip()
    error = str(payload.get("error") or "").strip()

    lines = [f"# {title}", ""]
    if state == "failed":
        lines.append("Task failed before producing a report artifact.")
        lines.append("")
        if error:
            lines.append(error)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    lines.extend(
        [
            "Task completed without a report artifact.",
            "",
            "See the `tasks/` tree in this session for step traces and metadata.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _browse_dir_name(payload: dict[str, Any], sibling_names: set[str]) -> str:
    raw_name = str(payload.get("task_name") or "").strip()
    if not raw_name:
        raw_name = _browse_fallback_name(payload)

    base_name = to_slug(raw_name) or "task"
    candidate = base_name
    index = 2
    while candidate in sibling_names:
        candidate = f"{base_name}_{index}"
        index += 1
    sibling_names.add(candidate)
    return candidate


def _browse_fallback_name(payload: dict[str, Any]) -> str:
    description = str(payload.get("description") or "").strip()
    if payload.get("parent_id") is None:
        description = _root_browse_source(description)
    return description or str(payload.get("task_id") or "task")


def _root_browse_source(description: str) -> str:
    text = description.strip()
    for prefix in ("Valuation:", "Analysis:"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    if "[QUERY]\n" in text:
        text = text.split("[QUERY]\n", 1)[1].strip()
    if "\n\n[REQUEST_CONTROL]" in text:
        text = text.split("\n\n[REQUEST_CONTROL]", 1)[0].strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(lines)


def task_description_from_effective_query(effective_query: str) -> str:
    """Single-line task label: strips THINKING_LEVEL / [QUERY] transport (same as browse slug)."""
    body = _root_browse_source(f"Analysis: {effective_query.strip()}")
    return f"Analysis: {body}" if body else "Analysis"


def to_slug(value: str, max_length: int = 30) -> str:
    chars: list[str] = []
    last_was_separator = False
    for char in value.strip():
        if char.isalnum():
            chars.append(char)
            last_was_separator = False
            continue
        if char in {"_", "-"} or char.isspace():
            if chars and not last_was_separator:
                chars.append("_")
                last_was_separator = True
    cleaned = "".join(chars).strip("_")
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[:max_length].rstrip("_")


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
