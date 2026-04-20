"""Ontology-grounded Fact types for the shared state layer.

FactAddress locates a fact on the ontology coordinate system:
(node_type, subject, property_key, period).

FactValue constrains the payload to a closed union, eliminating ``Any``.

The metric registry maps free-form LLM output strings to canonical
``property_key`` values so that the boundary parser can normalise them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# FactAddress — ontology coordinate
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FactAddress:
    """Ontology coordinate that identifies *what* a fact is about."""

    node_type: str
    """NodeDefinition name: Company, FinancialStatements, Indicator, …"""

    subject: str
    """Primary key value: corp name, stock code, event id, …"""

    property_key: str
    """Canonical property key from the ontology (e.g. ``revenue``)."""

    period: str = ""
    """Temporal qualifier: ``2024``, ``2024Q1``, ``2025-01-01``, …"""

    @property
    def canonical_key(self) -> str:
        parts = [self.node_type, self.subject, self.property_key]
        if self.period:
            parts.append(self.period)
        return ":".join(parts)


# ---------------------------------------------------------------------------
# FactValue — closed union replacing ``Any``
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NumericValue:
    amount: float
    unit: str = ""  # KRW, USD, %, ratio, shares, …

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NumericValue):
            return NotImplemented
        return self.amount == other.amount and self.unit == other.unit


@dataclass(frozen=True)
class TextValue:
    text: str

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TextValue):
            return NotImplemented
        return self.text == other.text


FactValue = Union[NumericValue, TextValue]


# ---------------------------------------------------------------------------
# Metric registry — canonical key → aliases
# ---------------------------------------------------------------------------
# The *key* is the canonical ``property_key`` stored in FactAddress.
# The *value* tuple lists every known alias the LLM might produce.
# Lookup is case-insensitive; underscores, spaces, and hyphens are stripped
# before comparison (see ``resolve_property_key``).

_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    # ── FinancialStatements ──────────────────────────────────────────
    "revenue": (
        "Revenue", "매출", "매출액", "total_revenue", "TotalRevenue",
        "Total Revenues", "sales", "매출(2025)", "annual_revenue",
        "quarterly_revenue",
    ),
    "operating_income": (
        "Operating Income", "영업이익", "OperatingProfit", "OP",
        "operating_profit", "Operating_Income", "Operating_Profit",
        "Profit from Business Activities", "annual_operating_income",
        "quarterly_operating_income",
    ),
    "net_income": (
        "Net Income", "당기��이익", "NetIncome", "Net_Income",
        "net income", "Net Profit", "지배주주순이익",
        "Profit Attributable to Owners",
        "Profit Attributable to Owners of Parent",
        "Net Profit (Attributable to Shareholders)",
        "Attributable to owners",
    ),
    "gross_profit": (
        "Gross Profit", "매출총이익", "GrossProfit", "gross profit",
        "gross_profit",
    ),
    "ebitda": (
        "EBITDA", "ebitda",
    ),
    "total_assets": (
        "Total Assets", "자산총계", "TotalAssets", "total assets",
        "total_assets",
    ),
    "total_liabilities": (
        "Total Liabilities", "부채총계", "TotalLiabilities",
        "total liabilities", "total_liabilities",
        "Total Liabilities (Current)",
    ),
    "total_equity": (
        "Total Equity", "자본총계", "TotalEquity", "total equity",
        "total_equity", "Total Liabilities & Equity",
    ),
    "capital_stock": (
        "자본금",
    ),
    "cost_of_revenue": (
        "CostOfRevenue", "cost of revenue", "cost_of_revenue",
        "Cost_of_Revenues",
    ),
    "sga_expense": (
        "SGAExpense", "SgaExpense", "sga expense", "sga_expense", "판관비",
        "G&A_Expenses",
    ),
    "retained_earnings": (
        "retained earnings", "retained_earnings",
    ),
    "current_assets": (
        "CurrentAssets", "current assets", "current_assets", "유동자산",
    ),
    "current_liabilities": (
        "CurrentLiabilities", "current liabilities", "current_liabilities",
        "유동부채",
    ),
    "cash_and_equivalents": (
        "CashAndEquivalents", "cash and equivalents", "cash_and_equivalents",
        "현금및현금성자산",
    ),
    "operating_cash_flow": (
        "OperatingCashFlow", "영업활동현금흐름", "operating_cash_flow",
        "영업활동현���흐름(OCF)",
        "Net Cash from Operating Activities",
    ),
    "dividends_paid": (
        "DividendsPaid", "배당금지급", "Dividend per Share",
    ),
    "tax_expense": (
        "tax expense",
    ),
    "long_term_debt": (
        "long_term_debt",
    ),
    "total_debt": (
        "Total Debt", "total_debt",
    ),
    "working_capital": (
        "working capital", "working_capital",
    ),

    # ── Indicator (derived) ──────────────────────────────────────────
    "eps": ("EPS",),
    "per": ("PER", "P/E", "P/E Ratio", "Forward_PE",),
    "pbr": ("PBR", "P/B", "P/B Ratio",),
    "bps": ("BPS",),
    "roe": ("ROE",),
    "roa": ("ROA",),
    "roic": ("ROIC",),
    "ev_ebitda": (
        "EV/EBITDA", "EV_EBITDA", "EV/EBIT", "Forward_EV_EBITDA",
        "Valuation_EV/EBITDA", "TargetEV_EBITDA",
    ),
    "ev_revenue": ("EV/Revenue",),
    "ev_fcf": ("EV/FCF",),
    "ps_ratio": ("P/S", "P/S Ratio (LTM)",),
    "current_ratio": (
        "CurrentRatio", "current ratio", "current_ratio",
    ),
    "debt_to_equity": (
        "DebtToEquity", "debt to equity", "debt_to_equity",
        "debt_to_equity_ratio", "부채비율",
    ),
    "debt_ratio": (
        "Debt Ratio", "Debt_Ratio", "debt_ratio",
    ),
    "net_debt": (
        "Net Debt", "NetDebt", "net_debt", "순부채", "순차입금",
    ),
    "net_debt_ratio": (
        "NetDebtRatio", "net_debt_ratio",
    ),
    "operating_margin": (
        "OPM", "operating_margin", "영업이익률", "Operating_Profit_Growth",
        "영업이익률(2025)", "annual_operating_margin",
        "quarterly_operating_margin", "net_margin", "net margin",
        "Net_Profit_Margin", "Net Profit Margin",
    ),
    "ebitda_margin": (
        "EBITDA Margin", "EBITDA Margin Projection",
    ),
    "gross_margin": (
        "gross_margin", "gross margin",
    ),
    "revenue_growth": (
        "Revenue Growth Rate", "매출성장률", "Revenue_Growth",
        "Revenue_Growth_Rate", "Revenue_Growth_Forecast",
        "Revenue_Growth_Guidance", "매출성장률전망", "revenue_growth_YoY",
    ),
    "earnings_growth": (
        "Earnings", "EPS_Growth_Rate", "영업이익성장률",
        "Operating_Profit_Growth_Forecast",
    ),

    # ── StockPrice ──────────────────────────────────────��────────────
    "stock_price": (
        "Stock Price", "stock_price", "주가", "current_price",
        "Share Price Date",
    ),
    "market_cap": (
        "MarketCap", "시가총액", "시가총액(조 원)", "market_cap_t",
        "market_cap_usd_b",
    ),
    "trading_volume": (
        "trading_volume",
    ),
    "52_week_range": (
        "52_week_range",
    ),
    "target_price": (
        "목표주가", "target_price", "analyst_target_price_avg",
        "Average 12-Month Target Price",
    ),
    "support_price": (
        "Support Price", "Support_Price_Lower", "Support_Price_Upper",
    ),
    "resistance_price": (
        "Resistance Price", "Resistance_Price_Lower",
        "Resistance_Price_Upper",
    ),

    # ── Company (qualitative / metadata) ─────────────────────────────
    "backlog": (
        "Backlog", "backlog", "수주잔고", "Order Backlog",
        "수주잔고_총액", "수주잔고_합계", "전체_수주잔고", "Total_Backlog",
    ),
    "order_intake": (
        "Order Intake", "수주가시성", "Order_Guidance",
    ),
    "business_overview": (
        "Business Overview", "business_model", "company_overview",
    ),
    "competitive_dynamics": (
        "Competitive_Dynamics", "competitive_dynamics",
        "competitive_advantage_source", "competitive_impact",
        "경쟁 우위", "경쟁사",
    ),
    "risk_factors": (
        "Risk Factors", "key_risk_factors", "major_risks",
    ),
    "investment_opinion": (
        "InvestmentOpinion", "investment_stance", "investment_rating",
        "recommendation", "analyst_recommendation", "투자판단",
    ),
    "valuation_summary": (
        "ValuationMetrics", "valuation_summary", "valuation_current",
        "peer_valuation", "relative_valuation_summary",
    ),
    "shares_outstanding": (
        "shares_outstanding",
    ),
    "employees": (
        "Employees",
    ),
}


# ---------------------------------------------------------------------------
# Reverse index: alias → canonical key (built once at import time)
# ---------------------------------------------------------------------------

def _normalise(s: str) -> str:
    """Strip casing, underscores, spaces, hyphens for fuzzy matching."""
    return s.lower().replace("_", "").replace(" ", "").replace("-", "")


_ALIAS_INDEX: dict[str, str] = {}


def _build_alias_index() -> None:
    for canonical, aliases in _METRIC_ALIASES.items():
        norm = _normalise(canonical)
        if norm not in _ALIAS_INDEX:
            _ALIAS_INDEX[norm] = canonical
        for alias in aliases:
            norm_alias = _normalise(alias)
            if norm_alias not in _ALIAS_INDEX:
                _ALIAS_INDEX[norm_alias] = canonical


_build_alias_index()


def resolve_property_key(raw: str) -> str | None:
    """Return the canonical property_key for *raw*, or ``None`` if unknown."""
    return _ALIAS_INDEX.get(_normalise(raw))


# ---------------------------------------------------------------------------
# Node type inference from property key
# ---------------------------------------------------------------------------

_FINANCIAL_STATEMENT_KEYS = frozenset({
    "revenue", "operating_income", "net_income", "gross_profit", "ebitda",
    "total_assets", "total_liabilities", "total_equity", "capital_stock",
    "cost_of_revenue", "sga_expense", "retained_earnings",
    "current_assets", "current_liabilities", "cash_and_equivalents",
    "operating_cash_flow", "dividends_paid", "tax_expense",
    "long_term_debt", "total_debt", "working_capital",
})

_INDICATOR_KEYS = frozenset({
    "eps", "per", "pbr", "bps", "roe", "roa", "roic",
    "ev_ebitda", "ev_revenue", "ev_fcf", "ps_ratio",
    "current_ratio", "debt_to_equity", "debt_ratio",
    "net_debt", "net_debt_ratio",
    "operating_margin", "ebitda_margin", "gross_margin",
    "revenue_growth", "earnings_growth",
})

_STOCK_PRICE_KEYS = frozenset({
    "stock_price", "market_cap", "trading_volume", "52_week_range",
    "target_price", "support_price", "resistance_price",
})

_COMPANY_KEYS = frozenset({
    "backlog", "order_intake", "business_overview",
    "competitive_dynamics", "risk_factors",
    "investment_opinion", "valuation_summary",
    "shares_outstanding", "employees",
})


def infer_node_type(property_key: str) -> str:
    """Infer the ontology node type from a canonical property key."""
    if property_key in _FINANCIAL_STATEMENT_KEYS:
        return "FinancialStatements"
    if property_key in _INDICATOR_KEYS:
        return "Indicator"
    if property_key in _STOCK_PRICE_KEYS:
        return "StockPrice"
    if property_key in _COMPANY_KEYS:
        return "Company"
    return "Observation"


# ---------------------------------------------------------------------------
# Boundary: raw LLM key/value → FactAddress + FactValue
# ---------------------------------------------------------------------------

import re  # noqa: E402 — intentionally placed after constants

_KEY_SPLIT_RE = re.compile(r"[:/]")
_PERIOD_RE = re.compile(
    r"^(?:\d{4}(?:Q[1-4])?(?:FY)?|FY\d{4}|\d{4}-\d{2}(?:-\d{2})?)$",
    re.IGNORECASE,
)


def _looks_like_period(token: str) -> bool:
    return bool(_PERIOD_RE.match(token.strip()))


def _extract_numeric(raw: object) -> float | None:
    """Try to read a number from various raw shapes."""
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        cleaned = raw.replace(",", "").replace("원", "").replace("조", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def parse_raw_fact_key(raw_key: str) -> tuple[str, str, str]:
    """Parse a free-form LLM fact key into ``(subject, metric_hint, period)``.

    Handles patterns like:
    - ``SK하이닉스:Revenue:2024``
    - ``042660:total_revenue:2023``
    - ``Fincantieri:Adjusted Net Profit:2024``
    - ``목표주가`` (single token → subject="", metric_hint=raw_key)
    """
    tokens = [t.strip() for t in _KEY_SPLIT_RE.split(raw_key) if t.strip()]
    if len(tokens) >= 3:
        # last token might be period
        if _looks_like_period(tokens[-1]):
            subject = tokens[0]
            metric_hint = ":".join(tokens[1:-1])
            period = tokens[-1]
            return subject, metric_hint, period
        # no period at end
        subject = tokens[0]
        metric_hint = ":".join(tokens[1:])
        return subject, metric_hint, ""
    if len(tokens) == 2:
        if _looks_like_period(tokens[-1]):
            return "", tokens[0], tokens[1]
        return tokens[0], tokens[1], ""
    # single token
    return "", raw_key, ""


def _extract_fact_payload(
    raw_value: object,
) -> tuple[object, bool, tuple[str, ...], int | None]:
    """Extract value/grounded/source metadata from raw LLM fact value.

    LLM may emit either a plain value or a dict with ``value``, ``grounded``,
    ``source_urls``, ``source_tier`` keys (boundary normalisation).
    """
    if isinstance(raw_value, dict) and "value" in raw_value:
        grounded = bool(raw_value.get("grounded", False))
        raw_urls = raw_value.get("source_urls") or ()
        source_urls = tuple(
            str(item).strip() for item in raw_urls if str(item).strip()
        )
        source_tier: int | None = None
        raw_source_tier = raw_value.get("source_tier")
        if raw_source_tier not in (None, ""):
            try:
                source_tier = int(raw_source_tier)
            except (TypeError, ValueError):
                source_tier = None
        return raw_value["value"], grounded, source_urls, source_tier
    return raw_value, False, (), None


_SOURCE_TIER_HINTS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (5, (".gov", "dart", "edgar", "filing")),
    (4, ("krx", "nasdaq", "nyse", "exchange")),
    (3, ("investor", "/ir")),
    (1, ("research", "securities", "broker")),
    (0, ("forum", "community", "reddit", "stocktwits", "blog", "cafe")),
)


def classify_source_urls(source_urls: tuple[str, ...]) -> int:
    best_rank = -1
    for raw_url in source_urls:
        parsed = urlparse(raw_url)
        haystack = f"{parsed.netloc.lower()}{parsed.path.lower()}"
        if not haystack:
            continue
        rank = 2
        for candidate_rank, hints in _SOURCE_TIER_HINTS:
            if any(hint in haystack for hint in hints):
                rank = candidate_rank
                break
        if rank > best_rank:
            best_rank = rank
    return best_rank


def parse_raw_fact(
    raw_key: str,
    raw_value: object,
    *,
    source_task_id: str,
    query_unit_ids: tuple[int, ...] = (),
    as_of_kst: str = "",
) -> "Fact":  # noqa: F821 — lazy import to avoid circular dependency
    """Boundary function: convert free-form LLM fact → domain ``Fact``.

    This is the single point where raw LLM output crosses into the typed
    domain.  Unknown metrics pass through with ``property_key`` set to the
    normalised hint and ``node_type`` defaulting to ``Observation``.
    """
    # lazy import to avoid circular dependency
    from .shared_state import Fact

    subject, metric_hint, period = parse_raw_fact_key(raw_key)
    inner_value, grounded, source_urls, source_tier = _extract_fact_payload(raw_value)
    if source_tier is None:
        source_tier = classify_source_urls(source_urls)

    canonical = resolve_property_key(metric_hint)
    if canonical is None:
        # unknown metric — preserve as-is in Observation
        property_key = _normalise(metric_hint) or metric_hint
        node_type = "Observation"
    else:
        property_key = canonical
        node_type = infer_node_type(canonical)

    address = FactAddress(
        node_type=node_type,
        subject=subject,
        property_key=property_key,
        period=period,
    )

    numeric = _extract_numeric(inner_value)
    if numeric is not None:
        fact_value: FactValue = NumericValue(amount=numeric)
    else:
        fact_value = TextValue(text=str(inner_value) if inner_value is not None else "")

    return Fact(
        address=address,
        value=fact_value,
        source_task_id=source_task_id,
        query_unit_ids=query_unit_ids,
        grounded=grounded,
        as_of_kst=as_of_kst,
        source_urls=source_urls,
        source_tier=source_tier,
    )
