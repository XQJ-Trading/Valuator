"""Boundary adapters (external I/O → domain types)."""

from __future__ import annotations

from domain.company import ListingSeed

from .krx_ticker_resolve import (
    clear_krx_records_cache,
    krx_on_miss,
    resolve_krx_listing_seeds,
)
from .sec_ticker_resolve import (
    clear_sec_records_cache,
    resolve_sec_listing_seeds,
    sec_on_miss,
)

__all__ = [
    "clear_krx_records_cache",
    "clear_sec_records_cache",
    "combined_on_miss",
    "krx_on_miss",
    "resolve_krx_listing_seeds",
    "resolve_sec_listing_seeds",
    "sec_on_miss",
]


def combined_on_miss(surface_form: str) -> tuple[ListingSeed, ...]:
    """Try KRX first, fall back to SEC."""
    result = krx_on_miss(surface_form)
    if result:
        return result
    return sec_on_miss(surface_form)
