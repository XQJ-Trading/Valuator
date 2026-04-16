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
