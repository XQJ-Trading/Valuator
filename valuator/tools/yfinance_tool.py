from typing import Any, Dict

from .base import BaseTool, ToolResult


class YFinanceBalanceSheetTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="yfinance_balance_sheet",
            description=(
                "Fetch balance sheet metrics and core ratios for a given ticker and year using yfinance."
            ),
        )

    async def execute(self, **kwargs) -> ToolResult:
        import datetime as dt
        import yfinance as yf

        raw = kwargs.get("ticker") or kwargs.get("corp")
        if not raw or not str(raw).strip():
            return ToolResult(success=False, result=None, error="'ticker' is required")

        year = str(kwargs.get("year") or kwargs.get("years") or "").strip()
        min_year = kwargs.get("min_year")
        if min_year is not None:
            min_year = int(min_year)

        symbol = str(raw).strip()
        ticker_candidates = [symbol]
        if symbol.isdigit() and len(symbol) == 6:
            ticker_candidates = [f"{symbol}.KS", f"{symbol}.KQ", symbol]

        def fetch(attr):
            for cand in ticker_candidates:
                bs = getattr(yf.Ticker(cand), attr)
                if bs is not None and not bs.empty:
                    return bs, cand
            return None, None

        bs, used_ticker = fetch("balance_sheet")
        if bs is None:
            bs, used_ticker = fetch("quarterly_balance_sheet")
        if bs is None:
            return ToolResult(
                success=False,
                result=None,
                error="No balance sheet available for ticker",
                metadata={"tried": ticker_candidates},
            )

        bs.columns = [str(c) for c in bs.columns]
        available_years = list(bs.columns)
        if not available_years:
            return ToolResult(
                success=False,
                result=None,
                error="No usable year found in balance sheet columns",
                metadata={"available_years": available_years},
            )

        numeric_cols = [(c, int(c[:4])) for c in available_years if c[:4].isdigit()]
        year_label = year or "latest"
        if not year or year.lower() == "latest":
            current_year = dt.datetime.now().year
            year_candidates = [
                c
                for c, y in numeric_cols
                if y <= current_year and (min_year is None or y >= min_year)
            ]
            if not year_candidates and min_year is not None:
                year_candidates = [c for c, y in numeric_cols if y <= current_year]
            if not year_candidates:
                return ToolResult(
                    success=False,
                    result=None,
                    error="No usable year found in balance sheet columns",
                    metadata={"available_years": available_years},
                )
            chosen_year = max(year_candidates, key=lambda c: int(c[:4]))
            tried_years = [year_label, chosen_year]
        else:
            if year in available_years:
                chosen_year = year
                tried_years = [year]
            elif year[:4].isdigit() and numeric_cols:
                target = int(year[:4])
                prev = [c for c, y in numeric_cols if y <= target]
                chosen_year = (
                    max(prev, key=lambda c: int(c[:4]))
                    if prev
                    else min(numeric_cols, key=lambda x: abs(x[1] - target))[0]
                )
                tried_years = [year, chosen_year]
            else:
                chosen_year = available_years[0]
                tried_years = [year, chosen_year]

        def pick(df, rows):
            if df is None or df.empty or chosen_year not in df.columns:
                return None, None
            for row in rows:
                if row in df.index:
                    val = df.loc[row, chosen_year]
                    if hasattr(val, "iloc"):
                        val = val.iloc[0]
                    return float(val), row
            return None, None

        total_assets, assets_row_used = pick(
            bs,
            ("Total Assets", "Total Assets Net Minority Interest", "Total Assets USD"),
        )
        total_liabilities, liab_row_used = pick(
            bs,
            (
                "Total Liabilities Net Minority Interest",
                "Total Liabilities",
                "Total Liabilities & Stockholders' Equity",
            ),
        )
        total_equity, equity_row_used = pick(
            bs,
            (
                "Stockholders Equity",
                "Total Stockholder Equity",
                "Total Equity Gross Minority Interest",
                "Total Equity Net Minority Interest",
            ),
        )
        if total_assets is None and total_liabilities is None and total_equity is None:
            return ToolResult(
                success=False,
                result=None,
                error="No balance sheet data found for given year/ticker",
                metadata={
                    "ticker": used_ticker,
                    "requested_year": year_label,
                    "used_year": chosen_year,
                    "available_years": available_years,
                },
            )

        t = yf.Ticker(used_ticker)
        cf = t.cashflow
        if cf is None or cf.empty:
            cf = t.quarterly_cashflow
        fin = t.financials
        if fin is None or fin.empty:
            fin = t.quarterly_financials
        current_assets, _ = pick(
            bs, ("Total Current Assets", "Current Assets", "Total Current Assets USD")
        )
        current_liabilities, _ = pick(
            bs,
            (
                "Total Current Liabilities",
                "Current Liabilities",
                "Total Current Liabilities USD",
            ),
        )
        operating_income, _ = pick(
            fin, ("Operating Income", "Operating Income or Loss")
        )
        interest_expense, _ = pick(
            fin,
            ("Interest Expense", "Interest Expense and Debt", "Interest Expense, Net"),
        )
        operating_cash_flow, _ = pick(
            cf,
            (
                "Total Cash From Operating Activities",
                "Cash Flow From Continuing Operating Activities",
            ),
        )
        capex, _ = pick(cf, ("Capital Expenditures", "Capital Expenditure"))
        result = {
            "ticker": used_ticker,
            "requested_year": year_label,
            "year": chosen_year,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "total_equity": total_equity,
            "current_assets": current_assets,
            "current_liabilities": current_liabilities,
            "operating_income": operating_income,
            "interest_expense": interest_expense,
            "operating_cash_flow": operating_cash_flow,
            "capex": capex,
        }
        if total_liabilities is not None and total_equity:
            result["debt_to_equity"] = total_liabilities / total_equity
        if current_assets is not None and current_liabilities:
            result["current_ratio"] = current_assets / current_liabilities
        if operating_income is not None and interest_expense:
            result["interest_coverage"] = operating_income / abs(interest_expense)
        if operating_cash_flow is not None and capex is not None:
            result["free_cash_flow"] = operating_cash_flow - capex
        return ToolResult(
            success=True,
            result=result,
            metadata={
                "source": "yfinance",
                "assets_row": assets_row_used,
                "liabilities_row": liab_row_used,
                "equity_row": equity_row_used,
                "available_years": available_years,
                "year_selection": tried_years,
            },
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ticker": {
                            "type": "string",
                            "description": "Ticker symbol (e.g., 'AAPL' or '005930')",
                        },
                        "year": {
                            "type": "string",
                            "description": "Year (e.g., '2025') or 'latest' to use the most recent available",
                            "default": "latest",
                        },
                        "min_year": {
                            "type": "integer",
                            "description": "Minimum acceptable year when using 'latest' (e.g., 2025)",
                            "default": None,
                        },
                    },
                    "required": ["ticker"],
                },
            },
        }
