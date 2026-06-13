from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from io import BytesIO
from re import Pattern
from typing import Any, Literal

from .types import Page, RawDocument

DEFAULT_TEXT_PAGE_TOKENS = 4_000
TEXT_MIME_TYPES = {"text/plain", "text/markdown", "text/x-markdown"}
PDF_MIME_TYPE = "application/pdf"
PPTX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)
MAPPABLE_PAGE_ORDINAL_ORIGINS = frozenset({"page_marker", "physical_page"})


@dataclass(frozen=True)
class PageMarkerPattern:
    pattern: Pattern[str]
    locator_kind: str = "marked_page"
    page_group: str | int = "page"
    boundary: Literal["end", "start"] = "end"


@dataclass(frozen=True)
class DocumentLoader:
    name: Literal["token_text", "marked_text", "pdf", "pptx"]
    page_unit: str
    unit_origin: Literal["token_window", "page_marker", "physical_page"]
    text_page_tokens: int = DEFAULT_TEXT_PAGE_TOKENS
    marker: PageMarkerPattern | None = None

    def __post_init__(self) -> None:
        if self.text_page_tokens <= 0:
            raise ValueError("text_page_tokens must be > 0")
        if self.name == "marked_text" and self.marker is None:
            raise ValueError("marked_text loader requires a page marker")
        if self.name != "marked_text" and self.marker is not None:
            raise ValueError(f"{self.name} loader does not accept a page marker")

    @classmethod
    def token_text(
        cls,
        *,
        text_page_tokens: int = DEFAULT_TEXT_PAGE_TOKENS,
    ) -> DocumentLoader:
        return cls(
            name="token_text",
            page_unit="token_window",
            unit_origin="token_window",
            text_page_tokens=text_page_tokens,
        )

    @classmethod
    def marked_text(cls, *, marker: PageMarkerPattern) -> DocumentLoader:
        return cls(
            name="marked_text",
            page_unit=marker.locator_kind,
            unit_origin="page_marker",
            marker=marker,
        )

    @classmethod
    def pdf(cls) -> DocumentLoader:
        return cls(
            name="pdf",
            page_unit="pdf_page",
            unit_origin="physical_page",
        )

    @classmethod
    def pptx(cls) -> DocumentLoader:
        return cls(
            name="pptx",
            page_unit="pptx_slide",
            unit_origin="physical_page",
        )

    def pages_from_raw(self, document: RawDocument) -> list[Page]:
        ingest = DocumentIngest(text_page_tokens=self.text_page_tokens)
        if self.name == "token_text":
            return ingest.pages_from_raw(document)
        if self.name == "pdf":
            return ingest.pages_from_pdf(document)
        if self.name == "pptx":
            return ingest.pages_from_pptx(document)
        if document.mime not in TEXT_MIME_TYPES:
            raise NotImplementedError("marked text loader supports text inputs only")
        if self.marker is None:
            raise ValueError("marked_text loader requires a page marker")
        return ingest.pages_from_marked_text(
            doc_id=document.doc_id,
            text=ingest._document_text(document),
            source=document.source,
            marker=self.marker,
        )

    def metadata(self) -> dict[str, Any]:
        metadata = {
            "loader": self.name,
            "page_unit": self.page_unit,
            "unit_origin": self.unit_origin,
            "toc_page_numbers_mappable": self.toc_page_numbers_mappable,
        }
        if self.name == "token_text":
            metadata["text_page_tokens"] = self.text_page_tokens
        elif self.marker is not None:
            metadata["marker_boundary"] = self.marker.boundary
        return metadata

    @property
    def toc_page_numbers_mappable(self) -> bool:
        return self.unit_origin in MAPPABLE_PAGE_ORDINAL_ORIGINS


def pages_have_mappable_page_ordinals(pages: list[Page]) -> bool:
    if not pages:
        return False

    ordinals: set[int] = set()
    for page in pages:
        locator = page.source_locator
        if locator.get("ordinal_origin") not in MAPPABLE_PAGE_ORDINAL_ORIGINS:
            return False
        if locator.get("page") != page.ordinal:
            return False
        if page.ordinal in ordinals:
            return False
        ordinals.add(page.ordinal)
    return True


def document_hash(document: RawDocument) -> str:
    raw = document.raw_bytes_or_text
    content = raw if isinstance(raw, bytes) else raw.encode("utf-8")
    digest = hashlib.sha256()
    digest.update(document.doc_id.encode("utf-8"))
    digest.update(b"\0")
    digest.update(document.source.encode("utf-8"))
    digest.update(b"\0")
    digest.update(document.mime.encode("utf-8"))
    digest.update(b"\0")
    digest.update(content)
    return digest.hexdigest()


class DocumentIngest:
    def __init__(self, *, text_page_tokens: int = DEFAULT_TEXT_PAGE_TOKENS) -> None:
        if text_page_tokens <= 0:
            raise ValueError("text_page_tokens must be > 0")
        self.text_page_tokens = text_page_tokens

    def pages_from_raw(self, document: RawDocument) -> list[Page]:
        if document.mime == PPTX_MIME_TYPE:
            return self.pages_from_pptx(document)
        if document.mime not in TEXT_MIME_TYPES:
            raise NotImplementedError("Phase 1 supports text and markdown inputs only")
        text = self._document_text(document)
        return self.pages_from_text(
            doc_id=document.doc_id,
            text=text,
            source=document.source,
        )

    def pages_from_text(self, *, doc_id: str, text: str, source: str) -> list[Page]:
        spans = [(match.start(), match.end()) for match in re.finditer(r"\S+", text)]
        if not spans:
            raise ValueError("document text is empty")

        pages: list[Page] = []
        for ordinal, start_index in enumerate(
            range(0, len(spans), self.text_page_tokens)
        ):
            page_spans = spans[start_index : start_index + self.text_page_tokens]
            start = page_spans[0][0]
            end = page_spans[-1][1]
            pages.append(
                Page(
                    doc_id=doc_id,
                    ordinal=ordinal,
                    text=text[start:end],
                    token_count=len(page_spans),
                    source_locator={
                        "kind": "char_range",
                        "source": source,
                        "ordinal_origin": "token_window",
                        "start": start,
                        "end": end,
                    },
                )
            )
        return pages

    def pages_from_pdf(self, document: RawDocument) -> list[Page]:
        if document.mime != PDF_MIME_TYPE:
            raise ValueError("pdf loader requires application/pdf mime")
        raw = document.raw_bytes_or_text
        if isinstance(raw, str):
            raise ValueError("pdf loader requires bytes")
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("pdf loader requires pypdf") from exc

        reader = PdfReader(BytesIO(raw))
        pages = [
            Page(
                doc_id=document.doc_id,
                ordinal=index,
                text=text,
                token_count=self._token_count(text),
                source_locator={
                    "kind": "pdf_page",
                    "source": document.source,
                    "ordinal_origin": "physical_page",
                    "page": index,
                },
            )
            for index, pdf_page in enumerate(reader.pages, start=1)
            for text in [(pdf_page.extract_text() or "").strip()]
        ]
        if not pages:
            raise ValueError("pdf document has no pages")
        return pages

    def pages_from_pptx(self, document: RawDocument) -> list[Page]:
        if document.mime != PPTX_MIME_TYPE:
            raise ValueError("pptx loader requires pptx mime")
        raw = document.raw_bytes_or_text
        if isinstance(raw, str):
            raise ValueError("pptx loader requires bytes")

        try:
            with zipfile.ZipFile(BytesIO(raw)) as archive:
                slide_names = sorted(
                    (
                        name
                        for name in archive.namelist()
                        if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
                    ),
                    key=self._pptx_slide_number,
                )
                if not slide_names:
                    raise ValueError("pptx document has no slides")
                pages = [
                    Page(
                        doc_id=document.doc_id,
                        ordinal=index,
                        text=text,
                        token_count=self._token_count(text),
                        source_locator={
                            "kind": "pptx_slide",
                            "source": document.source,
                            "ordinal_origin": "physical_page",
                            "page": index,
                        },
                    )
                    for index, slide_name in enumerate(slide_names, start=1)
                    for text in [self._pptx_slide_text(archive.read(slide_name))]
                ]
        except (ET.ParseError, zipfile.BadZipFile) as exc:
            raise ValueError("pptx loader requires a valid .pptx file") from exc

        return pages

    def pages_from_marked_text(
        self,
        *,
        doc_id: str,
        text: str,
        source: str,
        marker: PageMarkerPattern,
    ) -> list[Page]:
        if marker.boundary == "start":
            return self._pages_from_start_marked_text(
                doc_id=doc_id,
                text=text,
                source=source,
                marker=marker,
            )

        pages: list[Page] = []
        parts: list[str] = []
        page_start = 0
        cursor = 0
        for line in text.splitlines(keepends=True):
            parts.append(line)
            cursor += len(line)
            match = marker.pattern.search(line.strip())
            if match is None:
                continue

            page_number = self._page_number(match, marker.page_group)
            page_text = "".join(parts).strip()
            pages.append(
                Page(
                    doc_id=doc_id,
                    ordinal=page_number,
                    text=page_text,
                    token_count=self._token_count(page_text),
                    source_locator={
                        "kind": marker.locator_kind,
                        "source": source,
                        "ordinal_origin": "page_marker",
                        "page": page_number,
                        "start": page_start,
                        "end": cursor,
                        "marker": line.strip(),
                    },
                )
            )
            parts = []
            page_start = cursor

        if not pages:
            raise ValueError("text does not contain page markers")
        return pages

    def _pages_from_start_marked_text(
        self,
        *,
        doc_id: str,
        text: str,
        source: str,
        marker: PageMarkerPattern,
    ) -> list[Page]:
        pages: list[Page] = []
        parts: list[str] = []
        page_start = 0
        cursor = 0
        current_page: int | None = None
        current_marker = ""
        for line in text.splitlines(keepends=True):
            line_start = cursor
            cursor += len(line)
            match = marker.pattern.search(line.strip())
            if match is None:
                parts.append(line)
                continue

            if current_page is not None:
                self._append_marked_page(
                    pages=pages,
                    doc_id=doc_id,
                    source=source,
                    marker=marker,
                    page_number=current_page,
                    page_text="".join(parts).strip(),
                    page_start=page_start,
                    page_end=line_start,
                    marker_text=current_marker,
                )
            current_page = self._page_number(match, marker.page_group)
            current_marker = line.strip()
            parts = [line]
            page_start = line_start

        if current_page is not None:
            self._append_marked_page(
                pages=pages,
                doc_id=doc_id,
                source=source,
                marker=marker,
                page_number=current_page,
                page_text="".join(parts).strip(),
                page_start=page_start,
                page_end=cursor,
                marker_text=current_marker,
            )

        if not pages:
            raise ValueError("text does not contain page markers")
        return pages

    def _append_marked_page(
        self,
        *,
        pages: list[Page],
        doc_id: str,
        source: str,
        marker: PageMarkerPattern,
        page_number: int,
        page_text: str,
        page_start: int,
        page_end: int,
        marker_text: str,
    ) -> None:
        pages.append(
            Page(
                doc_id=doc_id,
                ordinal=page_number,
                text=page_text,
                token_count=self._token_count(page_text),
                source_locator={
                    "kind": marker.locator_kind,
                    "source": source,
                    "ordinal_origin": "page_marker",
                    "page": page_number,
                    "start": page_start,
                    "end": page_end,
                    "marker": marker_text,
                },
            )
        )

    @staticmethod
    def _document_text(document: RawDocument) -> str:
        raw = document.raw_bytes_or_text
        if isinstance(raw, str):
            return raw
        return raw.decode("utf-8-sig")

    @staticmethod
    def _pptx_slide_number(path: str) -> int:
        match = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", path)
        if match is None:
            return 0
        return int(match.group(1))

    @classmethod
    def _pptx_slide_text(cls, xml_bytes: bytes) -> str:
        root = ET.fromstring(xml_bytes)
        paragraphs: list[str] = []
        for paragraph in root.iter():
            if cls._xml_local_name(paragraph.tag) != "p":
                continue
            parts = [
                (node.text or "").strip()
                for node in paragraph.iter()
                if cls._xml_local_name(node.tag) == "t"
            ]
            line = " ".join(part for part in parts if part)
            if line:
                paragraphs.append(line)
        return "\n".join(paragraphs).strip()

    @staticmethod
    def _xml_local_name(tag: str) -> str:
        return tag.rsplit("}", maxsplit=1)[-1]

    @staticmethod
    def _token_count(text: str) -> int:
        return sum(1 for _ in re.finditer(r"\S+", text))

    @staticmethod
    def _page_number(match: re.Match[str], group: str | int) -> int:
        try:
            value = match.group(group)
        except IndexError:
            value = match.group(1)
        return int(value)
