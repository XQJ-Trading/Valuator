from __future__ import annotations

from valuator.documents import (
    Page,
    find_heading_anchor,
    find_heading_anchor_in_pages,
    heading_appears_near_page_start,
    heading_similarity,
)


def _page(ordinal: int, text: str) -> Page:
    return Page(
        doc_id="doc-1",
        ordinal=ordinal,
        text=text,
        token_count=len(text.split()),
        source_locator={
            "kind": "test_page",
            "ordinal_origin": "page_marker",
            "page": ordinal,
            "start": ordinal * 1_000,
            "end": ordinal * 1_000 + len(text),
        },
    )


def test_find_heading_anchor_matches_korean_heading_split_across_lines() -> None:
    page = _page(
        12,
        "앞선 본문입니다.\n\n연결\n재무상태표\n(단위: 백만원)\n",
    )

    match = find_heading_anchor("연결재무상태표", page)

    assert match is not None
    assert match.page_ordinal == 12
    assert match.matched_text == "연결\n재무상태표"
    assert match.line_start == 3
    assert match.line_end == 4
    assert match.source_start == 12_000 + page.text.index("연결")


def test_find_heading_anchor_skips_ignored_toc_lines() -> None:
    page = _page(
        1,
        "목차\n"
        "제1장 회사의 개요 1\n"
        "제1장 회사의 개요\n"
        "설립 및 주요 사업 설명\n",
    )

    match = find_heading_anchor(
        "제1장 회사의 개요",
        page,
        ignored_line_numbers={1, 2},
    )

    assert match is not None
    assert match.line_start == 3
    assert match.local_start == page.text.index("제1장 회사의 개요\n")


def test_find_heading_anchor_tolerates_korean_spacing_and_punctuation() -> None:
    score, method = heading_similarity(
        "제 2 장 사업의 내용",
        "제2장. 사업의내용",
    )

    assert method == "jamo_substring"
    assert score == 1.0


def test_find_heading_anchor_matches_english_sec_heading() -> None:
    page = _page(
        28,
        "Prior section tail\n"
        "Item 8. Financial Statements and Supplementary Data\n"
        "Index to Consolidated Financial Statements Page\n",
    )

    match = find_heading_anchor(
        "Item 8. Financial Statements and Supplementary Data",
        page,
    )

    assert match is not None
    assert match.local_start == page.text.index("Item 8")
    assert match.method == "jamo_substring"


def test_find_heading_anchor_rejects_unrelated_korean_heading() -> None:
    page = _page(
        20,
        "연결재무상태표\n자산\n부채\n자본\n",
    )

    assert find_heading_anchor("연결손익계산서", page) is None


def test_find_heading_anchor_in_pages_limits_to_candidate_radius() -> None:
    pages = [
        _page(4, "감사의견\n본문\n"),
        _page(5, "재무제표\n본문\n"),
        _page(6, "연결손익계산서\n매출액\n영업이익\n"),
    ]

    assert (
        find_heading_anchor_in_pages(
            "연결손익계산서",
            pages,
            candidate_page=4,
            search_radius=1,
        )
        is None
    )
    match = find_heading_anchor_in_pages(
        "연결손익계산서",
        pages,
        candidate_page=5,
        search_radius=1,
    )

    assert match is not None
    assert match.page_ordinal == 6


def test_heading_appears_near_page_start_uses_anchor_offset() -> None:
    page = _page(
        51,
        "Item 9. Changes in and Disagreements with Accountants\nNone.\n",
    )
    late_page = _page(
        51,
        "이전 섹션의 긴 본문입니다.\n" * 40
        + "Item 9. Changes in and Disagreements with Accountants\nNone.\n",
    )

    assert heading_appears_near_page_start(
        "Item 9. Changes in and Disagreements with Accountants",
        page,
    )
    assert not heading_appears_near_page_start(
        "Item 9. Changes in and Disagreements with Accountants",
        late_page,
    )
