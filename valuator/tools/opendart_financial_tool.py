from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from domain.boundary.krx_stock_price_collector import fetch_krx_daily_price_bar
from domain.boundary.krx_ticker_resolve import resolve_krx_corp_record
from domain.boundary.opendart_financial import fetch_opendart_financial
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

        current_price = _resolve_current_price(record)
        corp_name = str(record.get("corp_name") or "").strip()

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
            if corp_name:
                data["corp_name"] = corp_name
            data["year"] = year
            if current_price is not None:
                data["current_price"] = current_price
            data = compute_metrics(data)
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
    "eps",
    "bps",
    "per",
    "pbr",
)


def _build_findings(result: dict[str, Any]) -> str:
    return ", ".join(
        f"{key}={result[key]}" for key in _FINDINGS_KEYS if result.get(key) is not None
    )
