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


# Global repository instance
history_repository = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global history_repository
    history_repository = create_history_repository()
    print(f"History repository initialized: {type(history_repository).__name__}")

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


async def save_chat_session(
    query: str,
    events: List[Dict[str, Any]],
    model: Optional[str] = None,
    success: bool = True,
) -> str:
    """Save chat session to history repository with query expansion logging enhancement"""

    # Extract and log web search activities from events for client visibility
    for event in events:
        if event.get("type") == "action":
            tool_input = event.get("tool_input", {})
            if isinstance(tool_input, dict) and "query" in tool_input:
                if tool_input.get("enable_expansion"):
                    # This is a query expansion call, log the original query
                    logger.info(
                        f"🔍 CLIENT LOG: Query expansion initiated for: '{tool_input['query']}'"
                    )
                elif "enable_expansion" in tool_input and not tool_input.get(
                    "enable_expansion"
                ):
                    logger.info(
                        f"🔍 CLIENT LOG: Regular search for: '{tool_input['query']}'"
                    )
            # Look for web_search tool calls and check if they trigger query expansion
            if event.get("tool") == "web_search" and tool_input.get("enable_expansion"):
                try:
                    # Find subsequent observation with search results
                    event_idx = events.index(event)
                    for next_event in events[event_idx + 1 :]:
                        if next_event.get("type") == "observation":
                            tool_result = next_event.get("tool_result", {})
                            if (
                                isinstance(tool_result, dict)
                                and tool_result.get("result")
                                and "expanded_queries_count"
                                in tool_result.get("result", {})
                            ):
                                # This is the query expansion result
                                result_data = tool_result.get("result", {})
                                expanded_count = result_data.get(
                                    "expanded_queries_count", 0
                                )
                                if expanded_count > 0:
                                    logger.info(
                                        f"🔍 CLIENT LOG: Query expansion generated {expanded_count} sub-queries"
                                    )
                                break
                except Exception:
                    pass

    # Rest of the function remains unchanged
    """
    Save chat session to history repository
    
    Args:
        query: User query
        events: List of StreamEvent dictionaries
        model: Model used for the chat
        success: Whether the chat was successful
        
    Returns:
        session_id: ID of the saved session
    """
    if history_repository is None:
        logger.warning("History repository not available, skipping save")
        return ""

    # Generate session ID
    timestamp = datetime.now()
    session_id = timestamp.strftime("chat_%Y%m%d_%H%M%S")

    # Extract final answer from events
    final_answer = ""
    for event in events:
        if event.get("type") == "final_answer":
            final_answer = event.get("content", "")
            break

    # Calculate duration (mock - we don't have start time)
    duration = len(events) * 0.1  # Approximate

    # Create session data
    session_data = {
        "session_id": session_id,
        "timestamp": timestamp.isoformat(),
        "query": query,
        "events": events,
        "final_answer": final_answer,
        "success": success,
        "duration": duration,
        "model": model or config.agent_model,
        "source": "server_chat",
    }

    try:
        saved_session_id = await history_repository.save_session(session_data)
        logger.info(f"Saved chat session: {saved_session_id}")
        return saved_session_id
    except Exception as e:
        logger.error(f"Failed to save chat session: {e}")
        return ""


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/v1/chat")
async def chat(request: ChatRequest):
    """
    Send a chat message to the AI agent

    Args:
        request: Chat request containing query and optional model

    Returns:
        List of StreamEvent objects representing the conversation
    """
    try:
        agent = AIAgent(model_name=request.model)

        # Collect all stream events
        events = []
        async for event in agent.solve_stream(request.query):
            events.append(event)

        # Save chat session to history
        await save_chat_session(request.query, events, request.model)

        return events
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        # Return error as StreamEvent format
        error_events = [
            {"type": "start", "content": "", "metadata": {}},
            {
                "type": "error",
                "content": str(e),
                "metadata": {"model": request.model or config.agent_model},
            },
            {"type": "end", "content": "", "metadata": {}},
        ]
        # Save error session too
        try:
            await save_chat_session(
                request.query, error_events, request.model, success=False
            )
        except Exception:
            pass  # Don't fail on save error
        return error_events


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


@app.get("/api/v1/models")
async def get_supported_models():
    """
    Get list of supported models

    Returns:
        List of supported model names and default model
    """
    return {"models": config.supported_models, "default": config.agent_model}


@app.post("/api/v1/chat/stream")
async def chat_stream_post(request: ChatRequest):
    """
    POST endpoint for chat stream - also saves to history

    Args:
        request: Chat request containing query and optional model
    """

    async def sse() -> AsyncGenerator[str, None]:
        events = []  # Collect events for saving
        try:
            yield "event: start\n" + "data: {}\n\n"

            agent = AIAgent(model_name=request.model)
            async for event in agent.solve_stream(request.query):
                events.append(event)  # Store for saving
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            yield "event: end\n" + "data: {}\n\n"

            # Save session after streaming completes
            try:
                await save_chat_session(request.query, events, request.model)
            except Exception as save_error:
                logger.error(f"Failed to save stream session: {save_error}")

        except Exception as e:
            err = {"type": "error", "message": str(e)}
            error_event = {
                "type": "error",
                "content": str(e),
                "metadata": {"model": request.model or config.agent_model},
            }
            events.append(error_event)

            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
            yield "event: end\n" + "data: {}\n\n"

            # Save error session
            try:
                await save_chat_session(
                    request.query, events, request.model, success=False
                )
            except Exception:
                pass

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
