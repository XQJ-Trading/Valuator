from __future__ import annotations

import json
from typing import Any

from valuator.models.protocol import LlmClient

from .store import IndexStore
from .types import (
    IndexedDocument,
    NodeSelection,
    Page,
    RetrievedNode,
    RetrievalResult,
    TreeNode,
)

TREE_RETRIEVER_SYSTEM_PROMPT = (
    "Return JSON only. Select the document tree nodes most relevant to the query. "
    "Use only node_id values present in the provided structure."
)

SELECT_PROMPT = (
    "Document id: {doc_id}\n\n"
    "Document structure without page text:\n{structure_json}\n\n"
    "Query:\n{sub_query}\n\n"
    "Return selected node ids and concise reasoning."
)

NODE_SELECTION_RESPONSE_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["doc_id", "selected_node_ids", "reasoning"],
    "properties": {
        "doc_id": {"type": "string"},
        "selected_node_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "reasoning": {"type": "string"},
    },
}


class TreeRetriever:
    def __init__(self, client: LlmClient) -> None:
        self.client = client

    async def select(
        self,
        *,
        doc_id: str,
        tree: TreeNode,
        sub_query: str,
        trace_method: str = "page_index.retrieve.select",
    ) -> NodeSelection:
        structure_json = json.dumps(
            self.get_document_structure(tree),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        data = await self.client.generate_json(
            prompt=SELECT_PROMPT.format(
                doc_id=doc_id,
                structure_json=structure_json,
                sub_query=sub_query,
            ),
            system_prompt=TREE_RETRIEVER_SYSTEM_PROMPT,
            response_json_schema=NODE_SELECTION_RESPONSE_JSON_SCHEMA,
            trace_method=trace_method,
        )
        selection = NodeSelection.model_validate(data)
        if selection.doc_id != doc_id:
            raise ValueError(
                f"selection doc_id {selection.doc_id!r} does not match {doc_id!r}"
            )
        known_ids = {node.node_id for node in self._walk_nodes(tree)}
        unknown_ids = [
            node_id
            for node_id in selection.selected_node_ids
            if node_id not in known_ids
        ]
        if unknown_ids:
            raise ValueError(f"selection contains unknown node ids: {unknown_ids}")
        return selection

    async def retrieve(
        self,
        *,
        store: IndexStore,
        document: IndexedDocument,
        sub_query: str,
        trace_method: str = "page_index.retrieve.select",
    ) -> RetrievalResult:
        selection = await self.select(
            doc_id=document.doc_id,
            tree=document.tree,
            sub_query=sub_query,
            trace_method=trace_method,
        )
        return RetrievalResult(
            doc_id=document.doc_id,
            doc_hash=document.doc_hash,
            query=sub_query,
            selection=selection,
            selected_nodes=[
                self.get_node_content(
                    store=store,
                    doc_hash=document.doc_hash,
                    tree=document.tree,
                    node_id=node_id,
                )
                for node_id in selection.selected_node_ids
            ],
        )

    def get_document_structure(self, tree: TreeNode) -> dict[str, Any]:
        return {
            "node_id": tree.node_id,
            "title": tree.title,
            "page_range": tree.page_range,
            "summary": tree.summary,
            "children": [
                self.get_document_structure(child) for child in tree.children
            ],
        }

    def get_page_content(
        self,
        *,
        store: IndexStore,
        doc_hash: str,
        tree: TreeNode,
        node_id: str,
    ) -> list[Page]:
        node = self.find_node(tree, node_id)
        return store.get_pages(
            doc_hash,
            start=node.page_range[0],
            end=node.page_range[1],
        )

    def get_node_content(
        self,
        *,
        store: IndexStore,
        doc_hash: str,
        tree: TreeNode,
        node_id: str,
    ) -> RetrievedNode:
        node = self.find_node(tree, node_id)
        return RetrievedNode(
            node_id=node.node_id,
            title=node.title,
            page_range=node.page_range,
            summary=node.summary,
            pages=self.get_page_content(
                store=store,
                doc_hash=doc_hash,
                tree=tree,
                node_id=node_id,
            ),
        )

    def find_node(self, tree: TreeNode, node_id: str) -> TreeNode:
        for node in self._walk_nodes(tree):
            if node.node_id == node_id:
                return node
        raise ValueError(f"unknown node_id: {node_id}")

    def _walk_nodes(self, node: TreeNode) -> list[TreeNode]:
        nodes = [node]
        for child in node.children:
            nodes.extend(self._walk_nodes(child))
        return nodes
