from __future__ import annotations

from domain.company import Company, Listing, Subject
from domain.query import QueryAnalysis, QueryIntent, fill_routing_defaults


def _subject(*, company_name: str, security_code: str, exchange: str) -> Subject:
    listing_id = f"{exchange}:{security_code}"
    company = Company(
        company_id=listing_id,
        company_name=company_name,
        aliases=(security_code,),
    )
    listing = Listing(
        listing_id=listing_id,
        company_id=listing_id,
        security_code=security_code,
        exchange=exchange,
        vendor_symbols={"yahoo": security_code},
    )
    return Subject(company=company, listing=listing)


def test_fill_routing_defaults_prefers_opendart_for_krx_subjects() -> None:
    analysis = QueryAnalysis(
        query_intent=QueryIntent(
            query="삼성전자 분석",
            subjects=(
                _subject(
                    company_name="삼성전자",
                    security_code="005930",
                    exchange="KOSPI",
                ),
            ),
        )
    )

    fill_routing_defaults(analysis, {})

    assert analysis.allowed_tools == [
        "web_search_tool",
        "opendart_tool",
        "code_execute_tool",
    ]


def test_fill_routing_defaults_prefers_yfinance_for_usa_subjects() -> None:
    analysis = QueryAnalysis(
        query_intent=QueryIntent(
            query="Apple analysis",
            subjects=(
                _subject(
                    company_name="Apple Inc.",
                    security_code="AAPL",
                    exchange="USA",
                ),
            ),
        )
    )

    fill_routing_defaults(analysis, {})

    assert analysis.allowed_tools == [
        "web_search_tool",
        "yfinance_balance_sheet",
        "sec_tool",
        "code_execute_tool",
    ]


def test_fill_routing_defaults_keeps_both_for_mixed_markets() -> None:
    analysis = QueryAnalysis(
        query_intent=QueryIntent(
            query="삼성전자와 Apple 비교",
            subjects=(
                _subject(
                    company_name="삼성전자",
                    security_code="005930",
                    exchange="KOSPI",
                ),
                _subject(
                    company_name="Apple Inc.",
                    security_code="AAPL",
                    exchange="USA",
                ),
            ),
        )
    )

    fill_routing_defaults(analysis, {})

    assert analysis.allowed_tools == [
        "web_search_tool",
        "opendart_tool",
        "sec_tool",
        "yfinance_balance_sheet",
        "code_execute_tool",
    ]
