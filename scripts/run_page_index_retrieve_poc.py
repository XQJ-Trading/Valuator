#!/usr/bin/env python3
from __future__ import annotations

# ruff: noqa: E402

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_page_index_poc import (
    DEFAULT_PAGE_INDEX_MODEL,
    DEFAULT_RETRIEVAL_INDEXING_COST_DIVISOR,
    PageIndexTraceWriter,
    retrieval_budget_from_indexing_cost,
    safe_output_prefix,
)
from valuator.documents import IndexStore, RetrievalResult, TreeRetriever
from valuator.evidence import EvidenceRow, SqliteEvidenceStore, stable_args_hash
from valuator.models.factory import create_llm_client
from valuator.utils.time_utils import kst_isoformat

DEFAULT_DB_PATH = ROOT / "data" / "page_index.db"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "page_index"
DEFAULT_RETRIEVER_MODEL = DEFAULT_PAGE_INDEX_MODEL


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a PageIndex retrieval PoC against an indexed document."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--doc-id", default="", help="Indexed document id.")
    parser.add_argument("--doc-hash", default="", help="Indexed document hash.")
    parser.add_argument(
        "--query",
        action="append",
        required=True,
        help="Retrieval query. Repeat for a parallel query batch.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_RETRIEVER_MODEL,
        help=f"Override retriever model name. Default: {DEFAULT_RETRIEVER_MODEL}.",
    )
    parser.add_argument(
        "--retrieval-budget-indexing-cost-divisor",
        type=float,
        default=DEFAULT_RETRIEVAL_INDEXING_COST_DIVISOR,
        help=(
            "Set retrieval search budget to indexing_cost_usd / divisor. "
            f"Default: {DEFAULT_RETRIEVAL_INDEXING_COST_DIVISOR:g}."
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-prefix", default="")
    parser.add_argument(
        "--max-page-chars",
        type=int,
        default=800,
        help="Maximum text chars printed per retrieved page. Default: 800",
    )
    parser.add_argument(
        "--evidence-db",
        type=Path,
        default=None,
        help="Optional evidence SQLite path to record selected nodes.",
    )
    parser.add_argument("--session-id", default="", help="Evidence session id.")
    parser.add_argument("--task-id", default="", help="Evidence task id.")
    parser.add_argument(
        "--unit-objective",
        default="",
        help="Evidence unit objective. Defaults to the query.",
    )
    parser.add_argument(
        "--query-concurrency",
        type=int,
        default=1,
        help="Bounded concurrency across repeated --query values. Default: 1",
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return (ROOT / expanded).resolve()


def load_document(store: IndexStore, args: argparse.Namespace):
    doc_hash = args.doc_hash.strip()
    if doc_hash:
        document = store.get(doc_hash)
        if document is None:
            raise ValueError(f"indexed document not found for doc_hash={doc_hash}")
        return document

    doc_id = args.doc_id.strip()
    if not doc_id:
        raise ValueError("either --doc-id or --doc-hash is required")
    document = store.get_by_doc_id(doc_id)
    if document is None:
        raise ValueError(f"indexed document not found for doc_id={doc_id}")
    return document


def page_text(text: str, max_chars: int) -> str:
    if max_chars < 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n...[truncated]"


def format_text_output(result: RetrievalResult, query: str) -> str:
    sep = "=" * 80
    lines: list[str] = [
        f"[Query] {query}",
        "",
        f"[Reasoning] {result.selection.reasoning}",
        "",
    ]
    for node in result.selected_nodes:
        page_range = node.page_range
        lines.append(sep)
        lines.append(f"Node {node.node_id} — {node.title}")
        lines.append(f"Pages {page_range[0]}-{page_range[1]}")
        if node.summary:
            lines.append(f"Summary: {node.summary}")
        lines.append(sep)
        lines.append("")
        for page in node.pages:
            lines.append(f"--- Page {page.ordinal} ---")
            lines.append(page.text)
            lines.append("")
    return "\n".join(lines)


def result_payload(result: RetrievalResult, *, max_page_chars: int) -> dict[str, Any]:
    selected_nodes: list[dict[str, Any]] = []
    total_page_tokens = 0
    for node in result.selected_nodes:
        total_page_tokens += sum(page.token_count for page in node.pages)
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
                "page_count": len(node.pages),
                "token_count": sum(page.token_count for page in node.pages),
                "pages": [
                    {
                        "ordinal": page.ordinal,
                        "token_count": page.token_count,
                        "source_locator": page.source_locator,
                        "text": page_text(page.text, max_page_chars),
                    }
                    for page in node.pages
                ],
            }
        )

    return {
        "doc_id": result.doc_id,
        "doc_hash": result.doc_hash,
        "query": result.query,
        "selected_node_ids": result.selection.selected_node_ids,
        "reasoning": result.selection.reasoning,
        "selected_node_count": len(result.selected_nodes),
        "loaded_page_count": sum(len(node.pages) for node in result.selected_nodes),
        "loaded_page_tokens": total_page_tokens,
        "selected_nodes": selected_nodes,
    }


def record_evidence(
    *,
    args: argparse.Namespace,
    payload: dict[str, Any],
    output_path: Path,
) -> list[dict[str, Any]]:
    if args.evidence_db is None:
        return []
    session_id = args.session_id.strip()
    if not session_id:
        raise ValueError("--session-id is required with --evidence-db")

    store = SqliteEvidenceStore(resolve_path(args.evidence_db))
    now = kst_isoformat()
    rows: list[dict[str, Any]] = []
    for node in payload["selected_nodes"]:
        stable_args = {
            "doc_id": payload["doc_id"],
            "query": payload["query"],
            "node_id": node["node_id"],
        }
        row = store.record(
            EvidenceRow(
                session_id=session_id,
                tool_name="page_index_retrieve",
                stable_args_hash=stable_args_hash(
                    "page_index_retrieve",
                    stable_args,
                ),
                status="satisfied" if node["page_count"] else "empty",
                value_summary=f"{node['title']} pages {node['page_range']}",
                value_ref=str(output_path),
                task_id=args.task_id.strip(),
                unit_objective=args.unit_objective.strip() or payload["query"],
                created_at=now,
                updated_at=now,
                stable_args=stable_args,
                tree_node_id=node["node_id"],
                page_range=list(node["page_range"]),
            )
        )
        rows.append(asdict(row))
    return rows


async def run_query(
    args: argparse.Namespace,
    *,
    store: IndexStore,
    document: Any,
    query: str,
    folder_name: str,
    file_prefix: str,
) -> dict[str, Any]:
    doc_dir = resolve_path(args.output_dir) / folder_name
    doc_dir.mkdir(parents=True, exist_ok=True)
    usage_path = doc_dir / f"{file_prefix}-llm_usage.jsonl"
    llm_calls_path = doc_dir / f"{file_prefix}-llm_calls.jsonl"
    output_path = doc_dir / f"{file_prefix}-result.json"
    text_path = doc_dir / f"{file_prefix}-text.txt"

    trace_writer = PageIndexTraceWriter(
        usage_path=usage_path,
        llm_calls_path=llm_calls_path,
        session_started_at=kst_isoformat(),
    )
    indexing_cost_usd = document.metadata.get("indexing_cost_usd")
    retrieval_cost_budget_usd = retrieval_budget_from_indexing_cost(
        indexing_cost_usd,
        divisor=args.retrieval_budget_indexing_cost_divisor,
    )
    client = create_llm_client(model=args.model, usage_writer=trace_writer)
    retriever = TreeRetriever(
        client,
        retrieval_cost_budget_usd=retrieval_cost_budget_usd,
    )
    result = await retriever.retrieve(
        store=store,
        document=document,
        sub_query=query,
    )
    trace_writer.append_total()

    payload = result_payload(result, max_page_chars=args.max_page_chars)
    payload["indexing_cost_usd"] = indexing_cost_usd
    payload["retrieval_cost_budget_usd"] = retrieval_cost_budget_usd
    payload["retrieval_budget_indexing_cost_divisor"] = (
        args.retrieval_budget_indexing_cost_divisor
    )
    evidence_rows = record_evidence(
        args=args,
        payload=payload,
        output_path=output_path,
    )
    if evidence_rows:
        payload["evidence_rows"] = evidence_rows
    payload["usage_path"] = str(usage_path)
    payload["llm_calls_path"] = str(llm_calls_path)
    text_path.write_text(
        format_text_output(result, query),
        encoding="utf-8",
    )
    payload["text_path"] = str(text_path)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    payload["output_path"] = str(output_path)
    return payload


async def gather_queries_limited(
    items: list[tuple[int, str]],
    *,
    concurrency: int,
    process: Any,
) -> list[dict[str, Any]]:
    if concurrency <= 0:
        raise ValueError("query_concurrency must be > 0")
    semaphore = asyncio.Semaphore(concurrency)

    async def guarded(item: tuple[int, str]) -> dict[str, Any]:
        async with semaphore:
            return await process(item)

    return list(await asyncio.gather(*(guarded(item) for item in items)))


async def run(args: argparse.Namespace) -> None:
    store = IndexStore(resolve_path(args.db))
    document = load_document(store, args)
    folder_name = safe_output_prefix(args.output_prefix or document.doc_id)
    queries = [(index, query) for index, query in enumerate(args.query, start=1)]

    async def process(item: tuple[int, str]) -> dict[str, Any]:
        index, query = item
        file_prefix = "retrieve" if len(queries) == 1 else f"retrieve-q{index}"
        return await run_query(
            args,
            store=store,
            document=document,
            query=query,
            folder_name=folder_name,
            file_prefix=file_prefix,
        )

    results = await gather_queries_limited(
        queries,
        concurrency=args.query_concurrency,
        process=process,
    )
    payload: dict[str, Any] | list[dict[str, Any]]
    payload = results[0] if len(results) == 1 else results
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
