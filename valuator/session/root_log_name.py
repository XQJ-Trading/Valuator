from __future__ import annotations

from datetime import datetime
from pathlib import Path

from domain.query import QueryAnalysis

from valuator.session.browse_tree import to_slug
from valuator.utils.time_utils import KST


def _strip_fs_invalid(text: str) -> str:
    out: list[str] = []
    for ch in text.strip():
        if ch in '\\/:*?"<>|\x00':
            out.append("_")
        else:
            out.append(ch)
    s = "".join(out).strip().strip(".")
    return s or "unknown"


def primary_company_name_segment(analysis: QueryAnalysis) -> str:
    subjects = analysis.query_intent.subjects
    if not subjects:
        return ""
    name = (subjects[0].company.company_name or "").strip()
    if not name:
        return ""
    return _strip_fs_invalid(name)


def build_unique_root_session_id(
    created_at_kst: datetime,
    analysis: QueryAnalysis,
    raw_query: str,
    root: Path,
) -> str:
    ts = created_at_kst.astimezone(KST).strftime("%Y%m%d-%H%M")
    segment = primary_company_name_segment(analysis)
    if not segment:
        segment = to_slug(raw_query, max_length=48) or "query"
    if len(segment) > 120:
        segment = segment[:120].rstrip()
    base = f"{ts}-{segment}"
    if not (root / base).exists():
        return base
    n = 2
    while (root / f"{base}_{n}").exists():
        n += 1
    return f"{base}_{n}"
