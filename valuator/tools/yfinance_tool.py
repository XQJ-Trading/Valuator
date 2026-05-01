from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from domain.knowledge.financial import (
    STATEMENT_FIELDS,
    VALUATION_INFO_KEYS,
    compute_metrics,
)
from domain.time import YearRange
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
    model_config = ConfigDict(arbitrary_types_allowed=True)

    ticker: str
    year_range: YearRange

    @classmethod
    def from_kwargs(cls, kwargs: dict[str, Any]) -> "YFinanceRequest":
        ticker = str(kwargs.get("ticker") or kwargs.get("corp") or "").strip()
        if not ticker:
            raise ValueError("'ticker' is required")
        start = kwargs.get("start_year")
        end = kwargs.get("end_year")
        if start is None or end is None:
            raise ValueError("'start_year' and 'end_year' are required")
        return cls(ticker=ticker, year_range=YearRange(start=int(start), end=int(end)))

    def fallback_query(self) -> str:
        return (
            f"{self.ticker} balance sheet total assets total liabilities total equity "
            f"market cap current price trailing pe price to book {self.year_range}"
        )


@dataclass(frozen=True)
class LoadedStatements:
    ticker: str
    balance_sheet: Any
    income_statement: Any
    cashflow: Any
    info: dict[str, Any]


class YFinanceBalanceSheetTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="yfinance_balance_sheet",
            description=(
                "Fetch balance sheet metrics and core ratios for a given ticker over a "
                "year range using yfinance."
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
        per_year: list[dict[str, Any]] = []
        missing: list[int] = []

        for year in request.year_range.years():
            column = _match_year_column(year, available_years)
            if column is None:
                missing.append(year)
                continue
            row = _extract_year(
                statements=statements,
                year=year,
                column=column,
            )
            if _is_empty_row(row):
                missing.append(year)
                continue
            _apply_valuation_info(row, statements.info)
            row = compute_metrics(row)
            row["findings"] = _build_findings(row)
            per_year.append(row)

        if not per_year:
            return ToolResult(
                success=False,
                result=None,
                error=(
                    f"No balance sheet data found for {request.ticker} "
                    f"in {request.year_range}"
                ),
                metadata={
                    "ticker": statements.ticker,
                    "available_years": available_years,
                    "missing_years": missing,
                },
            )

        return ToolResult(
            success=True,
            result={
                "ticker": statements.ticker,
                "year_range": str(request.year_range),
                "results": per_year,
                "missing_years": missing,
                "findings": "\n".join(item["findings"] for item in per_year),
            },
            metadata={
                "source": "yfinance",
                "available_years": available_years,
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


def _match_year_column(year: int, available_years: list[str]) -> str | None:
    """Pick the column whose leading 'YYYY' matches the requested year."""
    target = str(year)
    for column in available_years:
        if column[:4] == target:
            return column
    return None


def _extract_year(
    *,
    statements: LoadedStatements,
    year: int,
    column: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "ticker": statements.ticker,
        "year": year,
    }
    for canonical in BALANCE_SHEET_FIELDS:
        row[canonical], _ = _pick_field(statements.balance_sheet, canonical, column)
    for canonical in INCOME_FIELDS:
        row[canonical], _ = _pick_field(statements.income_statement, canonical, column)
    for canonical in CASHFLOW_FIELDS:
        row[canonical], _ = _pick_field(statements.cashflow, canonical, column)
    return row


def _is_empty_row(row: dict[str, Any]) -> bool:
    return (
        row.get("total_assets") is None
        and row.get("total_liabilities") is None
        and row.get("total_equity") is None
    )


def _pick_field(
    statement: Any | None,
    canonical: str,
    column: str,
) -> tuple[float | None, str | None]:
    if statement is None or column not in statement.columns:
        return None, None

    field = FIELD_MAP[canonical]
    for row_name in field.aliases:
        if row_name not in statement.index:
            continue
        value = statement.loc[row_name, column]
        if hasattr(value, "iloc"):
            value = value.iloc[0]
        return float(value), row_name
    return None, None


def _apply_valuation_info(result: dict[str, Any], info: dict[str, Any]) -> None:
    for result_key, info_key in VALUATION_INFO_KEYS:
        result[result_key] = info.get(info_key)


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
