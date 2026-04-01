from __future__ import annotations

import json
from pathlib import Path

import pytest

from valuator.models.gemini_direct import GeminiClient
from valuator.session import SessionTraceWriter
from valuator.utils.llm_usage import TokenUsage
from valuator.utils.logger import close_session_log_file, logger, session_log_file


def test_session_trace_writer_records_task_hierarchy_and_trace_artifacts(
    tmp_path: Path,
) -> None:
    writer = SessionTraceWriter(
        session_id="S-test",
        query="삼성전자 valuation",
        model="gemini-3-flash-preview",
        created_at="2026-03-21T02:31:05.577471Z",
        base_dir=tmp_path,
    )

    writer.append_event({"type": "start", "content": "삼성전자 valuation"})
    writer.append_call(
        method="query_analysis.analyze",
        model="gemini-3-flash-preview",
        usage=TokenUsage(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
        latency_seconds=1.25,
        started_at="2026-03-21T02:31:05.582740Z",
    )
    writer.write_task_step(
        task_id="root",
        task_seq=1,
        phase="decision",
        action="execute",
        status="success",
        started_at="2026-03-21T02:31:05.582740Z",
        duration_ms=12.5,
        reason="need company overview",
        summary="execute(web_search_tool)",
        tool_name="web_search_tool",
        tool_args={"query": "삼성전자 개요"},
        input_payload={"task": {"id": "root", "description": "삼성전자 valuation"}},
        result_payload={"action": "execute"},
    )
    writer.write_task_step(
        task_id="root",
        task_seq=1,
        phase="tool_result",
        action="execute",
        status="success",
        started_at="2026-03-21T02:31:06.000000Z",
        duration_ms=5012.0,
        summary="사업 구조, 반도체 중심 기업",
        tool_name="web_search_tool",
        tool_args={"query": "삼성전자 개요"},
        tool_success=True,
        result_payload={
            "success": True,
            "result": {"findings": "사업 구조, 반도체 중심 기업"},
        },
    )
    writer.log_llm_call(
        trace_method="agent.step.root",
        model="gemini-3-flash-preview",
        prompt="prompt",
        system_prompt="system",
        response_mime_type="application/json",
        response_json_schema={"type": "object"},
        response_text='{"action":"finalize"}',
        usage={
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
        latency_ms=1250.0,
        started_at="2026-03-21T02:31:05.582740Z",
    )
    writer.append_total()
    writer.update_session(
        status="completed",
        completed_at="2026-03-21T02:31:10.000000Z",
        final_answer="done",
        duration=4.5,
    )

    session_dir = tmp_path / "session_S-test"
    session_data = json.loads(
        (session_dir / "session.json").read_text(encoding="utf-8")
    )
    event_rows = (
        (session_dir / "trace" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    usage_rows = (
        (session_dir / "trace" / "llm_usage.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    timeline_rows = (
        (session_dir / "timeline.jsonl").read_text(encoding="utf-8").splitlines()
    )
    task_steps = (
        (session_dir / "debug" / "steps" / "root" / "steps.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    task_markdown = (session_dir / "tasks" / "root" / "task.md").read_text(
        encoding="utf-8"
    )
    llm_call = json.loads(
        (session_dir / "tasks" / "root" / "llm_calls" / "step_01.json").read_text(
            encoding="utf-8"
        )
    )

    assert session_data["status"] == "completed"
    assert session_data["event_count"] == 1
    assert session_data["step_count"] == 2
    assert session_data["llm_call_count"] == 1
    assert session_data["final_answer"] == "done"
    assert session_data["paths"]["timeline"] == "timeline.jsonl"
    assert session_data["paths"]["trace"] == "trace"
    assert session_data["paths"]["debug_steps"] == "debug/steps"
    assert len(event_rows) == 1
    assert len(usage_rows) == 2
    assert len(timeline_rows) == 2
    assert len(task_steps) == 2
    assert "execute(web_search_tool)" in timeline_rows[0]
    assert "execute(web_search_tool)" in task_markdown
    assert "**result**: success (5012ms)" in task_markdown
    assert llm_call["task_id"] == "root"
    assert llm_call["response_text"] == '{"action":"finalize"}'


def test_session_trace_writer_routes_diagnostic_records_to_events_log(
    tmp_path: Path,
) -> None:
    writer = SessionTraceWriter(
        session_id="S-method",
        query="method trace",
        model="gemini-3-flash-preview",
        created_at="2026-03-21T02:31:05.577471Z",
        base_dir=tmp_path,
    )

    writer.write_diagnostic_record(
        category="analysis",
        method="query_analysis.analyze",
        status="success",
        summary="domains=1 units=1 requirements=1",
        started_at="2026-03-21T02:31:05.582740Z",
        duration_ms=12.5,
        input_payload={"query": "alpha"},
        result_payload={"domain_ids": ["dcf"]},
    )

    session_dir = tmp_path / "session_S-method"
    session_data = json.loads(
        (session_dir / "session.json").read_text(encoding="utf-8")
    )
    rows = (
        (session_dir / "trace" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    payload = json.loads(rows[0])

    assert session_data["event_count"] == 1
    assert len(rows) == 1
    assert payload["type"] == "diagnostic_record"
    assert payload["category"] == "analysis"
    assert payload["method"] == "query_analysis.analyze"
    assert payload["status"] == "success"


def test_session_log_file_routes_runtime_logs(tmp_path: Path) -> None:
    log_path = tmp_path / "runtime.log"

    with session_log_file(log_path):
        logger.info("runtime log check")

    close_session_log_file(log_path)

    content = log_path.read_text(encoding="utf-8")
    assert "runtime log check" in content


class _DummyUsageMetadata:
    def model_dump(self) -> dict[str, int]:
        return {
            "prompt_tokens": 12,
            "completion_tokens": 8,
            "total_tokens": 20,
        }


class _DummyResponse:
    text = '{"answer":"ok"}'
    usage_metadata = _DummyUsageMetadata()


class _NoisyResponse:
    text = '```json\n{"answer":"ok"}\n```\nNo further text.'
    usage_metadata = _DummyUsageMetadata()


class _DummyModels:
    def generate_content(
        self, *, model: str, contents: str, config: object
    ) -> _DummyResponse:
        del model, contents, config
        return _DummyResponse()


class _NoisyModels:
    def generate_content(
        self, *, model: str, contents: str, config: object
    ) -> _NoisyResponse:
        del model, contents, config
        return _NoisyResponse()


class _DummyClient:
    def __init__(self) -> None:
        self.models = _DummyModels()


class _NoisyClient:
    def __init__(self) -> None:
        self.models = _NoisyModels()


@pytest.mark.asyncio
async def test_gemini_client_writes_llm_call_under_task_dir_and_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "valuator.models.gemini_direct.ensure_supported_google_genai_runtime",
        lambda: "test-runtime",
    )
    writer = SessionTraceWriter(
        session_id="S-gemini",
        query="test query",
        model="gemini-3-flash-preview",
        created_at="2026-03-21T02:31:05.577471Z",
        base_dir=tmp_path,
    )
    client = GeminiClient(
        model="gemini-3-flash-preview",
        api_key="test-key",
        client=_DummyClient(),
        usage_writer=writer,
    )

    payload = await client.generate_json(
        prompt="return answer",
        system_prompt="system prompt",
        response_json_schema={"type": "object"},
        trace_method="agent.step.root",
    )

    session_dir = tmp_path / "session_S-gemini"
    usage_rows = (
        (session_dir / "trace" / "llm_usage.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    step_data = json.loads(
        (session_dir / "tasks" / "root" / "llm_calls" / "step_01.json").read_text(
            encoding="utf-8"
        )
    )

    assert payload == {"answer": "ok"}
    assert len(usage_rows) == 1
    assert step_data["prompt"] == "return answer"
    assert step_data["system_prompt"] == "system prompt"
    assert step_data["task_id"] == "root"


@pytest.mark.asyncio
async def test_gemini_client_recovers_json_object_from_noisy_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "valuator.models.gemini_direct.ensure_supported_google_genai_runtime",
        lambda: "test-runtime",
    )
    client = GeminiClient(
        model="gemini-3-flash-preview",
        api_key="test-key",
        client=_NoisyClient(),
    )

    payload = await client.generate_json(
        prompt="return answer",
        system_prompt="system prompt",
        response_json_schema={"type": "object"},
        trace_method="agent.step.root",
    )

    assert payload == {"answer": "ok"}
