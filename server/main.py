import asyncio
import json
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ai_agent.agent.react_agent import ReActGeminiAgent


app = FastAPI(title="AI Agent Server", version="0.1.0")

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
    use_react: bool | None = None


@app.on_event("startup")
async def startup_event():
    # Lazy-init placeholder if needed later
    pass


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/v1/chat")
async def chat(request: ChatRequest):
    agent = ReActGeminiAgent()
    if request.use_react is None:
        reply = await agent.chat_enhanced(request.query)
    else:
        if request.use_react:
            result = await agent.solve_with_react(request.query, force_react=True)
            reply = result.get("response", "")
        else:
            reply = await agent.chat(request.query)
    return {"response": reply}


@app.post("/api/v1/chat/stream")
async def chat_stream(request: ChatRequest):
    async def sse() -> AsyncGenerator[str, None]:
        try:
            # Initial handshake event helps clients show immediate activity
            yield "event: start\n" + "data: {}\n\n"

            agent = ReActGeminiAgent()

            if request.use_react:
                async for event in agent.solve_with_react_stream(request.query, force_react=True):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            else:
                async for chunk in agent.chat_stream(request.query):
                    data = {"type": "token", "content": chunk}
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

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


@app.get("/api/v1/chat/stream")
async def chat_stream_get(query: str, use_react: bool = False):
    async def sse() -> AsyncGenerator[str, None]:
        try:
            yield "event: start\n" + "data: {}\n\n"

            agent = ReActGeminiAgent()
            if use_react:
                async for event in agent.solve_with_react_stream(query, force_react=True):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            else:
                async for chunk in agent.chat_stream(query):
                    data = {"type": "token", "content": chunk}
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

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


