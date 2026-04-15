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


def primary_ticker_corp_segment(analysis: QueryAnalysis) -> str:
    subjects = analysis.query_intent.subjects
    if not subjects:
        return ""
    subj = subjects[0]
    corp = (subj.company.company_name or "").strip()
    ticker = ""
    if subj.listing is not None:
        ticker = (subj.listing.security_code or "").strip()
        if not ticker:
            ticker = (subj.listing.yahoo_symbol or "").strip()
    if not ticker:
        ticker = "NA"
    raw = f"{ticker}({corp})" if corp else ticker
    return _strip_fs_invalid(raw)


def build_unique_root_session_id(
    created_at_kst: datetime,
    analysis: QueryAnalysis,
    raw_query: str,
    root: Path,
) -> str:
    ts = created_at_kst.astimezone(KST).strftime("%Y%m%d-%H%M")
    segment = primary_ticker_corp_segment(analysis)
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
