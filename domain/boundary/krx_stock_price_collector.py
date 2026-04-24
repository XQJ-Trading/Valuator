"""Boundary: KRX 일봉 → DailyPriceBar (listing_id·온톨로지 정합)."""

from __future__ import annotations

import re
from datetime import date, timedelta

from domain.company import Company, company_with_reference_from_daily_bar
from domain.price_bar import DailyPriceBar

_STOCK_CODE_RE = re.compile(r"^\d{6}$")
_LOOKBACK_DAYS = 40


def normalize_krx_stock_code(raw: str) -> str:
    s = raw.strip()
    if s.upper().startswith("KRX:"):
        s = s[4:].strip()
    if not s.isdigit():
        raise ValueError(f"invalid KRX stock code: {raw!r}")
    if len(s) > 6:
        raise ValueError(f"invalid KRX stock code: {raw!r}")
    normalized = s.zfill(6)
    if not _STOCK_CODE_RE.match(normalized):
        raise ValueError(f"invalid KRX stock code: {raw!r}")
    return normalized


def _canonical_krx_listing_id(stock_code: str) -> str:
    return f"KRX:{normalize_krx_stock_code(stock_code)}"


def fetch_krx_daily_price_bar(listing_id: str) -> DailyPriceBar:
    """`listing_id`는 `KRX:######` 형식. KRX 일봉(직전 영업일 종가 등)."""
    from pykrx import stock

    code = normalize_krx_stock_code(listing_id)
    canonical_id = _canonical_krx_listing_id(code)
    end = date.today()
    start = end - timedelta(days=_LOOKBACK_DAYS)
    df = stock.get_market_ohlcv(
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
        code,
    )
    if df.empty:
        raise ValueError(f"no KRX OHLCV for listing_id={canonical_id!r}")

    last = df.iloc[-1]
    return DailyPriceBar(
        listing_id=canonical_id,
        as_of=df.index[-1].date(),
        open_krw=int(last["시가"]),
        high_krw=int(last["고가"]),
        low_krw=int(last["저가"]),
        close_krw=int(last["종가"]),
        volume_shares=int(last["거래량"]),
    )


def fetch_krx_latest_quote(stock_code: str) -> DailyPriceBar:
    """6자리·`KRX:` 접두 허용 — 내부적으로 `KRX:` listing_id로 수집."""
    return fetch_krx_daily_price_bar(stock_code)


def fetch_krx_reference_for_company(company: Company) -> Company:
    """KRX 상장(`company_id`가 `KRX:`)인 경우 일봉 종가를 기준 주가로 붙인다."""
    if not company.company_id.upper().startswith("KRX:"):
        raise ValueError(f"KRX company_id required, got {company.company_id!r}")
    bar = fetch_krx_daily_price_bar(company.company_id)
    return company_with_reference_from_daily_bar(company, bar)
