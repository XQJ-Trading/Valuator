from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StatementField:
    canonical: str
    aliases: tuple[str, ...]
    statement: str


@dataclass(frozen=True, slots=True)
class DerivedMetric:
    name: str
    numerator: str
    denominator: str
    abs_denominator: bool = False


@dataclass(frozen=True, slots=True)
class DerivedDifference:
    name: str
    minuend: str
    subtrahend: str


STATEMENT_FIELDS: tuple[StatementField, ...] = (
    StatementField(
        "total_assets",
        ("Total Assets", "Total Assets Net Minority Interest", "Total Assets USD"),
        "balance_sheet",
    ),
    StatementField(
        "total_liabilities",
        (
            "Total Liabilities Net Minority Interest",
            "Total Liabilities",
            "Total Liabilities & Stockholders' Equity",
        ),
        "balance_sheet",
    ),
    StatementField(
        "total_equity",
        (
            "Stockholders Equity",
            "Total Stockholder Equity",
            "Total Equity Gross Minority Interest",
            "Total Equity Net Minority Interest",
        ),
        "balance_sheet",
    ),
    StatementField(
        "current_assets",
        ("Total Current Assets", "Current Assets", "Total Current Assets USD"),
        "balance_sheet",
    ),
    StatementField(
        "current_liabilities",
        (
            "Total Current Liabilities",
            "Current Liabilities",
            "Total Current Liabilities USD",
        ),
        "balance_sheet",
    ),
    StatementField(
        "operating_income",
        ("Operating Income", "Operating Income or Loss"),
        "income",
    ),
    StatementField(
        "interest_expense",
        ("Interest Expense", "Interest Expense and Debt", "Interest Expense, Net"),
        "income",
    ),
    StatementField(
        "operating_cash_flow",
        (
            "Total Cash From Operating Activities",
            "Cash Flow From Continuing Operating Activities",
        ),
        "cash_flow",
    ),
    StatementField(
        "capex",
        ("Capital Expenditures", "Capital Expenditure"),
        "cash_flow",
    ),
)

DERIVED_RATIOS: tuple[DerivedMetric, ...] = (
    DerivedMetric("debt_to_equity", "total_liabilities", "total_equity"),
    DerivedMetric("current_ratio", "current_assets", "current_liabilities"),
    DerivedMetric(
        "interest_coverage",
        "operating_income",
        "interest_expense",
        abs_denominator=True,
    ),
)

DERIVED_DIFFERENCES: tuple[DerivedDifference, ...] = (
    DerivedDifference("free_cash_flow", "operating_cash_flow", "capex"),
)

VALUATION_INFO_KEYS: tuple[tuple[str, str], ...] = (
    ("market_cap", "marketCap"),
    ("current_price", "currentPrice"),
    ("trailing_pe", "trailingPE"),
    ("forward_pe", "forwardPE"),
    ("price_to_book", "priceToBook"),
    ("enterprise_value", "enterpriseValue"),
    ("currency", "currency"),
)
