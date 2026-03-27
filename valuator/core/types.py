from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskState(Enum):
    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    DONE = "done"
    FAILED = "failed"


class Action(Enum):
    DECOMPOSE = "decompose"
    EXECUTE = "execute"
    WAIT = "wait"
    AGGREGATE = "aggregate"
    FINALIZE = "finalize"
    FAIL = "fail"


@dataclass(frozen=True)
class ToolRequest:
    tool_name: str
    args: dict[str, Any]


@dataclass
class TaskSpec:
    description: str
    tool_hint: str = ""
    depends_on_siblings: list[int] = field(default_factory=list)


@dataclass
class TaskDecision:
    action: Action
    children: list[TaskSpec] = field(default_factory=list)
    tool_request: ToolRequest | None = None
    wait_for: list[str] = field(default_factory=list)
    wait_for_facts: list[str] = field(default_factory=list)
    output: Any = None
    facts: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass
class AgentEvent:
    type: str
    task_id: str
    detail: dict[str, Any] = field(default_factory=dict)
