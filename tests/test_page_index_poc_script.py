from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from scripts.export_sec_10k_text import (
    default_output_path,
    page_index_manifest,
    safe_ticker,
)
from scripts.run_page_index_retrieve_poc import (
    gather_queries_limited,
    page_text,
    result_payload,
)
from scripts.run_page_index_poc import (
    LoaderConfig,
    PageIndexTraceWriter,
    build_pages,
    default_loader,
    gather_limited,
    input_mime,
    load_manifest,
    parse_args,
    safe_output_prefix,
)
from valuator.documents import (
    DocumentLoader,
    NodeSelection,
    Page,
    PageMarkerPattern,
    RawDocument,
    RetrievedNode,
)
from valuator.documents import RetrievalResult
from valuator.utils.llm_usage import TokenUsage


def test_page_index_trace_writer_records_usage_and_llm_calls(tmp_path) -> None:
    usage_path = tmp_path / "llm_usage.jsonl"
    calls_path = tmp_path / "llm_calls.jsonl"
    writer = PageIndexTraceWriter(
        usage_path=usage_path,
        llm_calls_path=calls_path,
        session_started_at="2026-05-21T20:00:00+09:00",
    )

    writer.append_call(
        method="page_index.init",
        model="gemini-3-flash-preview",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=3, total_tokens=13),
        latency_seconds=0.25,
        started_at="2026-05-21T20:00:01+09:00",
    )
    writer.log_llm_call(
        trace_method="page_index.init",
        model="gemini-3-flash-preview",
        prompt="prompt",
        system_prompt="system",
        response_mime_type="application/json",
        response_json_schema={"type": "object"},
        response_text='{"ok": true}',
        usage={"total_tokens": 13},
        latency_ms=250.0,
        started_at="2026-05-21T20:00:01+09:00",
    )
    writer.append_total()

    usage_rows = [
        json.loads(line)
        for line in usage_path.read_text(encoding="utf-8").splitlines()
    ]
    call_rows = [
        json.loads(line)
        for line in calls_path.read_text(encoding="utf-8").splitlines()
    ]

    assert [row["method"] for row in usage_rows] == ["page_index.init", "TOTAL"]
    assert call_rows[0]["trace_method"] == "page_index.init"
    assert call_rows[0]["error"] is None


def test_page_index_poc_builds_pages_from_generic_markers() -> None:
    document = RawDocument(
        doc_id="generic-doc",
        source="memory://generic-doc",
        raw_bytes_or_text="first page\n-- page 7 --\nsecond page\n-- page 8 --\n",
    )

    pages = build_pages(
        document=document,
        loader=DocumentLoader.marked_text(
            marker=PageMarkerPattern(
                pattern=re.compile(r"-- page (?P<page>\d+) --$"),
                locator_kind="source_page",
            )
        ),
    )

    assert [page.ordinal for page in pages] == [7, 8]
    assert pages[0].source_locator["kind"] == "source_page"
    assert pages[0].source_locator["ordinal_origin"] == "page_marker"
    assert pages[1].text.startswith("second page")


def test_page_index_poc_helpers_are_generic() -> None:
    assert default_loader(Path("report.pdf")).metadata()["page_unit"] == "pdf_page"
    assert default_loader(Path("report.pdf")).metadata()["toc_page_numbers_mappable"]
    assert default_loader(Path("report.txt")).metadata()["page_unit"] == "token_window"
    assert not default_loader(Path("report.txt")).metadata()["toc_page_numbers_mappable"]
    assert input_mime(Path("report.pdf")) == "application/pdf"
    assert input_mime(Path("report.md")) == "text/markdown"
    assert input_mime(Path("report.txt")) == "text/plain"
    assert safe_output_prefix("annual report/fy 2024") == "annual-report-fy-2024"


def test_page_index_poc_parser_keeps_toc_detector_out_of_runtime_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["run_page_index_poc.py", "--input-file", "report.pdf"],
    )

    args = parse_args()

    assert "toc_scan_max_tokens" not in vars(args)
    assert "toc_min_confidence" not in vars(args)


def test_page_index_manifest_loads_marked_text_document(tmp_path) -> None:
    manifest_path = tmp_path / "page_index.json"
    input_path = tmp_path / "report.txt"
    input_path.write_text("page one\nPage 1\n", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "input_file": str(input_path),
                        "doc_id": "report",
                        "loader": {
                            "kind": "marked_text",
                            "marker": {
                                "regex": r"Page (?P<page>\d+)$",
                                "locator_kind": "source_page",
                            },
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    documents = load_manifest(manifest_path)
    pages = build_pages(
        document=RawDocument(
            doc_id=documents[0].doc_id,
            source=documents[0].source,
            raw_bytes_or_text=input_path.read_text(encoding="utf-8"),
            mime=documents[0].mime,
        ),
        loader=documents[0].loader,
    )

    assert documents[0].output_prefix == "report"
    assert documents[0].loader.metadata()["page_unit"] == "source_page"
    assert documents[0].loader.metadata()["toc_page_numbers_mappable"]
    assert [page.ordinal for page in pages] == [1]


def test_marked_text_loader_config_requires_marker() -> None:
    with pytest.raises(ValueError, match="requires loader.marker"):
        LoaderConfig(kind="marked_text")


def test_sec_export_helper_builds_stable_output_path() -> None:
    assert safe_ticker("AAPL.O") == "aaplo"
    assert default_output_path(
        output_dir=Path("data/page_index"),
        ticker="AAPL",
        year=2024,
    ) == Path("data/page_index/aapl-2024/source.txt")
    manifest = page_index_manifest(
        output_path=Path("data/page_index/aapl-2024/source.txt"),
        doc_id="aapl-2024",
        source="https://example.test/aapl",
    )
    assert manifest["documents"][0]["loader"]["kind"] == "marked_text"


def test_retrieve_poc_payload_truncates_loaded_page_text() -> None:
    assert page_text("abcdef", 3) == "abc\n...[truncated]"

    payload = result_payload(
        RetrievalResult(
            doc_id="doc-1",
            doc_hash="hash-1",
            query="query",
            selection=NodeSelection(
                doc_id="doc-1",
                selected_node_ids=["n.1"],
                reasoning="reason",
            ),
            selected_nodes=[
                RetrievedNode(
                    node_id="n.1",
                    title="Section",
                    page_range=[1, 1],
                    summary="summary",
                    pages=[
                        Page(
                            doc_id="doc-1",
                            ordinal=1,
                            text="abcdef",
                            token_count=2,
                            source_locator={"kind": "source_page", "page": 1},
                        )
                    ],
                )
            ],
        ),
        max_page_chars=4,
    )

    assert payload["selected_node_ids"] == ["n.1"]
    assert payload["loaded_page_tokens"] == 2
    assert payload["selected_nodes"][0]["pages"][0]["text"] == "abcd\n...[truncated]"


@pytest.mark.asyncio
async def test_page_index_poc_batch_helper_limits_document_concurrency() -> None:
    active = 0
    max_active = 0

    async def process(path: Path) -> dict[str, object]:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1
        return {"path": str(path)}

    results = await gather_limited(
        [Path("a.txt"), Path("b.txt"), Path("c.txt")],
        concurrency=2,
        process=process,
    )

    assert max_active == 2
    assert [row["path"] for row in results] == ["a.txt", "b.txt", "c.txt"]


@pytest.mark.asyncio
async def test_retrieve_poc_batch_helper_limits_query_concurrency() -> None:
    active = 0
    max_active = 0

    async def process(item: tuple[int, str]) -> dict[str, object]:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1
        return {"item": item}

    results = await gather_queries_limited(
        [(1, "one"), (2, "two"), (3, "three")],
        concurrency=2,
        process=process,
    )

    assert max_active == 2
    assert [row["item"] for row in results] == [
        (1, "one"),
        (2, "two"),
        (3, "three"),
    ]
