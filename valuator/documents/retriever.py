from __future__ import annotations

import asyncio
import json
from typing import Any

from valuator.models.protocol import LlmClient

from .sections import DocumentPosition, SectionSpan, section_pages
from .store import IndexStore
from .types import (
    ContentSpan,
    IndexedDocument,
    NodeSelection,
    Page,
    RetrievedNode,
    RetrievalResult,
    TreeNode,
)

DEFAULT_MAX_EVIDENCE_PAGES_PER_NODE = 5
DEFAULT_MAX_EVIDENCE_TOKENS_PER_NODE = 20_000
DEFAULT_MAX_REFINEMENT_DEPTH = 6

TREE_RETRIEVER_SYSTEM_PROMPT = (
    "Return JSON only. Select the document tree nodes most relevant to the query. "
    "Use only node_id values present in the provided structure. Prefer the smallest "
    "nodes that fully cover the needed evidence; use broad parent nodes only for "
    "routing when their children are insufficient."
)

SELECT_PROMPT = (
    "Document id: {doc_id}\n\n"
    "Document structure without page text:\n{structure_json}\n\n"
    "Query:\n{sub_query}\n\n"
    "Return selected node ids and concise reasoning. If a relevant node has "
    "children, prefer the most specific child or descendant nodes that answer "
    "the query."
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
    def __init__(
        self,
        client: LlmClient,
        *,
        max_evidence_pages_per_node: int = DEFAULT_MAX_EVIDENCE_PAGES_PER_NODE,
        max_evidence_tokens_per_node: int = DEFAULT_MAX_EVIDENCE_TOKENS_PER_NODE,
        max_refinement_depth: int = DEFAULT_MAX_REFINEMENT_DEPTH,
    ) -> None:
        if max_evidence_pages_per_node <= 0:
            raise ValueError("max_evidence_pages_per_node must be > 0")
        if max_evidence_tokens_per_node <= 0:
            raise ValueError("max_evidence_tokens_per_node must be > 0")
        if max_refinement_depth < 0:
            raise ValueError("max_refinement_depth must be >= 0")
        self.client = client
        self.max_evidence_pages_per_node = max_evidence_pages_per_node
        self.max_evidence_tokens_per_node = max_evidence_tokens_per_node
        self.max_refinement_depth = max_refinement_depth

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
        routing_selection = await self.select(
            doc_id=document.doc_id,
            tree=document.tree,
            sub_query=sub_query,
            trace_method=trace_method,
        )
        evidence_node_ids, refinement_notes = await self._refine_selection(
            store=store,
            document=document,
            sub_query=sub_query,
            selected_node_ids=routing_selection.selected_node_ids,
        )
        evidence_node_ids = self._drop_selected_ancestors(
            document.tree,
            self._dedupe_node_ids(evidence_node_ids),
        )
        evidence_node_ids = self._merge_selected_siblings(
            store=store,
            doc_hash=document.doc_hash,
            tree=document.tree,
            selected_node_ids=evidence_node_ids,
        )
        selection = NodeSelection(
            doc_id=document.doc_id,
            selected_node_ids=evidence_node_ids,
            reasoning=self._selection_reasoning(
                routing_selection.reasoning,
                refinement_notes,
            ),
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

    async def retrieve_many(
        self,
        *,
        store: IndexStore,
        document: IndexedDocument,
        sub_queries: list[str],
        concurrency: int = 4,
    ) -> list[RetrievalResult]:
        if concurrency <= 0:
            raise ValueError("concurrency must be > 0")
        semaphore = asyncio.Semaphore(concurrency)

        async def guarded(sub_query: str) -> RetrievalResult:
            async with semaphore:
                return await self.retrieve(
                    store=store,
                    document=document,
                    sub_query=sub_query,
                )

        return list(await asyncio.gather(*(guarded(query) for query in sub_queries)))

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
        if node.content_span is not None:
            return section_pages(
                self._section_span_from_content_span(node.content_span),
                store.get_pages(
                    doc_hash,
                    start=node.content_span.page_range[0],
                    end=node.content_span.page_range[1],
                ),
            )
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
            content_span=node.content_span,
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

    async def _refine_selection(
        self,
        *,
        store: IndexStore,
        document: IndexedDocument,
        sub_query: str,
        selected_node_ids: list[str],
    ) -> tuple[list[str], list[str]]:
        evidence_node_ids: list[str] = []
        refinement_notes: list[str] = []
        for node_id in selected_node_ids:
            node = self.find_node(document.tree, node_id)
            refined_ids = await self._refine_node_for_evidence(
                store=store,
                doc_id=document.doc_id,
                doc_hash=document.doc_hash,
                node=node,
                sub_query=sub_query,
                depth=0,
            )
            evidence_node_ids.extend(refined_ids)
            if refined_ids != [node_id]:
                refinement_notes.append(
                    f"{node_id} -> {', '.join(refined_ids)}"
                )
        return evidence_node_ids, refinement_notes

    async def _refine_node_for_evidence(
        self,
        *,
        store: IndexStore,
        doc_id: str,
        doc_hash: str,
        node: TreeNode,
        sub_query: str,
        depth: int,
    ) -> list[str]:
        if (
            not self._node_exceeds_evidence_limits(
                store=store,
                doc_hash=doc_hash,
                node=node,
            )
            or not node.children
            or depth >= self.max_refinement_depth
        ):
            return [node.node_id]

        selection = await self.select(
            doc_id=doc_id,
            tree=node,
            sub_query=sub_query,
            trace_method="page_index.retrieve.refine",
        )
        selected_ids = [
            node_id
            for node_id in self._dedupe_node_ids(selection.selected_node_ids)
            if node_id != node.node_id
        ]
        if not selected_ids:
            selected_ids = [child.node_id for child in node.children]

        refined_ids: list[str] = []
        for node_id in selected_ids:
            child_or_descendant = self.find_node(node, node_id)
            refined_ids.extend(
                await self._refine_node_for_evidence(
                    store=store,
                    doc_id=doc_id,
                    doc_hash=doc_hash,
                    node=child_or_descendant,
                    sub_query=sub_query,
                    depth=depth + 1,
                )
            )
        return refined_ids

    def _node_exceeds_evidence_limits(
        self,
        *,
        store: IndexStore,
        doc_hash: str,
        node: TreeNode,
    ) -> bool:
        if self._node_page_count(node) > self.max_evidence_pages_per_node:
            return True
        return (
            sum(
                page.token_count
                for page in self.get_page_content(
                    store=store,
                    doc_hash=doc_hash,
                    tree=node,
                    node_id=node.node_id,
                )
            )
            > self.max_evidence_tokens_per_node
        )

    def _merge_selected_siblings(
        self,
        *,
        store: IndexStore,
        doc_hash: str,
        tree: TreeNode,
        selected_node_ids: list[str],
    ) -> list[str]:
        selected = set(selected_node_ids)
        changed = True
        while changed:
            changed = False
            for node in reversed(self._walk_nodes(tree)):
                child_ids = [child.node_id for child in node.children]
                if (
                    child_ids
                    and all(child_id in selected for child_id in child_ids)
                    and self._children_cover_node(node)
                    and not self._node_exceeds_evidence_limits(
                        store=store,
                        doc_hash=doc_hash,
                        node=node,
                    )
                ):
                    selected.difference_update(child_ids)
                    selected.add(node.node_id)
                    changed = True

        order = {
            node.node_id: index
            for index, node in enumerate(self._walk_nodes(tree))
        }
        return sorted(selected, key=lambda node_id: order[node_id])

    def _drop_selected_ancestors(
        self,
        tree: TreeNode,
        selected_node_ids: list[str],
    ) -> list[str]:
        selected = set(selected_node_ids)
        nodes_by_id = {node.node_id: node for node in self._walk_nodes(tree)}
        return [
            node_id
            for node_id in selected_node_ids
            if not any(
                descendant.node_id in selected
                for descendant in self._walk_nodes(nodes_by_id[node_id])
                if descendant.node_id != node_id
            )
        ]

    @staticmethod
    def _dedupe_node_ids(node_ids: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for node_id in node_ids:
            if node_id in seen:
                continue
            seen.add(node_id)
            deduped.append(node_id)
        return deduped

    @staticmethod
    def _node_page_count(node: TreeNode) -> int:
        page_range = (
            node.content_span.page_range
            if node.content_span is not None
            else node.page_range
        )
        return page_range[1] - page_range[0] + 1

    @staticmethod
    def _children_cover_node(node: TreeNode) -> bool:
        if not node.children:
            return False
        child_ranges = sorted(
            (
                child.content_span.page_range
                if child.content_span is not None
                else child.page_range
            )
            for child in node.children
        )
        node_range = (
            node.content_span.page_range
            if node.content_span is not None
            else node.page_range
        )
        covered_start = child_ranges[0][0]
        covered_end = child_ranges[0][1]
        for start, end in child_ranges[1:]:
            if start > covered_end + 1:
                return False
            covered_end = max(covered_end, end)
        return covered_start <= node_range[0] and covered_end >= node_range[1]

    @staticmethod
    def _selection_reasoning(
        routing_reasoning: str,
        refinement_notes: list[str],
    ) -> str:
        if not refinement_notes:
            return routing_reasoning
        return (
            f"{routing_reasoning}\n\n"
            "Refined large routing nodes to evidence nodes: "
            f"{'; '.join(refinement_notes)}."
        )

    @staticmethod
    def _section_span_from_content_span(span: ContentSpan) -> SectionSpan:
        return SectionSpan(
            start=DocumentPosition(
                page_ordinal=span.start.page_ordinal,
                local_offset=span.start.local_offset,
                source_offset=span.start.source_offset,
            ),
            end=DocumentPosition(
                page_ordinal=span.end.page_ordinal,
                local_offset=span.end.local_offset,
                source_offset=span.end.source_offset,
            ),
            page_range=(span.page_range[0], span.page_range[1]),
        )

    def _walk_nodes(self, node: TreeNode) -> list[TreeNode]:
        nodes = [node]
        for child in node.children:
            nodes.extend(self._walk_nodes(child))
        return nodes
