#!/usr/bin/env python3
from __future__ import annotations

# ruff: noqa: E402

import argparse
import asyncio
import json
import re
import sys
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from valuator.documents import (  # noqa: E402
    DocumentIngest,
    IndexStore,
    IndexedDocument,
    Page,
    PageMarkerPattern,
    PageIndexer,
    RawDocument,
    document_hash,
)
from valuator.models.factory import create_llm_client  # noqa: E402
from valuator.utils.llm_usage import LLMUsageWriter, TokenUsage  # noqa: E402
from valuator.utils.time_utils import kst_isoformat  # noqa: E402

DEFAULT_DB_PATH = ROOT / "data" / "page_index.db"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "page_index"


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
        description="Run the Phase 1 PageIndex PoC against a local text document."
    )
    parser.add_argument(
        "--input-file",
        type=Path,
        required=True,
        help="Local text or markdown file to index.",
    )
    parser.add_argument(
        "--doc-id",
        default="",
        help="Stable document id. Defaults to the input file stem.",
    )
    parser.add_argument(
        "--source",
        default="",
        help="Logical source locator. Defaults to the resolved input file path.",
    )
    parser.add_argument(
        "--mime",
        default="text/plain",
        help="Input MIME type. Phase 1 supports text/plain and markdown.",
    )
    parser.add_argument(
        "--output-prefix",
        default="",
        help="Filename prefix for tree/usage/call outputs. Defaults to doc-id slug.",
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
        "--text-page-tokens",
        type=int,
        default=2_000,
        help="Token window used by text ingest. Default: 2000",
    )
    parser.add_argument(
        "--page-marker-regex",
        default="",
        help=(
            "Optional line regex containing a page capture group. When provided, "
            "marked source pages are used instead of token windows."
        ),
    )
    parser.add_argument(
        "--page-marker-group",
        default="page",
        help="Regex capture group name or index for page number. Default: page",
    )
    parser.add_argument(
        "--page-marker-kind",
        default="marked_page",
        help="source_locator kind used for marked pages. Default: marked_page",
    )
    parser.add_argument(
        "--page-marker-boundary",
        choices=("end", "start"),
        default="end",
        help="Whether marker lines start or end a page. Default: end",
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
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return (ROOT / expanded).resolve()


def marker_group(value: str) -> str | int:
    return int(value) if value.isdigit() else value


def marker_boundary(value: str) -> Literal["end", "start"]:
    if value not in {"end", "start"}:
        raise ValueError("page marker boundary must be 'end' or 'start'")
    return value


def safe_output_prefix(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return normalized.strip("-._") or "document"


def build_pages(
    *,
    document: RawDocument,
    text_page_tokens: int,
    page_marker_regex: str,
    page_marker_group: str,
    page_marker_kind: str,
    page_marker_boundary: str,
) -> list[Page]:
    text = str(document.raw_bytes_or_text)
    ingest = DocumentIngest(text_page_tokens=text_page_tokens)
    if page_marker_regex:
        return ingest.pages_from_marked_text(
            doc_id=document.doc_id,
            text=text,
            source=document.source,
            marker=PageMarkerPattern(
                pattern=re.compile(page_marker_regex),
                locator_kind=page_marker_kind,
                page_group=marker_group(page_marker_group),
                boundary=marker_boundary(page_marker_boundary),
            ),
        )
    return ingest.pages_from_raw(document)


async def run(args: argparse.Namespace) -> None:
    input_path = resolve_path(args.input_file)
    text = input_path.read_text(encoding="utf-8")
    doc_id = args.doc_id.strip() or input_path.stem
    source = args.source.strip() or str(input_path)
    mime = args.mime.strip() or "text/plain"
    raw_document = RawDocument(
        doc_id=doc_id,
        source=source,
        raw_bytes_or_text=text,
        mime=mime,
    )
    doc_hash = document_hash(raw_document)
    page_marker_kind = args.page_marker_kind.strip() or "marked_page"
    pages = build_pages(
        document=raw_document,
        text_page_tokens=args.text_page_tokens,
        page_marker_regex=args.page_marker_regex.strip(),
        page_marker_group=args.page_marker_group.strip(),
        page_marker_kind=page_marker_kind,
        page_marker_boundary=args.page_marker_boundary,
    )

    output_dir = resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_prefix = safe_output_prefix(args.output_prefix or raw_document.doc_id)
    usage_path = output_dir / f"{output_prefix}-llm_usage.jsonl"
    llm_calls_path = output_dir / f"{output_prefix}-llm_calls.jsonl"
    trace_writer = PageIndexTraceWriter(
        usage_path=usage_path,
        llm_calls_path=llm_calls_path,
        session_started_at=kst_isoformat(),
    )
    client = create_llm_client(model=args.model or None, usage_writer=trace_writer)
    indexer = PageIndexer(
        client,
        group_max_tokens=args.group_max_tokens,
        max_page_num_each_node=args.max_page_num_each_node,
        max_token_num_each_node=args.max_token_num_each_node,
        max_recursion_depth=args.max_recursion_depth,
    )
    tree = await indexer.build_tree(pages)
    trace_writer.append_total()

    indexed = IndexedDocument(
        doc_id=raw_document.doc_id,
        doc_hash=doc_hash,
        page_count=len(pages),
        tree=tree,
        metadata={
            "input_file": str(input_path),
            "source": raw_document.source,
            "mime": raw_document.mime,
            "page_unit": page_marker_kind if args.page_marker_regex else "token_window",
            "text_page_tokens": args.text_page_tokens,
            "metrics": asdict(indexer.metrics),
        },
    )
    store = IndexStore(resolve_path(args.db))
    store.record(indexed, pages)

    tree_path = output_dir / f"{output_prefix}-tree.json"
    tree_path.write_text(
        json.dumps(indexed.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "doc_id": indexed.doc_id,
                "doc_hash": indexed.doc_hash,
                "page_count": indexed.page_count,
                "tree_path": str(tree_path),
                "usage_path": str(usage_path),
                "llm_calls_path": str(llm_calls_path),
                "db_path": str(resolve_path(args.db)),
                "metrics": asdict(indexer.metrics),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
