from __future__ import annotations

import json
from pathlib import Path

from scripts.export_sec_10k_text import default_output_path, safe_ticker
from scripts.run_page_index_retrieve_poc import page_text, result_payload
from scripts.run_page_index_poc import (
    PageIndexTraceWriter,
    build_pages,
    marker_boundary,
    marker_group,
    safe_output_prefix,
)
from valuator.documents import NodeSelection, Page, RawDocument, RetrievedNode
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
        text_page_tokens=100,
        page_marker_regex=r"-- page (?P<page>\d+) --$",
        page_marker_group="page",
        page_marker_kind="source_page",
        page_marker_boundary="end",
    )

    assert [page.ordinal for page in pages] == [7, 8]
    assert pages[0].source_locator["kind"] == "source_page"
    assert pages[1].text.startswith("second page")


def test_page_index_poc_helpers_are_generic() -> None:
    assert marker_group("1") == 1
    assert marker_group("page") == "page"
    assert marker_boundary("start") == "start"
    assert safe_output_prefix("annual report/fy 2024") == "annual-report-fy-2024"


def test_sec_export_helper_builds_stable_output_path() -> None:
    assert safe_ticker("AAPL.O") == "aaplo"
    assert default_output_path(
        output_dir=Path("data/page_index"),
        ticker="AAPL",
        year=2024,
    ) == Path("data/page_index/aapl-2024.txt")


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
