from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RawDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    source: str
    raw_bytes_or_text: str | bytes
    mime: str = "text/plain"


class Page(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    ordinal: int
    text: str
    token_count: int
    source_locator: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ordinal")
    @classmethod
    def _ordinal_is_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("ordinal must be >= 0")
        return value

    @field_validator("token_count")
    @classmethod
    def _token_count_is_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("token_count must be >= 0")
        return value


class TreeNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    title: str
    page_range: list[int] = Field(min_length=2, max_length=2)
    summary: str
    children: list[TreeNode] = Field(default_factory=list)

    @model_validator(mode="after")
    def _page_range_is_ordered(self) -> TreeNode:
        if self.page_range[0] > self.page_range[1]:
            raise ValueError("page_range start must be <= end")
        return self


class IndexedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    doc_hash: str
    page_count: int
    tree: TreeNode
    metadata: dict[str, Any] = Field(default_factory=dict)


class NodeSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    selected_node_ids: list[str]
    reasoning: str


class RetrievedNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    title: str
    page_range: list[int] = Field(min_length=2, max_length=2)
    summary: str
    pages: list[Page] = Field(default_factory=list)


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    doc_hash: str
    query: str
    selection: NodeSelection
    selected_nodes: list[RetrievedNode] = Field(default_factory=list)
