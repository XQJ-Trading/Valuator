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


def as_of_date_from_utc(as_of_utc: str) -> date:
    if len(as_of_utc) >= 10 and as_of_utc[4] == "-" and as_of_utc[7] == "-":
        return date.fromisoformat(as_of_utc[:10])
    raise ValueError(f"invalid as_of_utc: {as_of_utc!r}")


def normalize_target_date_token(raw: str, *, as_of_utc: str | None) -> str:
    s = raw.strip()
    if not s:
        return ""
    if _ISO_DATE.fullmatch(s):
        return s
    if as_of_utc is None:
        raise ValueError("as_of_utc context required for period tokens")
    as_of = as_of_date_from_utc(as_of_utc)
    if s.upper() == "CURRENT_DATE":
        return as_of.isoformat()
    m = _P_MINUS_YEARS.fullmatch(s)
    if m:
        years = int(m.group(1))
        return _add_years(as_of, -years).isoformat()
    raise ValueError(f"invalid target date token: {raw!r}")
