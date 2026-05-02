"""Ontology — domain metric schema for structured task output.

Defines property keys that tasks use when reporting quantitative
findings.  The ontology is injected into LLM prompts as an output format
guide so that tasks produce consistently-keyed metrics.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PropertyDef:
    """A single metric definition."""

    key: str
    category: str  # "financial", "indicator", "price", "qualitative"
    value_type: str  # "numeric" | "text"
    unit_hint: str = ""
    input_keys: tuple[str, ...] = ()


# ─── Metric Registry ───────────────────────────────────────────────────────────
# Extend by adding a single PropertyDef line.

PROPERTIES: tuple[PropertyDef, ...] = (
    # Financial Statements
    PropertyDef(
        "revenue",
        "financial",
        "numeric",
        "KRW",
        input_keys=("total_revenue",),
    ),
    PropertyDef("operating_income", "financial", "numeric", "KRW"),
    PropertyDef("net_income", "financial", "numeric", "KRW"),
    PropertyDef("gross_profit", "financial", "numeric", "KRW"),
    PropertyDef("ebitda", "financial", "numeric", "KRW"),
    PropertyDef("total_assets", "financial", "numeric", "KRW"),
    PropertyDef("total_liabilities", "financial", "numeric", "KRW"),
    PropertyDef("total_equity", "financial", "numeric", "KRW"),
    PropertyDef("cost_of_revenue", "financial", "numeric", "KRW"),
    PropertyDef("sga_expense", "financial", "numeric", "KRW"),
    PropertyDef("current_assets", "financial", "numeric", "KRW"),
    PropertyDef("current_liabilities", "financial", "numeric", "KRW"),
    PropertyDef("cash_and_equivalents", "financial", "numeric", "KRW"),
    PropertyDef("operating_cash_flow", "financial", "numeric", "KRW"),
    PropertyDef("dividends_paid", "financial", "numeric", "KRW"),
    PropertyDef("long_term_debt", "financial", "numeric", "KRW"),
    PropertyDef("total_debt", "financial", "numeric", "KRW"),
    PropertyDef("working_capital", "financial", "numeric", "KRW"),
    # Indicators (derived)
    PropertyDef("eps", "indicator", "numeric", "KRW"),
    PropertyDef("per", "indicator", "numeric", "배"),
    PropertyDef("pbr", "indicator", "numeric", "배"),
    PropertyDef("bps", "indicator", "numeric", "KRW"),
    PropertyDef("roe", "indicator", "numeric", "%"),
    PropertyDef("roa", "indicator", "numeric", "%"),
    PropertyDef("roic", "indicator", "numeric", "%"),
    PropertyDef("ev_ebitda", "indicator", "numeric", "배"),
    PropertyDef("ev_revenue", "indicator", "numeric", "배"),
    PropertyDef("ev_fcf", "indicator", "numeric", "배"),
    PropertyDef("ps_ratio", "indicator", "numeric", "배"),
    PropertyDef("current_ratio", "indicator", "numeric", "배"),
    PropertyDef("debt_to_equity", "indicator", "numeric", "%"),
    PropertyDef("net_debt", "indicator", "numeric", "KRW"),
    PropertyDef("operating_margin", "indicator", "numeric", "%"),
    PropertyDef("ebitda_margin", "indicator", "numeric", "%"),
    PropertyDef("gross_margin", "indicator", "numeric", "%"),
    PropertyDef("revenue_growth", "indicator", "numeric", "%"),
    PropertyDef("earnings_growth", "indicator", "numeric", "%"),
    PropertyDef("net_margin", "indicator", "numeric", "%"),
    # Stock Price
    PropertyDef(
        "stock_price",
        "price",
        "numeric",
        "KRW",
        input_keys=("current_price",),
    ),
    PropertyDef("price_open", "price", "numeric", "KRW"),
    PropertyDef("price_high", "price", "numeric", "KRW"),
    PropertyDef("price_low", "price", "numeric", "KRW"),
    PropertyDef("volume", "price", "numeric", "주"),
    PropertyDef("market_cap", "price", "numeric", "KRW"),
    PropertyDef("target_price", "price", "numeric", "KRW"),
    # Qualitative / Company
    PropertyDef("backlog", "qualitative", "numeric", "KRW"),
    PropertyDef("order_intake", "qualitative", "numeric", "KRW"),
    PropertyDef("business_overview", "qualitative", "text"),
    PropertyDef("competitive_dynamics", "qualitative", "text"),
    PropertyDef("risk_factors", "qualitative", "text"),
    PropertyDef("investment_opinion", "qualitative", "text"),
    PropertyDef("valuation_summary", "qualitative", "text"),
)

# ─── Result-Key Lookup ────────────────────────────────────────────────────────

def _build_result_key_lookup(properties: tuple[PropertyDef, ...]) -> dict[str, str]:
    property_keys = {p.key for p in properties}
    result_key_to_property_key = {p.key: p.key for p in properties}

    for prop in properties:
        for input_key in prop.input_keys:
            if input_key in property_keys:
                raise ValueError(
                    f"input key {input_key!r} collides with ontology property key"
                )
            existing = result_key_to_property_key.get(input_key)
            if existing is not None and existing != prop.key:
                raise ValueError(
                    f"input key {input_key!r} maps to both {existing!r} and {prop.key!r}"
                )
            result_key_to_property_key[input_key] = prop.key
    return result_key_to_property_key


PROPERTY_KEY_BY_RESULT_KEY: dict[str, str] = _build_result_key_lookup(PROPERTIES)


def schema_for_prompt() -> str:
    """Ontology guide to inject into LLM prompts for structured output."""
    lines = [
        "facts의 key는 '{subject}:{property_key}:{period}' 형식으로 작성하라.",
        "period는 '2024', '2024Q1', '2025-01' 등 시점을 나타낸다.",
        "사용 가능한 property_key:",
    ]
    by_category: dict[str, list[PropertyDef]] = {}
    for p in PROPERTIES:
        by_category.setdefault(p.category, []).append(p)
    for category, props in by_category.items():
        keys = ", ".join(p.key for p in props)
        lines.append(f"  [{category}] {keys}")
    lines.append("목록에 없는 지표도 자유 형식으로 사용 가능하다.")
    return "\n".join(lines)
