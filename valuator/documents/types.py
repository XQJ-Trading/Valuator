from __future__ import annotations

from typing import Any

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


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


class DetectedTOC(BaseModel):
    model_config = ConfigDict(extra="forbid")

    toc_pages: list[int] = Field(min_length=1)
    raw_text: str

    @field_validator("toc_pages")
    @classmethod
    def _toc_pages_are_unique(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("toc_pages must be unique")
        return value


class Outline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    destination_page: int | None = Field(
        default=None,
        validation_alias=AliasChoices("destination_page", "page_number"),
    )
    children: list[Outline] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def _title_is_not_blank(cls, value: str) -> str:
        title = " ".join(value.strip().split())
        if not title:
            raise ValueError("title must not be blank")
        return title

    @field_validator("destination_page")
    @classmethod
    def _destination_page_is_non_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("destination_page must be >= 0")
        return value

    @property
    def page_number(self) -> int | None:
        return self.destination_page


TOCEntry = Outline


class ContentPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_ordinal: int
    local_offset: int
    source_offset: int | None = None


class ContentSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: ContentPosition
    end: ContentPosition
    page_range: list[int] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def _page_range_is_ordered(self) -> ContentSpan:
        if self.page_range[0] > self.page_range[1]:
            raise ValueError("page_range start must be <= end")
        return self


class TreeNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    title: str
    page_range: list[int] = Field(min_length=2, max_length=2)
    summary: str
    content_span: ContentSpan | None = None
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
    content_span: ContentSpan | None = None
    pages: list[Page] = Field(default_factory=list)


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    doc_hash: str
    query: str
    selection: NodeSelection
    selected_nodes: list[RetrievedNode] = Field(default_factory=list)
