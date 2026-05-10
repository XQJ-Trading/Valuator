#!/usr/bin/env python3
from __future__ import annotations

# ruff: noqa: E402

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from valuator.runtime import create_tool_registry, finalize_trace  # noqa: E402
from valuator.models.factory import create_llm_client  # noqa: E402
from valuator.session import SessionTraceWriter, ValuatorSessionStore  # noqa: E402
from valuator.session.trace import json_ready  # noqa: E402
from valuator.session.browse_tree import (  # noqa: E402
    task_description_from_effective_query,
)
from valuator.session.root_log_name import build_unique_root_session_id  # noqa: E402
from valuator.utils.config import session_files_root  # noqa: E402
from valuator.utils.config import WEB_SEARCH_PROVIDER_NAMES  # noqa: E402
from valuator.utils.logger import close_session_log_file, session_log_file  # noqa: E402
from valuator.utils.time_utils import KST, Measurement, kst_as_of_format  # noqa: E402
from valuator.core.types import EventType  # noqa: E402

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
        default="low",
        help="Optional thinking level tag appended to the effective query. Omitted by default.",
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
        "--web-search-provider",
        choices=WEB_SEARCH_PROVIDER_NAMES,
        default=None,
        help="Override web search backend. Defaults to WEB_SEARCH_PROVIDER / project config.",
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
    as_of_kst: str,
    usage_writer: object | None = None,
):
    from domain import DomainRouter, QueryAnalyzer, QueryIntent

    measurement = Measurement.start()
    try:
        from domain.boundary import combined_on_miss

        router = DomainRouter(
            analyzer=QueryAnalyzer(
                client=create_llm_client(model=model),
                on_miss=combined_on_miss,
            ),
        )
        router.bind_usage_writer(usage_writer)
        _, analysis = await router.analyze(
            QueryIntent(query=query),
            as_of_kst=as_of_kst,
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
                input_payload={"query": query, "model": model, "as_of_kst": as_of_kst},
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
                f"units={len(analysis.units)} "
                f"requirements={len(analysis.requirements)}"
            ),
            started_at=measurement.started_at,
            duration_ms=round(measurement.latency_seconds() * 1000.0, 3),
            input_payload={"query": query, "model": model, "as_of_kst": as_of_kst},
            result_payload=asdict(analysis),
        )
    return analysis


def _write_cli_trace_compat(trace_writer: SessionTraceWriter) -> None:
    session_dir = trace_writer.session_dir
    output_dir = session_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    events_src = session_dir / "trace" / "events.jsonl"
    if events_src.exists():
        shutil.copyfile(events_src, output_dir / "events.jsonl")

    runtime_src = session_dir / "trace" / "runtime.log"
    if runtime_src.exists():
        shutil.copyfile(runtime_src, output_dir / "runtime.log")

    method_rows: list[dict[str, object]] = []
    for steps_path in sorted(session_dir.glob("debug/steps/**/steps.jsonl")):
        task_id = str(
            steps_path.parent.relative_to(session_dir / "debug" / "steps")
        ).replace("/", ".")
        for line in steps_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            method_rows.append(
                {
                    "category": row.get("phase"),
                    "method": f"task.{task_id}",
                    "task_id": task_id,
                    "status": row.get("status"),
                    "summary": row.get("summary", ""),
                    "started_at": row.get("timestamp"),
                    "duration_ms": row.get("duration_ms"),
                    "input": row.get("input"),
                    "result": row.get("result"),
                    "error": row.get("error"),
                }
            )
    with (output_dir / "method_calls.jsonl").open("w", encoding="utf-8") as file_obj:
        for row in method_rows:
            file_obj.write(json.dumps(json_ready(row), ensure_ascii=False) + "\n")


def render_event(event, *, jsonl: bool) -> str:
    if jsonl:
        return json.dumps(json_ready(asdict(event)), ensure_ascii=False)

    event_type = event.type
    task_id = event.task_id
    detail = event.detail

    def _task_name() -> str:
        return str(detail.get("task_name") or "").strip()

    if event_type == EventType.STEP_STARTED:
        global_seq = detail.get("global_seq")
        step = detail.get("step", "?")
        if global_seq is None:
            step_text = f"l{step}"
        else:
            step_text = f"g{global_seq} l{step}"
        tn = _task_name()
        name_part = f"{tn} " if tn else ""
        desc = str(detail.get("description", "") or "").replace("\n", " ").strip()
        return (f"[step] {task_id} {name_part}{step_text} {desc}").strip()

    if event_type == EventType.TOOL_EXECUTED:
        tool = str(detail.get("tool") or "").strip()
        duration_ms = detail.get("duration_ms")
        duration_text = (
            f" ({float(duration_ms):.1f}ms)"
            if isinstance(duration_ms, (int, float))
            else ""
        )
        tn = _task_name()
        name_part = f"{tn} " if tn else ""
        return (
            f"[tool] {task_id} {name_part}{tool}{duration_text} "
            f"{json.dumps(json_ready(detail.get('args') or {}), ensure_ascii=False)}"
        )

    if event_type == EventType.STEP_COMPLETED:
        if detail.get("kind") == "conflict":
            return (
                f"[conflict] {task_id} {detail.get('key')}: "
                f"{json.dumps(json_ready(detail.get('existing')), ensure_ascii=False)} vs "
                f"{json.dumps(json_ready(detail.get('incoming')), ensure_ascii=False)}"
            )
        action = detail.get("action")
        if action:
            return f"[decision] {task_id} {str(action).upper()}".strip()

    if event_type == EventType.FAILED:
        if detail.get("kind") == "step_invalid":
            return (
                f"[step_invalid] {task_id} "
                f"#{detail.get('invalid_decision_count', '?')} {detail.get('error', '')}"
            ).strip()
        tn = _task_name()
        name_part = f" {tn}" if tn else ""
        return f"[failed] {task_id}{name_part} {detail.get('error', '')}".strip()

    if event_type in (EventType.AGGREGATED, EventType.FINALIZED):
        tn = _task_name()
        name_part = f" {tn}" if tn else ""
        return f"[done] {task_id}{name_part}".strip()

    if event_type == EventType.DECOMPOSED:
        tn = _task_name()
        name_part = f" {tn}" if tn else ""
        cc = detail.get("child_count", "?")
        return f"[decomposed] {task_id}{name_part} {cc}".strip()

    return f"[{event_type}] {task_id} {json.dumps(detail, ensure_ascii=False, default=str)}"


async def run(args: argparse.Namespace) -> int:
    from valuator.core import Agent, AgentEvent, ComplexTask, Scheduler
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
        args.concurrency if args.concurrency is not None else config.agent_concurrency
    )
    created_at = datetime.now(KST)
    as_of_kst = kst_as_of_format(created_at)
    analysis = await build_query_analysis(
        effective_query,
        model,
        as_of_kst=as_of_kst,
        usage_writer=None,
    )
    session_id = build_unique_root_session_id(
        created_at,
        analysis,
        raw_query,
        session_files_root(),
    )
    session_store = ValuatorSessionStore(
        session_id=session_id,
        query=raw_query,
        model=model,
        created_at=created_at,
        root_dir=session_files_root(),
    )
    # Agent and task steps use session_store.trace_writer; LLM usage and on_event must use the same writer.
    trace_writer = session_store.trace_writer
    runtime_log_path = trace_writer.runtime_log_path

    with session_log_file(runtime_log_path):
        tool_registry = None
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
                description=task_description_from_effective_query(effective_query),
            )
            await asyncio.to_thread(session_store.update_trace_query, effective_query)
            await asyncio.to_thread(session_store.sync_task_tree, root_task)
            root_task.query_unit_ids = list(range(len(analysis.units)))
            await asyncio.to_thread(
                session_store.write_plan,
                effective_query=effective_query,
                analysis=analysis,
                root_task=root_task,
            )

            if args.dump_analysis:
                print(json.dumps(asdict(analysis), ensure_ascii=False, indent=2))
                print()

            async def on_event(event: AgentEvent) -> None:
                await asyncio.to_thread(trace_writer.append_event, asdict(event))
                print(render_event(event, jsonl=args.jsonl_events), flush=True)

            tool_registry = create_tool_registry(
                model,
                usage_writer=trace_writer,
                web_search_provider=args.web_search_provider,
            )

            agent = Agent(
                scheduler=Scheduler(
                    max_steps_per_task=max_steps,
                    concurrency=concurrency,
                ),
                tool_registry=tool_registry,
                llm_client=create_llm_client(
                    model=model,
                    usage_writer=trace_writer,
                ),
                query_analysis=analysis,
                on_event=on_event,
                session_store=session_store,
                trace_writer=trace_writer,
            )
            output = await agent.run(effective_query, root_task)
            final_text = await asyncio.to_thread(
                session_store.final_output_markdown, output
            )
            await asyncio.to_thread(
                session_store.write_final_output,
                final_text,
                root_task=root_task,
            )
            await asyncio.to_thread(session_store.sync_task_tree, root_task)
            await asyncio.to_thread(session_store.build_browse_tree)
            await asyncio.to_thread(
                trace_writer.append_event,
                {
                    "type": "final_answer",
                    "content": final_text,
                },
            )
            await asyncio.to_thread(
                trace_writer.append_event,
                {"type": "end", "content": "completed"},
            )
            completed_at = datetime.now(KST)
            await asyncio.to_thread(
                finalize_trace,
                trace_writer,
                status="completed",
                completed_at=completed_at,
                final_answer=final_text,
                duration=max(0.0, (completed_at - created_at).total_seconds()),
            )
            await asyncio.to_thread(
                session_store.update_session,
                status="completed",
                updated_at=completed_at,
            )
            await asyncio.to_thread(_write_cli_trace_compat, trace_writer)
            print("\n[final]\n")
            print(final_text)
            return 0
        except BaseException as exc:
            error_text = str(exc) or exc.__class__.__name__
            await asyncio.to_thread(
                trace_writer.append_event,
                {"type": "error", "message": error_text},
            )
            completed_at = datetime.now(KST)
            await asyncio.to_thread(
                finalize_trace,
                trace_writer,
                status="failed",
                completed_at=completed_at,
                error=error_text,
                duration=max(0.0, (completed_at - created_at).total_seconds()),
            )
            await asyncio.to_thread(
                session_store.update_session,
                status="failed",
                error=error_text,
                updated_at=completed_at,
            )
            await asyncio.to_thread(_write_cli_trace_compat, trace_writer)
            raise
        finally:
            if tool_registry is not None:
                close = getattr(tool_registry, "close", None)
                if callable(close):
                    close()
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
