from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.query import QueryAnalysis, QueryUnit
from valuator.tools.base import ToolResult

from .shared_state import SharedStateView
from .types import TaskState


@dataclass(frozen=True)
class TaskSummary:
    id: str
    description: str
    state: TaskState
    output: Any = None


@dataclass(frozen=True)
class TaskContext:
    task_id: str
    description: str
    step_count: int
    as_of_utc: str = ""
    tool_results: list[ToolResult] = field(default_factory=list)
    child_outputs: dict[str, Any] = field(default_factory=dict)
    current_children: list[TaskSummary] = field(default_factory=list)
    ancestry: list[TaskSummary] = field(default_factory=list)
    siblings: dict[str, TaskSummary] = field(default_factory=dict)
    shared: SharedStateView = field(default_factory=lambda: SharedStateView({}, []))
    query: str = ""
    query_analysis: QueryAnalysis = field(default_factory=QueryAnalysis)
    query_units: list[QueryUnit] = field(default_factory=list)
    available_tools: list[str] = field(default_factory=list)
