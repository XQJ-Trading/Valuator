from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from valuator.utils.time_utils import KST, kst_isoformat


def write_task_markdown(
    *,
    steps_path: Path,
    task_dir: Path,
    task_id: str,
    read_json,
) -> None:
    rows = [
        json.loads(line)
        for line in steps_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    task_payload = read_json(task_dir / "task.json") or {}
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
        lines.extend(task_markdown_block(row))
        lines.append("")
    (task_dir / "task.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def task_markdown_block(row: Mapping[str, Any]) -> list[str]:
    seq = row.get("seq", "?")
    phase = str(row.get("phase") or "")
    action = str(row.get("action") or "").strip()
    lines = [f"## Step {seq} [{display_time(row.get('timestamp'))}] {phase}"]
    if phase == "decision":
        if action == "execute" and row.get("tool_name"):
            lines.append(f"**action**: execute({row['tool_name']})")
            if row.get("tool_args") is not None:
                lines.append(
                    f"  args: {json.dumps(row['tool_args'], ensure_ascii=False, default=str)}"
                )
        elif action == "decompose":
            lines.append("**action**: decompose")
            child_lines = child_markdown_lines(row)
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
        preview = result_preview(row)
        if preview:
            lines.append(f"  {preview}")
    elif phase == "task_result":
        lines.append(f"**task**: {row.get('status', 'unknown')}")
        preview = result_preview(row)
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


def child_markdown_lines(row: Mapping[str, Any]) -> list[str]:
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


def result_preview(row: Mapping[str, Any]) -> str:
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


def timeline_summary(row: Mapping[str, Any]) -> str:
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


def display_time(value: Any) -> str:
    timestamp = kst_isoformat(value)
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return timestamp
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    else:
        parsed = parsed.astimezone(KST)
    return parsed.strftime("%H:%M:%S KST")

