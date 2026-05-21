from __future__ import annotations

import re
from typing import Any

import pytest

from valuator.documents import (
    DocumentIngest,
    IndexStore,
    IndexedDocument,
    Page,
    PageMarkerPattern,
    PageIndexer,
    RawDocument,
    TreeRetriever,
    TreeNode,
    document_hash,
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
        "start": 11,
        "end": 22,
    }
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
    assert pages[0].source_locator["page"] == 1
    assert pages[1].text.startswith("Risk factors")


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
    loaded_pages = retriever.get_page_content(
        store=store,
        doc_hash="hash-1",
        tree=tree,
        node_id=selection.selected_node_ids[0],
    )

    assert selection.selected_node_ids == ["n.2"]
    assert result.selection.selected_node_ids == ["n.2"]
    assert result.selected_nodes[0].node_id == "n.2"
    assert [page.ordinal for page in loaded_pages] == [2]
    assert loaded_pages[0].text == "second page raw text"


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
