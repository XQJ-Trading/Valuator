from __future__ import annotations

from dataclasses import dataclass
import re

from pydantic import BaseModel, ConfigDict, Field

from valuator.models.protocol import LlmClient

from .ingest import pages_have_mappable_page_ordinals
from .types import DetectedTOC, Outline, Page

DEFAULT_TOC_CHECK_PAGE_NUM = 20
DEFAULT_TOC_SCAN_MAX_TOKENS = 10_000
DEFAULT_TOC_MIN_CONFIDENCE = 0.70

TOC_DETECT_SYSTEM_PROMPT = (
    "Return JSON only. Detect the table-of-contents span in the beginning of a "
    "document. A table of contents lists section headings or document parts for "
    "navigation, often with page numbers. Do not classify normal body pages as "
    "TOC only because they contain numbered headings."
)

TOC_CHUNK_PROMPT = (
    "Find the table-of-contents pages in this beginning document chunk.\n\n"
    "{chunk_text}\n\n"
    "Return the page ordinals from the shown chunk that belong to the table of "
    "contents. Also return toc_text as the exact table-of-contents listing text "
    "only, preserving the original line breaks: exclude cover text, filing "
    "headers, forward-looking statements, and body section content. Return "
    'has_toc=false, an empty list, and toc_text="" if there is no TOC.'
)

TOC_TRANSFORM_SYSTEM_PROMPT = (
    "Return JSON only. Convert a detected table of contents into a clean nested "
    "outline. Preserve document order and nesting. Do not add sections that are "
    "not present in the TOC text."
)

TOC_TRANSFORM_PROMPT = (
    "Convert this table-of-contents text into structured entries.\n\n"
    "{toc_text}\n\n"
    "Rules:\n"
    "- Return only navigation entries, not cover/header/body prose.\n"
    "- Merge split labels and titles into one entry title, for example "
    '"Item 1." plus "Business" becomes "Item 1. Business".\n'
    "- Put an integer in destination_page only when the TOC explicitly gives a "
    "destination page number for that entry. Use null for headings such as "
    '"Part I" when no destination page is shown.\n'
    "- Preserve hierarchy such as Part -> Item -> subsection when visible.\n"
    "- If the text is not a usable TOC, return entries=[] and confidence=0.\n"
)

TOC_TRANSFORM_RESPONSE_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["entries", "confidence", "reasoning"],
    "properties": {
        "entries": {
            "type": "array",
            "items": {"$ref": "#/$defs/Outline"},
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reasoning": {"type": "string"},
    },
    "$defs": {
        "Outline": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "destination_page", "children"],
            "properties": {
                "title": {"type": "string"},
                "destination_page": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                },
                "children": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/Outline"},
                },
            },
        }
    },
}


class _TOCChunkDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    has_toc: bool
    toc_page_ordinals: list[int] = Field(default_factory=list)
    toc_text: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""


class _TOCTransformDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[Outline] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""


@dataclass
class TOCDetectionMetrics:
    chunk_scan_calls: int = 0
    chunk_scan_pages: int = 0
    chunk_scan_tokens: int = 0
    selected_page_count: int = 0
    candidate_span_count: int = 0
    toc_maybe_truncated: bool = False
    no_toc_reason: str = ""


@dataclass
class TOCTransformMetrics:
    transform_calls: int = 0
    entry_count: int = 0
    entries_with_page_numbers: int = 0
    has_page_numbers: bool = False
    no_toc_reason: str = ""


class TOCDetector:
    def __init__(
        self,
        client: LlmClient,
        *,
        toc_check_page_num: int = DEFAULT_TOC_CHECK_PAGE_NUM,
        toc_scan_max_tokens: int = DEFAULT_TOC_SCAN_MAX_TOKENS,
        min_confidence: float = DEFAULT_TOC_MIN_CONFIDENCE,
    ) -> None:
        if toc_check_page_num <= 0:
            raise ValueError("toc_check_page_num must be > 0")
        if toc_scan_max_tokens <= 0:
            raise ValueError("toc_scan_max_tokens must be > 0")
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")
        self.client = client
        self.toc_check_page_num = toc_check_page_num
        self.toc_scan_max_tokens = toc_scan_max_tokens
        self.min_confidence = min_confidence
        self.metrics = TOCDetectionMetrics()

    async def detect(self, pages: list[Page]) -> DetectedTOC | None:
        self.metrics = TOCDetectionMetrics()
        if not pages:
            self.metrics.no_toc_reason = "empty_document"
            return None

        scan_pages = self._scan_pages(pages)
        self.metrics.chunk_scan_pages = len(scan_pages)
        self.metrics.chunk_scan_tokens = sum(page.token_count for page in scan_pages)
        data = await self.client.generate_json(
            prompt=TOC_CHUNK_PROMPT.format(chunk_text=self._pages_text(scan_pages)),
            system_prompt=TOC_DETECT_SYSTEM_PROMPT,
            response_json_schema=_TOCChunkDecision.model_json_schema(),
            trace_method="page_index.toc.detect.chunk",
        )
        self.metrics.chunk_scan_calls += 1
        decision = _TOCChunkDecision.model_validate(data)
        if not decision.has_toc or not decision.toc_page_ordinals:
            self.metrics.no_toc_reason = "no_chunk_candidate"
            return None
        if decision.confidence < self.min_confidence:
            self.metrics.no_toc_reason = "low_confidence"
            return None

        selected_pages = self._selected_span(scan_pages, decision.toc_page_ordinals)
        if not selected_pages:
            self.metrics.no_toc_reason = "no_valid_contiguous_span"
            return None

        self.metrics.selected_page_count = len(selected_pages)
        self.metrics.toc_maybe_truncated = (
            selected_pages[-1].ordinal == scan_pages[-1].ordinal
            and scan_pages[-1].ordinal != pages[-1].ordinal
        )
        return DetectedTOC(
            toc_pages=[page.ordinal for page in selected_pages],
            raw_text=decision.toc_text.strip(),
        )

    def _scan_pages(self, pages: list[Page]) -> list[Page]:
        candidates = pages[: self.toc_check_page_num]
        selected: list[Page] = []
        token_count = 0
        for page in candidates:
            if selected and token_count + page.token_count > self.toc_scan_max_tokens:
                break
            selected.append(page)
            token_count += page.token_count
        return selected or candidates[:1]

    def _selected_span(
        self,
        scan_pages: list[Page],
        toc_page_ordinals: list[int],
    ) -> list[Page]:
        page_by_ordinal = {page.ordinal: page for page in scan_pages}
        selected_ordinals = set(toc_page_ordinals)
        unknown = selected_ordinals - set(page_by_ordinal)
        if unknown:
            raise ValueError(
                "TOC chunk detector returned unknown page ordinals "
                f"{sorted(unknown)}"
            )

        spans: list[list[Page]] = []
        current: list[Page] = []
        for page in scan_pages:
            if page.ordinal in selected_ordinals:
                current.append(page)
            elif current:
                spans.append(current)
                current = []
        if current:
            spans.append(current)

        self.metrics.candidate_span_count = len(spans)
        if not spans:
            return []
        return max(spans, key=lambda span: (len(span), -scan_pages.index(span[0])))

    @staticmethod
    def _pages_text(pages: list[Page]) -> str:
        return "\n\n".join(
            f"[ordinal {page.ordinal}]\n{page.text.strip()}" for page in pages
        )


async def transform_toc(
    client: LlmClient,
    detected_toc: DetectedTOC | None,
    pages: list[Page],
    *,
    min_confidence: float = DEFAULT_TOC_MIN_CONFIDENCE,
) -> tuple[list[Outline] | None, TOCTransformMetrics]:
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence must be between 0 and 1")

    metrics = TOCTransformMetrics()
    if detected_toc is None:
        metrics.no_toc_reason = "no_detected_toc"
        return None, metrics

    toc_text = toc_guidance_text(detected_toc).strip()
    if not toc_text:
        metrics.no_toc_reason = "empty_toc_text"
        return None, metrics

    data = await client.generate_json(
        prompt=TOC_TRANSFORM_PROMPT.format(toc_text=toc_text),
        system_prompt=TOC_TRANSFORM_SYSTEM_PROMPT,
        response_json_schema=TOC_TRANSFORM_RESPONSE_JSON_SCHEMA,
        trace_method="page_index.toc.transform",
    )
    metrics.transform_calls += 1
    decision = _TOCTransformDecision.model_validate(data)
    if decision.confidence < min_confidence:
        metrics.no_toc_reason = "low_confidence"
        return None, metrics

    entries = _pruned_entries(decision.entries)
    if not entries:
        metrics.no_toc_reason = "empty_entries"
        return None, metrics

    metrics.entry_count = _entry_count(entries)
    metrics.entries_with_page_numbers = _entries_with_page_numbers(entries)
    metrics.has_page_numbers = (
        metrics.entries_with_page_numbers > 0
        and pages_have_mappable_page_ordinals(pages)
    )
    return entries, metrics


def toc_guidance_text(detected_toc: DetectedTOC) -> str:
    return re.sub(
        r"(?m)^\[ordinal \d+\]\s*$",
        "[detected TOC page]",
        detected_toc.raw_text,
    )


def remove_detected_toc_from_pages(
    pages: list[Page],
    detected_toc: DetectedTOC | None,
) -> list[Page]:
    if detected_toc is None or not detected_toc.raw_text.strip():
        return pages

    toc_lines = _normalized_content_lines(detected_toc.raw_text)
    if not toc_lines:
        return pages

    toc_ordinals = set(detected_toc.toc_pages)
    return [
        _page_without_toc(page, toc_lines) if page.ordinal in toc_ordinals else page
        for page in pages
    ]


def detected_toc_line_numbers_by_page(
    pages: list[Page],
    detected_toc: DetectedTOC | None,
) -> dict[int, set[int]]:
    if detected_toc is None or not detected_toc.raw_text.strip():
        return {}

    toc_lines = _normalized_content_lines(detected_toc.raw_text)
    if not toc_lines:
        return {}

    toc_ordinals = set(detected_toc.toc_pages)
    ignored: dict[int, set[int]] = {}
    for page in pages:
        if page.ordinal not in toc_ordinals:
            continue
        span = _matched_toc_line_span(page.text.splitlines(keepends=True), toc_lines)
        if span is None:
            continue
        start, end = span
        ignored[page.ordinal] = set(range(start + 1, end + 1))
    return ignored


def _page_without_toc(page: Page, toc_lines: list[str]) -> Page:
    lines = page.text.splitlines(keepends=True)
    span = _matched_toc_line_span(lines, toc_lines)
    if span is None:
        return page

    start, end = span
    text = "".join([*lines[:start], *lines[end:]]).strip()
    if not text:
        return page
    source_locator = dict(page.source_locator)
    source_locator["toc_removed"] = True
    return page.model_copy(
        update={
            "text": text,
            "token_count": _token_count(text),
            "source_locator": source_locator,
        }
    )


def _matched_toc_line_span(
    page_lines: list[str],
    toc_lines: list[str],
) -> tuple[int, int] | None:
    normalized_page_lines = [_normalize_line(line) for line in page_lines]
    for start, page_line in enumerate(normalized_page_lines):
        if page_line != toc_lines[0]:
            continue

        page_index = start
        toc_index = 0
        last_match = start
        while page_index < len(normalized_page_lines) and toc_index < len(toc_lines):
            if normalized_page_lines[page_index] == toc_lines[toc_index]:
                last_match = page_index
                toc_index += 1
            page_index += 1

        if toc_index == len(toc_lines):
            return start, last_match + 1

    return None


def _normalized_content_lines(text: str) -> list[str]:
    return [
        normalized
        for line in text.splitlines()
        for normalized in [_normalize_line(line)]
        if normalized and not re.fullmatch(r"\[ordinal \d+\]", normalized)
    ]


def _normalize_line(line: str) -> str:
    return " ".join(line.strip().split())


def _token_count(text: str) -> int:
    return sum(1 for _ in re.finditer(r"\S+", text))


def _pruned_entries(entries: list[Outline]) -> list[Outline]:
    pruned: list[Outline] = []
    for entry in entries:
        children = _pruned_entries(entry.children)
        title = " ".join(entry.title.split())
        if not title:
            continue
        pruned.append(
            Outline(
                title=title,
                destination_page=entry.destination_page,
                children=children,
            )
        )
    return pruned


def _entry_count(entries: list[Outline]) -> int:
    return sum(1 + _entry_count(entry.children) for entry in entries)


def _entries_with_page_numbers(entries: list[Outline]) -> int:
    return sum(
        (1 if entry.destination_page is not None else 0)
        + _entries_with_page_numbers(entry.children)
        for entry in entries
    )
