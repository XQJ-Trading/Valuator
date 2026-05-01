from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from domain.boundary.krx_stock_price_collector import fetch_krx_daily_price_bar
from domain.boundary.krx_ticker_resolve import resolve_krx_corp_record
from domain.boundary.opendart_financial import fetch_opendart_financial
from domain.knowledge.financial import DERIVED_DIFFERENCES, DERIVED_RATIOS
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
                metadata={
                    "fallback": {
                        "tool_name": "web_search_tool",
                        "tool_args": {
                            "query": (
                                f"{request.corp} financial statements "
                                f"{request.year_range}"
                            ),
                        },
                    },
                },
            )

        current_price = _resolve_current_price(record)

        per_year: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        used_fs_divs: set[str] = set()

        for year in request.year_range.years():
            data, used_fs_div, error = _fetch_year(
                corp_code=corp_code,
                year=year,
                preferred_fs_div=request.fs_div,
            )
            if data is None:
                missing.append({"year": year, "error": error or "unknown error"})
                continue
            data["corp"] = request.corp
            data["year"] = year
            if current_price is not None:
                data["current_price"] = current_price
            _apply_derived_metrics(data)
            data["findings"] = _build_findings(data)
            per_year.append(data)
            used_fs_divs.add(used_fs_div)

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
                "findings": "\n".join(item["findings"] for item in per_year),
            },
            metadata={
                "source": "opendart",
                "corp_code": corp_code,
                "fs_divs": sorted(used_fs_divs),
            },
        )


def _fetch_year(
    *,
    corp_code: str,
    year: int,
    preferred_fs_div: str,
) -> tuple[dict[str, float | None] | None, str, str | None]:
    """Fetch one year, falling back from CFS to OFS when consolidated is empty."""
    data, primary_err = fetch_opendart_financial(
        corp_code=corp_code, year=year, fs_div=preferred_fs_div
    )
    if data is not None:
        return data, preferred_fs_div, None

    if preferred_fs_div != "CFS":
        return None, preferred_fs_div, primary_err

    data, ofs_err = fetch_opendart_financial(
        corp_code=corp_code, year=year, fs_div="OFS"
    )
    if data is not None:
        return data, "OFS", None

    if primary_err and ofs_err and primary_err != ofs_err:
        return None, preferred_fs_div, f"CFS: {primary_err}; OFS: {ofs_err}"
    return None, preferred_fs_div, ofs_err or primary_err


def _resolve_current_price(record: dict[str, Any]) -> float | None:
    stock_code = record.get("stock_code", "")
    if not stock_code:
        return None
    try:
        return fetch_krx_daily_price_bar(f"KRX:{stock_code}").close_krw
    except Exception:
        return None


def _apply_derived_metrics(result: dict[str, Any]) -> None:
    for metric in DERIVED_RATIOS:
        numerator = result.get(metric.numerator)
        denominator = result.get(metric.denominator)
        if numerator is None or denominator in (None, 0):
            continue
        denominator_value = abs(denominator) if metric.abs_denominator else denominator
        if not denominator_value:
            continue
        result[metric.name] = numerator / denominator_value

    for metric in DERIVED_DIFFERENCES:
        minuend = result.get(metric.minuend)
        subtrahend = result.get(metric.subtrahend)
        if minuend is None or subtrahend is None:
            continue
        result[metric.name] = minuend - subtrahend

    _calc_ebitda(result)
    _calc_operating_margin(result)
    _calc_net_margin(result)
    _calc_effective_tax_rate(result)
    _calc_working_capital(result)
    _calc_net_debt(result)
    _calc_shareholder_return(result)
    _calc_per_pbr(result)


def _calc_ebitda(result: dict[str, Any]) -> None:
    operating_income = result.get("operating_income")
    depreciation = result.get("depreciation", 0) or 0
    amortization = result.get("amortization", 0) or 0
    if operating_income is not None:
        result["ebitda"] = operating_income + depreciation + amortization


def _calc_operating_margin(result: dict[str, Any]) -> None:
    operating_income = result.get("operating_income")
    total_revenue = result.get("total_revenue")
    if operating_income is not None and total_revenue:
        result["operating_margin"] = operating_income / total_revenue


def _calc_net_margin(result: dict[str, Any]) -> None:
    net_income = result.get("net_income")
    total_revenue = result.get("total_revenue")
    if net_income is not None and total_revenue:
        result["net_margin"] = net_income / total_revenue


def _calc_effective_tax_rate(result: dict[str, Any]) -> None:
    tax_expense = result.get("tax_expense")
    net_income = result.get("net_income")
    if net_income is None or tax_expense is None:
        return
    pretax_income = net_income + tax_expense
    if pretax_income:
        result["effective_tax_rate"] = tax_expense / pretax_income


def _calc_working_capital(result: dict[str, Any]) -> None:
    current_assets = result.get("current_assets")
    current_liabilities = result.get("current_liabilities")
    if current_assets is not None and current_liabilities is not None:
        result["working_capital"] = current_assets - current_liabilities


def _calc_net_debt(result: dict[str, Any]) -> None:
    short_term_debt = result.get("short_term_debt", 0) or 0
    long_term_debt = result.get("long_term_debt", 0) or 0
    cash_and_equivalents = result.get("cash_and_equivalents", 0) or 0
    total_debt = short_term_debt + long_term_debt
    if total_debt:
        result["total_debt"] = total_debt
        result["net_debt"] = total_debt - cash_and_equivalents


def _calc_shareholder_return(result: dict[str, Any]) -> None:
    dividends_paid = result.get("dividends_paid")
    share_buyback = result.get("share_buyback")
    if dividends_paid is None and share_buyback is None:
        return
    result["total_shareholder_return"] = abs(dividends_paid or 0) + abs(
        share_buyback or 0
    )


def _calc_per_pbr(result: dict[str, Any]) -> None:
    current_price = result.get("current_price")
    if current_price is None:
        return
    eps_basic = result.get("eps_basic")
    if eps_basic and eps_basic > 0:
        result["per"] = current_price / eps_basic
    bps = result.get("bps")
    if bps and bps > 0:
        result["pbr"] = current_price / bps


def _build_findings(result: dict[str, Any]) -> str:
    keys = (
        "corp",
        "year",
        "total_assets",
        "total_equity",
        "total_revenue",
        "net_income",
        "operating_income",
        "ebitda",
        "gross_margin",
        "operating_margin",
        "net_margin",
        "debt_to_equity",
        "current_ratio",
        "net_debt",
        "interest_coverage",
        "operating_cash_flow",
        "free_cash_flow",
        "total_shareholder_return",
        "eps_basic",
        "eps_diluted",
        "bps",
        "per",
        "pbr",
    )
    return ", ".join(f"{key}={result.get(key)}" for key in keys if result.get(key) is not None)
