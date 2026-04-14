from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .markdown import render_report_markdown, strip_markdown_title


@dataclass(frozen=True)
class ReportSource:
    task_id: str
    title: str
    source_type: str
    markdown: str
    report_input: Any
    raw_result: Any
    report_path: str | None
    raw_path: str | None


def artifact_text(value: Any, error: str | None) -> str:
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


def load_report_source(
    *,
    task_id: str,
    task_dir: Path,
    task_name: str,
    rel: Callable[[Path], str],
) -> ReportSource:
    for source_type, markdown_path, raw_path in (
        (
            "aggregation",
            task_dir / "aggregation" / "report.md",
            task_dir / "aggregation" / "raw_results.json",
        ),
        (
            "execution",
            task_dir / "execution" / "result.md",
            task_dir / "execution" / "result.json",
        ),
    ):
        raw_payload = read_json_if_exists(raw_path)
        report_input = None
        raw_result = None
        if raw_payload is not None:
            if source_type == "aggregation":
                report_input = raw_payload.get("output")
                if report_input is None:
                    report_input = raw_payload.get("facts")
                raw_result = raw_payload.get("facts")
                if raw_result is None:
                    raw_result = raw_payload.get("output")
            else:
                report_input = raw_payload.get("raw_result")
                raw_result = raw_payload.get("raw_result")
        if markdown_path.exists():
            return ReportSource(
                task_id=task_id,
                title=task_name,
                source_type=source_type,
                markdown=strip_markdown_title(markdown_path.read_text(encoding="utf-8")),
                report_input=report_input,
                raw_result=raw_result,
                report_path=rel(markdown_path),
                raw_path=rel(raw_path) if raw_payload is not None else None,
            )
        if raw_payload is not None:
            return ReportSource(
                task_id=task_id,
                title=task_name,
                source_type=source_type,
                markdown="",
                report_input=report_input,
                raw_result=raw_result,
                report_path=None,
                raw_path=rel(raw_path),
            )

    return ReportSource(
        task_id=task_id,
        title=task_name,
        source_type="",
        markdown="",
        report_input=None,
        raw_result=None,
        report_path=None,
        raw_path=None,
    )


def render_aggregation_report(
    *,
    title: str,
    output: Any,
    child_sources: list[ReportSource],
    current_source: ReportSource,
) -> tuple[str, dict[str, Any]]:
    lines = [f"# {title}", ""]
    summary = render_report_markdown(output)
    if not summary:
        summary = current_source.markdown or render_report_markdown(
            current_source.report_input
        )
    if summary:
        lines.extend([summary, ""])

    evidence_started = False
    for child in child_sources:
        body = child.markdown or render_report_markdown(child.report_input)
        if not body:
            continue
        if summary and not evidence_started:
            lines.extend(["## Supporting Evidence", ""])
            evidence_started = True
        lines.extend([f"### {child.title}", "", body, ""])

    if not summary and not evidence_started:
        lines = [f"# {title}", "", "(no report content)"]

    if isinstance(output, Mapping):
        facts = (
            dict(output["facts"])
            if output.get("status") == "facts_only"
            and isinstance(output.get("facts"), Mapping)
            else dict(output)
        )
    elif isinstance(output, str) and output.strip():
        facts = {"summary": output.strip()}
    else:
        facts = (
            current_source.raw_result if current_source.raw_result is not None else {}
        )

    return "\n".join(lines).strip() + "\n", facts


def read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
