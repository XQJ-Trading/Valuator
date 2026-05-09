"""Annual record: 재무(`YearFinancials`) + 연말 시장(`MarketView`) 결합."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.boundary.krx_stock_price_collector import MarketView
from domain.boundary.opendart_financial import YearFinancials


@dataclass(frozen=True)
class AnnualRecord:
    """한 해 재무와 연말 시장 데이터의 결합. 직렬화 직전의 도메인 타입."""

    corp: str
    corp_name: str | None
    year: int
    financials: YearFinancials
    market: MarketView | None

    # ---- 시장 직접값 우선, 없으면 재무에서 유도 ------------------------------

    @property
    def stock_price(self) -> float | None:
        return self.market.stock_price if self.market else None

    @property
    def stock_price_as_of(self) -> str | None:
        return self.market.as_of.isoformat() if self.market else None

    @property
    def market_cap(self) -> float | None:
        return self.market.market_cap if self.market else None

    @property
    def shares_outstanding(self) -> float | None:
        if self.market and self.market.shares_outstanding is not None:
            return self.market.shares_outstanding
        net_income = self.financials.values.get("net_income")
        eps = self._raw_eps()
        if net_income not in (None, 0) and eps not in (None, 0):
            return net_income / eps
        return None

    @property
    def eps(self) -> float | None:
        eps = self._raw_eps()
        if eps is not None:
            return eps
        net_income = self.financials.values.get("net_income")
        shares = self.shares_outstanding
        if net_income not in (None, 0) and shares not in (None, 0):
            return net_income / shares
        return None

    @property
    def bps(self) -> float | None:
        if self.market and self.market.bps is not None:
            return self.market.bps
        equity = self.financials.values.get("total_equity")
        shares = self.shares_outstanding
        if equity not in (None, 0) and shares not in (None, 0):
            return equity / shares
        return None

    @property
    def per(self) -> float | None:
        if self.market and self.market.per is not None:
            return self.market.per
        price = self.stock_price
        eps = self.eps
        if price is not None and eps not in (None, 0):
            return price / eps
        cap = self.market_cap
        net_income = self.financials.values.get("net_income")
        if cap is not None and net_income not in (None, 0):
            return cap / net_income
        return None

    @property
    def pbr(self) -> float | None:
        if self.market and self.market.pbr is not None:
            return self.market.pbr
        price = self.stock_price
        bps = self.bps
        if price is not None and bps not in (None, 0):
            return price / bps
        cap = self.market_cap
        equity = self.financials.values.get("total_equity")
        if cap is not None and equity not in (None, 0):
            return cap / equity
        return None

    def _raw_eps(self) -> float | None:
        if self.market and self.market.eps is not None:
            return self.market.eps
        return self.financials.values.get("eps")

    # ---- 직렬화 ---------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Tool 결과로 노출하는 평탄한 dict. 재무값 + 시장값 + 유도값."""
        result: dict[str, Any] = dict(self.financials.values)
        result["corp"] = self.corp
        if self.corp_name:
            result["corp_name"] = self.corp_name
        result["year"] = self.year
        result["fs_div"] = self.financials.fs_div
        result["source_rcept_no"] = self.financials.source_rcept_no
        result["source_bsns_year"] = self.financials.source_bsns_year
        result["restated"] = self.financials.restated

        for key, value in (
            ("stock_price", self.stock_price),
            ("stock_price_as_of", self.stock_price_as_of),
            ("market_cap", self.market_cap),
            ("shares_outstanding", self.shares_outstanding),
            ("eps", self.eps),
            ("bps", self.bps),
            ("per", self.per),
            ("pbr", self.pbr),
        ):
            if value is not None:
                result[key] = value

        if self.market is not None:
            if self.market.dividend_yield is not None:
                result["dividend_yield"] = self.market.dividend_yield
            if self.market.dps is not None:
                result["dps"] = self.market.dps
        return result
