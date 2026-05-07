"""Boundary adapters (external I/O → domain types)."""

from __future__ import annotations

from domain.company import (
    ListingSeed,
    Subject,
    company_with_reference_from_daily_bar,
    representative_listing,
)
from domain.price_bar import DailyPriceBar

from .krx_stock_price_collector import (
    fetch_krx_daily_price_bar,
    fetch_krx_latest_quote,
    fetch_krx_reference_for_company,
    fetch_krx_valuation_snapshot,
    fetch_krx_year_end_valuation,
    normalize_krx_stock_code,
)
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
    "DailyPriceBar",
    "clear_krx_records_cache",
    "clear_sec_records_cache",
    "combined_on_miss",
    "fetch_krx_daily_price_bar",
    "fetch_krx_latest_quote",
    "fetch_krx_reference_for_company",
    "fetch_krx_valuation_snapshot",
    "fetch_krx_year_end_valuation",
    "krx_on_miss",
    "normalize_krx_stock_code",
    "resolve_krx_listing_seeds",
    "resolve_sec_listing_seeds",
    "enrich_krx_subjects",
    "sec_on_miss",
]


def combined_on_miss(surface_form: str) -> tuple[ListingSeed, ...]:
    """Try KRX first, fall back to SEC."""
    result = krx_on_miss(surface_form)
    if result:
        return result
    return sec_on_miss(surface_form)


def enrich_krx_subjects(
    subjects: tuple[Subject, ...],
) -> tuple[Subject, ...]:
    """KRX 상장 subject에 기준 주가(종가)를 붙인다. 실패 시 원본 유지."""
    from dataclasses import replace

    enriched: list[Subject] = []
    for subject in subjects:
        listing = subject.listing or representative_listing(subject)
        if (
            listing is not None
            and listing.market == "KRX"
            and subject.company.reference_stock_price is None
        ):
            try:
                bar = fetch_krx_daily_price_bar(listing.listing_id)
                new_company = company_with_reference_from_daily_bar(
                    subject.company, bar
                )
                enriched.append(replace(subject, company=new_company))
                continue
            except Exception:
                pass
        enriched.append(subject)
    return tuple(enriched)
