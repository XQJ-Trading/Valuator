from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from valuator.models.gemini_direct import ensure_supported_google_genai_runtime
from valuator.utils.logger import logger

from .session_viewer_api import ensure_viewer_roots, router as session_viewer_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    google_genai_version = ensure_supported_google_genai_runtime()
    logger.info("google-genai runtime verified: %s", google_genai_version)
    ensure_viewer_roots()

    yield

    logger.info("Shutting down application...")
    logger.info("Application shutdown complete")


app = FastAPI(title="AI Agent Server", version="1.5.0", lifespan=lifespan)

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
app.include_router(session_viewer_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
