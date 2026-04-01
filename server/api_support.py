from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime
from typing import Any

from domain import DomainLoader, DomainRouter, QueryAnalyzer, QueryIntent
from domain.boundary import sec_on_miss
from valuator.core import AgentEvent
from valuator.models.factory import create_llm_client
from valuator.utils.config import config, is_openrouter_model_name, resolve_llm_model_name
from valuator.utils.time_utils import Measurement


async def build_query_analysis(
    query: str,
    model: str,
    *,
    as_of_utc: str | None = None,
    usage_writer: Any | None = None,
):
    effective_as_of_utc = as_of_utc or datetime.utcnow().isoformat() + "Z"
    measurement = Measurement.start()
    try:
        domain_index, modules = DomainLoader().load()
        router = DomainRouter(
            analyzer=QueryAnalyzer(
                client=create_llm_client(model=model),
                on_miss=sec_on_miss,
            ),
        )
        router.bind_usage_writer(usage_writer)
        try:
            _, analysis = await router.analyze(
                QueryIntent(query=query),
                domain_index,
                modules,
                as_of_utc=effective_as_of_utc,
            )
        except TypeError as exc:
            if "as_of_utc" not in str(exc):
                raise
            _, analysis = await router.analyze(
                QueryIntent(query=query),
                domain_index,
                modules,
            )
    except Exception as exc:
        write_diagnostic_record = getattr(usage_writer, "write_diagnostic_record", None)
        if callable(write_diagnostic_record):
            await asyncio.to_thread(
                write_diagnostic_record,
                category="analysis",
                method="query_analysis.analyze",
                status="failed",
                summary=str(exc),
                started_at=measurement.started_at,
                duration_ms=round(measurement.latency_seconds() * 1000.0, 3),
                input_payload={
                    "query": query,
                    "model": model,
                    "as_of_utc": effective_as_of_utc,
                },
                result_payload={"error": str(exc)},
                error=str(exc),
            )
        raise

    write_diagnostic_record = getattr(usage_writer, "write_diagnostic_record", None)
    if callable(write_diagnostic_record):
        await asyncio.to_thread(
            write_diagnostic_record,
            category="analysis",
            method="query_analysis.analyze",
            status="success",
            summary=(
                f"domains={len(analysis.domain_ids)} "
                f"units={len(analysis.units)} "
                f"requirements={len(analysis.requirements)}"
            ),
            started_at=measurement.started_at,
            duration_ms=round(measurement.latency_seconds() * 1000.0, 3),
            input_payload={
                "query": query,
                "model": model,
                "as_of_utc": effective_as_of_utc,
            },
            result_payload=asdict(analysis),
        )
    return analysis


def agent_event_to_stream_event(event: AgentEvent) -> dict[str, Any]:
    detail = event.detail
    if event.type == "step_started":
        return {
            "type": "thought",
            "task_id": event.task_id,
            "content": (
                f"Task step 시작 - {event.task_id} "
                f"({detail.get('step', '?')}): {detail.get('description', '')}"
            ).strip(),
        }
    if event.type == "tool_executed":
        tool_result = detail.get("tool_result")
        result_content = ""
        if isinstance(tool_result, dict):
            result_content = str(
                tool_result.get("result") or tool_result.get("error") or ""
            )
        duration_ms = detail.get("duration_ms")
        duration_text = (
            f" ({float(duration_ms):.1f}ms)"
            if isinstance(duration_ms, (int, float))
            else ""
        )
        return {
            "type": "action",
            "task_id": event.task_id,
            "tool": detail.get("tool"),
            "tool_input": detail.get("args"),
            "tool_result": tool_result,
            "content": (
                f"Tool 실행 - {detail.get('tool', '')}{duration_text}: {result_content}"
            ).strip(),
        }
    if event.type == "failed" and detail.get("kind") == "step_invalid":
        return {
            "type": "observation",
            "task_id": event.task_id,
            "error": detail.get("error"),
            "content": (
                f"Invalid step - {event.task_id} "
                f"({detail.get('invalid_decision_count', '?')}): {detail.get('error', '')}"
            ).strip(),
        }
    if event.type == "step_completed":
        if detail.get("kind") == "conflict":
            return {
                "type": "observation",
                "task_id": event.task_id,
                "content": (
                    f"Conflict 감지 - {detail.get('key')}: "
                    f"{detail.get('existing')} vs {detail.get('incoming')}"
                ),
            }
        action = str(detail.get("action") or "").upper()
        return {
            "type": "thought",
            "task_id": event.task_id,
            "content": f"{event.task_id} → {action}".strip(),
        }
    if event.type in ("aggregated", "finalized"):
        return {
            "type": "observation",
            "task_id": event.task_id,
            "content": f"Task 완료 - {event.task_id}",
            "tool_output": detail.get("output"),
        }
    if event.type == "failed":
        return {
            "type": "observation",
            "task_id": event.task_id,
            "error": detail.get("error"),
            "content": f"Task 실패 - {event.task_id}: {detail.get('error', '')}".strip(),
        }
    return {
        "type": "observation",
        "task_id": event.task_id,
        "content": str(detail),
    }


def resolve_request_model(value: str | None) -> str | None:
    if value is None:
        return None
    openrouter_enabled = config.llm_backend == "openrouter" and bool(
        config.openrouter_api_key
    )
    raw = value.strip()
    if not raw:
        raise ValueError("Model cannot be empty")
    model = resolve_llm_model_name(raw, openrouter_backend=openrouter_enabled)
    if openrouter_enabled:
        return model
    if model in config.supported_models:
        return model
    if is_openrouter_model_name(model) and not openrouter_enabled:
        return config.agent_model
    raise ValueError(
        f"Unsupported model: {value}. "
        f"Supported models are: {', '.join(config.supported_models)}"
    )


def sessions_to_summaries(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for session in sessions:
        steps = session.get("steps") or []
        final_answer = str(session.get("final_answer") or "")
        tools_used = sorted(
            {
                str(step.get("tool"))
                for step in steps
                if isinstance(step, dict) and isinstance(step.get("tool"), str)
            }
        )
        summaries.append(
            {
                "session_id": str(session.get("session_id") or ""),
                "timestamp": str(
                    session.get("timestamp")
                    or session.get("created_at")
                    or datetime.utcnow().isoformat()
                ),
                "query": str(session.get("query") or ""),
                "final_answer": final_answer,
                "success": bool(session.get("success", True)),
                "duration": float(session.get("duration", 0.0)),
                "step_count": len(steps),
                "tools_used": tools_used,
            }
        )
    return summaries


def session_to_stream_events(session: dict[str, Any]) -> list[dict[str, Any]]:
    steps = session.get("steps")
    if isinstance(steps, list) and steps:
        events: list[dict[str, Any]] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            event_type = str(step.get("type") or "observation")
            content = str(step.get("content") or "")
            event: dict[str, Any] = {"type": event_type, "content": content}
            for key in (
                "tool",
                "tool_input",
                "tool_output",
                "tool_result",
                "error",
                "query",
            ):
                if key in step:
                    event[key] = step[key]
            events.append(event)
        return events

    query = str(session.get("query") or "")
    final_answer = str(session.get("final_answer") or "")
    return [
        {"type": "start", "query": query, "content": query},
        {"type": "final_answer", "content": final_answer},
        {"type": "end", "content": "완료"},
    ]
