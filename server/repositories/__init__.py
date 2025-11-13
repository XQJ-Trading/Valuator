from .base import SessionRepository
from .file_repository import FileSessionRepository
from .mongo_repository import MongoSessionRepository

# Lazy import to avoid circular dependency
def _get_task_rewrite_repositories():
    from .task_rewrite_repository import (
        FileTaskRewriteRepository,
        MongoTaskRewriteRepository,
        TaskRewriteRepository,
    )
    return (
        FileTaskRewriteRepository,
        MongoTaskRewriteRepository,
        TaskRewriteRepository,
    )

__all__ = [
    "SessionRepository",
    "FileSessionRepository",
    "MongoSessionRepository",
    "TaskRewriteRepository",
    "FileTaskRewriteRepository",
    "MongoTaskRewriteRepository",
]
