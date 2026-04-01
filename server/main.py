from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from valuator.models.gemini_direct import ensure_supported_google_genai_runtime
from valuator.utils.logger import logger

from .factories import create_history_repository, create_task_rewrite_repository
from .repositories import MongoSessionRepository, MongoTaskRewriteRepository
from .routes import router as api_router
from . import state
from .services.session_service import SessionService
from .services.task_rewrite.service import TaskRewriteService
from .session_viewer_api import ensure_viewer_roots, router as session_viewer_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    google_genai_version = ensure_supported_google_genai_runtime()
    logger.info("google-genai runtime verified: %s", google_genai_version)
    state.history_repository = create_history_repository()
    print(f"History repository initialized: {type(state.history_repository).__name__}")

    state.session_service = SessionService(history_repository=state.history_repository)
    print("SessionService initialized")

    state.task_rewrite_repository = create_task_rewrite_repository()
    state.task_rewrite_service = TaskRewriteService(
        repository=state.task_rewrite_repository
    )
    print("TaskRewriteService initialized")
    ensure_viewer_roots()

    yield

    logger.info("Shutting down application...")

    if state.task_rewrite_repository and isinstance(
        state.task_rewrite_repository, MongoTaskRewriteRepository
    ):
        try:
            state.task_rewrite_repository.close()
            logger.info("Task rewrite MongoDB connection closed")
        except Exception as e:
            logger.error(f"Error closing task rewrite MongoDB connection: {e}")

    if state.history_repository and isinstance(
        state.history_repository, MongoSessionRepository
    ):
        try:
            state.history_repository.close()
            logger.info("History MongoDB connection closed")
        except Exception as e:
            logger.error(f"Error closing history MongoDB connection: {e}")

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
app.include_router(api_router)
