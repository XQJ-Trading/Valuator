from __future__ import annotations

from valuator.documents import (
    DetectedTOC,
    Outline,
    Page,
    resolve_toc_section_tree,
    section_text,
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


def test_resolve_toc_section_tree_extends_child_to_parent_end_anchor() -> None:
    pages = [
        _page(
            28,
            "Prior section tail\n"
            "Item 8. Financial Statements and Supplementary Data\n"
            "Index to Consolidated Financial Statements Page\n",
        ),
        _page(29, "Consolidated Statements of Operations\nNet sales\n"),
        *[_page(ordinal, f"Statement page {ordinal}\n") for ordinal in range(30, 34)],
        _page(34, "Notes to Consolidated Financial Statements\nNote 1\n"),
        *[_page(ordinal, f"Notes page {ordinal}\n") for ordinal in range(35, 48)],
        _page(48, "Report of Independent Registered Public Accounting Firm\nOpinion\n"),
        _page(49, "Audit report continuation\n"),
        _page(50, "Internal control audit report continuation\n"),
        _page(51, "Item 9. Changes in and Disagreements with Accountants\nNone.\n"),
    ]
    entries = [
        Outline(
            title="Item 8. Financial Statements and Supplementary Data",
            destination_page=28,
            children=[
                Outline(
                    title="Consolidated Statements of Operations",
                    destination_page=29,
                ),
                Outline(
                    title="Notes to Consolidated Financial Statements",
                    destination_page=34,
                ),
                Outline(
                    title="Report of Independent Registered Public Accounting Firm",
                    destination_page=48,
                ),
            ],
        ),
        Outline(
            title="Item 9. Changes in and Disagreements with Accountants",
            destination_page=51,
        ),
    ]

    sections = resolve_toc_section_tree(entries, pages)

    assert len(sections) == 2
    item_8 = sections[0]
    assert item_8.anchor is not None
    assert item_8.content_span is not None
    assert item_8.content_span.page_range == (28, 50)
    assert item_8.children[0].content_span is not None
    assert item_8.children[0].content_span.page_range == (29, 33)
    assert item_8.children[1].content_span is not None
    assert item_8.children[1].content_span.page_range == (34, 47)
    report = item_8.children[2]
    assert report.content_span is not None
    assert report.content_span.page_range == (48, 50)
    assert "Internal control audit report continuation" in section_text(
        report.content_span,
        pages,
    )


def test_resolve_toc_section_tree_slices_same_page_korean_sections() -> None:
    page = _page(
        1,
        "표지\n"
        "목차\n"
        "제1장 회사의 개요 1\n"
        "제2장 사업의 내용 1\n"
        "제1장 회사의 개요\n"
        "설립 및 주요 사업 설명\n"
        "제2장 사업의 내용\n"
        "매출과 영업이익 설명\n",
    )
    entries = [
        Outline(title="제1장 회사의 개요", destination_page=1),
        Outline(title="제2장 사업의 내용", destination_page=1),
    ]

    detected_toc = DetectedTOC(
        toc_pages=[1],
        raw_text="목차\n제1장 회사의 개요 1\n제2장 사업의 내용 1",
    )

    sections = resolve_toc_section_tree(entries, [page], detected_toc=detected_toc)

    first = sections[0]
    second = sections[1]
    assert first.anchor is not None
    assert second.anchor is not None
    assert first.content_span is not None
    assert second.content_span is not None
    assert first.content_span.page_range == (1, 1)
    assert second.content_span.page_range == (1, 1)
    first_text = section_text(first.content_span, [page])
    second_text = section_text(second.content_span, [page])
    assert "설립 및 주요 사업 설명" in first_text
    assert "매출과 영업이익 설명" not in first_text
    assert "매출과 영업이익 설명" in second_text
