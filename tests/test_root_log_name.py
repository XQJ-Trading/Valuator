"""Session folder basename: {yyyymmdd}-{HHMM}-{company name or query slug}."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from domain.company import Company, Listing, Subject
from domain.query import QueryAnalysis, QueryIntent, QueryUnit

from valuator.session.root_log_name import build_unique_root_session_id
from valuator.utils.time_utils import KST


def _analysis_with_subject(subject: Subject | None) -> QueryAnalysis:
    subjects = (subject,) if subject is not None else ()
    return QueryAnalysis(
        query_intent=QueryIntent(query="q", subjects=subjects),
    )


def test_segment_prefers_unit_entity_label_over_subject_order(tmp_path: Path) -> None:
    listing = Listing(
        listing_id="KRX:010820",
        company_id="KRX:010820",
        security_code="010820",
        exchange="KOSPI",
        vendor_symbols={},
    )
    wrong = Company(
        company_id="KRX:010820",
        company_name="퍼스텍",
        aliases=(),
    )
    analysis = QueryAnalysis(
        query_intent=QueryIntent(
            query="엘에스 일렉트릭 분석",
            subjects=(Subject(company=wrong, listing=listing),),
        ),
        entities={"e0": "LS ELECTRIC", "t0": "010820"},
        entity_kinds={"e0": "company", "t0": "ticker"},
        units=[
            QueryUnit(
                id="u0",
                objective="financials",
                retrieval_query="LS ELECTRIC financials",
                entity_ids=["e0", "t0"],
            )
        ],
    )
    sid = build_unique_root_session_id(
        datetime(2026, 4, 16, 1, 53, tzinfo=KST),
        analysis,
        "ignored when unit entities set",
        tmp_path,
    )
    assert sid.startswith("20260416-0153-LS ELECTRIC")


def test_segment_prefers_company_name_over_ticker(tmp_path: Path) -> None:
    listing = Listing(
        listing_id="L1",
        company_id="C1",
        security_code="006260",
        exchange="KOSPI",
        vendor_symbols={},
    )
    company = Company(
        company_id="C1",
        company_name="LS",
        aliases=(),
    )
    analysis = _analysis_with_subject(Subject(company=company, listing=listing))
    sid = build_unique_root_session_id(
        datetime(2026, 4, 16, 1, 53, tzinfo=KST),
        analysis,
        "ignored when company set",
        tmp_path,
    )
    assert sid.startswith("20260416-0153-LS")


def test_segment_skips_non_company_unit_entity_prefers_subject_name(
    tmp_path: Path,
) -> None:
    listing = Listing(
        listing_id="KRX:042660",
        company_id="KRX:042660",
        security_code="042660",
        exchange="KOSPI",
        vendor_symbols={},
    )
    company = Company(
        company_id="KRX:042660",
        company_name="한화오션",
        aliases=(),
    )
    analysis = QueryAnalysis(
        query_intent=QueryIntent(
            query="한화오션 분석해줘",
            subjects=(Subject(company=company, listing=listing),),
        ),
        entities={"industry_shipbuilding": "조선업"},
        entity_kinds={"industry_shipbuilding": "theme"},
        units=[
            QueryUnit(
                id="u0",
                objective="industry_position",
                retrieval_query="한화오션 조선업 점유율",
                entity_ids=["industry_shipbuilding"],
            )
        ],
    )
    sid = build_unique_root_session_id(
        datetime(2026, 4, 21, 0, 38, tzinfo=KST),
        analysis,
        "한화오션 분석해줘",
        tmp_path,
    )
    assert sid.startswith("20260421-0038-한화오션")


def test_segment_skips_ticker_uses_query_slug_when_no_company_name(
    tmp_path: Path,
) -> None:
    listing = Listing(
        listing_id="L1",
        company_id="C1",
        security_code="006260",
        exchange="KOSPI",
        vendor_symbols={},
    )
    company = Company(company_id="C1", company_name="", aliases=())
    analysis = _analysis_with_subject(Subject(company=company, listing=listing))
    sid = build_unique_root_session_id(
        datetime(2026, 4, 16, 1, 53, tzinfo=KST),
        analysis,
        "hello raw",
        tmp_path,
    )
    assert sid.startswith("20260416-0153-hello_raw")


def test_segment_falls_back_to_query_slug_without_subject(tmp_path: Path) -> None:
    analysis = _analysis_with_subject(None)
    sid = build_unique_root_session_id(
        datetime(2026, 4, 16, 1, 53, tzinfo=KST),
        analysis,
        "hello world",
        tmp_path,
    )
    assert "hello_world" in sid
