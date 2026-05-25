from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .heading_anchor import (
    HeadingAnchorMatch,
    find_heading_anchor_in_pages,
)
from .toc import detected_toc_line_numbers_by_page
from .types import DetectedTOC, Outline, Page


@dataclass(frozen=True)
class DocumentPosition:
    page_ordinal: int
    local_offset: int
    source_offset: int | None = None


@dataclass(frozen=True)
class SectionAnchor:
    title: str
    page_ordinal: int
    local_start: int
    local_end: int
    matched_text: str
    score: float
    method: str
    source_start: int | None = None
    source_end: int | None = None

    @property
    def start_position(self) -> DocumentPosition:
        return DocumentPosition(
            page_ordinal=self.page_ordinal,
            local_offset=self.local_start,
            source_offset=self.source_start,
        )

    @property
    def end_position(self) -> DocumentPosition:
        return DocumentPosition(
            page_ordinal=self.page_ordinal,
            local_offset=self.local_end,
            source_offset=self.source_end,
        )


@dataclass(frozen=True)
class SectionSpan:
    start: DocumentPosition
    end: DocumentPosition
    page_range: tuple[int, int]


@dataclass(frozen=True)
class SectionNode:
    title: str
    structure_path: str
    destination_page: int | None
    anchor: SectionAnchor | None
    content_span: SectionSpan | None
    children: tuple[SectionNode, ...] = ()


def resolve_toc_section_tree(
    outlines: list[Outline],
    pages: list[Page],
    *,
    detected_toc: DetectedTOC | None = None,
    search_radius: int = 1,
    min_score: float = 0.88,
    max_window_lines: int = 3,
) -> tuple[SectionNode, ...]:
    """Resolve TOC entries into body-heading anchors and content spans.

    Outline hierarchy remains the structural source of truth. Destination pages are
    used only as search hints for locating body anchors. Section content spans
    are then derived from each anchor to the next sibling anchor.
    """
    if not outlines or not pages:
        return ()

    ignored_lines_by_page = detected_toc_line_numbers_by_page(pages, detected_toc)
    page_order = _page_order(pages)
    page_by_ordinal = {page.ordinal: page for page in pages}
    document_end = _document_end(pages)
    nodes = tuple(
        _resolve_entry(
            outline,
            pages=pages,
            structure_path=str(index),
            ignored_lines_by_page=ignored_lines_by_page,
            search_radius=search_radius,
            min_score=min_score,
            max_window_lines=max_window_lines,
        )
        for index, outline in enumerate(outlines, start=1)
    )
    return _assign_spans_to_siblings(
        nodes,
        parent_end=document_end,
        page_order=page_order,
        page_by_ordinal=page_by_ordinal,
    )


def section_text(span: SectionSpan, pages: list[Page]) -> str:
    """Return text covered by a section span using exclusive end semantics."""
    page_by_ordinal = {page.ordinal: page for page in pages}
    ordered_pages = [
        page
        for page in sorted(pages, key=lambda page: page.ordinal)
        if span.page_range[0] <= page.ordinal <= span.page_range[1]
    ]
    chunks: list[str] = []
    for page in ordered_pages:
        start = span.start.local_offset if page.ordinal == span.start.page_ordinal else 0
        end = span.end.local_offset if page.ordinal == span.end.page_ordinal else len(page.text)
        if start < end:
            chunks.append(page.text[start:end])
    if not chunks and span.start.page_ordinal == span.end.page_ordinal:
        page = page_by_ordinal.get(span.start.page_ordinal)
        if page is not None and span.start.local_offset < span.end.local_offset:
            return page.text[span.start.local_offset : span.end.local_offset]
    return "\n".join(chunk.strip() for chunk in chunks if chunk.strip())


def section_pages(span: SectionSpan, pages: list[Page]) -> list[Page]:
    """Return per-page text slices covered by a section span."""
    ordered_pages = [
        page
        for page in sorted(pages, key=lambda page: page.ordinal)
        if span.page_range[0] <= page.ordinal <= span.page_range[1]
    ]
    sliced: list[Page] = []
    for page in ordered_pages:
        start = span.start.local_offset if page.ordinal == span.start.page_ordinal else 0
        end = span.end.local_offset if page.ordinal == span.end.page_ordinal else len(page.text)
        start = max(0, min(start, len(page.text)))
        end = max(0, min(end, len(page.text)))
        if start >= end:
            continue
        text = page.text[start:end]
        source_locator = dict(page.source_locator)
        source_locator["content_slice"] = {
            "start_page": span.start.page_ordinal,
            "start_offset": span.start.local_offset,
            "end_page": span.end.page_ordinal,
            "end_offset": span.end.local_offset,
            "page_start_offset": start,
            "page_end_offset": end,
        }
        source_start = source_locator.get("start")
        if isinstance(source_start, int):
            source_locator["start"] = source_start + start
            source_locator["end"] = source_start + end
        sliced.append(
            page.model_copy(
                update={
                    "text": text,
                    "token_count": _token_count(text),
                    "source_locator": source_locator,
                }
            )
        )
    return sliced


def _resolve_entry(
    outline: Outline,
    *,
    pages: list[Page],
    structure_path: str,
    ignored_lines_by_page: dict[int, set[int]],
    search_radius: int,
    min_score: float,
    max_window_lines: int,
) -> SectionNode:
    match = (
        find_heading_anchor_in_pages(
            outline.title,
            pages,
            candidate_page=outline.destination_page,
            search_radius=search_radius,
            ignored_lines_by_page=ignored_lines_by_page,
            min_score=min_score,
            max_window_lines=max_window_lines,
        )
        if outline.destination_page is not None
        else None
    )
    children = tuple(
        _resolve_entry(
            child,
            pages=pages,
            structure_path=f"{structure_path}.{index}",
            ignored_lines_by_page=ignored_lines_by_page,
            search_radius=search_radius,
            min_score=min_score,
            max_window_lines=max_window_lines,
        )
        for index, child in enumerate(outline.children, start=1)
    )
    return SectionNode(
        title=outline.title,
        structure_path=structure_path,
        destination_page=outline.destination_page,
        anchor=_anchor_from_match(outline.title, match) if match is not None else None,
        content_span=None,
        children=children,
    )


def _assign_spans_to_siblings(
    nodes: tuple[SectionNode, ...],
    *,
    parent_end: DocumentPosition,
    page_order: dict[int, int],
    page_by_ordinal: dict[int, Page],
) -> tuple[SectionNode, ...]:
    assigned: list[SectionNode] = []
    for index, node in enumerate(nodes):
        start = _effective_start(node, page_order)
        end = _next_sibling_start(nodes, index + 1, page_order) or parent_end
        span = (
            _span_from_positions(
                start,
                end,
                page_order=page_order,
                page_by_ordinal=page_by_ordinal,
            )
            if start is not None and _position_before(start, end, page_order)
            else None
        )
        children = _assign_spans_to_siblings(
            node.children,
            parent_end=end,
            page_order=page_order,
            page_by_ordinal=page_by_ordinal,
        )
        assigned.append(
            replace(
                node,
                content_span=span,
                children=children,
            )
        )
    return tuple(assigned)


def _anchor_from_match(title: str, match: HeadingAnchorMatch) -> SectionAnchor:
    return SectionAnchor(
        title=title,
        page_ordinal=match.page_ordinal,
        local_start=match.local_start,
        local_end=match.local_end,
        matched_text=match.matched_text,
        score=match.score,
        method=match.method,
        source_start=match.source_start,
        source_end=match.source_end,
    )


def _effective_start(
    node: SectionNode,
    page_order: dict[int, int],
) -> DocumentPosition | None:
    candidates: list[DocumentPosition] = []
    if node.anchor is not None:
        candidates.append(node.anchor.start_position)
    for child in node.children:
        child_start = _effective_start(child, page_order)
        if child_start is not None:
            candidates.append(child_start)
    if not candidates:
        return None
    return min(candidates, key=lambda position: _position_key(position, page_order))


def _next_sibling_start(
    nodes: tuple[SectionNode, ...],
    start_index: int,
    page_order: dict[int, int],
) -> DocumentPosition | None:
    starts = [
        start
        for node in nodes[start_index:]
        for start in [_effective_start(node, page_order)]
        if start is not None
    ]
    if not starts:
        return None
    return min(starts, key=lambda position: _position_key(position, page_order))


def _span_from_positions(
    start: DocumentPosition,
    end: DocumentPosition,
    *,
    page_order: dict[int, int],
    page_by_ordinal: dict[int, Page],
) -> SectionSpan:
    return SectionSpan(
        start=start,
        end=end,
        page_range=_page_range_for_span(
            start,
            end,
            page_order=page_order,
            page_by_ordinal=page_by_ordinal,
        ),
    )


def _page_range_for_span(
    start: DocumentPosition,
    end: DocumentPosition,
    *,
    page_order: dict[int, int],
    page_by_ordinal: dict[int, Page],
) -> tuple[int, int]:
    if start.page_ordinal == end.page_ordinal:
        return (start.page_ordinal, start.page_ordinal)
    if end.local_offset > 0:
        return (start.page_ordinal, end.page_ordinal)

    previous_page = _previous_page_ordinal(end.page_ordinal, page_order)
    if previous_page is None:
        return (start.page_ordinal, start.page_ordinal)
    if page_order[previous_page] < page_order[start.page_ordinal]:
        return (start.page_ordinal, start.page_ordinal)
    if previous_page not in page_by_ordinal:
        return (start.page_ordinal, start.page_ordinal)
    return (start.page_ordinal, previous_page)


def _document_end(pages: list[Page]) -> DocumentPosition:
    last_page = max(pages, key=lambda page: page.ordinal)
    source_start = last_page.source_locator.get("start")
    source_offset = (
        source_start + len(last_page.text)
        if isinstance(source_start, int)
        else None
    )
    return DocumentPosition(
        page_ordinal=last_page.ordinal,
        local_offset=len(last_page.text),
        source_offset=source_offset,
    )


def _page_order(pages: list[Page]) -> dict[int, int]:
    return {
        page.ordinal: index
        for index, page in enumerate(sorted(pages, key=lambda page: page.ordinal))
    }


def _previous_page_ordinal(
    page_ordinal: int,
    page_order: dict[int, int],
) -> int | None:
    index = page_order.get(page_ordinal)
    if index is None or index == 0:
        return None
    by_index = {value: key for key, value in page_order.items()}
    return by_index.get(index - 1)


def _token_count(text: str) -> int:
    return sum(1 for _ in re.finditer(r"\S+", text))


def _position_before(
    left: DocumentPosition,
    right: DocumentPosition,
    page_order: dict[int, int],
) -> bool:
    return _position_key(left, page_order) < _position_key(right, page_order)


def _position_key(
    position: DocumentPosition,
    page_order: dict[int, int],
) -> tuple[int, int]:
    return (
        page_order.get(position.page_ordinal, position.page_ordinal),
        position.local_offset,
    )
