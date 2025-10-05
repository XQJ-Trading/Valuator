import asyncio
import json
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from ai_agent.agent.react_agent import AIAgent
from ai_agent.repositories import FileSessionRepository, MongoSessionRepository
from ai_agent.utils.config import config
from server.adapters import HistoryAdapter


# Supported Gemini models
SUPPORTED_MODELS = [
    "gemini-flash-latest",
    "gemini-pro-latest"
]

app = FastAPI(title="AI Agent Server", version="1.5.0")

# Initialize repository based on configuration
def create_repository():
    """Create repository instance based on configuration"""
    if config.mongodb_enabled and config.mongodb_uri:
        try:
            return MongoSessionRepository(
                mongodb_uri=config.mongodb_uri,
                database=config.mongodb_database,
                collection=config.mongodb_collection
            )
        except Exception as e:
            print(f"Failed to initialize MongoDB repository: {e}")
            print("Falling back to file repository")
            return FileSessionRepository("logs/react_sessions")
    else:
        return FileSessionRepository("logs/react_sessions")

# Global repository instance
history_repository = None

# CORS for local frontend dev (adjust origins as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    query: str
    model: Optional[str] = None
    
    @field_validator('model')
    @classmethod
    def validate_model(cls, v):
        if v is not None and v not in SUPPORTED_MODELS:
            raise ValueError(
                f"Unsupported model: {v}. "
                f"Supported models are: {', '.join(SUPPORTED_MODELS)}"
            )
        return v


@app.on_event("startup")
async def startup_event():
    global history_repository
    history_repository = create_repository()
    print(f"History repository initialized: {type(history_repository).__name__}")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/v1/chat")
async def chat(request: ChatRequest):
    agent = AIAgent(model_name=request.model)
    reply = await agent.chat(request.query)
    return {"response": reply}


@app.post("/api/v1/chat/stream")
async def chat_stream(request: ChatRequest):
    async def sse() -> AsyncGenerator[str, None]:
        try:
            # Initial handshake event helps clients show immediate activity
            yield "event: start\n" + "data: {}\n\n"

            agent = AIAgent(model_name=request.model)
            async for event in agent.solve_stream(request.query):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            yield "event: end\n" + "data: {}\n\n"

        except Exception as e:
            err = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
            yield "event: end\n" + "data: {}\n\n"

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


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
        raise HTTPException(status_code=500, detail="History repository not initialized")
    
    try:
        sessions = await history_repository.list_sessions(limit=limit, offset=offset)
        summaries = HistoryAdapter.sessions_to_summaries(sessions)
        
        return {
            "sessions": summaries,
            "total": len(summaries),
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve history: {str(e)}")


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
        raise HTTPException(status_code=500, detail="History repository not initialized")
    
    try:
        session = await history_repository.get_session(session_id)
        
        if session is None:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        
        return session
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve session: {str(e)}")


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
        raise HTTPException(status_code=500, detail="History repository not initialized")
    
    async def sse() -> AsyncGenerator[str, None]:
        try:
            # Load session
            session = await history_repository.get_session(session_id)
            
            if session is None:
                error_event = {"type": "error", "message": f"Session not found: {session_id}"}
                yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
                yield "event: end\n" + "data: {}\n\n"
                return
            
            # Convert to stream events
            events = HistoryAdapter.session_to_stream_events(session)
            
            # Stream events
            for event in events:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                
                # Add small delay for better UX (optional)
                await asyncio.sleep(0.1)
            
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


@app.get("/api/v1/history/search")
async def search_history(q: str, limit: int = 20):
    """
    Search sessions by query string
    
    Args:
        q: Search query string
        limit: Maximum number of results to return (default: 20)
    
    Returns:
        List of matching session summaries
    """
    if history_repository is None:
        raise HTTPException(status_code=500, detail="History repository not initialized")
    
    if not q or len(q.strip()) == 0:
        raise HTTPException(status_code=400, detail="Search query cannot be empty")
    
    try:
        sessions = await history_repository.search_sessions(q)
        
        # Limit results
        sessions = sessions[:limit]
        
        summaries = HistoryAdapter.sessions_to_summaries(sessions)
        
        return {
            "query": q,
            "sessions": summaries,
            "total": len(summaries)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search history: {str(e)}")


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
        raise HTTPException(status_code=500, detail="History repository not initialized")
    
    try:
        success = await history_repository.delete_session(session_id)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        
        return {
            "message": f"Session deleted successfully: {session_id}",
            "session_id": session_id
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete session: {str(e)}")


@app.get("/api/v1/models")
async def get_supported_models():
    """
    Get list of supported models
    
    Returns:
        List of supported model names
    """
    return {
        "models": SUPPORTED_MODELS,
        "default": config.agent_model
    }


@app.get("/api/v1/chat/stream")
async def chat_stream_get(query: str, model: Optional[str] = None):
    """
    GET endpoint for chat stream (for compatibility)
    
    Args:
        query: User query
        model: Optional model name (must be one of supported models)
    """
    # Validate model if provided
    if model is not None and model not in SUPPORTED_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported model: {model}. Supported models are: {', '.join(SUPPORTED_MODELS)}"
        )
    
    async def sse() -> AsyncGenerator[str, None]:
        try:
            yield "event: start\n" + "data: {}\n\n"

            agent = AIAgent(model_name=model)
            async for event in agent.solve_stream(query):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            yield "event: end\n" + "data: {}\n\n"
        except Exception as e:
            err = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
            yield "event: end\n" + "data: {}\n\n"

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
