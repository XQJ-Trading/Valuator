#!/usr/bin/env python3
from __future__ import annotations

# ruff: noqa: E402

import argparse
import asyncio
import json
import re
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pydantic import BaseModel, ConfigDict, Field, model_validator  # noqa: E402

from valuator.documents import (  # noqa: E402
    DocumentLoader,
    IndexStore,
    IndexedDocument,
    Page,
    PageMarkerPattern,
    PageIndexer,
    RawDocument,
    TOCDetector,
    document_hash,
    remove_detected_toc_from_pages,
    transform_toc,
)
from valuator.models.factory import create_llm_client  # noqa: E402
from valuator.utils.llm_usage import LLMUsageWriter, TokenUsage  # noqa: E402
from valuator.utils.time_utils import kst_isoformat  # noqa: E402

DEFAULT_DB_PATH = ROOT / "data" / "page_index.db"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "page_index"
DEFAULT_TOKEN_TEXT_PAGE_TOKENS = 2_000


class MarkerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regex: str
    locator_kind: str = "marked_page"
    page_group: str | int = "page"
    boundary: Literal["end", "start"] = "end"

    def to_pattern(self) -> PageMarkerPattern:
        return PageMarkerPattern(
            pattern=re.compile(self.regex),
            locator_kind=self.locator_kind,
            page_group=self.page_group,
            boundary=self.boundary,
        )


class LoaderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["token_text", "marked_text", "pdf"] = "token_text"
    text_page_tokens: int = Field(default=DEFAULT_TOKEN_TEXT_PAGE_TOKENS, gt=0)
    marker: MarkerConfig | None = None

    @model_validator(mode="after")
    def _validate_marker(self) -> LoaderConfig:
        if self.kind == "marked_text" and self.marker is None:
            raise ValueError("marked_text loader requires loader.marker")
        if self.kind != "marked_text" and self.marker is not None:
            raise ValueError(f"{self.kind} loader does not accept loader.marker")
        return self

    def to_loader(self) -> DocumentLoader:
        if self.kind == "marked_text":
            if self.marker is None:
                raise ValueError("marked_text loader requires loader.marker")
            return DocumentLoader.marked_text(marker=self.marker.to_pattern())
        if self.kind == "pdf":
            return DocumentLoader.pdf()
        return DocumentLoader.token_text(text_page_tokens=self.text_page_tokens)


class ManifestDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_file: Path
    doc_id: str = ""
    source: str = ""
    mime: str = ""
    output_prefix: str = ""
    loader: LoaderConfig = Field(default_factory=LoaderConfig)


class PageIndexManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents: list[ManifestDocument] = Field(min_length=1)


@dataclass(frozen=True)
class InputDocument:
    input_path: Path
    doc_id: str
    source: str
    mime: str
    output_prefix: str
    loader: DocumentLoader


class PageIndexTraceWriter:
    def __init__(
        self,
        *,
        usage_path: Path,
        llm_calls_path: Path,
        session_started_at: str,
    ) -> None:
        self.llm_calls_path = llm_calls_path
        self._usage_writer = LLMUsageWriter(
            usage_path,
            session_started_at=session_started_at,
        )
        self._lock = threading.RLock()
        self._llm_call_index = 0
        self.llm_calls_path.parent.mkdir(parents=True, exist_ok=True)
        self.llm_calls_path.write_text("", encoding="utf-8")

    def append_call(
        self,
        *,
        method: str,
        model: str,
        usage: TokenUsage,
        latency_seconds: float,
        started_at: str,
        cache_source: str | None = None,
        cache_storage_hours: float = 0.0,
    ) -> None:
        self._usage_writer.append_call(
            method=method,
            model=model,
            usage=usage,
            latency_seconds=latency_seconds,
            started_at=started_at,
            cache_source=cache_source,
            cache_storage_hours=cache_storage_hours,
        )

    def append_total(self) -> None:
        self._usage_writer.append_total()

    def log_llm_call(
        self,
        *,
        trace_method: str,
        model: str,
        prompt: str,
        system_prompt: str,
        response_mime_type: str | None,
        response_json_schema: dict[str, Any] | None,
        response_text: str | None,
        usage: Mapping[str, Any] | None,
        latency_ms: float,
        started_at: str,
        cache_source: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            self._llm_call_index += 1
            payload = {
                "llm_call_index": self._llm_call_index,
                "started_at": started_at,
                "trace_method": trace_method,
                "model": model,
                "cache_source": cache_source,
                "prompt": prompt,
                "system_prompt": system_prompt,
                "response_mime_type": response_mime_type,
                "response_json_schema": response_json_schema,
                "response_text": response_text,
                "usage": dict(usage or {}),
                "latency_ms": latency_ms,
                "error": error,
            }
            with self.llm_calls_path.open("a", encoding="utf-8") as file_obj:
                file_obj.write(json.dumps(payload, ensure_ascii=False) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Phase 1 PageIndex PoC against local PDF or text documents."
    )
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument(
        "--input-file",
        type=Path,
        action="append",
        help=(
            "Local PDF, text, or markdown file to index with the default loader "
            "for its extension. Repeat for a document batch."
        ),
    )
    inputs.add_argument(
        "--manifest",
        type=Path,
        help="JSON manifest for document metadata and loader-specific parsing.",
    )
    parser.add_argument(
        "--doc-id",
        default="",
        help="Stable id for one direct --input-file. Defaults to the file stem.",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Override model name. Defaults to AGENT_MODEL / project config.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite output path. Default: {DEFAULT_DB_PATH.relative_to(ROOT)}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"JSON output directory. Default: {DEFAULT_OUTPUT_DIR.relative_to(ROOT)}",
    )
    parser.add_argument(
        "--group-max-tokens",
        type=int,
        default=20_000,
        help="Token budget for each PageIndex LLM group. Default: 20000",
    )
    parser.add_argument(
        "--max-page-num-each-node",
        type=int,
        default=10,
        help="Recursive split page threshold. Default: 10",
    )
    parser.add_argument(
        "--max-token-num-each-node",
        type=int,
        default=20_000,
        help="Recursive split token threshold. Default: 20000",
    )
    parser.add_argument(
        "--max-recursion-depth",
        type=int,
        default=4,
        help="Maximum automatic recursive split depth. Default: 4",
    )
    parser.add_argument(
        "--recursion-concurrency",
        type=int,
        default=4,
        help="Bounded concurrency for disjoint recursive splits. Default: 4",
    )
    parser.add_argument(
        "--document-concurrency",
        type=int,
        default=1,
        help="Bounded concurrency across input or manifest documents. Default: 1",
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return (ROOT / expanded).resolve()


def safe_output_prefix(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return normalized.strip("-._") or "document"


def build_pages(*, document: RawDocument, loader: DocumentLoader) -> list[Page]:
    return loader.pages_from_raw(document)


def input_mime(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return "application/pdf"
    if path.suffix.lower() in {".md", ".markdown"}:
        return "text/markdown"
    return "text/plain"


def default_loader(path: Path) -> DocumentLoader:
    if path.suffix.lower() == ".pdf":
        return DocumentLoader.pdf()
    return DocumentLoader.token_text(
        text_page_tokens=DEFAULT_TOKEN_TEXT_PAGE_TOKENS
    )


def input_document_from_manifest(document: ManifestDocument) -> InputDocument:
    input_path = resolve_path(document.input_file)
    doc_id = document.doc_id.strip() or input_path.stem
    source = document.source.strip() or str(input_path)
    mime = document.mime.strip() or input_mime(input_path)
    output_prefix = document.output_prefix.strip() or doc_id
    return InputDocument(
        input_path=input_path,
        doc_id=doc_id,
        source=source,
        mime=mime,
        output_prefix=output_prefix,
        loader=document.loader.to_loader(),
    )


def load_manifest(path: Path) -> list[InputDocument]:
    manifest_path = resolve_path(path)
    manifest = PageIndexManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    return [
        input_document_from_manifest(document)
        for document in manifest.documents
    ]


def load_input_documents(args: argparse.Namespace) -> list[InputDocument]:
    if args.document_concurrency <= 0:
        raise ValueError("document_concurrency must be > 0")
    if args.manifest is not None:
        if args.doc_id.strip():
            raise ValueError("--doc-id cannot be combined with --manifest")
        documents = load_manifest(args.manifest)
    else:
        input_paths = [resolve_path(path) for path in args.input_file]
        if len(input_paths) > 1 and args.doc_id.strip():
            raise ValueError("--doc-id can only be used with one --input-file")
        documents = [
            InputDocument(
                input_path=input_path,
                doc_id=args.doc_id.strip() or input_path.stem,
                source=str(input_path),
                mime=input_mime(input_path),
                output_prefix=args.doc_id.strip() or input_path.stem,
                loader=default_loader(input_path),
            )
            for input_path in input_paths
        ]

    output_prefixes = [safe_output_prefix(document.output_prefix) for document in documents]
    if len(set(output_prefixes)) != len(output_prefixes):
        raise ValueError("document output prefixes must be unique")
    doc_ids = [document.doc_id for document in documents]
    if len(set(doc_ids)) != len(doc_ids):
        raise ValueError("document doc ids must be unique")
    return documents


async def gather_limited(
    items: list[Any],
    *,
    concurrency: int,
    process: Any,
) -> list[dict[str, Any]]:
    if concurrency <= 0:
        raise ValueError("document_concurrency must be > 0")
    semaphore = asyncio.Semaphore(concurrency)

    async def guarded(item: Any) -> dict[str, Any]:
        async with semaphore:
            return await process(item)

    return list(await asyncio.gather(*(guarded(item) for item in items)))


async def index_input_document(
    args: argparse.Namespace,
    *,
    input_document: InputDocument,
    store: IndexStore,
    db_path: Path,
) -> dict[str, Any]:
    input_path = input_document.input_path
    raw_input = (
        input_path.read_bytes()
        if input_document.mime == "application/pdf"
        else input_path.read_text(encoding="utf-8")
    )
    raw_document = RawDocument(
        doc_id=input_document.doc_id,
        source=input_document.source,
        raw_bytes_or_text=raw_input,
        mime=input_document.mime,
    )
    doc_hash = document_hash(raw_document)
    pages = build_pages(
        document=raw_document,
        loader=input_document.loader,
    )

    output_dir = resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_prefix = safe_output_prefix(input_document.output_prefix)
    usage_path = output_dir / f"{output_prefix}-llm_usage.jsonl"
    llm_calls_path = output_dir / f"{output_prefix}-llm_calls.jsonl"
    trace_writer = PageIndexTraceWriter(
        usage_path=usage_path,
        llm_calls_path=llm_calls_path,
        session_started_at=kst_isoformat(),
    )
    client = create_llm_client(model=args.model or None, usage_writer=trace_writer)
    toc_detector = TOCDetector(client)
    detected_toc = await toc_detector.detect(pages)
    index_pages = remove_detected_toc_from_pages(pages, detected_toc)
    toc_text_removed_pages = sum(
        1 for page in index_pages if page.source_locator.get("toc_removed")
    )
    outlines, toc_transform_metrics = await transform_toc(
        client,
        detected_toc,
        index_pages,
    )
    indexer = PageIndexer(
        client,
        group_max_tokens=args.group_max_tokens,
        max_page_num_each_node=args.max_page_num_each_node,
        max_token_num_each_node=args.max_token_num_each_node,
        max_recursion_depth=args.max_recursion_depth,
        recursion_concurrency=args.recursion_concurrency,
    )
    tree = await indexer.build_tree(
        index_pages,
        detected_toc=detected_toc,
        outlines=outlines,
    )
    trace_writer.append_total()

    indexed = IndexedDocument(
        doc_id=raw_document.doc_id,
        doc_hash=doc_hash,
        page_count=len(index_pages),
        tree=tree,
        metadata={
            "input_file": str(input_path),
            "source": raw_document.source,
            "mime": raw_document.mime,
            "raw_page_count": len(pages),
            "toc_text_removed_pages": toc_text_removed_pages,
            **input_document.loader.metadata(),
            "detected_toc_pages": detected_toc.toc_pages if detected_toc else [],
            "toc_detection_metrics": asdict(toc_detector.metrics),
            "toc_transform_metrics": asdict(toc_transform_metrics),
            "toc_entry_count": toc_transform_metrics.entry_count,
            "toc_has_page_numbers": toc_transform_metrics.has_page_numbers,
            "tree_build_route": indexer.metrics.tree_build_route,
            "metrics": asdict(indexer.metrics),
        },
    )
    store.record(indexed, index_pages)

    tree_path = output_dir / f"{output_prefix}-tree.json"
    tree_path.write_text(
        json.dumps(
            indexed.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "doc_id": indexed.doc_id,
        "doc_hash": indexed.doc_hash,
        "page_count": indexed.page_count,
        "tree_path": str(tree_path),
        "usage_path": str(usage_path),
        "llm_calls_path": str(llm_calls_path),
        "db_path": str(db_path),
        "detected_toc_pages": indexed.metadata["detected_toc_pages"],
        "toc_detection_metrics": indexed.metadata["toc_detection_metrics"],
        "toc_transform_metrics": indexed.metadata["toc_transform_metrics"],
        "toc_text_removed_pages": indexed.metadata["toc_text_removed_pages"],
        "toc_entry_count": indexed.metadata["toc_entry_count"],
        "toc_has_page_numbers": indexed.metadata["toc_has_page_numbers"],
        "tree_build_route": indexed.metadata["tree_build_route"],
        "metrics": asdict(indexer.metrics),
    }


async def run(args: argparse.Namespace) -> None:
    input_documents = load_input_documents(args)
    db_path = resolve_path(args.db)
    store = IndexStore(db_path)

    async def process(input_document: InputDocument) -> dict[str, Any]:
        return await index_input_document(
            args,
            input_document=input_document,
            store=store,
            db_path=db_path,
        )

    results = await gather_limited(
        input_documents,
        concurrency=args.document_concurrency,
        process=process,
    )
    payload: dict[str, Any] | list[dict[str, Any]]
    payload = results[0] if len(results) == 1 else results
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
