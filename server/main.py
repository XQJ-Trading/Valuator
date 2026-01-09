import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from pydantic import BaseModel, field_validator

from .adapters import HistoryAdapter
from .core.agent.react_agent import AIAgent
from .core.utils.config import config
from .core.utils.logger import logger
from .repositories import (
    FileSessionRepository,
    FileTaskRewriteRepository,
    MongoSessionRepository,
    MongoTaskRewriteRepository,
    TaskRewriteRepository,
)
from .services.session import SessionService
from .services.task_rewrite.service import TaskRewriteService


# Initialize history repository for server (separate from ReactLogger)
def create_history_repository():
    """Create history repository instance for server history (separate from ReactLogger)"""
    if config.mongodb_enabled and config.mongodb_uri:
        try:
            # Use different collection for server history
            return MongoSessionRepository(
                mongodb_uri=config.mongodb_uri,
                database=config.mongodb_database,
                collection=f"{config.mongodb_collection}_server_history",
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
    if config.mongodb_enabled and config.mongodb_uri:
        try:
            return MongoTaskRewriteRepository(
                mongodb_uri=config.mongodb_uri,
                database=config.mongodb_database,
                collection="task_rewrite",
            )
        except Exception as e:
            print(f"Failed to initialize MongoDB repository for task rewrite: {e}")
            print("Falling back to file repository")
            return FileTaskRewriteRepository("logs/task_rewrite")
    else:
        return FileTaskRewriteRepository("logs/task_rewrite")


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
        summaries = HistoryAdapter.sessions_to_summaries(sessions)

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
            events = HistoryAdapter.session_to_stream_events(session)

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
async def list_active_sessions(limit: int = 20, offset: int = 0):
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
