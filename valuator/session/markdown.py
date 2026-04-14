from __future__ import annotations

from collections.abc import Mapping
from typing import Any

PRIMARY_MARKDOWN_KEYS = ("markdown", "report", "content")
REPORT_MARKDOWN_KEYS = (
    "markdown",
    "report",
    "content",
    "findings",
    "result",
    "summary",
    "domain_summary",
)


def extract_primary_markdown_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        for key in PRIMARY_MARKDOWN_KEYS:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return ""


def strip_markdown_title(markdown: str) -> str:
    text = markdown.strip()
    if not text.startswith("#"):
        return text
    lines = text.splitlines()
    if not lines or not lines[0].startswith("#"):
        return text
    index = 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    return "\n".join(lines[index:]).strip()


def markdown_document(title: str, body: str) -> str:
    content = strip_markdown_title(body).strip()
    if not content:
        return ""
    return f"# {title}\n\n{content}"


def render_report_markdown(value: Any) -> str:
    if isinstance(value, Mapping) and value.get("status") == "facts_only":
        facts = value.get("facts")
        value = facts if isinstance(facts, Mapping) else facts

    if isinstance(value, Mapping):
        for key in REPORT_MARKDOWN_KEYS:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return strip_markdown_title(candidate)

    text = extract_primary_markdown_text(value)
    if text:
        return strip_markdown_title(text)

    def render(current: Any, heading_level: int = 2) -> str:
        if current is None:
            return ""
        if isinstance(current, str):
            return current.strip()
        if isinstance(current, Mapping):
            lines: list[str] = []
            for key, item in current.items():
                if key in {"status", "source_task_id", "query", "sources"}:
                    continue
                rendered = render(item, min(heading_level + 1, 6)).strip()
                if not rendered:
                    continue
                label = str(key).replace("_", " ").strip()
                if "\n" not in rendered and not rendered.startswith("- "):
                    lines.append(f"- **{label}**: {rendered}")
                else:
                    lines.extend([f"{'#' * heading_level} {label}", "", rendered, ""])
            return "\n".join(lines).strip()
        if isinstance(current, list):
            if all(not isinstance(item, (Mapping, list)) for item in current):
                return "\n".join(
                    f"- {text}"
                    for text in (str(item).strip() for item in current)
                    if text
                ).strip()
            lines = []
            for index, item in enumerate(current, start=1):
                rendered = render(item, min(heading_level + 1, 6)).strip()
                if rendered:
                    lines.extend(
                        [f"{'#' * heading_level} Item {index}", "", rendered, ""]
                    )
            return "\n".join(lines).strip()
        return str(current).strip()

    return render(value).strip()


def render_final_markdown(
    value: Any,
    *,
    title: str = "Final",
    report_body: str = "",
) -> str:
    primary = extract_primary_markdown_text(value)
    if primary:
        return primary
    if report_body.strip():
        return markdown_document(title, report_body)
    rendered = render_report_markdown(value)
    if rendered:
        return markdown_document(title, rendered)
    return ""
