from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

from .context import TaskContext
from .types import TaskDecision, TaskState, ToolRequest, ToolResult

TaskStepDecider = Callable[["Task", TaskContext], Awaitable[TaskDecision]]


class Task(ABC):
    def __init__(
        self,
        *,
        id: str,
        description: str,
        task_name: str = "",
        tool_hint: str = "",
        query_unit_ids: list[int] | None = None,
        decide: TaskStepDecider | None = None,
    ) -> None:
        self.id = id
        self.description = description
        self.task_name = task_name
        self.tool_hint = tool_hint
        self.query_unit_ids = list(query_unit_ids or [])
        self.state = TaskState.CREATED
        self.parent_id: str | None = None
        self.step_count = 0
        self.invalid_decision_count = 0
        self.tool_results: list[ToolResult] = []
        self.child_outputs: dict[str, Any] = {}
        self.published_facts: dict[str, Any] = {}
        self.output: Any = None
        self.error: str | None = None
        self.last_tool_request: ToolRequest | None = None
        self.last_tool_success: bool | None = None
        self.failed_tool_request_signatures: set[str] = set()
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
        target.task_name = self.task_name
        target.query_unit_ids = list(self.query_unit_ids)
        target.state = self.state
        target.parent_id = self.parent_id
        target.step_count = self.step_count
        target.invalid_decision_count = self.invalid_decision_count
        target.tool_results = list(self.tool_results)
        target.child_outputs = dict(self.child_outputs)
        target.published_facts = dict(self.published_facts)
        target.output = self.output
        target.error = self.error
        target.last_tool_request = self.last_tool_request
        target.last_tool_success = self.last_tool_success
        target.failed_tool_request_signatures = set(
            self.failed_tool_request_signatures
        )
        target.last_invalid_error = self.last_invalid_error
        return target

    def implicit_aggregate_payload(self) -> tuple[Any, dict[str, Any]]:
        if self.child_outputs:
            facts_only = [
                output
                for output in self.child_outputs.values()
                if isinstance(output, dict)
                and output.get("status") == "facts_only"
                and isinstance(output.get("facts"), dict)
            ]
            if facts_only and len(facts_only) == len(self.child_outputs):
                merged_facts: dict[str, Any] = {}
                for output in facts_only:
                    merged_facts.update(dict(output["facts"]))
                return None, merged_facts

        if self.last_tool_success and self.tool_results:
            return self.tool_results[-1].result, {}
        return None, {}

    def completion_payload(self) -> Any:
        if self.output is not None:
            return self.output
        if self.published_facts:
            return {
                "status": "facts_only",
                "facts": dict(self.published_facts),
                "source_task_id": self.id,
            }
        return None

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
