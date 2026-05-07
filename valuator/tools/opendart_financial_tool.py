from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from domain.boundary.krx_stock_price_collector import (
    MarketView,
    fetch_krx_market_view,
    fetch_krx_year_end_market_view,
)
from domain.boundary.krx_ticker_resolve import resolve_krx_corp_record
from domain.boundary.opendart_financial import YearFinancials, fetch_opendart_year
from domain.knowledge.annual_record import AnnualRecord
from domain.knowledge.financial import compute_metrics
from domain.time import YearRange
from .base import BaseTool, ToolResult


class OpenDartFinancialRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    corp: str
    year_range: YearRange
    fs_div: str = "CFS"

    @classmethod
    def from_kwargs(cls, kwargs: dict[str, Any]) -> "OpenDartFinancialRequest":
        corp = str(kwargs.get("corp") or "").strip()
        if not corp:
            raise ValueError("'corp' is required")
        year_range = _year_range_from_kwargs(kwargs)
        fs_div = str(kwargs.get("fs_div") or "CFS").strip().upper()
        if fs_div not in {"CFS", "OFS"}:
            raise ValueError("'fs_div' must be 'CFS' or 'OFS'")
        return cls(corp=corp, year_range=year_range, fs_div=fs_div)


def _year_range_from_kwargs(kwargs: dict[str, Any]) -> YearRange:
    start = kwargs.get("start_year")
    end = kwargs.get("end_year")
    if start is None or end is None:
        raise ValueError("'start_year' and 'end_year' are required")
    return YearRange(start=int(start), end=int(end))


class OpenDartFinancialTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="opendart_financial_tool",
            description="Fetch Korean company financial statements (BS/IS/CF) from DART.",
        )

    async def execute(self, **kwargs) -> ToolResult:
        try:
            request = OpenDartFinancialRequest.from_kwargs(kwargs)
        except ValueError as exc:
            return ToolResult(success=False, result=None, error=str(exc))

        record = resolve_krx_corp_record(request.corp)
        corp_code = record.get("corp_code") if record is not None else None
        if not corp_code:
            return ToolResult(
                success=False,
                result=None,
                error=f"Corp code not found: {request.corp}",
            )

        stock_code = str(record.get("stock_code") or "").strip()
        corp_name = str(record.get("corp_name") or "").strip() or None
        current_market = _resolve_current_market(stock_code)

        per_year: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        used_fs_divs: set[str] = set()

        for year in request.year_range.years():
            financials, error = _fetch_year(
                corp_code=corp_code,
                year=year,
                preferred_fs_div=request.fs_div,
            )
            if financials is None:
                missing.append({"year": year, "error": error or "unknown error"})
                continue

            record = AnnualRecord(
                corp=request.corp,
                corp_name=corp_name,
                year=year,
                financials=financials,
                market=_resolve_year_end_market(stock_code, year),
            )
            row = record.to_dict()
            row = compute_metrics(row)
            row["findings"] = _build_findings(row)
            per_year.append(row)
            used_fs_divs.add(financials.fs_div)
            sources.append(
                {
                    "year": year,
                    "rcept_no": financials.source_rcept_no,
                    "restated": financials.restated,
                    "fs_div": financials.fs_div,
                }
            )

        if not per_year:
            reasons = "; ".join(f"{m['year']}: {m['error']}" for m in missing)
            return ToolResult(
                success=False,
                result=None,
                error=(
                    f"No financial data: corp={request.corp}, "
                    f"year_range={request.year_range} — {reasons}"
                ),
                metadata={
                    "dart_errors": missing,
                    "fallback": {
                        "tool_name": "yfinance_balance_sheet",
                        "tool_args": {"ticker": request.corp},
                    },
                },
            )

        return ToolResult(
            success=True,
            result={
                "corp": request.corp,
                "year_range": str(request.year_range),
                "results": per_year,
                "missing_years": missing,
                "market_snapshot": _market_snapshot_dict(current_market),
                "findings": "\n".join(item["findings"] for item in per_year),
            },
            metadata={
                "source": "opendart",
                "corp_code": corp_code,
                "fs_divs": sorted(used_fs_divs),
                "sources": sources,
            },
        )


def _fetch_year(
    *,
    corp_code: str,
    year: int,
    preferred_fs_div: str,
) -> tuple[YearFinancials | None, str | None]:
    """Fetch one year, falling back from CFS to OFS when consolidated is empty."""
    financials, primary_err = fetch_opendart_year(
        corp_code=corp_code, year=year, fs_div=preferred_fs_div
    )
    if financials is not None:
        return financials, None

    if preferred_fs_div != "CFS":
        return None, primary_err

    financials, ofs_err = fetch_opendart_year(
        corp_code=corp_code, year=year, fs_div="OFS"
    )
    if financials is not None:
        return financials, None

    if primary_err and ofs_err and primary_err != ofs_err:
        return None, f"CFS: {primary_err}; OFS: {ofs_err}"
    return None, ofs_err or primary_err


def _resolve_current_market(stock_code: str) -> MarketView | None:
    if not stock_code:
        return None
    try:
        return fetch_krx_market_view(f"KRX:{stock_code}")
    except Exception:
        return None


def _resolve_year_end_market(stock_code: str, year: int) -> MarketView | None:
    if not stock_code:
        return None
    try:
        return fetch_krx_year_end_market_view(f"KRX:{stock_code}", year)
    except Exception:
        return None


def _market_snapshot_dict(market: MarketView | None) -> dict[str, Any]:
    if market is None:
        return {}
    snapshot: dict[str, Any] = {
        "listing_id": market.listing_id,
        "stock_price_as_of": market.as_of.isoformat(),
    }
    for key, value in (
        ("stock_price", market.stock_price),
        ("market_cap", market.market_cap),
        ("shares_outstanding", market.shares_outstanding),
        ("eps", market.eps),
        ("bps", market.bps),
        ("per", market.per),
        ("pbr", market.pbr),
        ("dividend_yield", market.dividend_yield),
        ("dps", market.dps),
    ):
        if value is not None:
            snapshot[key] = value
    if market.stock_price is not None:
        snapshot["current_price"] = market.stock_price
    return snapshot


_FINDINGS_KEYS: tuple[str, ...] = (
    "corp",
    "year",
    "stock_price_as_of",
    "source_rcept_no",
    "source_bsns_year",
    "restated",
    # Balance Sheet
    "total_assets",
    "current_assets",
    "total_liabilities",
    "current_liabilities",
    "short_term_debt",
    "long_term_debt",
    "cash_and_equivalents",
    "total_equity",
    "retained_earnings",
    # Income Statement
    "total_revenue",
    "cost_of_revenue",
    "gross_profit",
    "sga_expense",
    "operating_income",
    "interest_expense",
    "tax_expense",
    "net_income",
    "ebitda",
    # Cash Flow
    "operating_cash_flow",
    "capex",
    "free_cash_flow",
    "dividends_paid",
    # Derived
    "gross_margin",
    "operating_margin",
    "net_margin",
    "effective_tax_rate",
    "debt_to_equity",
    "current_ratio",
    "interest_coverage",
    "working_capital",
    "total_debt",
    "net_debt",
    "total_shareholder_return",
    "stock_price",
    "market_cap",
    "shares_outstanding",
    "eps",
    "bps",
    "per",
    "pbr",
)


def _build_findings(result: dict[str, Any]) -> str:
    return ", ".join(
        f"{key}={result[key]}" for key in _FINDINGS_KEYS if result.get(key) is not None
    )
