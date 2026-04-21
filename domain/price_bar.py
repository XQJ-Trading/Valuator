"""상장종목 일봉 시세 — 온톨로지 `stock_price`·`price_*`·`volume`과 정합."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from domain.company import ReferenceStockPrice


@dataclass(frozen=True, slots=True)
class DailyPriceBar:
    """직전(또는 구간 내 최종) 영업일 OHLCV. 종가가 온톨로지 `stock_price`에 해당."""

    listing_id: str
    as_of: date
    open_krw: int
    high_krw: int
    low_krw: int
    close_krw: int
    volume_shares: int

    def as_reference_stock_price(self) -> ReferenceStockPrice:
        """Company.reference_stock_price / 기준 주가에 넣을 값."""
        return ReferenceStockPrice(
            krw=self.close_krw,
            as_of=self.as_of,
            listing_id=self.listing_id,
        )

    def ontology_period(self) -> str:
        """facts 키 `{subject}:{property_key}:{period}` 의 period (예: 2026-04-21)."""
        return self.as_of.isoformat()

    def ontology_numeric_values(self) -> dict[str, int]:
        """등록된 price 지표 키만 — LLM/파이프라인 facts와 동일 스키마."""
        return {
            "stock_price": self.close_krw,
            "price_open": self.open_krw,
            "price_high": self.high_krw,
            "price_low": self.low_krw,
            "volume": self.volume_shares,
        }
