import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from pydantic import BaseModel, field_validator

from valuator.core import Engine
from valuator.utils.config import config
from valuator.utils.logger import logger
from .repositories import (
    FileSessionRepository,
    FileTaskRewriteRepository,
    MongoSessionRepository,
    MongoTaskRewriteRepository,
    TaskRewriteRepository,
)
from .services.task_rewrite.service import TaskRewriteService


# Initialize history repository for server (separate from ReactLogger)
def create_history_repository():
    """Create history repository instance for server history (separate from ReactLogger)"""
    mongodb_enabled = os.getenv("MONGODB_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    mongodb_uri = os.getenv("MONGODB_URI")
    mongodb_database = os.getenv("MONGODB_DATABASE", "valuator")
    mongodb_collection = os.getenv("MONGODB_COLLECTION", "sessions")

    if mongodb_enabled and mongodb_uri:
        try:
            # Use different collection for server history
            return MongoSessionRepository(
                mongodb_uri=mongodb_uri,
                database=mongodb_database,
                collection=f"{mongodb_collection}_server_history",
            )
        except Exception as e:
            print(f"Failed to initialize MongoDB repository for server history: {e}")
            print("Falling back to file repository")
            return FileSessionRepository("logs/server_history")
    else:
        # Use different directory for server history
        return FileSessionRepository("logs/server_history")


# Initialize task rewrite repository
def create_task_rewrite_repository() -> TaskRewriteRepository:
    """Create task rewrite repository instance"""
    mongodb_enabled = os.getenv("MONGODB_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    mongodb_uri = os.getenv("MONGODB_URI")
    mongodb_database = os.getenv("MONGODB_DATABASE", "valuator")

    if mongodb_enabled and mongodb_uri:
        try:
            return MongoTaskRewriteRepository(
                mongodb_uri=mongodb_uri,
                database=mongodb_database,
                collection="task_rewrite",
            )
        except Exception as e:
            print(f"Failed to initialize MongoDB repository for task rewrite: {e}")
            print("Falling back to file repository")
            return FileTaskRewriteRepository("logs/task_rewrite")
    else:
        return FileTaskRewriteRepository("logs/task_rewrite")


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
            for key in ("tool", "tool_input", "tool_output", "tool_result", "error", "query"):
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
    steps: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "query": self.query,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "event_count": len(self.steps),
            "error": self.error,
            "model": self.model,
        }


@dataclass
class _RuntimeSession:
    record: SessionRecord
    subscribers: list[asyncio.Queue]
    task: asyncio.Task | None = None


class SessionService:
    def __init__(self, history_repository: Any):
        self.history_repository = history_repository
        self._active: dict[str, _RuntimeSession] = {}

    async def start_session(
        self,
        *,
        query: str,
        model: str | None = None,
        thinking_level: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> SessionRecord:
        _ = thinking_level, context
        session_id = f"S-{datetime.utcnow().strftime('%Y%m%d-%H%M%S%fZ')}"
        record = SessionRecord(
            session_id=session_id,
            query=query,
            model=model or config.agent_model,
            status=SessionStatus.RUNNING,
            created_at=datetime.utcnow(),
        )
        runtime = _RuntimeSession(record=record, subscribers=[])
        runtime.task = asyncio.create_task(self._run(runtime))
        self._active[session_id] = runtime
        return record

    async def get_session(self, session_id: str) -> SessionRecord | None:
        runtime = self._active.get(session_id)
        return runtime.record if runtime else None

    async def subscribe_to_session(self, session_id: str) -> AsyncGenerator[dict[str, Any], None]:
        runtime = self._active.get(session_id)
        if runtime is None:
            raise ValueError(f"Session not found: {session_id}")

        queue: asyncio.Queue = asyncio.Queue()
        for event in runtime.record.steps:
            await queue.put(event)
        await queue.put(None if runtime.record.status == SessionStatus.RUNNING else "END")

        runtime.subscribers.append(queue)
        try:
            while True:
                item = await queue.get()
                if item == "END":
                    break
                if item is None:
                    continue
                yield item
        finally:
            if queue in runtime.subscribers:
                runtime.subscribers.remove(queue)

    async def end_session(self, session_id: str) -> bool:
        runtime = self._active.get(session_id)
        if runtime is None:
            return False

        if runtime.task and not runtime.task.done():
            runtime.task.cancel()
            try:
                await runtime.task
            except asyncio.CancelledError:
                pass

        runtime.record.status = SessionStatus.FAILED
        runtime.record.completed_at = datetime.utcnow()
        runtime.record.error = "terminated"
        await self._persist(runtime.record, success=False)
        await self._finish(session_id)
        return True

    async def list_sessions(self, limit: int = 20, offset: int = 0) -> list[SessionRecord]:
        rows = [state.record for state in self._active.values()]
        rows.sort(key=lambda item: item.created_at, reverse=True)
        return rows[offset : offset + limit]

    async def _run(self, runtime: _RuntimeSession) -> None:
        record = runtime.record
        try:
            await self._emit(runtime, {"type": "start", "query": record.query, "content": record.query})
            await self._emit(
                runtime,
                {
                    "type": "thought",
                    "content": "Valuator pipeline 시작",
                },
            )

            engine = Engine.create(session_id=record.session_id, model=record.model)
            engine.workspace.prepare()
            engine.workspace.write_user_input(record.query)

            await self._emit(
                runtime,
                {
                    "type": "action",
                    "stage": "plan",
                    "content": "Step 1/5 - 계획 수립 중",
                },
            )
            plan = await engine.planner.plan(record.query)
            await self._emit(
                runtime,
                {
                    "type": "observation",
                    "stage": "plan",
                    "content": f"Step 1/5 완료 - task {len(plan.tasks)}개",
                },
            )

            final_path: Path | None = None
            latest_review: dict[str, Any] = {}
            for round_idx in range(1, engine.max_rounds + 1):
                engine.workspace.set_round(round_idx)
                engine.workspace.write_plan(plan)

                await self._emit(
                    runtime,
                    {
                        "type": "action",
                        "stage": "execute",
                        "round": round_idx,
                        "content": f"Step 2/5 - 실행 중 (round {round_idx})",
                    },
                )
                leaf_total = len([task for task in plan.tasks if task.task_type == "leaf"])
                completed_leaf_count = 0
                leaf_count_lock = asyncio.Lock()

                async def _on_leaf_start(task: Any) -> None:
                    await self._emit(
                        runtime,
                        {
                            "type": "action",
                            "stage": "execute-task",
                            "round": round_idx,
                            "task_id": task.id,
                            "content": f"Leaf 시작 - {task.id}",
                        },
                    )

                async def _on_leaf_complete(task: Any, _: dict[str, Any]) -> None:
                    nonlocal completed_leaf_count
                    async with leaf_count_lock:
                        completed_leaf_count += 1
                        current = completed_leaf_count
                    await self._emit(
                        runtime,
                        {
                            "type": "observation",
                            "stage": "execute-task",
                            "round": round_idx,
                            "task_id": task.id,
                            "content": f"Leaf 완료 - {task.id} ({current}/{leaf_total})",
                        },
                    )

                execution = await engine.executor.execute(
                    record.query,
                    plan,
                    engine.workspace,
                    on_leaf_start=_on_leaf_start,
                    on_leaf_complete=_on_leaf_complete,
                )
                completed_leaf_ids = execution.get("leaf_completed_tasks") or []
                await self._emit(
                    runtime,
                    {
                        "type": "observation",
                        "stage": "execute",
                        "round": round_idx,
                        "content": (
                            f"Step 2/5 완료 - leaf task {len(completed_leaf_ids)}개 실행"
                        ),
                    },
                )

                await self._emit(
                    runtime,
                    {
                        "type": "action",
                        "stage": "aggregate",
                        "round": round_idx,
                        "content": f"Step 3/5 - 집계 중 (round {round_idx})",
                    },
                )
                async def _on_task_aggregated(task: Any, index: int, total: int) -> None:
                    await self._emit(
                        runtime,
                        {
                            "type": "observation",
                            "stage": "aggregate-task",
                            "round": round_idx,
                            "task_id": task.id,
                            "content": f"집계 완료 - {task.id} ({index}/{total})",
                        },
                    )

                aggregation = await engine.aggregator.aggregate(
                    record.query,
                    plan,
                    execution,
                    engine.workspace,
                    on_task_aggregated=_on_task_aggregated,
                )
                final_path = engine.workspace.write_final(aggregation["final_markdown"])
                await self._emit(
                    runtime,
                    {
                        "type": "observation",
                        "stage": "aggregate",
                        "round": round_idx,
                        "content": "Step 3/5 완료 - 최종 초안 생성",
                    },
                )

                await self._emit(
                    runtime,
                    {
                        "type": "action",
                        "stage": "review",
                        "round": round_idx,
                        "content": f"Step 4/5 - 리뷰 중 (round {round_idx})",
                    },
                )
                review = await engine.reviewer.review(plan, execution, aggregation)
                review["actions"] = engine._require_action_list(review.get("actions"))
                review_status = "pass" if not review["actions"] else "fail"
                review["status"] = review_status
                review["round"] = round_idx
                engine.workspace.write_review(review)
                latest_review = review
                await self._emit(
                    runtime,
                    {
                        "type": "review",
                        "stage": "review",
                        "round": round_idx,
                        "content": (
                            "Step 4/5 완료 - "
                            + ("PASS (추가 조치 없음)" if review_status == "pass" else "FAIL (재계획 필요)")
                        ),
                    },
                )

                if review_status == "pass":
                    break
                if round_idx >= engine.max_rounds:
                    break

                await self._emit(
                    runtime,
                    {
                        "type": "action",
                        "stage": "replan",
                        "round": round_idx,
                        "content": f"Step 5/5 - 재계획 중 (round {round_idx})",
                    },
                )
                plan = await engine.planner.replan(plan, review)
                await self._emit(
                    runtime,
                    {
                        "type": "observation",
                        "stage": "replan",
                        "round": round_idx,
                        "content": f"Step 5/5 완료 - task {len(plan.tasks)}개로 갱신",
                    },
                )

            if final_path is None:
                raise RuntimeError("engine did not produce final artifacts")

            final_markdown = ""
            if final_path.exists():
                final_markdown = final_path.read_text(encoding="utf-8").strip()
            if final_markdown:
                await self._emit(
                    runtime,
                    {
                        "type": "final_answer",
                        "content": final_markdown,
                    },
                )

            await self._emit(
                runtime,
                {
                    "type": "review",
                    "stage": "summary",
                    "content": (
                        f"최종 상태: {str(latest_review.get('status', 'unknown')).upper()}"
                        if latest_review
                        else "최종 상태: UNKNOWN"
                    ),
                },
            )
            await self._emit(runtime, {"type": "end", "content": "완료"})
            record.status = SessionStatus.COMPLETED
            record.completed_at = datetime.utcnow()
            await self._persist(record, success=True)
        except Exception as exc:
            logger.error("Session run failed: %s", exc)
            record.status = SessionStatus.FAILED
            record.completed_at = datetime.utcnow()
            record.error = str(exc)
            await self._emit(runtime, {"type": "error", "message": str(exc)})
            await self._persist(record, success=False)
        finally:
            await self._finish(record.session_id)

    async def _emit(self, runtime: _RuntimeSession, event: dict[str, Any]) -> None:
        runtime.record.steps.append(event)
        for queue in list(runtime.subscribers):
            await queue.put(event)

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
        }
        await self.history_repository.save_session(payload)

    async def _finish(self, session_id: str) -> None:
        runtime = self._active.pop(session_id, None)
        if runtime is None:
            return
        for queue in runtime.subscribers:
            await queue.put("END")

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


# Global instances
history_repository = None
task_rewrite_repository = None
session_service: Optional[SessionService] = None
task_rewrite_service: Optional[TaskRewriteService] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global history_repository, task_rewrite_repository, session_service, task_rewrite_service
    history_repository = create_history_repository()
    print(f"History repository initialized: {type(history_repository).__name__}")

    # Initialize session service
    session_service = SessionService(history_repository=history_repository)
    print(f"SessionService initialized")

    # Initialize task rewrite service
    task_rewrite_repository = create_task_rewrite_repository()
    task_rewrite_service = TaskRewriteService(repository=task_rewrite_repository)
    print(f"TaskRewriteService initialized")

    yield

    # Shutdown: Close MongoDB connections if applicable
    logger.info("Shutting down application...")

    # Close task rewrite repository MongoDB connection
    if task_rewrite_repository and isinstance(
        task_rewrite_repository, MongoTaskRewriteRepository
    ):
        try:
            task_rewrite_repository.close()
            logger.info("Task rewrite MongoDB connection closed")
        except Exception as e:
            logger.error(f"Error closing task rewrite MongoDB connection: {e}")

    # Close history repository MongoDB connection
    if history_repository and isinstance(history_repository, MongoSessionRepository):
        try:
            history_repository.close()
            logger.info("History MongoDB connection closed")
        except Exception as e:
            logger.error(f"Error closing history MongoDB connection: {e}")

    logger.info("Application shutdown complete")


app = FastAPI(title="AI Agent Server", version="1.5.0", lifespan=lifespan)

# CORS for local frontend dev (adjust origins as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    query: str
    model: Optional[str] = None
    thinking_level: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    valuation_profile: Optional[str | bool] = None
    system_context: Optional[str] = None

    @field_validator("model")
    @classmethod
    def validate_model(cls, v):
        if v is not None and v not in config.supported_models:
            raise ValueError(
                f"Unsupported model: {v}. "
                f"Supported models are: {', '.join(config.supported_models)}"
            )
        return v

    @field_validator("thinking_level")
    @classmethod
    def validate_thinking_level(cls, v):
        if v is not None and v.lower() not in ("high", "low"):
            raise ValueError(
                f"Invalid thinking_level: {v}. Must be 'high', 'low', or None."
            )
        return v.lower() if v else None


class TaskRewriteRequest(BaseModel):
    task: str
    model: Optional[str] = None
    custom_prompt: Optional[str] = None
    thinking_level: Optional[str] = None

    @field_validator("model")
    @classmethod
    def validate_model(cls, v):
        if v is not None and v not in config.supported_models:
            raise ValueError(
                f"Unsupported model: {v}. "
                f"Supported models are: {', '.join(config.supported_models)}"
            )
        return v

    @field_validator("thinking_level")
    @classmethod
    def validate_thinking_level(cls, v):
        if v is not None and v.lower() not in ("high", "low"):
            raise ValueError(
                f"Invalid thinking_level: {v}. Must be 'high', 'low', or None."
            )
        return v.lower() if v else None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/v1/models")
async def get_supported_models():
    """
    Get list of supported models

    Returns:
        List of supported model names and default model
    """
    return {"models": config.supported_models, "default": config.agent_model}


# History API Endpoints


@app.get("/api/v1/history")
async def get_history(limit: int = 10, offset: int = 0):
    """
    Get list of session history with pagination

    Args:
        limit: Maximum number of sessions to return (default: 10)
        offset: Number of sessions to skip (default: 0)

    Returns:
        List of session summaries
    """
    if history_repository is None:
        raise HTTPException(
            status_code=500, detail="History repository not initialized"
        )

    try:
        sessions = await history_repository.list_sessions(limit=limit, offset=offset)
        summaries = sessions_to_summaries(sessions)

        return {
            "sessions": summaries,
            "total": len(summaries),
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve history: {str(e)}"
        )


@app.get("/api/v1/history/{session_id}")
async def get_session_detail(session_id: str):
    """
    Get detailed information for a specific session

    Args:
        session_id: ID of the session to retrieve

    Returns:
        Full session data
    """
    if history_repository is None:
        raise HTTPException(
            status_code=500, detail="History repository not initialized"
        )

    try:
        session = await history_repository.get_session(session_id)

        if session is None:
            raise HTTPException(
                status_code=404, detail=f"Session not found: {session_id}"
            )

        return session
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve session: {str(e)}"
        )


@app.get("/api/v1/history/{session_id}/stream")
async def replay_session_as_stream(session_id: str):
    """
    Replay a session as a stream of events (compatible with frontend stream format)

    Args:
        session_id: ID of the session to replay

    Returns:
        Server-sent events stream of the session
    """
    if history_repository is None:
        raise HTTPException(
            status_code=500, detail="History repository not initialized"
        )

    async def sse() -> AsyncGenerator[str, None]:
        try:
            # Load session
            session = await history_repository.get_session(session_id)

            if session is None:
                error_event = {
                    "type": "error",
                    "message": f"Session not found: {session_id}",
                }
                yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
                yield "event: end\n" + "data: {}\n\n"
                return

            # Convert to stream events
            events = session_to_stream_events(session)

            # Stream events
            for event in events:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        except Exception as e:
            error_event = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
            yield "event: end\n" + "data: {}\n\n"

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.delete("/api/v1/history/{session_id}")
async def delete_session(session_id: str):
    """
    Delete a specific session

    Args:
        session_id: ID of the session to delete

    Returns:
        Success message
    """
    if history_repository is None:
        raise HTTPException(
            status_code=500, detail="History repository not initialized"
        )

    try:
        success = await history_repository.delete_session(session_id)

        if not success:
            raise HTTPException(
                status_code=404, detail=f"Session not found: {session_id}"
            )

        return {
            "message": f"Session deleted successfully: {session_id}",
            "session_id": session_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to delete session: {str(e)}"
        )


# ============================================================================
# NEW SESSION-BASED API (독립적인 세션-스트림 구조)
# ============================================================================


@app.post("/api/v1/sessions")
async def create_session(request: ChatRequest):
    """
    Create a new session and start background task (세션 생성 및 백그라운드 작업 시작)

    Args:
        request: Chat request containing query and optional model

    Returns:
        Session information with session_id
    """
    if session_service is None:
        raise HTTPException(status_code=500, detail="SessionService not initialized")

    try:
        # Create and start session (SessionService handles background task)
        ctx = dict(request.context) if request.context else {}
        if request.system_context:
            ctx["system_context"] = request.system_context
        if request.valuation_profile is not None:
            ctx["valuation_profile"] = request.valuation_profile
        session = await session_service.start_session(
            query=request.query,
            model=request.model,
            thinking_level=request.thinking_level,
            context=ctx or None,
        )

        logger.info(f"Created session: {session.session_id}")

        return {
            "session_id": session.session_id,
            "status": session.status.value,
            "created_at": session.created_at.isoformat(),
            "query": session.query,
            "model": session.model,
        }
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create session: {str(e)}"
        )


@app.get("/api/v1/sessions/{session_id}")
async def get_session(session_id: str):
    """
    Get session details (세션 상태 조회)
    - 활성 세션(메모리)이 있으면 먼저 반환
    - 없으면 자동으로 히스토리에서 조회
    - 히스토리에 있으면 redirect 필드 포함, 없으면 404

    Args:
        session_id: Session ID

    Returns:
        Session details or redirect information
    """
    if session_service is None:
        raise HTTPException(status_code=500, detail="SessionService not initialized")

    try:
        # 1. 먼저 활성 세션(메모리)에서 조회
        session = await session_service.get_session(session_id)
        if session is not None:
            return session.to_dict()

        # 2. 활성 세션이 없으면 히스토리에서 조회
        if history_repository is not None:
            history_session = await history_repository.get_session(session_id)
            if history_session is not None:
                # 히스토리에 있으면 redirect 정보 포함해서 반환
                return {
                    "redirect": f"/history/{session_id}",
                    "session_id": session_id,
                    "status": "completed",
                }

        # 3. 어디에도 없으면 404
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get session: {str(e)}")


@app.get("/api/v1/sessions/{session_id}/stream")
async def stream_session_events(session_id: str):
    """
    Subscribe to session events as SSE stream (세션 이벤트 실시간 스트림)
    - 언제든지 재연결 가능
    - 이전 이벤트부터 다시 받을 수 있음

    Args:
        session_id: Session ID

    Returns:
        Server-sent events stream
    """
    if session_service is None:
        raise HTTPException(status_code=500, detail="SessionService not initialized")

    async def sse() -> AsyncGenerator[str, None]:
        KEEP_ALIVE_INTERVAL = 15  # 15초마다 keep-alive

        try:
            logger.info(f"Client subscribing to session: {session_id}")

            # 이벤트 큐 생성 (keep-alive와 실제 이벤트를 통합)
            event_queue: asyncio.Queue = asyncio.Queue()
            subscription_active = True

            async def keep_alive_sender():
                """주기적으로 keep-alive를 큐에 추가"""
                while subscription_active:
                    await asyncio.sleep(KEEP_ALIVE_INTERVAL)
                    if subscription_active:
                        await event_queue.put(None)  # None = keep-alive 신호

            async def event_subscriber():
                """세션 이벤트를 큐에 추가"""
                try:
                    async for event in session_service.subscribe_to_session(session_id):
                        await event_queue.put(event)
                except Exception as e:
                    logger.error(f"Event subscription error: {e}")
                    await event_queue.put({"type": "error", "message": str(e)})
                finally:
                    await event_queue.put("END")  # 종료 신호

            # 두 태스크 시작
            keep_alive_task = asyncio.create_task(keep_alive_sender())
            subscriber_task = asyncio.create_task(event_subscriber())

            try:
                # 큐에서 이벤트 처리
                while True:
                    item = await event_queue.get()

                    if item == "END":
                        # 스트림 종료
                        break
                    elif item is None:
                        # Keep-alive
                        yield ": keep-alive\n\n"
                    else:
                        # 실제 이벤트
                        yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

                logger.info(f"Stream ended for session: {session_id}")
            finally:
                # 태스크 정리
                subscription_active = False
                keep_alive_task.cancel()
                subscriber_task.cancel()
                try:
                    await keep_alive_task
                except asyncio.CancelledError:
                    pass
                try:
                    await subscriber_task
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            logger.error(f"Error streaming session events: {e}")
            error_event = {
                "type": "error",
                "message": str(e),
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.delete("/api/v1/sessions/{session_id}")
async def delete_session_endpoint(session_id: str):
    """
    Delete/cleanup a session (세션 종료 및 정리)

    Args:
        session_id: Session ID

    Returns:
        Success message
    """
    if session_service is None:
        raise HTTPException(status_code=500, detail="SessionService not initialized")

    try:
        success = await session_service.end_session(session_id)
        if not success:
            raise HTTPException(
                status_code=404, detail=f"Session not found: {session_id}"
            )

        return {
            "message": f"Session deleted successfully: {session_id}",
            "session_id": session_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete session: {str(e)}"
        )


@app.get("/api/v1/sessions")
async def list_active_sessions(
    limit: int = 20,
    offset: int = 0,
    scope: str = Query("active", pattern="^(active|all)$"),
):
    """
    List active sessions (활성 세션 목록)

    Args:
        limit: Maximum number of sessions
        offset: Offset for pagination

    Returns:
        List of active sessions
    """
    if session_service is None:
        raise HTTPException(status_code=500, detail="SessionService not initialized")

    try:
        if scope == "all" and history_repository is not None:
            active = await session_service.list_sessions(limit=limit + offset, offset=0)
            active_rows = [session.to_dict() for session in active]

            historical = await history_repository.list_sessions(limit=limit + offset, offset=0)
            summaries = sessions_to_summaries(historical)
            history_rows = [
                {
                    "session_id": item.get("session_id", ""),
                    "query": item.get("query", ""),
                    "status": "completed" if item.get("success", False) else "failed",
                    "created_at": item.get("timestamp"),
                    "completed_at": item.get("timestamp"),
                    "event_count": item.get("step_count", 0),
                }
                for item in summaries
            ]

            seen: set[str] = set()
            sessions: list[dict[str, Any]] = []
            for row in active_rows + history_rows:
                session_id = str(row.get("session_id") or "")
                if not session_id or session_id in seen:
                    continue
                seen.add(session_id)
                sessions.append(row)

            total = len(sessions)
            sessions = sessions[offset : offset + limit]
            return {
                "sessions": sessions,
                "total": total,
                "limit": limit,
                "offset": offset,
            }

        sessions = await session_service.list_sessions(limit=limit, offset=offset)
        return {
            "sessions": [session.to_dict() for session in sessions],
            "total": len(sessions),
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to list sessions: {str(e)}"
        )


def _valuator_sessions_root() -> Path:
    return Path(__file__).resolve().parents[1] / "valuator" / "sessions"


def _resolve_valuator_session_dir(session_id: str) -> Path:
    root = _valuator_sessions_root().resolve()
    candidate = (root / session_id).resolve()
    if root not in candidate.parents:
        raise HTTPException(status_code=400, detail="Invalid session path")
    if not candidate.exists() or not candidate.is_dir():
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return candidate


def _latest_round_dir(parent: Path) -> tuple[Path | None, int | None]:
    if not parent.exists():
        return None, None
    best_dir: Path | None = None
    best_round: int | None = None
    for child in parent.iterdir():
        if not child.is_dir():
            continue
        match = re.fullmatch(r"round-(\d+)", child.name)
        if not match:
            continue
        value = int(match.group(1))
        if best_round is None or value > best_round:
            best_round = value
            best_dir = child
    return best_dir, best_round


def _read_json_or_default(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return default


def _load_valuator_snapshot_payload(session_dir: Path, session_id: str) -> dict[str, Any]:
    plan_path = session_dir / "plan" / "active" / "decomposition.json"
    if not plan_path.exists():
        raise HTTPException(status_code=404, detail="Plan decomposition not found")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    query = str(plan.get("query", "")).strip()
    if not query:
        input_path = session_dir / "input" / "user_input.md"
        if input_path.exists():
            query = input_path.read_text(encoding="utf-8").strip()

    execution_artifacts: list[dict[str, Any]] = []
    execution_round_dir, execution_round = _latest_round_dir(session_dir / "execution")
    if execution_round_dir is not None:
        outputs_dir = execution_round_dir / "outputs"
        if outputs_dir.exists():
            for task_dir in sorted(outputs_dir.iterdir()):
                if not task_dir.is_dir():
                    continue
                task_id = task_dir.name
                result_path = task_dir / "result.md"
                if not result_path.exists():
                    continue
                meta = _read_json_or_default(task_dir / "result.md.meta.json", {})
                execution_artifacts.append(
                    {
                        "task_id": task_id,
                        "logical_output_path": f"/execution/outputs/{task_id}/result.md",
                        "tool": meta.get("tool"),
                        "args_hash": meta.get("args_hash"),
                        "exists": True,
                    }
                )

    aggregation_reports: list[dict[str, Any]] = []
    aggregation_round_dir, aggregation_round = _latest_round_dir(session_dir / "aggregation")
    if aggregation_round_dir is not None:
        for report in sorted(aggregation_round_dir.rglob("report.md")):
            task_id = report.parent.name
            aggregation_reports.append(
                {
                    "task_id": task_id,
                    "logical_report_path": f"/aggregation/{task_id}/report.md",
                    "exists": True,
                }
            )

    review = _read_json_or_default(
        session_dir / "review" / "latest.json",
        {"status": "running", "actions": [], "round": None},
    )
    if "actions" not in review or not isinstance(review.get("actions"), list):
        review["actions"] = []
    if "coverage_feedback" not in review or not isinstance(
        review.get("coverage_feedback"), dict
    ):
        review["coverage_feedback"] = {}

    latest_round = review.get("round") or execution_round or aggregation_round
    output_exists = (session_dir / "output" / "final.md").exists()
    status = str(review.get("status") or ("completed" if output_exists else "running"))

    return {
        "session_id": session_id,
        "query": query,
        "round": latest_round,
        "status": status,
        "plan": {
            "query_units": plan.get("query_units") or [],
            "contract": plan.get("contract"),
            "tasks": plan.get("tasks") or [],
            "root_task_id": plan.get("root_task_id"),
        },
        "execution": {"artifacts": execution_artifacts},
        "aggregation": {"reports": aggregation_reports},
        "review": {
            "status": review.get("status", "running"),
            "round": review.get("round"),
            "actions": review.get("actions", []),
            "coverage_feedback": review.get("coverage_feedback", {}),
        },
    }


@app.get("/api/v1/sessions/{session_id}/valuator/snapshot")
async def get_valuator_snapshot(session_id: str):
    session_dir = _resolve_valuator_session_dir(session_id)
    try:
        return _load_valuator_snapshot_payload(session_dir, session_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to build valuator snapshot for {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to build snapshot: {str(e)}")


@app.get("/api/v1/sessions/{session_id}/valuator/tasks/{task_id}")
async def get_valuator_task_detail(session_id: str, task_id: str):
    session_dir = _resolve_valuator_session_dir(session_id)
    execution_round_dir, _ = _latest_round_dir(session_dir / "execution")
    aggregation_round_dir, _ = _latest_round_dir(session_dir / "aggregation")

    execution_text = ""
    aggregation_text = ""
    metadata: dict[str, str] = {}

    if execution_round_dir is not None:
        exec_path = execution_round_dir / "outputs" / task_id / "result.md"
        if exec_path.exists():
            execution_text = exec_path.read_text(encoding="utf-8")
        meta_path = execution_round_dir / "outputs" / task_id / "result.md.meta.json"
        raw_meta = _read_json_or_default(meta_path, {})
        metadata = {str(k): str(v) for k, v in raw_meta.items()}

    if aggregation_round_dir is not None:
        agg_path = aggregation_round_dir / task_id / "report.md"
        if agg_path.exists():
            aggregation_text = agg_path.read_text(encoding="utf-8")

    if not execution_text and not aggregation_text:
        raise HTTPException(status_code=404, detail=f"Task artifacts not found: {task_id}")

    return {
        "session_id": session_id,
        "task_id": task_id,
        "execution_markdown": execution_text,
        "aggregation_markdown": aggregation_text,
        "output_metadata": metadata,
    }


@app.get("/api/v1/sessions/{session_id}/valuator/final")
async def get_valuator_final(session_id: str):
    session_dir = _resolve_valuator_session_dir(session_id)
    final_path = session_dir / "output" / "final.md"
    if not final_path.exists():
        raise HTTPException(status_code=404, detail="Final markdown not found")
    return {
        "session_id": session_id,
        "markdown": final_path.read_text(encoding="utf-8"),
    }


# ============================================================================
# TASK REWRITE API
# ============================================================================


@app.post("/api/v1/task-rewrite")
async def rewrite_task(request: TaskRewriteRequest):
    """
    Rewrite a task text using LLM

    Args:
        request: TaskRewriteRequest containing task, optional model and custom_prompt

    Returns:
        Rewritten task with metadata
    """
    if task_rewrite_service is None:
        raise HTTPException(
            status_code=500, detail="TaskRewriteService not initialized"
        )

    try:
        # Use default model if not specified
        model = request.model or config.agent_model

        # Rewrite the task
        history = await task_rewrite_service.rewrite_task(
            task=request.task,
            model=model,
            custom_prompt=request.custom_prompt,
            thinking_level=request.thinking_level,
        )

        return {
            "rewrite_id": history.rewrite_id,
            "original_task": history.original_task,
            "rewritten_task": history.rewritten_task,
            "model": history.model,
            "created_at": history.created_at.isoformat(),
        }
    except Exception as e:
        logger.error(f"Error rewriting task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to rewrite task: {str(e)}")


@app.get("/api/v1/task-rewrite/history")
async def get_task_rewrite_history(limit: int = 10, offset: int = 0):
    """
    Get list of task rewrite history with pagination

    Args:
        limit: Maximum number of rewrites to return (default: 10)
        offset: Number of rewrites to skip (default: 0)

    Returns:
        List of rewrite summaries
    """
    if task_rewrite_service is None:
        raise HTTPException(
            status_code=500, detail="TaskRewriteService not initialized"
        )

    try:
        rewrites = await task_rewrite_service.list_rewrites(limit=limit, offset=offset)
        return {
            "rewrites": [rewrite.to_dict() for rewrite in rewrites],
            "total": len(rewrites),
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        logger.error(f"Error retrieving task rewrite history: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve history: {str(e)}"
        )


@app.get("/api/v1/task-rewrite/{rewrite_id}")
async def get_task_rewrite_detail(rewrite_id: str):
    """
    Get detailed information for a specific rewrite

    Args:
        rewrite_id: ID of the rewrite to retrieve

    Returns:
        Full rewrite data
    """
    if task_rewrite_service is None:
        raise HTTPException(
            status_code=500, detail="TaskRewriteService not initialized"
        )

    try:
        rewrite = await task_rewrite_service.get_rewrite(rewrite_id)

        if rewrite is None:
            raise HTTPException(
                status_code=404, detail=f"Rewrite not found: {rewrite_id}"
            )

        return rewrite.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving rewrite: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve rewrite: {str(e)}"
        )


@app.delete("/api/v1/task-rewrite/{rewrite_id}")
async def delete_task_rewrite(rewrite_id: str):
    """
    Delete a specific rewrite

    Args:
        rewrite_id: ID of the rewrite to delete

    Returns:
        Success message
    """
    if task_rewrite_service is None:
        raise HTTPException(
            status_code=500, detail="TaskRewriteService not initialized"
        )

    try:
        success = await task_rewrite_service.delete_rewrite(rewrite_id)

        if not success:
            raise HTTPException(
                status_code=404, detail=f"Rewrite not found: {rewrite_id}"
            )

        return {
            "message": f"Rewrite deleted successfully: {rewrite_id}",
            "rewrite_id": rewrite_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting rewrite: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete rewrite: {str(e)}"
        )


# Developer API Endpoints - Gemini Logs


@app.get("/api/v1/dev/gemini-logs")
async def get_gemini_logs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    sort: str = Query("newest", regex="^(newest|oldest|size)$"),
):
    """
    Get list of Gemini request/response log files

    Args:
        limit: Maximum number of files to return (default: 20, max: 100)
        offset: Number of files to skip (default: 0)
        search: Search term for filename
        date_from: Start date filter (YYYYMMDD format)
        date_to: End date filter (YYYYMMDD format)
        model: Model name filter
        sort: Sort order (newest, oldest, size)

    Returns:
        List of log file metadata
    """
    try:
        logs_dir = Path("logs/gemini_low_level_request")
        if not logs_dir.exists():
            return {
                "files": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
            }

        file_metadatas = []

        def add_metadata(filepath: Path, display_name: str, timestamp_str: str) -> None:
            file_datetime = _parse_gemini_timestamp(timestamp_str)
            file_date = file_datetime.date() if file_datetime else None
            time_str = file_datetime.strftime("%H:%M:%S") if file_datetime else None
            file_size = filepath.stat().st_size
            file_model = None
            if model is not None:
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        file_model = data.get("model")
                except Exception:
                    pass

            file_metadatas.append(
                {
                    "filename": display_name,
                    "timestamp": timestamp_str,
                    "date": file_date.isoformat() if file_date else None,
                    "time": time_str,
                    "datetime": file_datetime.isoformat() if file_datetime else None,
                    "size": file_size,
                    "size_formatted": _format_file_size(file_size),
                    "model": file_model,
                    "filepath": str(filepath),
                }
            )

        # Session/step logs (new structure)
        for session_dir in logs_dir.glob("session_*"):
            if not session_dir.is_dir():
                continue
            for step_file in session_dir.glob("step_*.json"):
                timestamp_str = _extract_step_timestamp(step_file.name)
                if not timestamp_str:
                    continue
                display_name = _encode_session_log_filename(session_dir.name, step_file.name)
                add_metadata(step_file, display_name, timestamp_str)

        # Legacy flat logs (backward compatibility)
        for filepath in logs_dir.glob("request_response_*.json"):
            timestamp_str = _extract_request_response_timestamp(filepath.name)
            if not timestamp_str:
                continue
            add_metadata(filepath, filepath.name, timestamp_str)
        
        # Apply filters
        filtered_files = file_metadatas
        
        # Search filter
        if search:
            search_lower = search.lower()
            filtered_files = [
                f for f in filtered_files
                if search_lower in f["filename"].lower() or search_lower in f["timestamp"].lower()
            ]
        
        # Date range filter
        if date_from:
            try:
                from_date = datetime.strptime(date_from, "%Y%m%d").date()
                filtered_files = [
                    f
                    for f in filtered_files
                    if f["date"] and datetime.fromisoformat(f["date"]).date() >= from_date
                ]
            except ValueError:
                pass
        
        if date_to:
            try:
                to_date = datetime.strptime(date_to, "%Y%m%d").date()
                filtered_files = [
                    f
                    for f in filtered_files
                    if f["date"] and datetime.fromisoformat(f["date"]).date() <= to_date
                ]
            except ValueError:
                pass
        
        # Model filter
        if model:
            # Need to load model from files that weren't loaded yet
            for f in filtered_files:
                if f["model"] is None:
                    try:
                        filepath = Path(f["filepath"])
                        with open(filepath, "r", encoding="utf-8") as file:
                            data = json.load(file)
                            f["model"] = data.get("model")
                    except Exception:
                        pass
            filtered_files = [f for f in filtered_files if f.get("model") == model]
        
        # Sort
        if sort == "newest":
            filtered_files.sort(key=lambda x: x["datetime"] or "", reverse=True)
        elif sort == "oldest":
            filtered_files.sort(key=lambda x: x["datetime"] or "")
        elif sort == "size":
            filtered_files.sort(key=lambda x: x["size"], reverse=True)
        
        # Pagination
        total = len(filtered_files)
        paginated_files = filtered_files[offset:offset + limit]
        
        # Remove filepath from response (not needed on frontend)
        for f in paginated_files:
            f.pop("filepath", None)
            # Load model if not already loaded
            if f["model"] is None:
                try:
                    filepath = logs_dir / f["filename"]
                    with open(filepath, "r", encoding="utf-8") as file:
                        data = json.load(file)
                        f["model"] = data.get("model")
                except Exception:
                    f["model"] = "unknown"
        
        return {
            "files": paginated_files,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        logger.error(f"Error retrieving Gemini logs: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve Gemini logs: {str(e)}"
        )


@app.get("/api/v1/dev/gemini-logs/{filename}")
async def get_gemini_log_detail(filename: str):
    """
    Get detailed information for a specific Gemini log file

    Args:
        filename: Log identifier (e.g., request_response_20260103_203318_123456.json
            or session_20260103_203318_123456__step_0001_20260103_203318_123456.json)

    Returns:
        Full log file data with metadata
    """
    try:
        logs_dir = Path("logs/gemini_low_level_request")
        filepath = _resolve_gemini_log_path(filename, logs_dir)
        
        if not filepath.exists():
            raise HTTPException(status_code=404, detail=f"Log file not found: {filename}")
        
        # Read file
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Extract metadata
        timestamp_str = data.get("timestamp")
        if not isinstance(timestamp_str, str):
            timestamp_str = _extract_request_response_timestamp(filepath.name)
        if not timestamp_str:
            timestamp_str = _extract_step_timestamp(filepath.name)
        file_datetime = _parse_gemini_timestamp(timestamp_str) if timestamp_str else None
        file_date = file_datetime.date() if file_datetime else None
        
        file_size = filepath.stat().st_size
        
        return {
            "filename": filename,
            "metadata": {
                "timestamp": timestamp_str,
                "date": file_date.isoformat() if file_date else None,
                "time": file_datetime.strftime("%H:%M:%S") if file_datetime else None,
                "datetime": file_datetime.isoformat() if file_datetime else None,
                "size": file_size,
                "size_formatted": _format_file_size(file_size),
                "model": data.get("model"),
            },
            "data": data,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving Gemini log detail: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve Gemini log: {str(e)}"
        )


@app.get("/api/v1/dev/gemini-logs/{filename}/download")
async def download_gemini_log(filename: str):
    """
    Download a specific Gemini log file

    Args:
        filename: Log identifier (e.g., request_response_20260103_203318_123456.json
            or session_20260103_203318_123456__step_0001_20260103_203318_123456.json)

    Returns:
        File download response
    """
    try:
        logs_dir = Path("logs/gemini_low_level_request")
        filepath = _resolve_gemini_log_path(filename, logs_dir)
        
        if not filepath.exists():
            raise HTTPException(status_code=404, detail=f"Log file not found: {filename}")
        
        return FileResponse(
            path=str(filepath),
            filename=filename,
            media_type="application/json",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading Gemini log: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to download Gemini log: {str(e)}"
        )


def _format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format"""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f}MB"


_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _encode_session_log_filename(session_dir: str, step_file: str) -> str:
    return f"{session_dir}__{step_file}"


def _decode_session_log_filename(filename: str) -> Optional[tuple[str, str]]:
    if "__" not in filename:
        return None
    session_part, step_part = filename.split("__", 1)
    if not session_part or not step_part:
        return None
    if not session_part.startswith("session_"):
        return None
    if not step_part.startswith("step_") or not step_part.endswith(".json"):
        return None
    if not _SAFE_NAME_RE.match(session_part):
        return None
    if not _SAFE_NAME_RE.match(step_part):
        return None
    return session_part, step_part


def _resolve_gemini_log_path(filename: str, logs_dir: Path) -> Path:
    if filename.startswith("request_response_") and filename.endswith(".json"):
        safe_name = os.path.basename(filename)
        return logs_dir / safe_name

    decoded = _decode_session_log_filename(filename)
    if decoded is None:
        raise HTTPException(status_code=400, detail="Invalid filename format")

    session_part, step_part = decoded
    return logs_dir / session_part / step_part


def _extract_request_response_timestamp(filename: str) -> Optional[str]:
    match = re.match(
        r"^request_response_(\d{8}_\d{6}(?:_\d{6})?)\.json$", filename
    )
    if match:
        return match.group(1)
    return None


def _extract_step_timestamp(filename: str) -> Optional[str]:
    match = re.match(r"^step_\d+_(\d{8}_\d{6}(?:_\d{6})?)\.json$", filename)
    if match:
        return match.group(1)
    return None


def _parse_gemini_timestamp(timestamp_str: Optional[str]) -> Optional[datetime]:
    if not timestamp_str:
        return None
    for fmt in ("%Y%m%d_%H%M%S_%f", "%Y%m%d_%H%M%S"):
        try:
            return datetime.strptime(timestamp_str, fmt)
        except ValueError:
            continue
    return None
