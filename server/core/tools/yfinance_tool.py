"""YFinance tool to fetch balance sheet metrics"""

from typing import Any, Dict, Optional, List, Tuple

from .base import BaseTool, ToolResult


class YFinanceBalanceSheetTool(BaseTool):
    """Fetch balance sheet figures for a given ticker and year using yfinance."""

    def __init__(self):
        super().__init__(
            name="yfinance_balance_sheet",
            description=(
                "Fetch Total Assets, Total Liabilities Net Minority Interest, and "
                "Stockholders Equity for a given ticker and year using yfinance."
            ),
        )

    async def execute(self, **kwargs) -> ToolResult:
        try:
            import pandas as pd  # noqa: F401
            import yfinance as yf

            raw_ticker = kwargs.get("ticker") or kwargs.get("corp")
            year_input = kwargs.get("year") or kwargs.get("years") or ""
            year_str: str = str(year_input).strip()
            min_year_input = kwargs.get("min_year")
            min_year: Optional[int] = None
            try:
                if min_year_input is not None:
                    min_year = int(str(min_year_input))
            except Exception:
                min_year = None

            if not raw_ticker or not str(raw_ticker).strip():
                return ToolResult(
                    success=False, result=None, error="'ticker' is required"
                )
            # If year is omitted, we'll use latest available below

            # Normalize ticker and try KR suffix heuristics if needed
            def normalize_ticker(input_symbol: str) -> List[str]:
                s = str(input_symbol).strip()
                candidates: List[str] = [s]
                # If 6-digit numeric (KR), try KS and KQ
                if s.isdigit() and len(s) == 6:
                    candidates = [f"{s}.KS", f"{s}.KQ", s]
                # Common KRX forms like 005930.KS already okay
                return candidates

            ticker_candidates = normalize_ticker(raw_ticker)

            # Attempt fetch with candidates until one returns data
            bs = None
            used_ticker: Optional[str] = None
            for cand in ticker_candidates:
                try:
                    ticker = yf.Ticker(cand)
                    tmp = ticker.balance_sheet
                    if tmp is not None and not tmp.empty:
                        bs = tmp
                        used_ticker = cand
                        break
                except Exception:
                    continue

            # Fallback to quarterly if annual empty
            if (bs is None or bs.empty) and ticker_candidates:
                for cand in ticker_candidates:
                    try:
                        ticker = yf.Ticker(cand)
                        tmp_q = ticker.quarterly_balance_sheet
                        if tmp_q is not None and not tmp_q.empty:
                            bs = tmp_q
                            used_ticker = cand
                            break
                    except Exception:
                        continue

            if bs is None or bs.empty or used_ticker is None:
                return ToolResult(
                    success=False,
                    result=None,
                    error="No balance sheet available for ticker",
                    metadata={"tried": ticker_candidates},
                )

            # Normalize columns to string in case they come as Period/Datetime
            bs.columns = [str(c) for c in bs.columns]

            # Find usable year: exact match or closest previous, else closest overall
            available_years: List[str] = list(bs.columns)

            def select_year(target_year: str, cols: List[str]) -> Tuple[str, List[str]]:
                # return (chosen_year, tried_years)
                tried: List[str] = []
                if target_year and target_year in cols:
                    return target_year, [target_year]
                # Try integer comparison
                try:
                    t = int(target_year)
                    numeric_cols = []
                    for c in cols:
                        try:
                            numeric_cols.append((c, int(c[:4])))
                        except Exception:
                            continue
                    # Prefer closest <= target
                    prev = [c for c, v in numeric_cols if v <= t]
                    if prev:
                        chosen = max(prev, key=lambda c: int(c[:4]))
                        tried = [target_year, chosen]
                        return chosen, tried
                    # Else closest overall by absolute distance
                    if numeric_cols:
                        chosen = min(numeric_cols, key=lambda x: abs(x[1] - t))[0]
                        tried = [target_year, chosen]
                        return chosen, tried
                except Exception:
                    pass
                # Fallback to first column
                return cols[0], [target_year, cols[0]]

            # Determine chosen year. Support year="latest" or omitted.
            import datetime as _dt

            current_year = _dt.datetime.now().year
            numeric_cols = []
            for c in available_years:
                try:
                    numeric_cols.append((c, int(c[:4])))
                except Exception:
                    continue

            def pick_latest(cols_numeric: List[Tuple[str, int]]) -> Optional[str]:
                # Respect current year, and optional min_year
                candidates = [c for c, y in cols_numeric if y <= current_year]
                if min_year is not None:
                    candidates = [c for c in candidates if int(c[:4]) >= min_year]
                if candidates:
                    return max(candidates, key=lambda c: int(c[:4]))
                # If min_year filtered all out, ignore min_year
                candidates = [c for c, y in cols_numeric if y <= current_year]
                if candidates:
                    return max(candidates, key=lambda c: int(c[:4]))
                return None

            if not year_str or year_str.lower() == "latest":
                latest = pick_latest(numeric_cols)
                if latest is None:
                    return ToolResult(
                        success=False,
                        result=None,
                        error="No usable year found in balance sheet columns",
                        metadata={"available_years": available_years},
                    )
                chosen_year = latest
                tried_years = [year_str or "latest", latest]
            else:
                chosen_year, tried_years = select_year(year_str, available_years)

            # Row label candidates for robustness
            asset_rows = [
                "Total Assets",
                "Total Assets Net Minority Interest",
                "Total Assets USD",
            ]
            liability_rows = [
                "Total Liabilities Net Minority Interest",
                "Total Liabilities",
                "Total Liabilities & Stockholders' Equity",
            ]
            equity_rows = [
                "Stockholders Equity",
                "Total Stockholder Equity",
                "Total Equity Gross Minority Interest",
                "Total Equity Net Minority Interest",
            ]

            def _safe_get_any(
                row_candidates: List[str], col: str
            ) -> Tuple[Optional[float], Optional[str]]:
                for row_name in row_candidates:
                    try:
                        val = bs.loc[row_name, col]
                        if hasattr(val, "iloc"):
                            return float(val.iloc[0]), row_name
                        return float(val), row_name
                    except Exception:
                        continue
                return None, None

            total_assets, assets_row_used = _safe_get_any(asset_rows, chosen_year)
            total_liabilities, liab_row_used = _safe_get_any(
                liability_rows, chosen_year
            )
            total_equity, equity_row_used = _safe_get_any(equity_rows, chosen_year)

            if (
                total_assets is None
                and total_liabilities is None
                and total_equity is None
            ):
                return ToolResult(
                    success=False,
                    result=None,
                    error="No balance sheet data found for given year/ticker",
                    metadata={
                        "ticker": used_ticker,
                        "requested_year": year_str or "latest",
                        "used_year": chosen_year,
                        "available_years": available_years,
                    },
                )

            return ToolResult(
                success=True,
                result={
                    "ticker": used_ticker,
                    "requested_year": year_str or "latest",
                    "year": chosen_year,
                    "total_assets": total_assets,
                    "total_liabilities": total_liabilities,
                    "total_equity": total_equity,
                },
                error=None,
                metadata={
                    "source": "yfinance",
                    "assets_row": assets_row_used,
                    "liabilities_row": liab_row_used,
                    "equity_row": equity_row_used,
                    "available_years": available_years,
                    "year_selection": tried_years,
                },
            )
        except Exception as e:
            return ToolResult(
                success=False, 
                result=None, 
                error=str(e),
                metadata={}
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
