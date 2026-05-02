from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class StatementField:
    canonical: str
    aliases: tuple[str, ...]
    statement: str


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

# 분석 지표. 각 항목은 (이름, 입력 키들, 공식). 공식은 입력값을 받아 결과를 반환.
# raw 재무제표 라인을 조합해 만드는 분석용 지표이며, raw가 우선이다 — 응답에 이미
# 같은 이름의 라인이 들어와 있으면 계산하지 않는다.
Metric = tuple[str, tuple[str, ...], Callable[..., float]]

METRICS: tuple[Metric, ...] = (
    ("gross_margin", ("gross_profit", "total_revenue"), lambda g, r: g / r),
    ("operating_margin", ("operating_income", "total_revenue"), lambda o, r: o / r),
    ("net_margin", ("net_income", "total_revenue"), lambda n, r: n / r),
    ("debt_to_equity", ("total_liabilities", "total_equity"), lambda li, eq: li / eq),
    ("current_ratio", ("current_assets", "current_liabilities"), lambda ca, cl: ca / cl),
    ("interest_coverage", ("operating_income", "interest_expense"), lambda op, ie: op / abs(ie)),
    ("effective_tax_rate", ("tax_expense", "net_income"), lambda tx, ni: tx / (ni + tx)),
    ("ebitda", ("operating_income", "depreciation", "amortization"), lambda op, dp, am: op + dp + am),
    ("total_debt", ("short_term_debt", "long_term_debt"), lambda st, lt: st + lt),
    ("net_debt", ("total_debt", "cash_and_equivalents"), lambda td, cs: td - cs),
    ("working_capital", ("current_assets", "current_liabilities"), lambda ca, cl: ca - cl),
    ("free_cash_flow", ("operating_cash_flow", "capex"), lambda o, c: o - c),
    (
        "total_shareholder_return",
        ("dividends_paid", "share_buyback"),
        lambda d, b: abs(d) + abs(b),
    ),
    ("per", ("current_price", "eps"), lambda p, e: p / e),
    ("pbr", ("current_price", "bps"), lambda p, b: p / b),
)


def compute_metrics(raw: dict[str, Any]) -> dict[str, Any]:
    """raw 재무제표 라인에 분석 지표를 추가한 새 dict를 반환. raw가 우선."""
    result = dict(raw)
    for name, keys, formula in METRICS:
        if result.get(name) is not None:
            continue
        values = [result.get(k) for k in keys]
        if any(v is None for v in values):
            continue
        try:
            result[name] = formula(*values)
        except ZeroDivisionError:
            continue
    return result

VALUATION_INFO_KEYS: tuple[tuple[str, str], ...] = (
    ("market_cap", "marketCap"),
    ("current_price", "currentPrice"),
    ("per", "trailingPE"),
    ("pbr", "priceToBook"),
    ("enterprise_value", "enterpriseValue"),
    ("currency", "currency"),
)

# OpenDART 응답의 sj_div 코드. 같은 account_id가 BS/CIS/CF/SCE 여러 곳에 등장할 수
# 있어(예: ifrs-full_ProfitLoss는 CIS·CF·SCE 모두에 출현), statement 필터 없이는
# 마지막 값으로 덮어씌워져 0이 들어가는 회귀가 발생한다. 매핑은 항상 (코드, sj_div)로 한다.
OPENDART_SJ_BS = "BS"
OPENDART_SJ_CIS = "CIS"
OPENDART_SJ_CF = "CF"

# account_id(K-IFRS element id)를 1차 키로 사용한다.
# `ifrs-full_*`는 IFRS 표준, `dart_*`는 한국 GAAP 확장.
OPENDART_ACCOUNT_ID_MAP: dict[tuple[str, str], str] = {
    # Balance Sheet
    ("ifrs-full_Assets", OPENDART_SJ_BS): "total_assets",
    ("ifrs-full_CurrentAssets", OPENDART_SJ_BS): "current_assets",
    ("ifrs-full_CashAndCashEquivalents", OPENDART_SJ_BS): "cash_and_equivalents",
    ("ifrs-full_Liabilities", OPENDART_SJ_BS): "total_liabilities",
    ("ifrs-full_CurrentLiabilities", OPENDART_SJ_BS): "current_liabilities",
    ("dart_LongTermBorrowingsGross", OPENDART_SJ_BS): "long_term_debt",
    ("ifrs-full_ShorttermBorrowings", OPENDART_SJ_BS): "short_term_debt",
    ("ifrs-full_Equity", OPENDART_SJ_BS): "total_equity",
    ("ifrs-full_RetainedEarnings", OPENDART_SJ_BS): "retained_earnings",
    # Income Statement
    ("ifrs-full_Revenue", OPENDART_SJ_CIS): "total_revenue",
    ("ifrs-full_CostOfSales", OPENDART_SJ_CIS): "cost_of_revenue",
    ("ifrs-full_GrossProfit", OPENDART_SJ_CIS): "gross_profit",
    ("dart_TotalSellingGeneralAdministrativeExpenses", OPENDART_SJ_CIS): "sga_expense",
    ("dart_OperatingIncomeLoss", OPENDART_SJ_CIS): "operating_income",
    ("ifrs-full_FinanceCosts", OPENDART_SJ_CIS): "interest_expense",
    ("ifrs-full_IncomeTaxExpenseContinuingOperations", OPENDART_SJ_CIS): "tax_expense",
    ("ifrs-full_ProfitLoss", OPENDART_SJ_CIS): "net_income",
    ("ifrs-full_BasicEarningsLossPerShare", OPENDART_SJ_CIS): "eps",
    # Cash Flow
    (
        "ifrs-full_CashFlowsFromUsedInOperatingActivities",
        OPENDART_SJ_CF,
    ): "operating_cash_flow",
    (
        "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        OPENDART_SJ_CF,
    ): "capex",
    (
        "ifrs-full_DividendsPaidClassifiedAsFinancingActivities",
        OPENDART_SJ_CF,
    ): "dividends_paid",
}

# account_id가 비었거나 `-표준계정코드 미사용-` sentinel, 또는 회사 커스텀 코드인 경우
# account_nm으로 fallback 매핑한다. K-IFRS Taxonomy로 표현되지 않는 한국 GAAP 특화
# 항목에만 필요하다. nm도 statement에 따라 다른 의미일 수 있어 (nm, sj_div) 키를 쓴다.
OPENDART_ACCOUNT_NM_MAP: dict[tuple[str, str], str] = {
    ("매출액", OPENDART_SJ_CIS): "total_revenue",
    ("주당순자산", OPENDART_SJ_CIS): "bps",
    ("영업활동으로인한현금흐름", OPENDART_SJ_CF): "operating_cash_flow",
    ("유형자산의취득", OPENDART_SJ_CF): "capex",
    ("자기주식의취득", OPENDART_SJ_CF): "share_buyback",
    ("감가상각비", OPENDART_SJ_CF): "depreciation",
    ("무형자산상각비", OPENDART_SJ_CF): "amortization",
}
