from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

from valuator.tools.base import ToolResult

from .context import TaskContext
from .types import TaskDecision, TaskState, ToolRequest

TaskStepDecider = Callable[["Task", TaskContext], Awaitable[TaskDecision]]


class Task(ABC):
    def __init__(
        self,
        *,
        id: str,
        description: str,
        tool_hint: str = "",
        decide: TaskStepDecider | None = None,
    ) -> None:
        self.id = id
        self.description = description
        self.tool_hint = tool_hint
        self.state = TaskState.CREATED
        self.parent_id: str | None = None
        self.step_count = 0
        self.invalid_decision_count = 0
        self.tool_results: list[ToolResult] = []
        self.child_outputs: dict[str, Any] = {}
        self.output: Any = None
        self.error: str | None = None
        self.last_tool_request: ToolRequest | None = None
        self.last_tool_success: bool | None = None
        self.last_invalid_error: str | None = None
        self._decide = decide

    def bind_step(self, decide: TaskStepDecider) -> None:
        self._decide = decide

    @property
    def decider(self) -> TaskStepDecider | None:
        return self._decide

    async def step(self, ctx: TaskContext) -> TaskDecision:
        if self._decide is None:
            raise RuntimeError(f"task step decider is not bound: {self.id}")
        return await self._decide(self, ctx)

    def copy_runtime_to(self, target: "Task") -> "Task":
        target.state = self.state
        target.parent_id = self.parent_id
        target.step_count = self.step_count
        target.invalid_decision_count = self.invalid_decision_count
        target.tool_results = list(self.tool_results)
        target.child_outputs = dict(self.child_outputs)
        target.output = self.output
        target.error = self.error
        target.last_tool_request = self.last_tool_request
        target.last_tool_success = self.last_tool_success
        target.last_invalid_error = self.last_invalid_error
        return target

    @abstractmethod
    def children(self) -> list["Task"]:
        ...

    @abstractmethod
    def add_child(self, child: "Task") -> None:
        ...


class AtomicTask(Task):
    def children(self) -> list[Task]:
        return []

    def add_child(self, child: Task) -> None:
        raise TypeError(f"{type(self).__name__} cannot have children")


class ComplexTask(Task):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._children: list[Task] = []

    def children(self) -> list[Task]:
        return list(self._children)

    def add_child(self, child: Task) -> None:
        child.parent_id = self.id
        self._children.append(child)

    def replace_child(self, current: Task, replacement: Task) -> None:
        for index, child in enumerate(self._children):
            if child.id != current.id:
                continue
            replacement.parent_id = self.id
            self._children[index] = replacement
            return
        raise KeyError(f"child not found: {current.id}")
