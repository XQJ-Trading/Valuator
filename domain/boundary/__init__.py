"""Boundary adapters (external I/O → domain types)."""

from __future__ import annotations

from .types import ListingSeed

from .krx_ticker_resolve import (
    clear_cache as clear_krx_cache,
    krx_on_miss,
    resolve_corp_code,
    resolve_seeds as resolve_krx,
)
from .sec_ticker_resolve import (
    clear_cache as clear_sec_cache,
    resolve_seeds as resolve_sec,
    sec_on_miss,
)

__all__ = [
    "clear_krx_cache",
    "clear_sec_cache",
    "combined_on_miss",
    "krx_on_miss",
    "resolve_corp_code",
    "resolve_krx",
    "resolve_sec",
    "sec_on_miss",
]


def combined_on_miss(surface_form: str) -> tuple[ListingSeed, ...]:
    """Try KRX first, fall back to SEC."""
    result = krx_on_miss(surface_form)
    if result:
        return result
    return sec_on_miss(surface_form)
