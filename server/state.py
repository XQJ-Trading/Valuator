from __future__ import annotations

from typing import Any

from .repositories import TaskRewriteRepository
from .services.task_rewrite.service import TaskRewriteService

history_repository: Any = None
task_rewrite_repository: TaskRewriteRepository | None = None
session_service: Any = None
task_rewrite_service: TaskRewriteService | None = None
