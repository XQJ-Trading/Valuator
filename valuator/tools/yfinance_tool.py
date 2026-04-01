from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from domain.knowledge.financial import (
    DERIVED_DIFFERENCES,
    DERIVED_RATIOS,
    STATEMENT_FIELDS,
    VALUATION_INFO_KEYS,
)
from .base import BaseTool, ToolResult

FIELD_MAP = {field.canonical: field for field in STATEMENT_FIELDS}
BALANCE_SHEET_FIELDS = (
    "total_assets",
    "total_liabilities",
    "total_equity",
    "current_assets",
    "current_liabilities",
)
INCOME_FIELDS = (
    "operating_income",
    "interest_expense",
    "total_revenue",
    "gross_profit",
    "net_income",
    "ebitda",
)
CASHFLOW_FIELDS = (
    "operating_cash_flow",
    "capex",
)


class YFinanceRequest(BaseModel):
    ticker: str
    year: str = "latest"
    min_year: int | None = None

    @classmethod
    def from_kwargs(cls, kwargs: dict[str, Any]) -> "YFinanceRequest":
        ticker = str(kwargs.get("ticker") or kwargs.get("corp") or "").strip()
        if not ticker:
            raise ValueError("'ticker' is required")

        year = str(kwargs.get("year") or kwargs.get("years") or "latest").strip()
        raw_min_year = kwargs.get("min_year")
        min_year = None if raw_min_year in (None, "") else int(raw_min_year)

        return cls.model_validate(
            {
                "ticker": ticker,
                "year": year or "latest",
                "min_year": min_year,
            }
        )

    def requested_year_label(self) -> str:
        return self.year or "latest"

    def fallback_query(self) -> str:
        return (
            f"{self.ticker} balance sheet total assets total liabilities total equity "
            f"market cap current price trailing pe price to book {self.requested_year_label()}"
        )


@dataclass(frozen=True)
class LoadedStatements:
    ticker: str
    balance_sheet: Any
    income_statement: Any
    cashflow: Any
    info: dict[str, Any]


@dataclass(frozen=True)
class YearSelection:
    requested_year: str
    chosen_year: str
    tried_years: tuple[str, ...]


class YFinanceBalanceSheetTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="yfinance_balance_sheet",
            description=(
                "Fetch balance sheet metrics and core ratios for a given ticker and year using yfinance."
            ),
        )

    async def execute(self, **kwargs) -> ToolResult:
        try:
            request = YFinanceRequest.from_kwargs(kwargs)
        except ValueError as exc:
            return ToolResult(success=False, result=None, error=str(exc))

        try:
            import yfinance as yf
        except Exception as exc:
            return ToolResult(
                success=False,
                result=None,
                error=f"yfinance dependency is unavailable: {exc}",
                metadata={
                    "error_code": "dependency_missing",
                    "fallback": {
                        "tool_name": "web_search_tool",
                        "tool_args": {"query": request.fallback_query()},
                    },
                },
            )

        statements = _load_statements(yf, request.ticker)
        if statements is None:
            return ToolResult(
                success=False,
                result=None,
                error="No balance sheet available for ticker",
                metadata={"tried": [request.ticker]},
            )

        available_years = list(statements.balance_sheet.columns)
        if not available_years:
            return ToolResult(
                success=False,
                result=None,
                error="No usable year found in balance sheet columns",
                metadata={"available_years": available_years},
            )

        try:
            year_selection = _resolve_year(
                requested_year=request.requested_year_label(),
                min_year=request.min_year,
                available_years=available_years,
            )
        except ValueError as exc:
            return ToolResult(
                success=False,
                result=None,
                error=str(exc),
                metadata={"available_years": available_years},
            )

        result, row_usage = _extract_result(
            statements=statements,
            year=year_selection.chosen_year,
            requested_year=year_selection.requested_year,
        )
        if (
            result["total_assets"] is None
            and result["total_liabilities"] is None
            and result["total_equity"] is None
        ):
            return ToolResult(
                success=False,
                result=None,
                error="No balance sheet data found for given year/ticker",
                metadata={
                    "ticker": statements.ticker,
                    "requested_year": year_selection.requested_year,
                    "used_year": year_selection.chosen_year,
                    "available_years": available_years,
                },
            )

        _apply_valuation_info(result, statements.info)
        _apply_derived_metrics(result)
        result["findings"] = _build_findings(result)

        return ToolResult(
            success=True,
            result=result,
            metadata={
                "source": "yfinance",
                "assets_row": row_usage["total_assets"],
                "liabilities_row": row_usage["total_liabilities"],
                "equity_row": row_usage["total_equity"],
                "available_years": available_years,
                "year_selection": list(year_selection.tried_years),
            },
        )

def _load_statements(yf_module: Any, ticker: str) -> LoadedStatements | None:
    ticker_client = yf_module.Ticker(ticker)
    balance_sheet = _first_available_statement(
        ticker_client,
        ("balance_sheet", "quarterly_balance_sheet"),
    )
    if balance_sheet is None:
        return None
    return LoadedStatements(
        ticker=ticker,
        balance_sheet=balance_sheet,
        income_statement=_first_available_statement(
            ticker_client,
            ("financials", "quarterly_financials"),
        ),
        cashflow=_first_available_statement(
            ticker_client,
            ("cashflow", "quarterly_cashflow"),
        ),
        info=dict(ticker_client.info or {}),
    )


def _first_available_statement(ticker_client: Any, attrs: tuple[str, ...]) -> Any | None:
    for attr in attrs:
        statement = _normalize_statement(getattr(ticker_client, attr))
        if statement is not None:
            return statement
    return None


def _normalize_statement(statement: Any) -> Any | None:
    if statement is None or statement.empty:
        return None
    statement.columns = [str(column) for column in statement.columns]
    return statement


def _resolve_year(
    *,
    requested_year: str,
    min_year: int | None,
    available_years: list[str],
) -> YearSelection:
    numeric_cols = [(column, int(column[:4])) for column in available_years if column[:4].isdigit()]
    if requested_year.lower() == "latest":
        current_year = datetime.now().year
        year_candidates = [
            column
            for column, year in numeric_cols
            if year <= current_year and (min_year is None or year >= min_year)
        ]
        if not year_candidates and min_year is not None:
            year_candidates = [
                column
                for column, year in numeric_cols
                if year <= current_year
            ]
        if not year_candidates:
            raise ValueError("No usable year found in balance sheet columns")
        chosen_year = max(year_candidates, key=lambda column: int(column[:4]))
        return YearSelection(
            requested_year=requested_year,
            chosen_year=chosen_year,
            tried_years=(requested_year, chosen_year),
        )

    if requested_year in available_years:
        return YearSelection(
            requested_year=requested_year,
            chosen_year=requested_year,
            tried_years=(requested_year,),
        )

    if requested_year[:4].isdigit() and numeric_cols:
        target_year = int(requested_year[:4])
        previous_years = [column for column, year in numeric_cols if year <= target_year]
        chosen_year = (
            max(previous_years, key=lambda column: int(column[:4]))
            if previous_years
            else min(numeric_cols, key=lambda item: abs(item[1] - target_year))[0]
        )
        return YearSelection(
            requested_year=requested_year,
            chosen_year=chosen_year,
            tried_years=(requested_year, chosen_year),
        )

    return YearSelection(
        requested_year=requested_year,
        chosen_year=available_years[0],
        tried_years=(requested_year, available_years[0]),
    )


def _extract_result(
    *,
    statements: LoadedStatements,
    year: str,
    requested_year: str,
) -> tuple[dict[str, Any], dict[str, str | None]]:
    result = {
        "ticker": statements.ticker,
        "requested_year": requested_year,
        "year": year,
    }
    row_usage: dict[str, str | None] = {
        "total_assets": None,
        "total_liabilities": None,
        "total_equity": None,
    }

    for canonical in BALANCE_SHEET_FIELDS:
        value, row_name = _pick_field(statements.balance_sheet, canonical, year)
        result[canonical] = value
        if canonical in row_usage:
            row_usage[canonical] = row_name

    for canonical in INCOME_FIELDS:
        value, _ = _pick_field(statements.income_statement, canonical, year)
        result[canonical] = value

    for canonical in CASHFLOW_FIELDS:
        value, _ = _pick_field(statements.cashflow, canonical, year)
        result[canonical] = value

    return result, row_usage


def _pick_field(
    statement: Any | None,
    canonical: str,
    year: str,
) -> tuple[float | None, str | None]:
    if statement is None or year not in statement.columns:
        return None, None

    field = FIELD_MAP[canonical]
    for row_name in field.aliases:
        if row_name not in statement.index:
            continue
        value = statement.loc[row_name, year]
        if hasattr(value, "iloc"):
            value = value.iloc[0]
        return float(value), row_name
    return None, None


def _apply_valuation_info(result: dict[str, Any], info: dict[str, Any]) -> None:
    for result_key, info_key in VALUATION_INFO_KEYS:
        result[result_key] = info.get(info_key)


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


def _build_findings(result: dict[str, Any]) -> str:
    return ", ".join(
        [
            f"ticker={result['ticker']}",
            f"year={result['year']}",
            f"market_cap={result.get('market_cap')}",
            f"current_price={result.get('current_price')}",
            f"trailing_pe={result.get('trailing_pe')}",
            f"price_to_book={result.get('price_to_book')}",
            f"total_revenue={result.get('total_revenue')}",
            f"net_income={result.get('net_income')}",
            f"debt_to_equity={result.get('debt_to_equity')}",
            f"current_ratio={result.get('current_ratio')}",
            f"gross_margin={result.get('gross_margin')}",
            f"interest_coverage={result.get('interest_coverage')}",
            f"free_cash_flow={result.get('free_cash_flow')}",
        ]
    )
