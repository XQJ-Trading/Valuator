from __future__ import annotations

from datetime import datetime
from pathlib import Path

from domain.query import QueryAnalysis, is_concrete_subject_kind

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


def _is_six_digit_numeric_label(value: str) -> bool:
    """Unit entity values that are only a 6-digit code are tickers, not display names."""
    s = value.strip()
    return len(s) == 6 and s.isdigit()


def _segment_from_unit_entities(analysis: QueryAnalysis) -> str:
    """Prefer labels bound to plan units (same graph as QueryUnit.entity_ids)."""
    for unit in analysis.units:
        for eid in unit.entity_ids:
            kind = (analysis.entity_kinds.get(eid) or "").strip()
            if kind and not is_concrete_subject_kind(kind):
                continue
            raw = (analysis.entities.get(eid) or "").strip()
            if not raw or _is_six_digit_numeric_label(raw):
                continue
            cleaned = _strip_fs_invalid(raw)
            if cleaned == "unknown":
                continue
            return cleaned
    return ""


def primary_company_name_segment(analysis: QueryAnalysis) -> str:
    from_units = _segment_from_unit_entities(analysis)
    if from_units:
        return from_units
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
