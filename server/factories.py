from __future__ import annotations

from valuator.utils.config import config

from .repositories import (
    FileSessionRepository,
    FileTaskRewriteRepository,
    MongoSessionRepository,
    MongoTaskRewriteRepository,
    TaskRewriteRepository,
)


def create_history_repository():
    """Create history repository instance for server history (separate from ReactLogger)"""
    if config.mongodb_enabled and config.mongodb_uri:
        try:
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
        return FileSessionRepository("logs/server_history")


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
