from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncGenerator

from valuator.runtime import create_tool_registry, final_output_text, finalize_trace
from valuator.core import Agent, ComplexTask, Scheduler, SharedState
from valuator.models.factory import create_llm_client
from valuator.session import SessionTraceWriter, ValuatorSessionStore
from valuator.utils.config import config
from valuator.utils.logger import close_session_log_file, logger, session_log_file

from ..api_support import agent_event_to_stream_event, build_query_analysis

class SessionStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SessionRecord:
    session_id: str
    query: str
    model: str
    status: SessionStatus
    created_at: datetime
    completed_at: datetime | None = None
    error: str | None = None
    thinking_level: str | None = None
    context: dict[str, Any] | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "query": self.query,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "event_count": len(self.steps),
            "error": self.error,
            "model": self.model,
            "thinking_level": self.thinking_level,
            "context": self.context,
        }


@dataclass
class _RuntimeSession:
    record: SessionRecord
    subscribers: list[asyncio.Queue]
    thinking_level: str | None = None
    context: dict[str, Any] | None = None
    task: asyncio.Task | None = None
    session_store: ValuatorSessionStore | None = None
    trace_writer: SessionTraceWriter | None = None


class SessionService:
    def __init__(self, history_repository: Any):
        self.history_repository = history_repository
        self._active: dict[str, _RuntimeSession] = {}
        self._completed: dict[str, _RuntimeSession] = {}
        self._completed_order: list[str] = []
        self._max_completed_sessions = 20

    async def start_session(
        self,
        *,
        query: str,
        model: str | None = None,
        thinking_level: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> SessionRecord:
        normalized_context = dict(context) if context else None
        effective_thinking_level = thinking_level or config.gemini_thinking_level
        session_id = f"S-{datetime.utcnow().strftime('%Y%m%d-%H%M%S%fZ')}"
        record = SessionRecord(
            session_id=session_id,
            query=query,
            model=model or config.agent_model,
            status=SessionStatus.RUNNING,
            created_at=datetime.utcnow(),
            thinking_level=effective_thinking_level,
            context=normalized_context,
        )
        runtime = _RuntimeSession(
            record=record,
            subscribers=[],
            thinking_level=effective_thinking_level,
            context=normalized_context,
            session_store=ValuatorSessionStore(
                session_id=session_id,
                query=query,
                model=record.model,
                created_at=record.created_at,
                context=normalized_context,
            ),
        )
        runtime.trace_writer = runtime.session_store.trace_writer
        runtime.task = asyncio.create_task(self._run(runtime))
        self._active[session_id] = runtime
        return record

    async def get_session(self, session_id: str) -> SessionRecord | None:
        runtime = self._runtime_for(session_id)
        return runtime.record if runtime else None

    async def subscribe_to_session(
        self, session_id: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        runtime = self._runtime_for(session_id)
        if runtime is None:
            raise ValueError(f"Session not found: {session_id}")

        queue: asyncio.Queue = asyncio.Queue()
        runtime.subscribers.append(queue)
        for event in runtime.record.steps:
            queue.put_nowait(event)
        if runtime.record.status != SessionStatus.RUNNING:
            queue.put_nowait("END")
        try:
            while True:
                item = await queue.get()
                if item == "END":
                    break
                yield item
        finally:
            if queue in runtime.subscribers:
                runtime.subscribers.remove(queue)

    async def end_session(self, session_id: str) -> bool:
        runtime = self._active.get(session_id)
        if runtime is None:
            removed = self._completed.pop(session_id, None)
            if removed is None:
                return False
            self._completed_order = [
                existing for existing in self._completed_order if existing != session_id
            ]
            for queue in removed.subscribers:
                queue.put_nowait("END")
            return True

        if runtime.task and not runtime.task.done():
            runtime.task.cancel()
            try:
                await runtime.task
            except asyncio.CancelledError:
                pass

        if runtime.record.status == SessionStatus.RUNNING:
            runtime.record.status = SessionStatus.FAILED
            runtime.record.completed_at = datetime.utcnow()
            runtime.record.error = "terminated"
            self._write_session_status(runtime)
            self._write_review(runtime)
            self._finalize_trace(runtime)
            await self._persist(runtime.record, success=False)
        await self._finish(session_id)
        return True

    async def list_sessions(
        self, limit: int = 20, offset: int = 0
    ) -> list[SessionRecord]:
        rows = [state.record for state in self._active.values()]
        rows.sort(key=lambda item: item.created_at, reverse=True)
        return rows[offset : offset + limit]

    async def _run(self, runtime: _RuntimeSession) -> None:
        record = runtime.record
        runtime_log_path = (
            runtime.trace_writer.runtime_log_path
            if runtime.trace_writer is not None
            else None
        )
        with session_log_file(runtime_log_path):
            try:
                await self._emit(
                    runtime,
                    {"type": "start", "query": record.query, "content": record.query},
                )
                effective_query = self._build_effective_query(
                    record.query,
                    thinking_level=runtime.thinking_level,
                    context=runtime.context,
                )
                root_task = ComplexTask(
                    id="root",
                    description=f"Analysis: {effective_query}",
                )
                if runtime.session_store is not None:
                    await asyncio.to_thread(
                        runtime.session_store.update_trace_query,
                        effective_query,
                    )
                    await asyncio.to_thread(
                        runtime.session_store.sync_task_tree,
                        root_task,
                    )
                await self._emit(
                    runtime,
                    {
                        "type": "thought",
                        "content": "Valuator agent 시작",
                    },
                )
                await self._emit(
                    runtime,
                    {
                        "type": "thought",
                        "content": "Query analysis 생성",
                    },
                )

                analysis = await build_query_analysis(
                    effective_query,
                    record.model,
                    as_of_utc=record.created_at.isoformat(),
                    usage_writer=runtime.trace_writer,
                )
                root_task.query_unit_ids = list(range(len(analysis.units)))
                if runtime.session_store is not None:
                    await asyncio.to_thread(
                        runtime.session_store.write_plan,
                        effective_query=effective_query,
                        analysis=analysis,
                        root_task=root_task,
                    )
                tool_registry = create_tool_registry(
                    record.model,
                    usage_writer=runtime.trace_writer,
                )
                agent = Agent(
                    scheduler=Scheduler(
                        max_steps_per_task=config.agent_max_steps_per_task,
                        concurrency=config.agent_concurrency,
                    ),
                    shared_state=SharedState(),
                    tool_registry=tool_registry,
                    llm_client=create_llm_client(
                        model=record.model,
                        usage_writer=runtime.trace_writer,
                    ),
                    query_analysis=analysis,
                    on_event=lambda event: self._emit(
                        runtime,
                        agent_event_to_stream_event(event),
                    ),
                    session_store=runtime.session_store,
                )
                agent_output = await agent.run(effective_query, root_task)
                final_markdown = final_output_text(agent_output)
                if runtime.session_store is not None:
                    final_markdown = await asyncio.to_thread(
                        runtime.session_store.final_output_markdown,
                        agent_output,
                    )

                if final_markdown:
                    await self._emit(
                        runtime,
                        {
                            "type": "final_answer",
                            "content": final_markdown,
                        },
                    )
                    if runtime.session_store is not None:
                        await asyncio.to_thread(
                            runtime.session_store.write_final_output,
                            final_markdown,
                            root_task=root_task,
                        )
                        await asyncio.to_thread(
                            runtime.session_store.sync_task_tree,
                            root_task,
                        )
                        await asyncio.to_thread(
                            runtime.session_store.build_browse_tree,
                        )

                await self._emit(
                    runtime,
                    {
                        "type": "review",
                        "stage": "summary",
                        "content": "최종 상태: COMPLETED",
                    },
                )
                await self._emit(runtime, {"type": "end", "content": "완료"})
                record.status = SessionStatus.COMPLETED
                record.completed_at = datetime.utcnow()
                await self._write_review(runtime)
                await self._write_session_status(runtime)
                await self._finalize_trace(runtime)
                await self._persist(record, success=True)
            except Exception as exc:
                logger.error("Session run failed: %s", exc)
                record.status = SessionStatus.FAILED
                record.completed_at = datetime.utcnow()
                record.error = str(exc)
                await self._emit(runtime, {"type": "error", "message": str(exc)})
                await self._write_review(runtime)
                await self._write_session_status(runtime)
                await self._finalize_trace(runtime)
                await self._persist(record, success=False)
            finally:
                close_session_log_file(runtime_log_path)
                await self._finish(record.session_id)

    async def _emit(self, runtime: _RuntimeSession, event: dict[str, Any]) -> None:
        runtime.record.steps.append(event)
        if runtime.trace_writer is not None:
            await asyncio.to_thread(runtime.trace_writer.append_event, event)
        for queue in list(runtime.subscribers):
            queue.put_nowait(event)

    async def _persist(self, record: SessionRecord, *, success: bool) -> None:
        if self.history_repository is None:
            return
        payload = {
            "session_id": record.session_id,
            "timestamp": record.created_at.isoformat(),
            "query": record.query,
            "steps": record.steps,
            "final_answer": self._final_answer(record.steps),
            "success": success,
            "duration": self._duration_seconds(record),
            "status": record.status.value,
            "model": record.model,
            "thinking_level": record.thinking_level,
            "context": record.context,
        }
        await self.history_repository.save_session(payload)

    async def _finish(self, session_id: str) -> None:
        runtime = self._active.pop(session_id, None)
        if runtime is not None:
            self._remember_completed(runtime)
        else:
            runtime = self._completed.get(session_id)
        if runtime is None:
            return
        for queue in runtime.subscribers:
            queue.put_nowait("END")

    def _runtime_for(self, session_id: str) -> _RuntimeSession | None:
        return self._active.get(session_id) or self._completed.get(session_id)

    def _remember_completed(self, runtime: _RuntimeSession) -> None:
        session_id = runtime.record.session_id
        already_known = session_id in self._completed
        self._completed[session_id] = runtime
        if not already_known:
            self._completed_order.append(session_id)

        while len(self._completed_order) > self._max_completed_sessions:
            expired_id = self._completed_order.pop(0)
            self._completed.pop(expired_id, None)

    @staticmethod
    def _build_effective_query(
        query: str,
        *,
        thinking_level: str | None,
        context: dict[str, Any] | None,
    ) -> str:
        sections: list[str] = []
        if thinking_level:
            sections.append(f"[THINKING_LEVEL]\n{thinking_level}")

        if context:
            context_copy = dict(context)
            system_context = str(context_copy.pop("system_context", "") or "").strip()
            if system_context:
                sections.append(f"[SYSTEM_CONTEXT]\n{system_context}")

            valuation_profile = context_copy.pop("valuation_profile", None)
            if valuation_profile is not None:
                sections.append(f"[VALUATION_PROFILE]\n{valuation_profile}")

            if context_copy:
                sections.append(
                    "[REQUEST_CONTEXT_JSON]\n"
                    + json.dumps(
                        context_copy, ensure_ascii=False, sort_keys=True, default=str
                    )
                )

        if not sections:
            return query

        request_control = "\n\n".join(sections)
        return f"{query}\n\n[REQUEST_CONTROL]\n{request_control}"

    @staticmethod
    def _final_answer(steps: list[dict[str, Any]]) -> str:
        for step in reversed(steps):
            if step.get("type") == "final_answer":
                return str(step.get("content") or "")
        return ""

    @staticmethod
    def _duration_seconds(record: SessionRecord) -> float:
        if record.completed_at is None:
            return 0.0
        return max(0.0, (record.completed_at - record.created_at).total_seconds())

    async def _finalize_trace(self, runtime: _RuntimeSession) -> None:
        await asyncio.to_thread(
            finalize_trace,
            runtime.trace_writer,
            status=runtime.record.status.value,
            completed_at=runtime.record.completed_at,
            error=runtime.record.error,
            final_answer=self._final_answer(runtime.record.steps),
            duration=self._duration_seconds(runtime.record),
        )

    async def _write_review(self, runtime: _RuntimeSession) -> None:
        if runtime.session_store is None:
            return
        await asyncio.to_thread(
            runtime.session_store.write_review,
            status=runtime.record.status.value,
        )

    async def _write_session_status(self, runtime: _RuntimeSession) -> None:
        if runtime.session_store is None:
            return
        await asyncio.to_thread(
            runtime.session_store.update_session,
            status=runtime.record.status.value,
            error=runtime.record.error,
            updated_at=runtime.record.completed_at or datetime.utcnow(),
        )

