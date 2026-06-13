from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
import unicodedata
from typing import Literal

from valuator.utils.hangul_fuzzy_key import jamo_fuzzy_key

from .types import Page

HeadingAnchorMethod = Literal[
    "jamo_substring",
    "jamo_candidate_substring",
    "jamo_fuzzy_window",
]

DEFAULT_HEADING_MIN_SCORE = 0.88
DEFAULT_HEADING_MAX_WINDOW_LINES = 3


@dataclass(frozen=True)
class HeadingAnchorMatch:
    page_ordinal: int
    local_start: int
    local_end: int
    matched_text: str
    score: float
    method: HeadingAnchorMethod
    line_start: int
    line_end: int
    source_start: int | None = None
    source_end: int | None = None


@dataclass(frozen=True)
class _LineSpan:
    line_number: int
    start: int
    end: int


def find_heading_anchor(
    title: str,
    page: Page,
    *,
    ignored_line_numbers: set[int] | None = None,
    min_score: float = DEFAULT_HEADING_MIN_SCORE,
    max_window_lines: int = DEFAULT_HEADING_MAX_WINDOW_LINES,
) -> HeadingAnchorMatch | None:
    """Find the likely start offset of a heading title within a page."""
    if max_window_lines <= 0:
        raise ValueError("max_window_lines must be > 0")

    title_key = _heading_key(title)
    if not title_key:
        return None

    best: HeadingAnchorMatch | None = None
    ignored_lines = ignored_line_numbers or set()
    lines = _non_empty_line_spans(page.text)
    for start_index, first_line in enumerate(lines):
        for end_index in range(
            start_index,
            min(len(lines), start_index + max_window_lines),
        ):
            window_lines = lines[start_index : end_index + 1]
            if _window_overlaps_ignored_lines(window_lines, ignored_lines):
                continue
            last_line = lines[end_index]
            candidate_text = page.text[first_line.start : last_line.end]
            score, method = heading_similarity(title, candidate_text)
            if score < min_score:
                continue
            match = _match_from_lines(
                page=page,
                first_line=first_line,
                last_line=last_line,
                matched_text=candidate_text,
                score=score,
                method=method,
            )
            if best is None or _is_better_match(match, best):
                best = match

    return best


def find_heading_anchor_in_pages(
    title: str,
    pages: list[Page],
    *,
    candidate_page: int | None = None,
    search_radius: int = 1,
    ignored_lines_by_page: Mapping[int, set[int]] | None = None,
    min_score: float = DEFAULT_HEADING_MIN_SCORE,
    max_window_lines: int = DEFAULT_HEADING_MAX_WINDOW_LINES,
) -> HeadingAnchorMatch | None:
    if search_radius < 0:
        raise ValueError("search_radius must be >= 0")

    search_pages = _candidate_pages(
        pages,
        candidate_page=candidate_page,
        search_radius=search_radius,
    )
    best: HeadingAnchorMatch | None = None
    for page in search_pages:
        match = find_heading_anchor(
            title,
            page,
            ignored_line_numbers=(
                ignored_lines_by_page.get(page.ordinal)
                if ignored_lines_by_page is not None
                else None
            ),
            min_score=min_score,
            max_window_lines=max_window_lines,
        )
        if match is None:
            continue
        if best is None or _is_better_match(match, best):
            best = match
    return best


def heading_appears_near_page_start(
    title: str,
    page: Page,
    *,
    max_start_offset: int = 500,
    min_score: float = DEFAULT_HEADING_MIN_SCORE,
    max_window_lines: int = DEFAULT_HEADING_MAX_WINDOW_LINES,
) -> bool:
    if max_start_offset < 0:
        raise ValueError("max_start_offset must be >= 0")
    match = find_heading_anchor(
        title,
        page,
        min_score=min_score,
        max_window_lines=max_window_lines,
    )
    return match is not None and match.local_start <= max_start_offset


def heading_similarity(
    title: str,
    candidate_text: str,
) -> tuple[float, HeadingAnchorMethod]:
    title_key = _heading_key(title)
    candidate_key = _heading_key(candidate_text)
    if not title_key or not candidate_key:
        return 0.0, "jamo_fuzzy_window"

    if title_key in candidate_key:
        return 1.0, "jamo_substring"
    if candidate_key in title_key and len(candidate_key) / len(title_key) >= 0.5:
        return 0.90, "jamo_candidate_substring"

    return (
        max(
            SequenceMatcher(None, title_key, candidate_key).ratio(),
            _partial_ratio(title_key, candidate_key),
        ),
        "jamo_fuzzy_window",
    )


def _heading_key(text: str) -> str:
    return jamo_fuzzy_key(unicodedata.normalize("NFKC", text))


def _non_empty_line_spans(text: str) -> list[_LineSpan]:
    lines: list[_LineSpan] = []
    cursor = 0
    for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
        raw = line.rstrip("\r\n")
        leading_len = len(raw) - len(raw.lstrip())
        trailing_len = len(raw.rstrip())
        if trailing_len > leading_len:
            lines.append(
                _LineSpan(
                    line_number=line_number,
                    start=cursor + leading_len,
                    end=cursor + trailing_len,
                )
            )
        cursor += len(line)
    return lines


def _window_overlaps_ignored_lines(
    lines: list[_LineSpan],
    ignored_line_numbers: set[int],
) -> bool:
    return any(line.line_number in ignored_line_numbers for line in lines)


def _partial_ratio(query_key: str, candidate_key: str) -> float:
    if not query_key or not candidate_key:
        return 0.0
    if len(candidate_key) <= len(query_key):
        return SequenceMatcher(None, query_key, candidate_key).ratio()

    window_len = len(query_key)
    best = 0.0
    for start in range(0, len(candidate_key) - window_len + 1):
        window = candidate_key[start : start + window_len]
        best = max(best, SequenceMatcher(None, query_key, window).ratio())
        if best >= 0.999:
            return 1.0
    return best


def _candidate_pages(
    pages: list[Page],
    *,
    candidate_page: int | None,
    search_radius: int,
) -> list[Page]:
    if candidate_page is None:
        return pages
    min_page = candidate_page - search_radius
    max_page = candidate_page + search_radius
    return [page for page in pages if min_page <= page.ordinal <= max_page]


def _match_from_lines(
    *,
    page: Page,
    first_line: _LineSpan,
    last_line: _LineSpan,
    matched_text: str,
    score: float,
    method: HeadingAnchorMethod,
) -> HeadingAnchorMatch:
    source_start = _source_offset(page, first_line.start)
    source_end = _source_offset(page, last_line.end)
    return HeadingAnchorMatch(
        page_ordinal=page.ordinal,
        local_start=first_line.start,
        local_end=last_line.end,
        matched_text=matched_text,
        score=score,
        method=method,
        line_start=first_line.line_number,
        line_end=last_line.line_number,
        source_start=source_start,
        source_end=source_end,
    )


def _source_offset(page: Page, local_offset: int) -> int | None:
    start = page.source_locator.get("start")
    if isinstance(start, int):
        return start + local_offset
    return None


def _is_better_match(left: HeadingAnchorMatch, right: HeadingAnchorMatch) -> bool:
    if left.score != right.score:
        return left.score > right.score
    left_lines = left.line_end - left.line_start
    right_lines = right.line_end - right.line_start
    if left_lines != right_lines:
        return left_lines < right_lines
    return left.local_start < right.local_start
