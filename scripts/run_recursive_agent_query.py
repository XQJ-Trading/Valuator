#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from valuator.agent_runtime import create_tool_registry, final_output_text, finalize_trace
from valuator.core.llm_usage import Measurement
from valuator.session_store import ValuatorSessionStore
from valuator.utils.logger import close_session_log_file, session_log_file

DEFAULT_QUERY_FILE = ROOT / "scripts" / "queries" / "amazon_analysis_ko.txt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the recursive agent against a real query text."
    )
    parser.add_argument(
        "--query",
        help="Inline query text. When omitted, --query-file is used.",
    )
    parser.add_argument(
        "--query-file",
        type=Path,
        default=DEFAULT_QUERY_FILE,
        help=f"Path to a UTF-8 query file. Default: {DEFAULT_QUERY_FILE.relative_to(ROOT)}",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Override model name. Defaults to AGENT_MODEL / project config.",
    )
    parser.add_argument(
        "--thinking-level",
        default="high",
        help="Optional thinking level tag appended to the effective query.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Maximum steps per task. Defaults to project config.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Maximum number of ready tasks processed per round. Defaults to project config.",
    )
    parser.add_argument(
        "--show-query",
        action="store_true",
        help="Print the effective query and exit without calling the model.",
    )
    parser.add_argument(
        "--dump-analysis",
        action="store_true",
        help="Print QueryAnalysis as JSON before running the agent.",
    )
    parser.add_argument(
        "--jsonl-events",
        action="store_true",
        help="Emit AgentEvent rows as JSON Lines instead of human-readable text.",
    )
    return parser.parse_args()


def read_query(args: argparse.Namespace) -> str:
    if args.query:
        query = str(args.query).strip()
        if query:
            return query
        raise ValueError("--query must not be empty")

    path = Path(args.query_file).expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"query file not found: {path}")

    query = path.read_text(encoding="utf-8").strip()
    if not query:
        raise ValueError(f"query file is empty: {path}")
    return query


def build_effective_query(query: str, thinking_level: str) -> str:
    level = thinking_level.strip()
    if not level:
        return query.strip()
    return f"[THINKING_LEVEL]\n{level}\n\n[QUERY]\n{query.strip()}"


async def build_query_analysis(
    query: str,
    model: str,
    *,
    usage_writer: object | None = None,
):
    from domain import DomainLoader, DomainRouter, QueryAnalyzer, QueryIntent
    from valuator.models.gemini_direct import GeminiClient

    measurement = Measurement.start()
    try:
        domain_index, modules = DomainLoader().load()
        router = DomainRouter(
            analyzer=QueryAnalyzer(client=GeminiClient(model=model)),
        )
        router.bind_usage_writer(usage_writer)
        _, analysis = await router.analyze(
            QueryIntent(query=query),
            domain_index,
            modules,
        )
    except Exception as exc:
        write_diagnostic_record = getattr(usage_writer, "write_diagnostic_record", None)
        if callable(write_diagnostic_record):
            write_diagnostic_record(
                category="analysis",
                method="query_analysis.analyze",
                status="failed",
                summary=str(exc),
                started_at=measurement.started_at,
                duration_ms=round(measurement.latency_seconds() * 1000.0, 3),
                input_payload={"query": query, "model": model},
                result_payload={"error": str(exc)},
                error=str(exc),
            )
        raise

    write_diagnostic_record = getattr(usage_writer, "write_diagnostic_record", None)
    if callable(write_diagnostic_record):
        write_diagnostic_record(
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
            input_payload={"query": query, "model": model},
            result_payload=asdict(analysis),
        )
    return analysis


def render_event(event, *, jsonl: bool) -> str:
    if jsonl:
        return json.dumps(asdict(event), ensure_ascii=False)

    event_type = event.type
    task_id = event.task_id
    detail = event.detail

    if event_type == "step_start":
        global_seq = detail.get("global_seq")
        step = detail.get("step", "?")
        if global_seq is None:
            step_text = f"l{step}"
        else:
            step_text = f"g{global_seq} l{step}"
        return f"[step] {task_id} {step_text} {detail.get('description', '')}".strip()
    if event_type == "decision":
        action = str(detail.get("action") or "").upper()
        reason = str(detail.get("reason") or "").strip()
        return f"[decision] {task_id} {action} {reason}".strip()
    if event_type == "tool_execute":
        tool = str(detail.get("tool") or "").strip()
        duration_ms = detail.get("duration_ms")
        duration_text = (
            f" ({float(duration_ms):.1f}ms)"
            if isinstance(duration_ms, (int, float))
            else ""
        )
        return (
            f"[tool] {task_id} {tool}{duration_text} "
            f"{json.dumps(detail.get('args') or {}, ensure_ascii=False)}"
        )
    if event_type == "step_invalid":
        return (
            f"[step_invalid] {task_id} "
            f"#{detail.get('invalid_decision_count', '?')} {detail.get('error', '')}"
        ).strip()
    if event_type == "task_done":
        return f"[done] {task_id}"
    if event_type == "task_failed":
        return f"[failed] {task_id} {detail.get('error', '')}".strip()
    if event_type == "conflict":
        return (
            f"[conflict] {task_id} {detail.get('key')}: "
            f"{json.dumps(detail.get('existing'), ensure_ascii=False)} vs "
            f"{json.dumps(detail.get('incoming'), ensure_ascii=False)}"
        )
    return f"[{event_type}] {task_id} {json.dumps(detail, ensure_ascii=False, default=str)}"


async def run(args: argparse.Namespace) -> int:
    from valuator.core import Agent, AgentEvent, ComplexTask, Scheduler, SharedState
    from valuator.models.gemini_direct import GeminiClient
    from valuator.utils.config import config

    raw_query = read_query(args)
    effective_query = build_effective_query(raw_query, args.thinking_level)

    if args.show_query:
        print(effective_query)
        return 0

    model = args.model.strip() or config.agent_model
    max_steps = (
        args.max_steps
        if args.max_steps is not None
        else config.agent_max_steps_per_task
    )
    concurrency = (
        args.concurrency
        if args.concurrency is not None
        else config.agent_concurrency
    )
    created_at = datetime.now(timezone.utc)
    session_id = f"CLI-{created_at.strftime('%Y%m%d-%H%M%S%fZ')}"
    session_store = ValuatorSessionStore(
        session_id=session_id,
        query=raw_query,
        model=model,
        created_at=created_at,
        root_dir=ROOT / "logs",
    )
    trace_writer = session_store.trace_writer
    runtime_log_path = trace_writer.runtime_log_path

    with session_log_file(runtime_log_path):
        try:
            trace_writer.append_event(
                {
                    "type": "start",
                    "query": effective_query,
                    "content": effective_query,
                }
            )
            root_task = ComplexTask(
                id="root",
                description=f"Valuation: {effective_query}",
            )
            session_store.update_trace_query(effective_query)
            session_store.sync_task_tree(root_task)
            analysis = await build_query_analysis(
                effective_query,
                model,
                usage_writer=trace_writer,
            )
            session_store.write_plan(
                effective_query=effective_query,
                analysis=analysis,
                root_task=root_task,
            )

            if args.dump_analysis:
                print(json.dumps(asdict(analysis), ensure_ascii=False, indent=2))
                print()

            async def on_event(event: AgentEvent) -> None:
                trace_writer.append_event(asdict(event))
                print(render_event(event, jsonl=args.jsonl_events), flush=True)

            agent = Agent(
                scheduler=Scheduler(
                    max_steps_per_task=max_steps,
                    concurrency=concurrency,
                ),
                shared_state=SharedState(),
                tool_registry=create_tool_registry(
                    model,
                    usage_writer=trace_writer,
                ),
                llm_client=GeminiClient(
                    model=model,
                    usage_writer=trace_writer,
                ),
                query_analysis=analysis,
                on_event=on_event,
                session_store=session_store,
            )
            output = await agent.run(effective_query, root_task)
            final_text = final_output_text(output)
            session_store.write_final_output(final_text, root_task=root_task)
            session_store.sync_task_tree(root_task)
            trace_writer.append_event(
                {
                    "type": "final_answer",
                    "content": final_text,
                }
            )
            trace_writer.append_event({"type": "end", "content": "completed"})
            completed_at = datetime.now(timezone.utc)
            finalize_trace(
                trace_writer,
                status="completed",
                completed_at=completed_at,
                final_answer=final_text,
                duration=max(0.0, (completed_at - created_at).total_seconds()),
            )
            session_store.update_session(status="completed", updated_at=completed_at)
            print("\n[final]\n")
            print(final_text)
            return 0
        except BaseException as exc:
            error_text = str(exc) or exc.__class__.__name__
            trace_writer.append_event({"type": "error", "message": error_text})
            completed_at = datetime.now(timezone.utc)
            finalize_trace(
                trace_writer,
                status="failed",
                completed_at=completed_at,
                error=error_text,
                duration=max(0.0, (completed_at - created_at).total_seconds()),
            )
            session_store.update_session(
                status="failed",
                error=error_text,
                updated_at=completed_at,
            )
            raise
        finally:
            close_session_log_file(runtime_log_path)


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
