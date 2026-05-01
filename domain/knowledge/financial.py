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
        "total_revenue",
        ("Total Revenue", "Total Revenue USD"),
        "income",
    ),
    StatementField(
        "gross_profit",
        ("Gross Profit",),
        "income",
    ),
    StatementField(
        "net_income",
        ("Net Income Common Stockholders", "Net Income"),
        "income",
    ),
    StatementField(
        "ebitda",
        ("EBITDA", "Normalized EBITDA"),
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
    DerivedMetric("gross_margin", "gross_profit", "total_revenue"),
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

OPENDART_ACCOUNT_MAP: dict[str, str] = {
    # Balance Sheet
    "자산총계": "total_assets",
    "유동자산": "current_assets",
    "현금및현금성자산": "cash_and_equivalents",
    "부채총계": "total_liabilities",
    "유동부채": "current_liabilities",
    "장기차입금": "long_term_debt",
    "단기차입금": "short_term_debt",
    "자본총계": "total_equity",
    "이익잉여금": "retained_earnings",
    # Income Statement
    "매출액": "total_revenue",
    "수익(매출액)": "total_revenue",
    "매출원가": "cost_of_revenue",
    "매출총이익": "gross_profit",
    "판매비와관리비": "sga_expense",
    "영업이익": "operating_income",
    "영업이익(손실)": "operating_income",
    "영업손익": "operating_income",
    "영업손익(손실)": "operating_income",
    "이자비용": "interest_expense",
    "법인세비용": "tax_expense",
    "당기순이익": "net_income",
    "기본주당이익": "eps_basic",
    "주당순자산": "bps",
    # Cash Flow
    "영업활동현금흐름": "operating_cash_flow",
    "영업활동으로인한현금흐름": "operating_cash_flow",
    "유형자산의취득": "capex",
    "배당금의지급": "dividends_paid",
    "배당금지급": "dividends_paid",
    "자기주식의취득": "share_buyback",
    "감가상각비": "depreciation",
    "무형자산상각비": "amortization",
}
