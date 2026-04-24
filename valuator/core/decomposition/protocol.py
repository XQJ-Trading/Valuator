from __future__ import annotations

from typing import Protocol

from ..context import TaskContext
from ..task import Task
from ..types import TaskDecision


class DecompositionGate(Protocol):
    async def gate(
        self,
        task: Task,
        decision: TaskDecision,
        ctx: TaskContext,
    ) -> TaskDecision:
        ...

    def has_prediction(self, task_id: str) -> bool:
        ...

    def observe_outcome(self, task_id: str, children: list[Task]) -> None:
        ...


class PassthroughGate:
    async def gate(
        self,
        task: Task,
        decision: TaskDecision,
        ctx: TaskContext,
    ) -> TaskDecision:
        del task, ctx
        return decision

    def has_prediction(self, task_id: str) -> bool:
        del task_id
        return False

    def observe_outcome(self, task_id: str, children: list[Task]) -> None:
        del task_id, children
