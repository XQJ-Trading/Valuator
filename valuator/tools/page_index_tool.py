from __future__ import annotations

from pathlib import Path
from typing import Any

from valuator.documents import IndexStore, RetrievalResult, TreeRetriever
from valuator.models.factory import create_llm_client
from valuator.utils.config import ROOT_DIR, config

from .base import BaseTool, ToolResult

DEFAULT_PAGE_INDEX_DB_PATH = ROOT_DIR / "data" / "page_index.db"


class PageIndexRetrieveTool(BaseTool):
    def __init__(
        self,
        *,
        db_path: str | Path = DEFAULT_PAGE_INDEX_DB_PATH,
        model: str | None = None,
        usage_writer: Any | None = None,
    ) -> None:
        super().__init__(
            "page_index_retrieve",
            "Retrieve relevant pages from an indexed document tree by doc_id/query.",
        )
        self.db_path = Path(db_path)
        self.client = create_llm_client(
            model=model or config.agent_model,
            usage_writer=usage_writer,
        )

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        self.client.bind_usage_writer(usage_writer)

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        doc_id = str(kwargs.get("doc_id") or "").strip()
        doc_hash = str(kwargs.get("doc_hash") or "").strip()
        max_page_chars = int(kwargs.get("max_page_chars") or 1200)
        if not query:
            return ToolResult(success=False, result=None, error="'query' is required")
        if not doc_id and not doc_hash:
            return ToolResult(
                success=False,
                result=None,
                error="either 'doc_id' or 'doc_hash' is required",
            )

        store = IndexStore(self.db_path)
        document = store.get(doc_hash) if doc_hash else store.get_by_doc_id(doc_id)
        if document is None:
            key = f"doc_hash={doc_hash}" if doc_hash else f"doc_id={doc_id}"
            return ToolResult(
                success=False,
                result=None,
                error=f"indexed document not found for {key}",
            )

        result = await TreeRetriever(self.client).retrieve(
            store=store,
            document=document,
            sub_query=query,
        )
        payload = retrieval_payload(result, max_page_chars=max_page_chars)
        return ToolResult(
            success=True,
            result=payload,
            metadata={
                "doc_id": document.doc_id,
                "doc_hash": document.doc_hash,
                "selected_node_ids": result.selection.selected_node_ids,
                "sources": citation_sources(payload),
            },
        )


def retrieval_payload(
    result: RetrievalResult,
    *,
    max_page_chars: int,
) -> dict[str, Any]:
    selected_nodes: list[dict[str, Any]] = []
    for node in result.selected_nodes:
        selected_nodes.append(
            {
                "node_id": node.node_id,
                "title": node.title,
                "page_range": node.page_range,
                "content_span": (
                    node.content_span.model_dump(mode="json")
                    if node.content_span is not None
                    else None
                ),
                "summary": node.summary,
                "pages": [
                    {
                        "ordinal": page.ordinal,
                        "source_locator": page.source_locator,
                        "text": _page_text(page.text, max_page_chars),
                    }
                    for page in node.pages
                ],
            }
        )
    return {
        "doc_id": result.doc_id,
        "doc_hash": result.doc_hash,
        "query": result.query,
        "reasoning": result.selection.reasoning,
        "selected_node_ids": result.selection.selected_node_ids,
        "selected_nodes": selected_nodes,
    }


def citation_sources(payload: dict[str, Any]) -> list[str]:
    sources: list[str] = []
    for node in payload["selected_nodes"]:
        for page in node["pages"]:
            locator = page.get("source_locator") or {}
            source = str(locator.get("source") or "")
            page_number = locator.get("page")
            if source and page_number is not None:
                sources.append(f"{source}#page={page_number}")
            elif source:
                sources.append(source)
    return sources


def _page_text(text: str, max_chars: int) -> str:
    if max_chars < 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n...[truncated]"
