import asyncio
import json
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ai_agent.agent.react_agent import AIAgent


app = FastAPI(title="AI Agent Server", version="1.5.0")

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


@app.on_event("startup")
async def startup_event():
    # Lazy-init placeholder if needed later
    pass


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/v1/chat")
async def chat(request: ChatRequest):
    agent = AIAgent()
    reply = await agent.chat(request.query)
    return {"response": reply}


@app.post("/api/v1/chat/stream")
async def chat_stream(request: ChatRequest):
    async def sse() -> AsyncGenerator[str, None]:
        try:
            # Initial handshake event helps clients show immediate activity
            yield "event: start\n" + "data: {}\n\n"

            agent = AIAgent()
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


@app.get("/api/v1/chat/stream")
async def chat_stream_get(query: str):
    async def sse() -> AsyncGenerator[str, None]:
        try:
            yield "event: start\n" + "data: {}\n\n"

            agent = AIAgent()
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
