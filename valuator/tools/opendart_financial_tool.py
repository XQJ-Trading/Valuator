from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from domain.boundary.opendart_financial import (
    fetch_opendart_financial,
    resolve_corp_code,
)
from domain.knowledge.financial import DERIVED_DIFFERENCES, DERIVED_RATIOS
from .base import BaseTool, ToolResult


class OpenDartFinancialRequest(BaseModel):
    corp: str
    year: int
    fs_div: str = "CFS"

    @classmethod
    def from_kwargs(cls, kwargs: dict[str, Any]) -> "OpenDartFinancialRequest":
        corp = str(kwargs.get("corp") or "").strip()
        if not corp:
            raise ValueError("'corp' is required")
        year = str(kwargs.get("year") or "").strip()
        if not year:
            raise ValueError("'year' is required")
        try:
            year_value = int(year)
        except ValueError as exc:
            raise ValueError("'year' must be an integer") from exc
        fs_div = str(kwargs.get("fs_div") or "CFS").strip().upper()
        if fs_div not in {"CFS", "OFS"}:
            raise ValueError("'fs_div' must be 'CFS' or 'OFS'")
        return cls.model_validate(
            {"corp": corp, "year": year_value, "fs_div": fs_div}
        )


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

        corp_code = resolve_corp_code(request.corp)
        if corp_code is None:
            return ToolResult(
                success=False,
                result=None,
                error=f"Corp code not found: {request.corp}",
                metadata={
                    "fallback": {
                        "tool_name": "web_search_tool",
                        "tool_args": {
                            "query": f"{request.corp} financial statements {request.year}",
                        },
                    },
                },
            )

        result = fetch_opendart_financial(
            corp_code=corp_code,
            year=request.year,
            fs_div=request.fs_div,
        )
        used_fs_div = request.fs_div
        if result is None and request.fs_div == "CFS":
            result = fetch_opendart_financial(
                corp_code=corp_code,
                year=request.year,
                fs_div="OFS",
            )
            if result is not None:
                used_fs_div = "OFS"

        if not result:
            return ToolResult(
                success=False,
                result=None,
                error=f"No financial data: corp={request.corp}, year={request.year}",
                metadata={
                    "fallback": {
                        "tool_name": "yfinance_balance_sheet",
                        "tool_args": {"ticker": request.corp, "year": str(request.year)},
                    },
                },
            )

        result["corp"] = request.corp
        result["year"] = request.year
        _apply_derived_metrics(result)
        result["findings"] = _build_findings(result)

        return ToolResult(
            success=True,
            result=result,
            metadata={
                "source": "opendart",
                "corp_code": corp_code,
                "fs_div": used_fs_div,
            },
        )


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
