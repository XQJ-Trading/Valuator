from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskState(Enum):
    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    DONE = "done"
    FAILED = "failed"


class TaskWorkPhase(Enum):
    """Work phase for allowed-action narrowing (orchestration, not TaskState)."""

    COLLECT = "collect"
    SYNTHESIZE = "synthesize"


class Action(Enum):
    DECOMPOSE = "decompose"
    EXECUTE = "execute"
    WAIT = "wait"
    AGGREGATE = "aggregate"
    FINALIZE = "finalize"
    FAIL = "fail"


class EventType(str, Enum):
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    DECOMPOSED = "decomposed"
    TOOL_EXECUTED = "tool_executed"
    AGGREGATED = "aggregated"
    FINALIZED = "finalized"
    FAILED = "failed"
    DECOMPOSITION_GATED = "decomposition_gated"


class ToolResult(BaseModel):
    success: bool = Field(..., description="Whether the tool execution was successful")
    result: Any = Field(..., description="Tool execution result")
    error: str | None = Field(None, description="Error message if execution failed")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


@dataclass(frozen=True)
class ToolRequest:
    tool_name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class FailedAttempt:
    tool_name: str
    args: dict[str, Any]
    error: str
    kind: str


@dataclass
class TaskSpec:
    description: str
    task_name: str = ""
    tool_hint: str = ""
    execution_tool: str = ""
    depends_on_siblings: list[int] = field(default_factory=list)
    query_unit_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class TaskDecision:
    action: Action
    children: tuple[TaskSpec, ...] = field(default_factory=tuple)
    tool_request: ToolRequest | None = None
    wait_for: tuple[str, ...] = field(default_factory=tuple)
    output: Any = None
    facts: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "children", tuple(self.children))
        object.__setattr__(self, "wait_for", tuple(self.wait_for))


@dataclass
class AgentEvent:
    type: EventType
    task_id: str
    detail: dict[str, Any] = field(default_factory=dict)
