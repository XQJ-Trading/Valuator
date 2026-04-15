"""Inline citation markers [1], [2], … → markdown links when URLs are available."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

# Not already `[n](url)`; 1-based index matches sources[0], sources[1], …
_CITATION = re.compile(r"\[(\d+)\](?!\()")


def _normalize_sources(metadata: Mapping[str, Any] | None) -> tuple[str, ...]:
    if metadata is None:
        return ()
    raw = metadata.get("sources")
    if not isinstance(raw, list):
        return ()
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        else:
            out.append("")
    return tuple(out)


def link_inline_citations(text: str, sources: Sequence[str]) -> str:
    """Turn [n] into [n](url) when sources[n-1] is an http(s) URL."""

    if not text.strip() or not sources:
        return text

    def repl(match: re.Match[str]) -> str:
        n = int(match.group(1))
        if n < 1 or n > len(sources):
            return match.group(0)
        url = sources[n - 1].strip()
        if not url.startswith(("http://", "https://")):
            return match.group(0)
        return f"[{n}]({url})"

    return _CITATION.sub(repl, text)


def apply_citation_links_to_tool_payload(
    result_obj: Any,
    metadata: Mapping[str, Any] | None,
) -> Any:
    """Apply link_inline_citations to known string fields on successful tool payloads."""

    sources = _normalize_sources(metadata)
    if not sources:
        return result_obj

    if isinstance(result_obj, str):
        return link_inline_citations(result_obj, sources)

    if not isinstance(result_obj, dict):
        return result_obj

    keys = (
        "markdown",
        "report",
        "content",
        "findings",
        "result",
        "domain_summary",
        "summary",
    )
    out = dict(result_obj)
    for key in keys:
        val = out.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = link_inline_citations(val, sources)
    return out
