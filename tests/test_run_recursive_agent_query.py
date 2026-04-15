from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pytest

from domain.query import QueryAnalysis
from valuator.core.types import AgentEvent, EventType
from valuator.session import SessionTraceWriter


def _load_script_module():
    path = (
        Path(__file__).resolve().parents[1] / "scripts" / "run_recursive_agent_query.py"
    )
    spec = importlib.util.spec_from_file_location("run_recursive_agent_query", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_render_event_includes_global_and_local_step() -> None:
    module = _load_script_module()
    event = AgentEvent(
        type=EventType.STEP_STARTED,
        task_id="root.1",
        detail={
            "global_seq": 7,
            "step": 2,
            "description": "analyze branch",
        },
    )

    rendered = module.render_event(event, jsonl=False)

    assert rendered == "[step] root.1 g7 l2 analyze branch"


def test_render_event_includes_task_name_in_step_line() -> None:
    module = _load_script_module()
    event = AgentEvent(
        type=EventType.STEP_STARTED,
        task_id="root.1",
        detail={
            "global_seq": 7,
            "step": 2,
            "description": "analyze branch",
            "task_name": "segment_financial_analysis",
        },
    )

    rendered = module.render_event(event, jsonl=False)

    assert rendered == "[step] root.1 segment_financial_analysis g7 l2 analyze branch"


def test_render_event_falls_back_to_local_step_only() -> None:
    module = _load_script_module()
    event = AgentEvent(
        type=EventType.STEP_STARTED,
        task_id="root.1",
        detail={
            "step": 2,
            "description": "analyze branch",
        },
    )

    rendered = module.render_event(event, jsonl=False)

    assert rendered == "[step] root.1 l2 analyze branch"


def test_render_event_collapses_newlines_in_step_description() -> None:
    module = _load_script_module()
    event = AgentEvent(
        type=EventType.STEP_STARTED,
        task_id="root",
        detail={
            "global_seq": 1,
            "step": 1,
            "description": "Analysis: line1\nline2",
        },
    )

    rendered = module.render_event(event, jsonl=False)

    assert "\n" not in rendered
    assert "Analysis: line1 line2" in rendered


@pytest.mark.asyncio
async def test_run_writes_cli_trace_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script_module()

    class _TestTraceWriter(SessionTraceWriter):
        def __init__(self, **kwargs):
            super().__init__(base_dir=tmp_path, **kwargs)

    class _DummyGeminiClient:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class _DummyAgent:
        def __init__(self, *args, **kwargs) -> None:
            self._on_event = kwargs["on_event"]
            self._trace_writer = kwargs["trace_writer"]

        async def run(self, query: str, root_task: object) -> dict[str, str]:
            del query, root_task
            started_at = "2026-03-21T02:31:05.582740Z"
            self._trace_writer.log_llm_call(
                trace_method="agent.step.root",
                model="stub-model",
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
                latency_ms=12.5,
                started_at=started_at,
            )
            self._trace_writer.append_method_call(
                category="decision",
                method="agent.step.root",
                task_id="root",
                status="success",
                summary="action=finalize",
                started_at=started_at,
                duration_ms=12.5,
                input_payload={"task": {"id": "root"}},
                result_payload={"action": "finalize"},
            )
            await self._on_event(
                AgentEvent(
                    type="decision",
                    task_id="root",
                    detail={"action": "finalize", "reason": "complete"},
                )
            )
            from valuator.utils.logger import logger

            logger.info("cli runtime trace")
            return {"content": "final content"}

    async def _build_query_analysis(*args, **kwargs) -> QueryAnalysis:
        del args, kwargs
        return QueryAnalysis(allowed_tools=["dummy_tool"])

    monkeypatch.setattr(module, "session_files_root", lambda: tmp_path)
    monkeypatch.setattr(module, "SessionTraceWriter", _TestTraceWriter)
    monkeypatch.setattr(module, "build_query_analysis", _build_query_analysis)
    monkeypatch.setattr(
        module, "create_tool_registry", lambda *args, **kwargs: object()
    )
    monkeypatch.setattr("valuator.core.Agent", _DummyAgent)
    monkeypatch.setattr(
        module,
        "create_llm_client",
        lambda *args, **kwargs: _DummyGeminiClient(*args, **kwargs),
    )

    args = argparse.Namespace(
        query="alpha query",
        query_file=module.DEFAULT_QUERY_FILE,
        model="stub-model",
        thinking_level="high",
        max_steps=1,
        concurrency=1,
        web_search_provider=None,
        show_query=False,
        dump_analysis=False,
        jsonl_events=False,
    )

    result = await module.run(args)

    assert result == 0
    session_dirs = sorted(d for d in tmp_path.iterdir() if d.is_dir())
    assert len(session_dirs) == 1

    session_dir = session_dirs[0]
    session_data = json.loads(
        (session_dir / "session.json").read_text(encoding="utf-8")
    )
    event_rows = (
        (session_dir / "output" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    method_rows = (
        (session_dir / "output" / "method_calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    runtime_log = (session_dir / "output" / "runtime.log").read_text(encoding="utf-8")
    step_files = sorted((session_dir / "debug" / "steps").glob("step_*.json"))

    assert session_data["status"] == "completed"
    assert session_data["final_answer"] == "final content"
    assert len(event_rows) >= 3
    assert len(method_rows) == 1
    assert len(step_files) == 1
    assert "cli runtime trace" in runtime_log
