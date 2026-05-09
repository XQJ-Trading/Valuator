"""Boundary: KRX 일봉 → DailyPriceBar (listing_id·온톨로지 정합)."""

from __future__ import annotations

import contextlib
import io
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

from domain.company import Company, company_with_reference_from_daily_bar
from domain.price_bar import DailyPriceBar

_STOCK_CODE_RE = re.compile(r"^\d{6}$")
_LOOKBACK_DAYS = 40


@dataclass(frozen=True)
class MarketView:
    """KRX 시장이 한 시점에 매긴 가격·배수. 기준일은 `as_of`."""

    listing_id: str
    as_of: date
    stock_price: float | None = None
    market_cap: float | None = None
    shares_outstanding: float | None = None
    eps: float | None = None
    bps: float | None = None
    per: float | None = None
    pbr: float | None = None
    dividend_yield: float | None = None
    dps: float | None = None


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


def fetch_krx_market_view(
    listing_id: str,
    *,
    end: date | None = None,
) -> MarketView:
    """KRX OHLCV + fundamental view ending at `end`.

    For annual records, callers should pass the fiscal year-end date.
    Raises if no data is available (no price and no fundamentals).
    """
    from pykrx import stock

    code = normalize_krx_stock_code(listing_id)
    canonical_id = _canonical_krx_listing_id(code)
    end_date = end or date.today()
    start_date = end_date - timedelta(days=_LOOKBACK_DAYS)
    start = start_date.strftime("%Y%m%d")
    end_text = end_date.strftime("%Y%m%d")

    as_of: date | None = None
    stock_price: float | None = None
    market_cap: float | None = None
    shares_outstanding: float | None = None
    eps: float | None = None
    bps: float | None = None
    per: float | None = None
    pbr: float | None = None
    dividend_yield: float | None = None
    dps: float | None = None

    ohlcv = stock.get_market_ohlcv(start, end_text, code)
    if not ohlcv.empty:
        last_price = ohlcv.iloc[-1]
        stock_price = float(last_price["종가"])
        as_of = ohlcv.index[-1].date()

    market_cap_df = _quiet_pykrx_optional_call(
        lambda: stock.get_market_cap_by_date(start, end_text, code)
    )
    if market_cap_df is not None and not market_cap_df.empty:
        last_cap = market_cap_df.iloc[-1]
        as_of = market_cap_df.index[-1].date()
        market_cap = _to_number(last_cap.get("시가총액"), omit_zero=True)
        shares_outstanding = _to_number(last_cap.get("상장주식수"), omit_zero=True)

    fundamentals = _quiet_pykrx_optional_call(
        lambda: stock.get_market_fundamental_by_date(start, end_text, code)
    )
    if fundamentals is not None and not fundamentals.empty:
        last_fundamental = fundamentals.iloc[-1]
        if as_of is None:
            as_of = fundamentals.index[-1].date()
        bps = _to_number(last_fundamental.get("BPS"), omit_zero=True)
        eps = _to_number(last_fundamental.get("EPS"), omit_zero=True)
        per = _to_number(last_fundamental.get("PER"), omit_zero=True)
        pbr = _to_number(last_fundamental.get("PBR"), omit_zero=True)
        dividend_yield = _to_number(last_fundamental.get("DIV"), omit_zero=True)
        dps = _to_number(last_fundamental.get("DPS"), omit_zero=True)

    if as_of is None:
        raise ValueError(f"no KRX market view for listing_id={canonical_id!r}")

    return MarketView(
        listing_id=canonical_id,
        as_of=as_of,
        stock_price=stock_price,
        market_cap=market_cap,
        shares_outstanding=shares_outstanding,
        eps=eps,
        bps=bps,
        per=per,
        pbr=pbr,
        dividend_yield=dividend_yield,
        dps=dps,
    )


def fetch_krx_year_end_market_view(
    listing_id: str,
    year: int,
) -> MarketView:
    """Year-end KRX market view for a fiscal year (clamped to today)."""
    today = date.today()
    end = date(year, 12, 31)
    if end > today:
        end = today
    return fetch_krx_market_view(listing_id, end=end)


def _to_number(value: Any, *, omit_zero: bool = False) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if omit_zero and number == 0:
        return None
    return number


def _quiet_pykrx_optional_call(call: Callable[[], Any]) -> Any | None:
    previous_disable_level = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            return call()
    except Exception:
        return None
    finally:
        logging.disable(previous_disable_level)


def fetch_krx_latest_quote(stock_code: str) -> DailyPriceBar:
    """6자리·`KRX:` 접두 허용 — 내부적으로 `KRX:` listing_id로 수집."""
    return fetch_krx_daily_price_bar(stock_code)


def fetch_krx_reference_for_company(company: Company) -> Company:
    """KRX 상장(`company_id`가 `KRX:`)인 경우 일봉 종가를 기준 주가로 붙인다."""
    if not company.company_id.upper().startswith("KRX:"):
        raise ValueError(f"KRX company_id required, got {company.company_id!r}")
    bar = fetch_krx_daily_price_bar(company.company_id)
    return company_with_reference_from_daily_bar(company, bar)
