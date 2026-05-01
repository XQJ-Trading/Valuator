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


# 정책: raw가 우선이다. 파생 계산은 raw가 결측일 때만 채워넣는다(backfill).
# 회사가 비표준 방식으로 ebitda/margin/per 등을 보고해도 그 값을 신뢰하고,
# 표준 공식 재계산으로 덮어씌우지 않는다.
def _apply_derived_metrics(result: dict[str, Any]) -> None:
    for metric in DERIVED_RATIOS:
        if result.get(metric.name) is not None:
            continue
        numerator = result.get(metric.numerator)
        denominator = result.get(metric.denominator)
        if numerator is None or denominator is None:
            continue
        denominator_value = abs(denominator) if metric.abs_denominator else denominator
        if not denominator_value:
            continue
        result[metric.name] = numerator / denominator_value

    for metric in DERIVED_DIFFERENCES:
        if result.get(metric.name) is not None:
            continue
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
    if result.get("ebitda") is not None:
        return
    operating_income = result.get("operating_income")
    depreciation = result.get("depreciation")
    amortization = result.get("amortization")
    if operating_income is None or depreciation is None or amortization is None:
        return
    result["ebitda"] = operating_income + depreciation + amortization


def _calc_operating_margin(result: dict[str, Any]) -> None:
    if result.get("operating_margin") is not None:
        return
    operating_income = result.get("operating_income")
    total_revenue = result.get("total_revenue")
    if operating_income is None or not total_revenue:
        return
    result["operating_margin"] = operating_income / total_revenue


def _calc_net_margin(result: dict[str, Any]) -> None:
    if result.get("net_margin") is not None:
        return
    net_income = result.get("net_income")
    total_revenue = result.get("total_revenue")
    if net_income is None or not total_revenue:
        return
    result["net_margin"] = net_income / total_revenue


def _calc_effective_tax_rate(result: dict[str, Any]) -> None:
    if result.get("effective_tax_rate") is not None:
        return
    tax_expense = result.get("tax_expense")
    net_income = result.get("net_income")
    if tax_expense is None or net_income is None:
        return
    pretax_income = net_income + tax_expense
    if not pretax_income:
        return
    result["effective_tax_rate"] = tax_expense / pretax_income


def _calc_working_capital(result: dict[str, Any]) -> None:
    if result.get("working_capital") is not None:
        return
    current_assets = result.get("current_assets")
    current_liabilities = result.get("current_liabilities")
    if current_assets is None or current_liabilities is None:
        return
    result["working_capital"] = current_assets - current_liabilities


def _calc_net_debt(result: dict[str, Any]) -> None:
    short_term_debt = result.get("short_term_debt")
    long_term_debt = result.get("long_term_debt")
    cash_and_equivalents = result.get("cash_and_equivalents")
    if (
        short_term_debt is None
        or long_term_debt is None
        or cash_and_equivalents is None
    ):
        return
    if result.get("total_debt") is None:
        result["total_debt"] = short_term_debt + long_term_debt
    if result.get("net_debt") is None:
        result["net_debt"] = result["total_debt"] - cash_and_equivalents


def _calc_shareholder_return(result: dict[str, Any]) -> None:
    if result.get("total_shareholder_return") is not None:
        return
    dividends_paid = result.get("dividends_paid")
    share_buyback = result.get("share_buyback")
    if dividends_paid is None or share_buyback is None:
        return
    result["total_shareholder_return"] = abs(dividends_paid) + abs(share_buyback)


def _calc_per_pbr(result: dict[str, Any]) -> None:
    current_price = result.get("current_price")
    if current_price is None:
        return
    if result.get("per") is None:
        eps_basic = result.get("eps_basic")
        if eps_basic is not None and eps_basic > 0:
            result["per"] = current_price / eps_basic
    if result.get("pbr") is None:
        bps = result.get("bps")
        if bps is not None and bps > 0:
            result["pbr"] = current_price / bps


_FINDINGS_KEYS: tuple[str, ...] = (
    "corp",
    "year",
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
    "eps_basic",
    "bps",
    "per",
    "pbr",
)


def _build_findings(result: dict[str, Any]) -> str:
    return ", ".join(
        f"{key}={result[key]}" for key in _FINDINGS_KEYS if result.get(key) is not None
    )
