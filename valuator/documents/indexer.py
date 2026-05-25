from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from valuator.models.protocol import LlmClient

from .ingest import pages_have_mappable_page_ordinals
from .toc import remove_detected_toc_from_pages, toc_guidance_text
from .types import DetectedTOC, Outline, Page, TreeNode

DEFAULT_GROUP_TOKENS = 20_000
DEFAULT_MAX_PAGE_NUM_EACH_NODE = 5
DEFAULT_MAX_TOKEN_NUM_EACH_NODE = 20_000
DEFAULT_MAX_RECURSION_DEPTH = 4
DEFAULT_RECURSION_CONCURRENCY = 4

PAGE_INDEX_SYSTEM_PROMPT = (
    "Return JSON only. Build a hierarchical document tree from the provided pages. "
    "Use inclusive page_range ordinals exactly as shown in [ordinal N] input markers. "
    "Do not copy table-of-contents page numbers unless they match an ordinal marker. "
    "Keep titles concise, summaries factual, and children ordered by document order. "
    "Do not invent page numbers or facts outside the provided pages."
)

INIT_PROMPT = (
    "Create the initial document tree from these pages.\n\n"
    "{group_text}\n\n"
    "Return a single root TreeNode covering the provided pages."
)

TOC_GUIDED_INIT_PROMPT = (
    "Create the initial document tree from these document pages, using the detected "
    "table of contents as the preferred outline when it matches the body text.\n\n"
    "Detected table-of-contents text. This is outline guidance only, not body "
    "page input and not a source of page_range ordinals:\n{toc_text}\n\n"
    "Document pages:\n{group_text}\n\n"
    "Do not create sections solely for the table-of-contents listing. Return a "
    "single root TreeNode covering the provided document pages."
)

CONTINUE_PROMPT = (
    "Extend the existing document tree with the next pages.\n\n"
    "Existing tree JSON:\n{tree_json}\n\n"
    "Next pages:\n{group_text}\n\n"
    "Return only a delta: updated root metadata and top-level child nodes that "
    "start in or materially continue through the next pages. Do not repeat "
    "unchanged previous child nodes."
)

TOC_GUIDED_CONTINUE_PROMPT = (
    "Extend the existing document tree with the next document pages, using the "
    "detected table of contents as the preferred outline when it matches the "
    "body text.\n\n"
    "Detected table-of-contents text. This is outline guidance only, not body "
    "page input and not a source of page_range ordinals:\n{toc_text}\n\n"
    "Existing tree JSON:\n{tree_json}\n\n"
    "Next document pages:\n{group_text}\n\n"
    "Return only a delta: updated root metadata and top-level child nodes that "
    "start in or materially continue through the next document pages. Do not "
    "repeat unchanged previous child nodes."
)

TREE_NODE_RESPONSE_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["node_id", "title", "page_range", "summary", "children"],
    "properties": {
        "node_id": {"type": "string"},
        "title": {"type": "string"},
        "page_range": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {"type": "integer"},
        },
        "summary": {"type": "string"},
        "children": {
            "type": "array",
            "items": {"$ref": "#/$defs/TreeNode"},
        },
    },
    "$defs": {
        "TreeNode": {
            "type": "object",
            "additionalProperties": False,
            "required": ["node_id", "title", "page_range", "summary", "children"],
            "properties": {
                "node_id": {"type": "string"},
                "title": {"type": "string"},
                "page_range": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": {"type": "integer"},
                },
                "summary": {"type": "string"},
                "children": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/TreeNode"},
                },
            },
        }
    },
}

TREE_CONTINUATION_RESPONSE_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "page_range", "summary", "children"],
    "properties": {
        "title": {"type": "string"},
        "page_range": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {"type": "integer"},
        },
        "summary": {"type": "string"},
        "children": {
            "type": "array",
            "items": {"$ref": "#/$defs/TreeNode"},
        },
    },
    "$defs": TREE_NODE_RESPONSE_JSON_SCHEMA["$defs"],
}


class TreeContinuation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    page_range: list[int] = Field(min_length=2, max_length=2)
    summary: str
    children: list[TreeNode] = Field(default_factory=list)


@dataclass(frozen=True)
class PageGroup:
    pages: list[Page]
    text: str
    token_count: int


@dataclass
class PageIndexMetrics:
    init_calls: int = 0
    continue_calls: int = 0
    tree_build_route: str = ""
    toc_direct_builds: int = 0
    toc_route_fallbacks: int = 0
    toc_entries: int = 0
    toc_entries_mapped: int = 0
    toc_guided_builds: int = 0
    toc_pages_used: int = 0
    toc_text_removed_pages: int = 0
    toc_range_adjustments: int = 0
    toc_out_of_range_nodes_dropped: int = 0
    recursion_calls: int = 0
    nodes_split: int = 0
    no_progress_skips: int = 0
    max_depth_skips: int = 0
    single_page_skips: int = 0
    recursion_fallback_splits: int = 0
    max_depth: int = 0
    recursion_batches: int = 0
    max_parallel_recursions: int = 0


@dataclass(frozen=True)
class _Violation:
    node: TreeNode
    depth: int


class PageIndexer:
    def __init__(
        self,
        client: LlmClient,
        *,
        group_max_tokens: int = DEFAULT_GROUP_TOKENS,
        overlap_page: int = 1,
        max_page_num_each_node: int = DEFAULT_MAX_PAGE_NUM_EACH_NODE,
        max_token_num_each_node: int = DEFAULT_MAX_TOKEN_NUM_EACH_NODE,
        max_recursion_depth: int = DEFAULT_MAX_RECURSION_DEPTH,
        recursion_concurrency: int = DEFAULT_RECURSION_CONCURRENCY,
    ) -> None:
        if recursion_concurrency <= 0:
            raise ValueError("recursion_concurrency must be > 0")
        self.client = client
        self.group_max_tokens = group_max_tokens
        self.overlap_page = overlap_page
        self.max_page_num_each_node = max_page_num_each_node
        self.max_token_num_each_node = max_token_num_each_node
        self.max_recursion_depth = max_recursion_depth
        self.recursion_concurrency = recursion_concurrency
        self.metrics = PageIndexMetrics()

    async def build_tree(
        self,
        pages: list[Page],
        *,
        detected_toc: DetectedTOC | None = None,
        outlines: list[Outline] | None = None,
        toc_entries: list[Outline] | None = None,
    ) -> TreeNode:
        self.metrics = PageIndexMetrics()
        outlines = outlines if outlines is not None else toc_entries
        build_pages = pages
        trace_method_prefix = "page_index"
        toc_text = ""
        if detected_toc is not None:
            self._reject_unknown_toc_pages(pages, detected_toc)
            self.metrics.toc_pages_used = len(detected_toc.toc_pages)
            build_pages = remove_detected_toc_from_pages(pages, detected_toc)
            self.metrics.toc_text_removed_pages = sum(
                1 for page in build_pages if page.source_locator.get("toc_removed")
            )
            trace_method_prefix = "page_index.toc_guided"
            toc_text = toc_guidance_text(detected_toc)

        tree = self._tree_from_outlines(outlines, build_pages)
        if tree is not None:
            await self._split_large_nodes(tree, build_pages)
            self._assign_stable_node_ids(tree)
            self.metrics.max_depth = self._tree_depth(tree)
            return tree

        if outlines:
            self.metrics.toc_route_fallbacks += 1

        tree = await self._process_no_toc(
            build_pages,
            trace_method_prefix=trace_method_prefix,
            toc_text=toc_text,
        )
        if self.metrics.tree_build_route == "":
            self.metrics.tree_build_route = (
                "toc_guided" if toc_text else "process_no_toc"
            )
        if toc_text:
            self.metrics.toc_guided_builds += 1
        await self._split_large_nodes(tree, build_pages)
        self._assign_stable_node_ids(tree)
        self.metrics.max_depth = self._tree_depth(tree)
        return tree

    def _tree_from_outlines(
        self,
        outlines: list[Outline] | None,
        pages: list[Page],
    ) -> TreeNode | None:
        if not outlines:
            return None
        self.metrics.toc_entries = self._outline_count(outlines)
        if not pages_have_mappable_page_ordinals(pages):
            return None
        page_ordinals = {page.ordinal for page in pages}
        self.metrics.toc_entries_mapped = self._mapped_outline_count(
            outlines,
            page_ordinals,
        )
        start = min(page.ordinal for page in pages)
        end = max(page.ordinal for page in pages)
        children = self._outline_nodes(
            outlines,
            parent_start=start,
            parent_end=end,
            page_ordinals=page_ordinals,
        )
        if not children:
            return None
        tree = TreeNode(
            node_id="toc-root",
            title="Document",
            page_range=[start, end],
            summary="Document tree built from the detected table of contents.",
            children=children,
        )
        self._reject_unknown_page_ranges(tree, pages)
        self.metrics.toc_direct_builds += 1
        self.metrics.tree_build_route = "toc_with_page_numbers"
        return tree

    def _outline_nodes(
        self,
        outlines: list[Outline],
        *,
        parent_start: int,
        parent_end: int,
        page_ordinals: set[int],
    ) -> list[TreeNode]:
        resolved = [
            (outline, start)
            for outline in outlines
            for start in [self._outline_start(outline, page_ordinals)]
            if start is not None and parent_start <= start <= parent_end
        ]
        resolved.sort(key=lambda item: item[1])

        nodes: list[TreeNode] = []
        for index, (outline, start) in enumerate(resolved):
            next_start = next(
                (
                    later_start
                    for _, later_start in resolved[index + 1 :]
                    if later_start > start
                ),
                None,
            )
            end = parent_end if next_start is None else min(parent_end, next_start - 1)
            if index + 1 < len(resolved) and resolved[index + 1][1] == start:
                end = start
            children = self._outline_nodes(
                outline.children,
                parent_start=start,
                parent_end=max(start, end),
                page_ordinals=page_ordinals,
            )
            nodes.append(
                TreeNode(
                    node_id=f"toc-{len(nodes) + 1}",
                    title=outline.title,
                    page_range=[start, max(start, end)],
                    summary=f"{outline.title} section from the detected table of contents.",
                    children=children,
                )
            )
        return nodes

    @classmethod
    def _outline_start(cls, outline: Outline, page_ordinals: set[int]) -> int | None:
        if outline.destination_page in page_ordinals:
            return outline.destination_page
        child_starts = [
            start
            for child in outline.children
            for start in [cls._outline_start(child, page_ordinals)]
            if start is not None
        ]
        return min(child_starts) if child_starts else None

    @classmethod
    def _outline_count(cls, outlines: list[Outline]) -> int:
        return sum(1 + cls._outline_count(outline.children) for outline in outlines)

    @classmethod
    def _mapped_outline_count(
        cls,
        outlines: list[Outline],
        page_ordinals: set[int],
    ) -> int:
        return sum(
            (1 if outline.destination_page in page_ordinals else 0)
            + cls._mapped_outline_count(outline.children, page_ordinals)
            for outline in outlines
        )

    def page_list_to_group_text(self, pages: list[Page]) -> list[PageGroup]:
        if not pages:
            raise ValueError("pages must not be empty")

        groups: list[PageGroup] = []
        current: list[Page] = []
        current_tokens = 0
        for page in pages:
            if current and current_tokens + page.token_count > self.group_max_tokens:
                groups.append(self._page_group(current))
                current = current[-self.overlap_page :] if self.overlap_page else []
                current_tokens = sum(item.token_count for item in current)
            current.append(page)
            current_tokens += page.token_count

        if current:
            groups.append(self._page_group(current))
        return groups

    async def _process_no_toc(
        self,
        pages: list[Page],
        *,
        trace_method_prefix: str,
        toc_text: str = "",
    ) -> TreeNode:
        groups = self.page_list_to_group_text(pages)
        tree = await self._generate_toc_init(
            groups[0],
            allowed_pages=groups[0].pages,
            trace_method=f"{trace_method_prefix}.init",
            toc_text=toc_text,
        )
        allowed_pages = list(groups[0].pages)
        for group in groups[1:]:
            allowed_pages = [*allowed_pages, *group.pages]
            tree = await self._generate_toc_continue(
                tree,
                group,
                allowed_pages=allowed_pages,
                trace_method=f"{trace_method_prefix}.continue",
                toc_text=toc_text,
            )
        return tree

    async def _generate_toc_init(
        self,
        group: PageGroup,
        *,
        allowed_pages: list[Page],
        trace_method: str,
        toc_text: str = "",
    ) -> TreeNode:
        self.metrics.init_calls += 1
        prompt = (
            TOC_GUIDED_INIT_PROMPT.format(toc_text=toc_text, group_text=group.text)
            if toc_text
            else INIT_PROMPT.format(group_text=group.text)
        )
        data = await self.client.generate_json(
            prompt=prompt,
            system_prompt=PAGE_INDEX_SYSTEM_PROMPT,
            response_json_schema=TREE_NODE_RESPONSE_JSON_SCHEMA,
            trace_method=trace_method,
        )
        tree = TreeNode.model_validate(data)
        if toc_text:
            self._normalize_tree_to_pages(tree, allowed_pages)
        self._reject_unknown_page_ranges(tree, allowed_pages)
        return tree

    async def _generate_toc_continue(
        self,
        tree: TreeNode,
        group: PageGroup,
        *,
        allowed_pages: list[Page],
        trace_method: str,
        toc_text: str = "",
    ) -> TreeNode:
        self.metrics.continue_calls += 1
        tree_json = json.dumps(tree.model_dump(mode="json"), ensure_ascii=False)
        prompt = (
            TOC_GUIDED_CONTINUE_PROMPT.format(
                toc_text=toc_text,
                tree_json=tree_json,
                group_text=group.text,
            )
            if toc_text
            else CONTINUE_PROMPT.format(tree_json=tree_json, group_text=group.text)
        )
        data = await self.client.generate_json(
            prompt=prompt,
            system_prompt=PAGE_INDEX_SYSTEM_PROMPT,
            response_json_schema=TREE_CONTINUATION_RESPONSE_JSON_SCHEMA,
            trace_method=trace_method,
        )
        continuation = TreeContinuation.model_validate(data)
        if toc_text:
            continuation = self._normalize_continuation_to_pages(
                continuation,
                allowed_pages,
            )
        self._reject_unknown_continuation_ranges(continuation, allowed_pages)
        self._merge_continuation(tree, continuation)
        return tree

    async def _split_large_nodes(self, tree: TreeNode, pages: list[Page]) -> None:
        protected: set[int] = set()
        while True:
            violations = self._splittable_violation_frontier(
                tree,
                pages,
                depth=1,
                protected=protected,
            )
            violations = self._disjoint_violations(violations)
            if not violations:
                return

            self.metrics.recursion_batches += 1
            self.metrics.max_parallel_recursions = max(
                self.metrics.max_parallel_recursions,
                min(len(violations), self.recursion_concurrency),
            )
            sub_trees = await self._process_violation_batch(violations, pages)
            for violation, sub_tree in zip(violations, sub_trees):
                self._merge_recursive_split(
                    violation=violation,
                    sub_tree=sub_tree,
                    protected=protected,
                )

    async def _process_violation_batch(
        self,
        violations: list[_Violation],
        pages: list[Page],
    ) -> list[TreeNode]:
        semaphore = asyncio.Semaphore(self.recursion_concurrency)

        async def process(violation: _Violation) -> TreeNode:
            async with semaphore:
                sub_pages = self._pages_in_range(pages, violation.node.page_range)
                self.metrics.recursion_calls += 1
                try:
                    return await self._process_no_toc(
                        sub_pages,
                        trace_method_prefix="page_index.large_node_recursion",
                    )
                except ValueError:
                    self.metrics.recursion_fallback_splits += 1
                    return self._fallback_split_tree(violation.node, sub_pages)

        return list(await asyncio.gather(*(process(item) for item in violations)))

    def _fallback_split_tree(self, node: TreeNode, pages: list[Page]) -> TreeNode:
        if len(pages) <= 1:
            return TreeNode(
                node_id="fallback-root",
                title=node.title,
                page_range=node.page_range,
                summary=node.summary,
                children=[],
            )
        midpoint = len(pages) // 2
        groups = [pages[:midpoint], pages[midpoint:]]
        return TreeNode(
            node_id="fallback-root",
            title=node.title,
            page_range=node.page_range,
            summary=node.summary,
            children=[
                TreeNode(
                    node_id=f"fallback-{index}",
                    title=f"{node.title} ({index})",
                    page_range=[group[0].ordinal, group[-1].ordinal],
                    summary="Deterministic fallback split after recursive tree generation failed.",
                    children=[],
                )
                for index, group in enumerate(groups, start=1)
                if group
            ],
        )

    def _merge_recursive_split(
        self,
        *,
        violation: _Violation,
        sub_tree: TreeNode,
        protected: set[int],
    ) -> None:
        children = sub_tree.children or [sub_tree]
        if not self._split_makes_progress(violation.node, children):
            protected.add(id(violation.node))
            self.metrics.no_progress_skips += 1
            return
        violation.node.children = children
        protected.add(id(violation.node))
        self.metrics.nodes_split += 1

    def _splittable_violation_frontier(
        self,
        node: TreeNode,
        pages: list[Page],
        *,
        depth: int,
        protected: set[int],
    ) -> list[_Violation]:
        if self._node_exceeds_limits(node, pages) and id(node) not in protected:
            sub_pages = self._pages_in_range(pages, node.page_range)
            if depth >= self.max_recursion_depth:
                protected.add(id(node))
                self.metrics.max_depth_skips += 1
            elif len(sub_pages) <= 1:
                protected.add(id(node))
                self.metrics.single_page_skips += 1
            else:
                return [_Violation(node=node, depth=depth)]

        violations: list[_Violation] = []
        for child in node.children:
            violations.extend(
                self._splittable_violation_frontier(
                    child,
                    pages,
                    depth=depth + 1,
                    protected=protected,
                )
            )
        return violations

    @staticmethod
    def _disjoint_violations(violations: list[_Violation]) -> list[_Violation]:
        selected: list[_Violation] = []
        for violation in sorted(
            violations,
            key=lambda item: (item.node.page_range[0], item.node.page_range[1]),
        ):
            if any(
                PageIndexer._ranges_overlap(
                    violation.node.page_range,
                    selected_item.node.page_range,
                )
                for selected_item in selected
            ):
                continue
            selected.append(violation)
        return selected

    @staticmethod
    def _ranges_overlap(left: list[int], right: list[int]) -> bool:
        return left[0] <= right[1] and right[0] <= left[1]

    def _node_exceeds_limits(self, node: TreeNode, pages: list[Page]) -> bool:
        sub_pages = self._pages_in_range(pages, node.page_range)
        return (
            len(sub_pages) > self.max_page_num_each_node
            or sum(page.token_count for page in sub_pages)
            > self.max_token_num_each_node
        )

    @staticmethod
    def _pages_in_range(pages: list[Page], page_range: list[int]) -> list[Page]:
        start, end = page_range
        return [page for page in pages if start <= page.ordinal <= end]

    @staticmethod
    def _split_makes_progress(node: TreeNode, children: list[TreeNode]) -> bool:
        if len(children) != 1:
            return True
        return children[0].page_range != node.page_range

    @staticmethod
    def _page_group(pages: list[Page]) -> PageGroup:
        text = "\n\n".join(f"[ordinal {page.ordinal}]\n{page.text}" for page in pages)
        return PageGroup(
            pages=pages,
            text=text,
            token_count=sum(page.token_count for page in pages),
        )

    @staticmethod
    def _reject_unknown_toc_pages(
        pages: list[Page],
        detected_toc: DetectedTOC,
    ) -> None:
        known_ordinals = {page.ordinal for page in pages}
        unknown = set(detected_toc.toc_pages) - known_ordinals
        if unknown:
            raise ValueError(
                "detected_toc contains unknown page ordinals "
                f"{sorted(unknown)}"
            )

    def _normalize_continuation_to_pages(
        self,
        continuation: TreeContinuation,
        pages: list[Page],
    ) -> TreeContinuation:
        root = TreeNode(
            node_id="continuation-root",
            title=continuation.title,
            page_range=continuation.page_range,
            summary=continuation.summary,
            children=continuation.children,
        )
        self._normalize_tree_to_pages(root, pages)
        return TreeContinuation(
            title=root.title,
            page_range=root.page_range,
            summary=root.summary,
            children=root.children,
        )

    def _normalize_tree_to_pages(self, node: TreeNode, pages: list[Page]) -> bool:
        allowed_ordinals = sorted(page.ordinal for page in pages)
        start, end = node.page_range
        overlapping = [
            ordinal for ordinal in allowed_ordinals if start <= ordinal <= end
        ]
        if not overlapping:
            return False

        normalized_range = [overlapping[0], overlapping[-1]]
        if node.page_range != normalized_range:
            node.page_range = normalized_range
            self.metrics.toc_range_adjustments += 1

        kept_children: list[TreeNode] = []
        for child in node.children:
            if self._normalize_tree_to_pages(child, pages):
                kept_children.append(child)
            else:
                self.metrics.toc_out_of_range_nodes_dropped += 1
        node.children = kept_children
        return True

    def _assign_stable_node_ids(self, node: TreeNode, prefix: str = "n") -> None:
        node.node_id = prefix
        for index, child in enumerate(node.children, start=1):
            self._assign_stable_node_ids(child, prefix=f"{prefix}.{index}")

    def _tree_depth(self, node: TreeNode) -> int:
        if not node.children:
            return 1
        return 1 + max(self._tree_depth(child) for child in node.children)

    def _reject_unknown_page_ranges(self, tree: TreeNode, pages: list[Page]) -> None:
        self._reject_unknown_ranges(self._walk_nodes(tree), pages)

    def _reject_unknown_continuation_ranges(
        self,
        continuation: TreeContinuation,
        pages: list[Page],
    ) -> None:
        root = TreeNode(
            node_id="continuation-root",
            title=continuation.title,
            page_range=continuation.page_range,
            summary=continuation.summary,
            children=continuation.children,
        )
        self._reject_unknown_page_ranges(root, pages)

    def _reject_unknown_ranges(self, nodes: list[TreeNode], pages: list[Page]) -> None:
        ordinals = {page.ordinal for page in pages}
        min_ordinal = min(ordinals)
        max_ordinal = max(ordinals)
        for node in nodes:
            start, end = node.page_range
            if start < min_ordinal or end > max_ordinal:
                raise ValueError(
                    f"{node.node_id} page_range {node.page_range} is outside "
                    f"known ordinals {min_ordinal}..{max_ordinal}"
                )
            if not any(start <= ordinal <= end for ordinal in ordinals):
                raise ValueError(
                    f"{node.node_id} page_range {node.page_range} does not overlap "
                    "known ordinals"
                )

    def _walk_nodes(self, node: TreeNode) -> list[TreeNode]:
        nodes = [node]
        for child in node.children:
            nodes.extend(self._walk_nodes(child))
        return nodes

    def _merge_continuation(
        self,
        tree: TreeNode,
        continuation: TreeContinuation,
    ) -> None:
        tree.title = continuation.title or tree.title
        tree.summary = continuation.summary or tree.summary
        tree.page_range = [
            min(tree.page_range[0], continuation.page_range[0]),
            max(tree.page_range[1], continuation.page_range[1]),
        ]
        for child in continuation.children:
            self._merge_child(tree.children, child)
        tree.children.sort(key=lambda node: (node.page_range[0], node.page_range[1]))

    def _merge_child(self, children: list[TreeNode], incoming: TreeNode) -> None:
        for existing in children:
            if not self._same_section(existing, incoming):
                continue
            existing.page_range = [
                min(existing.page_range[0], incoming.page_range[0]),
                max(existing.page_range[1], incoming.page_range[1]),
            ]
            existing.summary = incoming.summary or existing.summary
            for grandchild in incoming.children:
                self._merge_child(existing.children, grandchild)
            existing.children.sort(
                key=lambda node: (node.page_range[0], node.page_range[1])
            )
            return
        children.append(incoming)

    @staticmethod
    def _same_section(left: TreeNode, right: TreeNode) -> bool:
        left_title = " ".join(left.title.lower().split())
        right_title = " ".join(right.title.lower().split())
        if left_title != right_title:
            return False
        left_start, left_end = left.page_range
        right_start, right_end = right.page_range
        return right_start <= left_end + 1 and left_start <= right_end + 1
