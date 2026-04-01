from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from valuator.utils.config import ROOT_DIR, config, session_files_root
from valuator.utils.logger import logger

from . import state
from .api_support import session_to_stream_events, sessions_to_summaries
from .gemini_log_utils import (
    _encode_session_log_filename,
    _extract_request_response_timestamp,
    _extract_step_timestamp,
    _parse_gemini_timestamp,
    _resolve_gemini_log_path,
)
from .schemas import ChatRequest, TaskRewriteRequest
from .valuator_snapshot import (
    _latest_round_dir,
    _load_valuator_snapshot_payload,
    _read_json_dict,
    _resolve_valuator_session_dir,
)

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/api/v1/models")
async def get_supported_models():
    """
    Get list of supported models

    Returns:
        List of supported model names and default model
    """
    payload: dict[str, Any] = {
        "models": config.supported_models,
        "default": config.agent_model,
    }
    if config.llm_backend == "openrouter" and config.openrouter_api_key:
        payload["openrouter"] = True
        payload["any_provider_model"] = True
    return payload


# History API Endpoints


@router.get("/api/v1/history")
async def get_history(limit: int = 10, offset: int = 0):
    """
    Get list of session history with pagination

    Args:
        limit: Maximum number of sessions to return (default: 10)
        offset: Number of sessions to skip (default: 0)

    Returns:
        List of session summaries
    """
    if state.history_repository is None:
        raise HTTPException(
            status_code=500, detail="History repository not initialized"
        )

    try:
        sessions = await state.history_repository.list_sessions(limit=limit, offset=offset)
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


@router.get("/api/v1/history/{session_id}")
async def get_session_detail(session_id: str):
    """
    Get detailed information for a specific session

    Args:
        session_id: ID of the session to retrieve

    Returns:
        Full session data
    """
    if state.history_repository is None:
        raise HTTPException(
            status_code=500, detail="History repository not initialized"
        )

    try:
        session = await state.history_repository.get_session(session_id)

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


@router.get("/api/v1/history/{session_id}/stream")
async def replay_session_as_stream(session_id: str):
    """
    Replay a session as a stream of events (compatible with frontend stream format)

    Args:
        session_id: ID of the session to replay

    Returns:
        Server-sent events stream of the session
    """
    if state.history_repository is None:
        raise HTTPException(
            status_code=500, detail="History repository not initialized"
        )

    async def sse() -> AsyncGenerator[str, None]:
        try:
            # Load session
            session = await state.history_repository.get_session(session_id)

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


@router.delete("/api/v1/history/{session_id}")
async def delete_session(session_id: str):
    """
    Delete a specific session

    Args:
        session_id: ID of the session to delete

    Returns:
        Success message
    """
    if state.history_repository is None:
        raise HTTPException(
            status_code=500, detail="History repository not initialized"
        )

    try:
        success = await state.history_repository.delete_session(session_id)

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


@router.post("/api/v1/sessions")
async def create_session(request: ChatRequest):
    """
    Create a new session and start background task (세션 생성 및 백그라운드 작업 시작)

    Args:
        request: Chat request containing query and optional model

    Returns:
        Session information with session_id
    """
    if state.session_service is None:
        raise HTTPException(status_code=500, detail="SessionService not initialized")

    try:
        # Create and start session (SessionService handles background task)
        ctx = dict(request.context) if request.context else {}
        if request.system_context:
            ctx["system_context"] = request.system_context
        if request.valuation_profile is not None:
            ctx["valuation_profile"] = request.valuation_profile
        session = await state.session_service.start_session(
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


@router.get("/api/v1/sessions/{session_id}")
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
    if state.session_service is None:
        raise HTTPException(status_code=500, detail="SessionService not initialized")

    try:
        # 1. 먼저 활성 세션(메모리)에서 조회
        session = await state.session_service.get_session(session_id)
        if session is not None:
            return session.to_dict()

        # 2. 활성 세션이 없으면 히스토리에서 조회
        if state.history_repository is not None:
            history_session = await state.history_repository.get_session(session_id)
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


@router.get("/api/v1/sessions/{session_id}/stream")
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
    if state.session_service is None:
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
                    async for event in state.session_service.subscribe_to_session(session_id):
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


@router.delete("/api/v1/sessions/{session_id}")
async def delete_session_endpoint(session_id: str):
    """
    Delete/cleanup a session (세션 종료 및 정리)

    Args:
        session_id: Session ID

    Returns:
        Success message
    """
    if state.session_service is None:
        raise HTTPException(status_code=500, detail="SessionService not initialized")

    try:
        success = await state.session_service.end_session(session_id)
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


@router.get("/api/v1/sessions")
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
    if state.session_service is None:
        raise HTTPException(status_code=500, detail="SessionService not initialized")

    try:
        if scope == "all" and state.history_repository is not None:
            active = await state.session_service.list_sessions(limit=limit + offset, offset=0)
            active_rows = [session.to_dict() for session in active]

            historical = await state.history_repository.list_sessions(
                limit=limit + offset, offset=0
            )
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

        sessions = await state.session_service.list_sessions(limit=limit, offset=offset)
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


@router.get("/api/v1/sessions/{session_id}/valuator/snapshot")
async def get_valuator_snapshot(session_id: str):
    session_dir = _resolve_valuator_session_dir(session_id)
    try:
        return _load_valuator_snapshot_payload(session_dir, session_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to build valuator snapshot for {session_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to build snapshot: {str(e)}"
        )


@router.get("/api/v1/sessions/{session_id}/valuator/tasks/{task_id}")
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
        raw_meta = _read_json_dict(meta_path) or {}
        metadata = {str(k): str(v) for k, v in raw_meta.items()}

    if aggregation_round_dir is not None:
        agg_path = aggregation_round_dir / task_id / "report.md"
        if agg_path.exists():
            aggregation_text = agg_path.read_text(encoding="utf-8")

    if not execution_text and not aggregation_text:
        raise HTTPException(
            status_code=404, detail=f"Task artifacts not found: {task_id}"
        )

    return {
        "session_id": session_id,
        "task_id": task_id,
        "execution_markdown": execution_text,
        "aggregation_markdown": aggregation_text,
        "output_metadata": metadata,
    }


@router.get("/api/v1/sessions/{session_id}/valuator/final")
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


@router.post("/api/v1/task-rewrite")
async def rewrite_task(request: TaskRewriteRequest):
    """
    Rewrite a task text using LLM

    Args:
        request: TaskRewriteRequest containing task, optional model and custom_prompt

    Returns:
        Rewritten task with metadata
    """
    if state.task_rewrite_service is None:
        raise HTTPException(
            status_code=500, detail="TaskRewriteService not initialized"
        )

    try:
        # Use default model if not specified
        model = request.model or config.agent_model

        # Rewrite the task
        history = await state.task_rewrite_service.rewrite_task(
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


@router.get("/api/v1/task-rewrite/history")
async def get_task_rewrite_history(limit: int = 10, offset: int = 0):
    """
    Get list of task rewrite history with pagination

    Args:
        limit: Maximum number of rewrites to return (default: 10)
        offset: Number of rewrites to skip (default: 0)

    Returns:
        List of rewrite summaries
    """
    if state.task_rewrite_service is None:
        raise HTTPException(
            status_code=500, detail="TaskRewriteService not initialized"
        )

    try:
        rewrites = await state.task_rewrite_service.list_rewrites(limit=limit, offset=offset)
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


@router.get("/api/v1/task-rewrite/{rewrite_id}")
async def get_task_rewrite_detail(rewrite_id: str):
    """
    Get detailed information for a specific rewrite

    Args:
        rewrite_id: ID of the rewrite to retrieve

    Returns:
        Full rewrite data
    """
    if state.task_rewrite_service is None:
        raise HTTPException(
            status_code=500, detail="TaskRewriteService not initialized"
        )

    try:
        rewrite = await state.task_rewrite_service.get_rewrite(rewrite_id)

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


@router.delete("/api/v1/task-rewrite/{rewrite_id}")
async def delete_task_rewrite(rewrite_id: str):
    """
    Delete a specific rewrite

    Args:
        rewrite_id: ID of the rewrite to delete

    Returns:
        Success message
    """
    if state.task_rewrite_service is None:
        raise HTTPException(
            status_code=500, detail="TaskRewriteService not initialized"
        )

    try:
        success = await state.task_rewrite_service.delete_rewrite(rewrite_id)

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


@router.get("/api/v1/dev/gemini-logs")
async def get_gemini_logs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    sort: str = Query("newest", pattern="^(newest|oldest)$"),
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
        sort: Sort order (newest, oldest)

    Returns:
        List of log file metadata
    """
    try:
        session_root = session_files_root()
        legacy_logs = ROOT_DIR / "logs"
        if not session_root.exists() and not legacy_logs.exists():
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
                    "model": file_model,
                    "filepath": str(filepath),
                }
            )

        # Session step logs under VALUATOR_SESSION_FILES_ROOT (e.g. logs/local/CLI-*/step_*.json)
        if session_root.exists():
            for session_dir in sorted(session_root.iterdir()):
                if not session_dir.is_dir():
                    continue
                for step_file in sorted(session_dir.glob("step_*.json")):
                    timestamp_str = _extract_step_timestamp(step_file.name)
                    if not timestamp_str:
                        continue
                    display_name = _encode_session_log_filename(
                        session_dir.name, step_file.name
                    )
                    add_metadata(step_file, display_name, timestamp_str)

        # Legacy flat logs at repo logs/ root
        if legacy_logs.exists():
            for filepath in sorted(legacy_logs.glob("request_response_*.json")):
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
                f
                for f in filtered_files
                if search_lower in f["filename"].lower()
                or search_lower in f["timestamp"].lower()
            ]

        # Date range filter
        if date_from:
            try:
                from_date = datetime.strptime(date_from, "%Y%m%d").date()
                filtered_files = [
                    f
                    for f in filtered_files
                    if f["date"]
                    and datetime.fromisoformat(f["date"]).date() >= from_date
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
        else:
            filtered_files.sort(key=lambda x: x["datetime"] or "")

        # Pagination
        total = len(filtered_files)
        paginated_files = filtered_files[offset : offset + limit]

        for f in paginated_files:
            if f.get("model") is None:
                try:
                    filepath = Path(f["filepath"])
                    with open(filepath, "r", encoding="utf-8") as file:
                        data = json.load(file)
                        f["model"] = data.get("model")
                except Exception:
                    f["model"] = "unknown"
            f.pop("filepath", None)

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


@router.get("/api/v1/dev/gemini-logs/{filename}")
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
        legacy_logs = ROOT_DIR / "logs"
        filepath = _resolve_gemini_log_path(
            filename,
            legacy_logs_dir=legacy_logs,
            session_root=session_files_root(),
        )

        if not filepath.exists():
            raise HTTPException(
                status_code=404, detail=f"Log file not found: {filename}"
            )

        # Read file
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Extract metadata
        timestamp_str = data.get("timestamp")
        if not isinstance(timestamp_str, str):
            timestamp_str = _extract_request_response_timestamp(filepath.name)
        if not timestamp_str:
            timestamp_str = _extract_step_timestamp(filepath.name)
        file_datetime = (
            _parse_gemini_timestamp(timestamp_str) if timestamp_str else None
        )
        file_date = file_datetime.date() if file_datetime else None

        return {
            "filename": filename,
            "metadata": {
                "timestamp": timestamp_str,
                "date": file_date.isoformat() if file_date else None,
                "time": file_datetime.strftime("%H:%M:%S") if file_datetime else None,
                "datetime": file_datetime.isoformat() if file_datetime else None,
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


@router.get("/api/v1/dev/gemini-logs/{filename}/download")
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
        legacy_logs = ROOT_DIR / "logs"
        filepath = _resolve_gemini_log_path(
            filename,
            legacy_logs_dir=legacy_logs,
            session_root=session_files_root(),
        )

        if not filepath.exists():
            raise HTTPException(
                status_code=404, detail=f"Log file not found: {filename}"
            )

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
