import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, field_validator

from .adapters import HistoryAdapter
from .core.agent.react_agent import AIAgent
from .core.utils.config import config
from .core.utils.logger import logger
from .repositories import FileSessionRepository, MongoSessionRepository
from .services.session import SessionService


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


# Global instances
history_repository = None
session_service: Optional[SessionService] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global history_repository, session_service
    history_repository = create_history_repository()
    print(f"History repository initialized: {type(history_repository).__name__}")

    # Initialize session service
    session_service = SessionService(history_repository=history_repository)
    print(f"SessionService initialized")

    yield

    # Shutdown (if needed)
    # Add any cleanup code here


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

    @field_validator("model")
    @classmethod
    def validate_model(cls, v):
        if v is not None and v not in config.supported_models:
            raise ValueError(
                f"Unsupported model: {v}. "
                f"Supported models are: {', '.join(config.supported_models)}"
            )
        return v


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
        session = await session_service.start_session(
            query=request.query, model=request.model
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
                    "status": "completed"
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
