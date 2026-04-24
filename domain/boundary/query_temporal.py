"""Normalize LLM query-unit temporal tokens at the domain boundary."""

from __future__ import annotations

import re
from datetime import date

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_P_MINUS_YEARS = re.compile(r"^P-(\d+)Y$", re.I)


def _add_years(d: date, delta: int) -> date:
    try:
        return date(d.year + delta, d.month, d.day)
    except ValueError:
        return date(d.year + delta, d.month, 28)


def as_of_calendar_date(as_of_iso: str) -> date:
    if len(as_of_iso) >= 10 and as_of_iso[4] == "-" and as_of_iso[7] == "-":
        return date.fromisoformat(as_of_iso[:10])
    raise ValueError(f"invalid as_of_iso: {as_of_iso!r}")


def normalize_target_date_token(raw: str, *, as_of_kst: str | None) -> str:
    s = raw.strip()
    if not s:
        return ""
    if _ISO_DATE.fullmatch(s):
        return s
    if as_of_kst is None:
        raise ValueError("as_of_kst context required for period tokens")
    as_of = as_of_calendar_date(as_of_kst)
    if s.upper() == "CURRENT_DATE":
        return as_of.isoformat()
    m = _P_MINUS_YEARS.fullmatch(s)
    if m:
        years = int(m.group(1))
        return _add_years(as_of, -years).isoformat()
    raise ValueError(f"invalid target date token: {raw!r}")
