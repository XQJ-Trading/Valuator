from __future__ import annotations

import asyncio
from io import BytesIO
import re
from typing import Any

import pytest
from pypdf import PdfWriter

from valuator.documents import (
    DetectedTOC,
    DocumentIngest,
    DocumentLoader,
    IndexStore,
    IndexedDocument,
    Outline,
    Page,
    PageMarkerPattern,
    PageIndexer,
    RawDocument,
    TreeRetriever,
    TreeNode,
    TOCDetector,
    document_hash,
    pages_have_mappable_page_ordinals,
    remove_detected_toc_from_pages,
    transform_toc,
)
from valuator.tools.page_index_tool import PageIndexRetrieveTool


class FakeLlmClient:
    model = "fake-model"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        del usage_writer

    async def get_or_create_explicit_cache(self, **kwargs: Any) -> str | None:
        del kwargs
        return None

    async def generate(self, *args: Any, **kwargs: Any) -> str:
        del args, kwargs
        return "{}"

    async def generate_json(self, **kwargs: Any) -> dict[str, Any]:
        trace_method = str(kwargs["trace_method"])
        self.calls.append(trace_method)
        if trace_method == "page_index.large_node_recursion.init":
            return {
                "node_id": "recursive-root",
                "title": "Recursive root",
                "page_range": [0, 5],
                "summary": "Refined section tree",
                "children": [
                    {
                        "node_id": "first-half",
                        "title": "First half",
                        "page_range": [0, 2],
                        "summary": "Pages 0 to 2",
                        "children": [],
                    },
                    {
                        "node_id": "second-half",
                        "title": "Second half",
                        "page_range": [3, 5],
                        "summary": "Pages 3 to 5",
                        "children": [],
                    },
                ],
            }
        return {
            "node_id": "root",
            "title": "Root",
            "page_range": [0, 5],
            "summary": "Coarse tree",
            "children": [],
        }


class SinglePageLlmClient(FakeLlmClient):
    async def generate_json(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(str(kwargs["trace_method"]))
        return {
            "node_id": "root",
            "title": "Single page root",
            "page_range": [0, 0],
            "summary": "Oversized single page",
            "children": [],
        }


class ContinueDeltaLlmClient(FakeLlmClient):
    async def generate_json(self, **kwargs: Any) -> dict[str, Any]:
        trace_method = str(kwargs["trace_method"])
        self.calls.append(trace_method)
        if trace_method == "page_index.continue":
            assert "complete updated root TreeNode" not in kwargs["prompt"]
            return {
                "title": "Root",
                "page_range": [0, 3],
                "summary": "Combined document",
                "children": [
                    {
                        "node_id": "part-b",
                        "title": "Part B",
                        "page_range": [2, 3],
                        "summary": "Second section",
                        "children": [],
                    }
                ],
            }
        return {
            "node_id": "root",
            "title": "Root",
            "page_range": [0, 1],
            "summary": "First section only",
            "children": [
                {
                    "node_id": "part-a",
                    "title": "Part A",
                    "page_range": [0, 1],
                    "summary": "First section",
                    "children": [],
                }
            ],
        }


class RetrieverLlmClient(FakeLlmClient):
    async def generate_json(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(str(kwargs["trace_method"]))
        assert "first page raw text" not in kwargs["prompt"]
        assert "second page raw text" not in kwargs["prompt"]
        return {
            "doc_id": "doc-1",
            "selected_node_ids": ["n.2"],
            "reasoning": "The second section matches the query.",
        }


class StaticSelectionLlmClient(FakeLlmClient):
    def __init__(self, selected_node_ids: list[str]) -> None:
        super().__init__()
        self.selected_node_ids = selected_node_ids

    async def generate_json(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(str(kwargs["trace_method"]))
        return {
            "doc_id": "doc-1",
            "selected_node_ids": self.selected_node_ids,
            "reasoning": "Static test selection.",
        }


class ParentThenChildSelectionLlmClient(FakeLlmClient):
    async def generate_json(self, **kwargs: Any) -> dict[str, Any]:
        trace_method = str(kwargs["trace_method"])
        self.calls.append(trace_method)
        assert "page 4 raw text" not in kwargs["prompt"]
        if trace_method == "page_index.retrieve.refine":
            return {
                "doc_id": "doc-1",
                "selected_node_ids": ["n.1.2"],
                "reasoning": "The child node has the specific evidence.",
            }
        return {
            "doc_id": "doc-1",
            "selected_node_ids": ["n.1"],
            "reasoning": "The parent section is relevant.",
        }


class ParentReselectingLlmClient(FakeLlmClient):
    async def generate_json(self, **kwargs: Any) -> dict[str, Any]:
        trace_method = str(kwargs["trace_method"])
        self.calls.append(trace_method)
        return {
            "doc_id": "doc-1",
            "selected_node_ids": ["n.1"],
            "reasoning": "The parent section is relevant.",
        }


class ParallelSplitLlmClient(FakeLlmClient):
    def __init__(self) -> None:
        super().__init__()
        self.active_recursions = 0
        self.max_active_recursions = 0

    async def generate_json(self, **kwargs: Any) -> dict[str, Any]:
        trace_method = str(kwargs["trace_method"])
        self.calls.append(trace_method)
        ordinals = [
            int(value)
            for value in re.findall(r"\[ordinal (\d+)\]", str(kwargs["prompt"]))
        ]
        start = min(ordinals)
        end = max(ordinals)
        if trace_method == "page_index.init":
            return self._tree(start, end, [])

        self.active_recursions += 1
        self.max_active_recursions = max(
            self.max_active_recursions,
            self.active_recursions,
        )
        await asyncio.sleep(0)
        try:
            midpoint = (start + end) // 2
            return self._tree(
                start,
                end,
                [
                    self._child("left", start, midpoint),
                    self._child("right", midpoint + 1, end),
                ],
            )
        finally:
            self.active_recursions -= 1

    @staticmethod
    def _tree(start: int, end: int, children: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "node_id": f"root-{start}-{end}",
            "title": f"Root {start}-{end}",
            "page_range": [start, end],
            "summary": "Parallel split tree",
            "children": children,
        }

    @staticmethod
    def _child(name: str, start: int, end: int) -> dict[str, Any]:
        return {
            "node_id": f"{name}-{start}-{end}",
            "title": f"{name} {start}-{end}",
            "page_range": [start, end],
            "summary": "Child section",
            "children": [],
        }


class TOCDetectorLlmClient(FakeLlmClient):
    def __init__(
        self,
        *,
        chunk_decision: dict[str, Any],
    ) -> None:
        super().__init__()
        self.chunk_decision = chunk_decision

    async def generate_json(self, **kwargs: Any) -> dict[str, Any]:
        trace_method = str(kwargs["trace_method"])
        self.calls.append(trace_method)
        if trace_method == "page_index.toc.detect.chunk":
            return self.chunk_decision
        return await super().generate_json(**kwargs)


class TOCGuidedIndexerLlmClient(FakeLlmClient):
    async def generate_json(self, **kwargs: Any) -> dict[str, Any]:
        trace_method = str(kwargs["trace_method"])
        self.calls.append(trace_method)
        if trace_method == "page_index.toc_guided.init":
            prompt = str(kwargs["prompt"])
            assert "Detected table-of-contents text" in prompt
            guidance_text = prompt.split("Document pages:", maxsplit=1)[0]
            assert "[detected TOC page]" in guidance_text
            assert "[ordinal 1]" not in guidance_text
            assert "Contents" in prompt
            document_pages = prompt.split("Document pages:", maxsplit=1)[1]
            assert "[ordinal 1]" in document_pages
            assert "[ordinal 2]" in document_pages
            return {
                "node_id": "root",
                "title": "Annual report",
                "page_range": [0, 3],
                "summary": "TOC-guided body tree",
                "children": [
                    {
                        "node_id": "out-of-range",
                        "title": "Out of range",
                        "page_range": [0, 0],
                        "summary": "Out-of-range node that should be dropped",
                        "children": [],
                    },
                    {
                        "node_id": "revenue",
                        "title": "Revenue",
                        "page_range": [0, 2],
                        "summary": "Revenue discussion",
                        "children": [],
                    },
                    {
                        "node_id": "risk",
                        "title": "Risk Factors",
                        "page_range": [3, 3],
                        "summary": "Risk discussion",
                        "children": [],
                    },
                ],
            }
        return await super().generate_json(**kwargs)


class TOCTransformLlmClient(FakeLlmClient):
    async def generate_json(self, **kwargs: Any) -> dict[str, Any]:
        trace_method = str(kwargs["trace_method"])
        self.calls.append(trace_method)
        if trace_method == "page_index.toc.transform":
            return {
                "entries": [
                    {
                        "title": "Part I",
                        "page_number": None,
                        "children": [
                            {
                                "title": "Item 1. Business",
                                "page_number": 1,
                                "children": [],
                            },
                            {
                                "title": "Item 1A. Risk Factors",
                                "page_number": 5,
                                "children": [],
                            },
                        ],
                    },
                    {
                        "title": "Part II",
                        "page_number": None,
                        "children": [
                            {
                                "title": "Item 7. MD&A",
                                "page_number": 10,
                                "children": [],
                            }
                        ],
                    },
                ],
                "confidence": 0.93,
                "reasoning": "Usable TOC.",
            }
        return await super().generate_json(**kwargs)


def pages_for_toc_detection(count: int) -> list[Page]:
    return [
        Page(
            doc_id="doc-1",
            ordinal=index,
            text=f"page {index} text " * 3,
            token_count=9,
            source_locator={"kind": "pdf_page", "page": index},
        )
        for index in range(count)
    ]


def test_text_ingest_splits_text_into_char_range_pages() -> None:
    document = RawDocument(
        doc_id="doc-1",
        source="memory://doc-1",
        raw_bytes_or_text="alpha beta gamma delta epsilon",
    )
    pages = DocumentIngest(text_page_tokens=2).pages_from_raw(document)

    assert [page.text for page in pages] == ["alpha beta", "gamma delta", "epsilon"]
    assert pages[1].source_locator == {
        "kind": "char_range",
        "source": "memory://doc-1",
        "ordinal_origin": "token_window",
        "start": 11,
        "end": 22,
    }
    assert not pages_have_mappable_page_ordinals(pages)
    assert document_hash(document) == document_hash(document)


def test_marked_text_ingest_preserves_source_page_numbers() -> None:
    text = "\n".join(
        [
            "Cover and item 1 text",
            "Page 1",
            "Risk factors text",
            "Page 2",
        ]
    )
    pages = DocumentIngest().pages_from_marked_text(
        doc_id="doc-1",
        text=text,
        source="memory://doc-1",
        marker=PageMarkerPattern(
            pattern=re.compile(r"Page (?P<page>\d+)$"),
            locator_kind="source_page",
        ),
    )

    assert [page.ordinal for page in pages] == [1, 2]
    assert pages[0].source_locator["kind"] == "source_page"
    assert pages[0].source_locator["ordinal_origin"] == "page_marker"
    assert pages[0].source_locator["page"] == 1
    assert pages[1].text.startswith("Risk factors")
    assert pages_have_mappable_page_ordinals(pages)


def test_start_marked_text_ingest_preserves_source_page_numbers() -> None:
    text = "\n".join(
        [
            "Page 10",
            "Cover and item 1 text",
            "Page 11",
            "Risk factors text",
        ]
    )
    pages = DocumentIngest().pages_from_marked_text(
        doc_id="doc-1",
        text=text,
        source="memory://doc-1",
        marker=PageMarkerPattern(
            pattern=re.compile(r"Page (?P<page>\d+)$"),
            locator_kind="source_page",
            boundary="start",
        ),
    )

    assert [page.ordinal for page in pages] == [10, 11]
    assert pages[0].text.startswith("Page 10")
    assert pages[1].text.startswith("Page 11")
    assert pages_have_mappable_page_ordinals(pages)


def test_marked_text_loader_fails_when_expected_markers_are_missing() -> None:
    loader = DocumentLoader.marked_text(
        marker=PageMarkerPattern(pattern=re.compile(r"Page (?P<page>\d+)$"))
    )

    with pytest.raises(ValueError, match="does not contain page markers"):
        loader.pages_from_raw(
            RawDocument(
                doc_id="doc-1",
                source="memory://doc-1",
                raw_bytes_or_text="text without page markers",
            )
        )


def test_pdf_loader_preserves_physical_pages() -> None:
    raw_pdf = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    writer.write(raw_pdf)

    pages = DocumentLoader.pdf().pages_from_raw(
        RawDocument(
            doc_id="pdf-doc",
            source="memory://pdf-doc",
            raw_bytes_or_text=raw_pdf.getvalue(),
            mime="application/pdf",
        )
    )

    assert [page.ordinal for page in pages] == [1, 2]
    assert pages[0].source_locator == {
        "kind": "pdf_page",
        "source": "memory://pdf-doc",
        "ordinal_origin": "physical_page",
        "page": 1,
    }
    assert pages_have_mappable_page_ordinals(pages)


@pytest.mark.asyncio
async def test_toc_detector_extracts_toc_pages_from_first_chunk() -> None:
    client = TOCDetectorLlmClient(
        chunk_decision={
            "has_toc": True,
            "toc_page_ordinals": [1, 2],
            "toc_text": "Contents\nRevenue 2\nRisk Factors 3",
            "confidence": 0.94,
            "reasoning": "Pages 1 and 2 contain TOC entries.",
        }
    )

    detected = await TOCDetector(
        client,
        toc_check_page_num=4,
    ).detect(pages_for_toc_detection(4))

    assert detected is not None
    assert detected.toc_pages == [1, 2]
    assert detected.raw_text == "Contents\nRevenue 2\nRisk Factors 3"
    assert client.calls == ["page_index.toc.detect.chunk"]


@pytest.mark.asyncio
async def test_toc_detector_rejects_low_confidence_chunk_candidate() -> None:
    client = TOCDetectorLlmClient(
        chunk_decision={
            "has_toc": True,
            "toc_page_ordinals": [1],
            "toc_text": "Weak table of contents",
            "confidence": 0.50,
            "reasoning": "Weak signal.",
        }
    )
    detector = TOCDetector(client, toc_check_page_num=3)

    detected = await detector.detect(pages_for_toc_detection(3))

    assert detected is None
    assert detector.metrics.chunk_scan_calls == 1
    assert detector.metrics.no_toc_reason == "low_confidence"


@pytest.mark.asyncio
async def test_toc_detector_chooses_longest_contiguous_span_and_marks_truncation() -> None:
    client = TOCDetectorLlmClient(
        chunk_decision={
            "has_toc": True,
            "toc_page_ordinals": [0, 2, 3],
            "toc_text": "Contents\nSection A 2\nSection B 3",
            "confidence": 0.91,
            "reasoning": "Two candidate spans, second one is longer.",
        }
    )
    detector = TOCDetector(
        client,
        toc_check_page_num=4,
    )

    detected = await detector.detect(pages_for_toc_detection(6))

    assert detected is not None
    assert detected.toc_pages == [2, 3]
    assert detector.metrics.candidate_span_count == 2
    assert detector.metrics.toc_maybe_truncated is True


def test_remove_detected_toc_from_pages_keeps_body_on_same_page() -> None:
    pages = [
        Page(
            doc_id="doc-1",
            ordinal=1,
            text=(
                "Cover text\n"
                "TABLE OF CONTENTS\n"
                "Item 1. Business\n"
                "1\n"
                "Item 1A. Risk Factors\n"
                "5\n"
                "Forward-looking statement\n"
                "PART I\n"
                "Item 1. Business\n"
                "Business body"
            ),
            token_count=20,
            source_locator={"kind": "pdf_page", "page": 1},
        )
    ]
    cleaned = remove_detected_toc_from_pages(
        pages,
        DetectedTOC(
            toc_pages=[1],
            raw_text=(
                "TABLE OF CONTENTS\n"
                "Item 1. Business\n"
                "1\n"
                "Item 1A. Risk Factors\n"
                "5"
            ),
        ),
    )

    assert "TABLE OF CONTENTS" not in cleaned[0].text
    assert "Forward-looking statement" in cleaned[0].text
    assert "Business body" in cleaned[0].text
    assert cleaned[0].source_locator["toc_removed"] is True


@pytest.mark.asyncio
async def test_transform_toc_returns_entries_and_metrics() -> None:
    pages = [
        Page(
            doc_id="doc-1",
            ordinal=ordinal,
            text={
                1: "Item 1. Business",
                5: "Item 1A. Risk Factors",
                10: "Item 7. MD&A",
            }.get(ordinal, f"page {ordinal}"),
            token_count=2,
            source_locator={
                "kind": "pdf_page",
                "ordinal_origin": "physical_page",
                "page": ordinal,
            },
        )
        for ordinal in range(1, 11)
    ]
    client = TOCTransformLlmClient()

    outlines, metrics = await transform_toc(
        client,
        DetectedTOC(toc_pages=[1], raw_text="TABLE OF CONTENTS"),
        pages,
    )

    assert outlines is not None
    assert [entry.title for entry in outlines] == ["Part I", "Part II"]
    assert metrics.entry_count == 5
    assert metrics.entries_with_page_numbers == 3
    assert metrics.has_page_numbers is True
    assert client.calls == ["page_index.toc.transform"]


@pytest.mark.asyncio
async def test_page_indexer_builds_tree_directly_from_mapped_toc() -> None:
    pages = [
        Page(
            doc_id="doc-1",
            ordinal=ordinal,
            text={
                1: "Item 1. Business",
                5: "Item 1A. Risk Factors",
                10: "Item 7. MD&A",
            }.get(ordinal, f"page {ordinal}"),
            token_count=2,
            source_locator={
                "kind": "pdf_page",
                "ordinal_origin": "physical_page",
                "page": ordinal,
            },
        )
        for ordinal in range(1, 11)
    ]
    indexer = PageIndexer(
        FakeLlmClient(),
        max_page_num_each_node=100,
        max_token_num_each_node=1_000,
    )

    tree = await indexer.build_tree(
        pages,
        outlines=[
            Outline(
                title="Part I",
                children=[
                    Outline(title="Item 1. Business", destination_page=1),
                    Outline(title="Item 1A. Risk Factors", destination_page=5),
                ],
            ),
            Outline(
                title="Part II",
                children=[Outline(title="Item 7. MD&A", destination_page=10)],
            ),
        ],
    )

    assert tree.page_range == [1, 10]
    assert [child.title for child in tree.children] == ["Part I", "Part II"]
    assert [child.page_range for child in tree.children] == [[1, 9], [10, 10]]
    assert [child.page_range for child in tree.children[0].children] == [
        [1, 4],
        [5, 9],
    ]
    assert indexer.metrics.tree_build_route == "toc_with_page_numbers"
    assert indexer.metrics.toc_direct_builds == 1
    assert indexer.metrics.toc_entries_mapped == 3


@pytest.mark.asyncio
async def test_toc_route_uses_content_spans_for_same_page_sections(tmp_path) -> None:
    pages = [
        Page(
            doc_id="doc-1",
            ordinal=1,
            text="Item 1A. Risk Factors\nRisk opening.\n",
            token_count=5,
            source_locator={
                "kind": "source_page",
                "ordinal_origin": "page_marker",
                "page": 1,
                "source": "memory://doc",
            },
        ),
        Page(
            doc_id="doc-1",
            ordinal=2,
            text="Risk middle.\n",
            token_count=2,
            source_locator={
                "kind": "source_page",
                "ordinal_origin": "page_marker",
                "page": 2,
                "source": "memory://doc",
            },
        ),
        Page(
            doc_id="doc-1",
            ordinal=3,
            text=(
                "Risk tail on shared page.\n"
                "Item 1B. Unresolved Staff Comments\n"
                "None.\n"
                "Item 1C. Cybersecurity\n"
                "Cybersecurity body.\n"
            ),
            token_count=13,
            source_locator={
                "kind": "source_page",
                "ordinal_origin": "page_marker",
                "page": 3,
                "source": "memory://doc",
            },
        ),
    ]
    client = FakeLlmClient()
    indexer = PageIndexer(
        client,
        max_page_num_each_node=100,
        max_token_num_each_node=1_000,
    )

    tree = await indexer.build_tree(
        pages,
        outlines=[
            Outline(
                title="Part I",
                children=[
                    Outline(title="Item 1A. Risk Factors", destination_page=1),
                    Outline(
                        title="Item 1B. Unresolved Staff Comments",
                        destination_page=3,
                    ),
                    Outline(title="Item 1C. Cybersecurity", destination_page=3),
                ],
            )
        ],
    )

    assert client.calls == []
    assert indexer.metrics.recursion_calls == 0
    part_i = tree.children[0]
    assert [child.title for child in part_i.children] == [
        "Item 1A. Risk Factors",
        "Item 1B. Unresolved Staff Comments",
        "Item 1C. Cybersecurity",
    ]
    assert [child.page_range for child in part_i.children] == [
        [1, 3],
        [3, 3],
        [3, 3],
    ]
    assert all(child.content_span is not None for child in part_i.children)

    indexed = IndexedDocument(
        doc_id="doc-1",
        doc_hash="hash-1",
        page_count=3,
        tree=tree,
        metadata={},
    )
    store = IndexStore(tmp_path / "page_index.db")
    store.record(indexed, pages)
    loaded = store.get("hash-1")
    assert loaded is not None
    retriever = TreeRetriever(StaticSelectionLlmClient(["n.1.1", "n.1.3"]))

    result = await retriever.retrieve(
        store=store,
        document=loaded,
        sub_query="Risk and cybersecurity.",
    )

    risk_text = "\n".join(page.text for page in result.selected_nodes[0].pages)
    cyber_text = "\n".join(page.text for page in result.selected_nodes[1].pages)
    assert "Risk tail on shared page" in risk_text
    assert "Item 1B. Unresolved Staff Comments" not in risk_text
    assert "Risk tail on shared page" not in cyber_text
    assert "Item 1C. Cybersecurity" in cyber_text
    assert "Cybersecurity body" in cyber_text


@pytest.mark.asyncio
async def test_page_indexer_falls_back_from_unmapped_toc_to_guided_build() -> None:
    pages = [
        Page(
            doc_id="doc-1",
            ordinal=1,
            text="Contents\nRevenue 2",
            token_count=3,
            source_locator={"kind": "pdf_page", "page": 1},
        ),
        Page(
            doc_id="doc-1",
            ordinal=2,
            text="Revenue body",
            token_count=2,
            source_locator={"kind": "pdf_page", "page": 2},
        ),
    ]
    indexer = PageIndexer(
        TOCGuidedIndexerLlmClient(),
        max_page_num_each_node=100,
        max_token_num_each_node=1_000,
    )

    tree = await indexer.build_tree(
        pages,
        detected_toc=DetectedTOC(
            toc_pages=[1],
            raw_text="[ordinal 1]\nContents\nRevenue 20",
        ),
        outlines=[Outline(title="Missing section", destination_page=20)],
    )

    assert tree.page_range == [1, 2]
    assert indexer.metrics.toc_route_fallbacks == 1
    assert indexer.metrics.tree_build_route == "toc_guided"


@pytest.mark.asyncio
async def test_page_indexer_uses_detected_toc_as_build_guidance() -> None:
    pages = [
        Page(
            doc_id="doc-1",
            ordinal=1,
            text="Contents\nRevenue 2\nRisk Factors 3",
            token_count=5,
            source_locator={"kind": "pdf_page", "page": 1},
        ),
        Page(
            doc_id="doc-1",
            ordinal=2,
            text="Revenue body",
            token_count=2,
            source_locator={"kind": "pdf_page", "page": 2},
        ),
        Page(
            doc_id="doc-1",
            ordinal=3,
            text="Risk Factors body",
            token_count=3,
            source_locator={"kind": "pdf_page", "page": 3},
        ),
    ]
    indexer = PageIndexer(
        TOCGuidedIndexerLlmClient(),
        group_max_tokens=100,
        max_page_num_each_node=100,
        max_token_num_each_node=1_000,
    )

    tree = await indexer.build_tree(
        pages,
        detected_toc=DetectedTOC(
            toc_pages=[1],
            raw_text="[ordinal 1]\nContents\nRevenue 2\nRisk Factors 3",
        ),
    )

    assert tree.page_range == [1, 3]
    assert [child.title for child in tree.children] == ["Revenue", "Risk Factors"]
    assert [child.page_range for child in tree.children] == [[1, 2], [3, 3]]
    assert indexer.metrics.toc_guided_builds == 1
    assert indexer.metrics.toc_pages_used == 1
    assert indexer.metrics.toc_range_adjustments == 2
    assert indexer.metrics.toc_out_of_range_nodes_dropped == 1


@pytest.mark.asyncio
async def test_page_indexer_rejects_unknown_detected_toc_pages() -> None:
    pages = [
        Page(
            doc_id="doc-1",
            ordinal=1,
            text="Only page",
            token_count=2,
            source_locator={"kind": "pdf_page", "page": 1},
        )
    ]
    indexer = PageIndexer(FakeLlmClient())

    with pytest.raises(ValueError, match="unknown page ordinals"):
        await indexer.build_tree(
            pages,
            detected_toc=DetectedTOC(toc_pages=[2], raw_text="[ordinal 2]\nTOC"),
        )


def test_index_store_round_trips_document_and_pages(tmp_path) -> None:
    pages = [
        Page(
            doc_id="doc-1",
            ordinal=0,
            text="alpha beta",
            token_count=2,
            source_locator={"kind": "char_range", "start": 0, "end": 10},
        )
    ]
    document = IndexedDocument(
        doc_id="doc-1",
        doc_hash="hash-1",
        page_count=1,
        tree=TreeNode(
            node_id="n",
            title="Root",
            page_range=[0, 0],
            summary="Only page",
            children=[],
        ),
        metadata={"source": "memory://doc-1"},
    )

    store = IndexStore(tmp_path / "page_index.db")
    store.record(document, pages)

    loaded = store.get("hash-1")
    loaded_by_doc_id = store.get_by_doc_id("doc-1")
    loaded_pages = store.get_pages("hash-1")

    assert loaded == document
    assert loaded_by_doc_id == document
    assert loaded_pages == pages


@pytest.mark.asyncio
async def test_page_indexer_recursively_splits_oversized_nodes() -> None:
    pages = [
        Page(
            doc_id="doc-1",
            ordinal=index,
            text=f"page {index}",
            token_count=2,
            source_locator={"kind": "char_range", "start": index, "end": index + 1},
        )
        for index in range(6)
    ]
    client = FakeLlmClient()
    indexer = PageIndexer(
        client,
        max_page_num_each_node=3,
        max_token_num_each_node=100,
        group_max_tokens=100,
    )

    tree = await indexer.build_tree(pages)

    assert client.calls == [
        "page_index.init",
        "page_index.large_node_recursion.init",
    ]
    assert tree.node_id == "n"
    assert [child.node_id for child in tree.children] == ["n.1", "n.2"]
    assert [child.page_range for child in tree.children] == [[0, 2], [3, 5]]
    assert indexer.metrics.recursion_calls == 1
    assert indexer.metrics.nodes_split == 1
    assert indexer.metrics.max_depth == 2


@pytest.mark.asyncio
async def test_page_indexer_splits_disjoint_recursive_frontier_in_parallel() -> None:
    pages = [
        Page(
            doc_id="doc-1",
            ordinal=index,
            text=f"page {index}",
            token_count=2,
            source_locator={"kind": "char_range", "start": index, "end": index + 1},
        )
        for index in range(8)
    ]
    client = ParallelSplitLlmClient()
    indexer = PageIndexer(
        client,
        max_page_num_each_node=2,
        max_token_num_each_node=100,
        group_max_tokens=100,
        recursion_concurrency=2,
    )

    tree = await indexer.build_tree(pages)

    assert tree.page_range == [0, 7]
    assert client.max_active_recursions == 2
    assert indexer.metrics.recursion_calls == 3
    assert indexer.metrics.recursion_batches == 2
    assert indexer.metrics.max_parallel_recursions == 2
    assert indexer.metrics.nodes_split == 3


@pytest.mark.asyncio
async def test_page_indexer_keeps_oversized_single_page_as_leaf() -> None:
    pages = [
        Page(
            doc_id="doc-1",
            ordinal=0,
            text="large page",
            token_count=50,
            source_locator={"kind": "char_range", "start": 0, "end": 10},
        )
    ]
    client = SinglePageLlmClient()
    indexer = PageIndexer(
        client,
        max_page_num_each_node=3,
        max_token_num_each_node=10,
        group_max_tokens=100,
    )

    tree = await indexer.build_tree(pages)

    assert client.calls == ["page_index.init"]
    assert tree.children == []
    assert indexer.metrics.single_page_skips == 1
    assert indexer.metrics.recursion_calls == 0


@pytest.mark.asyncio
async def test_page_indexer_merges_continue_delta_without_rewriting_tree() -> None:
    pages = [
        Page(
            doc_id="doc-1",
            ordinal=index,
            text=f"page {index}",
            token_count=10,
            source_locator={"kind": "char_range", "start": index, "end": index + 1},
        )
        for index in range(4)
    ]
    client = ContinueDeltaLlmClient()
    indexer = PageIndexer(
        client,
        group_max_tokens=20,
        overlap_page=0,
        max_page_num_each_node=100,
        max_token_num_each_node=1_000,
    )

    tree = await indexer.build_tree(pages)

    assert client.calls == ["page_index.init", "page_index.continue"]
    assert tree.page_range == [0, 3]
    assert tree.summary == "Combined document"
    assert [(child.title, child.page_range) for child in tree.children] == [
        ("Part A", [0, 1]),
        ("Part B", [2, 3]),
    ]


@pytest.mark.asyncio
async def test_tree_retriever_selects_nodes_and_lazy_loads_pages(tmp_path) -> None:
    pages = [
        Page(
            doc_id="doc-1",
            ordinal=1,
            text="first page raw text",
            token_count=4,
            source_locator={"kind": "source_page", "page": 1},
        ),
        Page(
            doc_id="doc-1",
            ordinal=2,
            text="second page raw text",
            token_count=4,
            source_locator={"kind": "source_page", "page": 2},
        ),
    ]
    tree = TreeNode(
        node_id="n",
        title="Root",
        page_range=[1, 2],
        summary="Root summary",
        children=[
            TreeNode(
                node_id="n.1",
                title="First section",
                page_range=[1, 1],
                summary="First summary",
                children=[],
            ),
            TreeNode(
                node_id="n.2",
                title="Second section",
                page_range=[2, 2],
                summary="Second summary",
                children=[],
            ),
        ],
    )
    indexed = IndexedDocument(
        doc_id="doc-1",
        doc_hash="hash-1",
        page_count=2,
        tree=tree,
        metadata={},
    )
    store = IndexStore(tmp_path / "page_index.db")
    store.record(indexed, pages)
    retriever = TreeRetriever(RetrieverLlmClient())

    selection = await retriever.select(
        doc_id="doc-1",
        tree=tree,
        sub_query="Find the second section.",
    )
    result = await retriever.retrieve(
        store=store,
        document=indexed,
        sub_query="Find the second section.",
    )
    result_batch = await retriever.retrieve_many(
        store=store,
        document=indexed,
        sub_queries=["Find the second section.", "Find it again."],
        concurrency=2,
    )
    loaded_pages = retriever.get_page_content(
        store=store,
        doc_hash="hash-1",
        tree=tree,
        node_id=selection.selected_node_ids[0],
    )

    assert selection.selected_node_ids == ["n.2"]
    assert result.selection.selected_node_ids == ["n.2"]
    assert [item.selection.selected_node_ids for item in result_batch] == [
        ["n.2"],
        ["n.2"],
    ]
    assert result.selected_nodes[0].node_id == "n.2"
    assert [page.ordinal for page in loaded_pages] == [2]
    assert loaded_pages[0].text == "second page raw text"


@pytest.mark.asyncio
async def test_tree_retriever_refines_large_parent_to_specific_child(tmp_path) -> None:
    pages = [
        Page(
            doc_id="doc-1",
            ordinal=ordinal,
            text=f"page {ordinal} raw text",
            token_count=1,
            source_locator={"kind": "source_page", "page": ordinal},
        )
        for ordinal in range(1, 7)
    ]
    tree = TreeNode(
        node_id="n",
        title="Root",
        page_range=[1, 6],
        summary="Root summary",
        children=[
            TreeNode(
                node_id="n.1",
                title="Large parent",
                page_range=[1, 6],
                summary="Large parent summary",
                children=[
                    TreeNode(
                        node_id="n.1.1",
                        title="First child",
                        page_range=[1, 3],
                        summary="First child summary",
                        children=[],
                    ),
                    TreeNode(
                        node_id="n.1.2",
                        title="Specific child",
                        page_range=[4, 4],
                        summary="Specific child summary",
                        children=[],
                    ),
                ],
            )
        ],
    )
    indexed = IndexedDocument(
        doc_id="doc-1",
        doc_hash="hash-1",
        page_count=6,
        tree=tree,
        metadata={},
    )
    store = IndexStore(tmp_path / "page_index.db")
    store.record(indexed, pages)
    client = ParentThenChildSelectionLlmClient()
    retriever = TreeRetriever(client, max_evidence_pages_per_node=2)

    result = await retriever.retrieve(
        store=store,
        document=indexed,
        sub_query="Find the specific child.",
    )

    assert client.calls == [
        "page_index.retrieve.select",
        "page_index.retrieve.refine",
    ]
    assert result.selection.selected_node_ids == ["n.1.2"]
    assert result.selected_nodes[0].node_id == "n.1.2"
    assert [page.ordinal for page in result.selected_nodes[0].pages] == [4]
    assert "Refined large routing nodes" in result.selection.reasoning


@pytest.mark.asyncio
async def test_tree_retriever_falls_back_to_children_when_parent_is_reselected(
    tmp_path,
) -> None:
    pages = [
        Page(
            doc_id="doc-1",
            ordinal=ordinal,
            text=f"page {ordinal} raw text",
            token_count=1,
            source_locator={"kind": "source_page", "page": ordinal},
        )
        for ordinal in range(1, 3)
    ]
    tree = TreeNode(
        node_id="n",
        title="Root",
        page_range=[1, 2],
        summary="Root summary",
        children=[
            TreeNode(
                node_id="n.1",
                title="Large parent",
                page_range=[1, 2],
                summary="Large parent summary",
                children=[
                    TreeNode(
                        node_id="n.1.1",
                        title="First child",
                        page_range=[1, 1],
                        summary="First child summary",
                        children=[],
                    ),
                    TreeNode(
                        node_id="n.1.2",
                        title="Second child",
                        page_range=[2, 2],
                        summary="Second child summary",
                        children=[],
                    ),
                ],
            )
        ],
    )
    indexed = IndexedDocument(
        doc_id="doc-1",
        doc_hash="hash-1",
        page_count=2,
        tree=tree,
        metadata={},
    )
    store = IndexStore(tmp_path / "page_index.db")
    store.record(indexed, pages)
    retriever = TreeRetriever(
        ParentReselectingLlmClient(),
        max_evidence_pages_per_node=1,
    )

    result = await retriever.retrieve(
        store=store,
        document=indexed,
        sub_query="Find the parent section.",
    )

    assert result.selection.selected_node_ids == ["n.1.1", "n.1.2"]
    assert [node.node_id for node in result.selected_nodes] == ["n.1.1", "n.1.2"]
    assert [node.pages[0].ordinal for node in result.selected_nodes] == [1, 2]


@pytest.mark.asyncio
async def test_page_index_retrieve_tool_returns_selected_pages(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [
        Page(
            doc_id="doc-1",
            ordinal=1,
            text="first page raw text",
            token_count=4,
            source_locator={"kind": "source_page", "source": "memory://doc", "page": 1},
        ),
        Page(
            doc_id="doc-1",
            ordinal=2,
            text="second page raw text",
            token_count=4,
            source_locator={"kind": "source_page", "source": "memory://doc", "page": 2},
        ),
    ]
    tree = TreeNode(
        node_id="n",
        title="Root",
        page_range=[1, 2],
        summary="Root summary",
        children=[
            TreeNode(
                node_id="n.2",
                title="Second section",
                page_range=[2, 2],
                summary="Second summary",
                children=[],
            )
        ],
    )
    db_path = tmp_path / "page_index.db"
    IndexStore(db_path).record(
        IndexedDocument(
            doc_id="doc-1",
            doc_hash="hash-1",
            page_count=2,
            tree=tree,
            metadata={},
        ),
        pages,
    )
    monkeypatch.setattr(
        "valuator.tools.page_index_tool.create_llm_client",
        lambda **kwargs: RetrieverLlmClient(),
    )

    result = await PageIndexRetrieveTool(db_path=db_path).execute(
        doc_id="doc-1",
        query="Find the second section.",
        max_page_chars=6,
    )

    assert result.success is True
    assert result.result["selected_node_ids"] == ["n.2"]
    assert result.result["selected_nodes"][0]["pages"][0]["text"].startswith("second")
    assert result.metadata["sources"] == ["memory://doc#page=2"]
