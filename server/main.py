from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from valuator.utils.logger import logger

from .auth import verify_auth
from .chat_api import router as chat_router
from .pdf_api import router as pdf_router
from .session_viewer_api import ensure_viewer_roots, router as session_viewer_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_viewer_roots()

    yield

    logger.info("Shutting down application...")


def _get_allowed_origins() -> list[str]:
    """Get allowed CORS origins from environment variable or defaults."""
    default_origins = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"
    origins_str = os.getenv("ALLOWED_ORIGINS", default_origins)
    return [o.strip() for o in origins_str.split(",") if o.strip()]


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI Agent Server",
        version="1.5.0",
        lifespan=lifespan,
        dependencies=[Depends(verify_auth)],
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_get_allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(session_viewer_router)
    app.include_router(chat_router)
    app.include_router(pdf_router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
