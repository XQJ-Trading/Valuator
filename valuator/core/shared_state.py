from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Fact:
    key: str
    value: Any
    source_task_id: str


@dataclass(frozen=True)
class Conflict:
    key: str
    existing: Fact
    incoming: Fact


@dataclass(frozen=True)
class SharedStateView:
    facts: dict[str, Fact]
    conflicts: list[Conflict]

    def get(self, key: str) -> Any | None:
        fact = self.facts.get(key)
        return fact.value if fact else None

    def has(self, key: str) -> bool:
        return key in self.facts


class SharedState:
    def __init__(self) -> None:
        self._facts: dict[str, Fact] = {}
        self._conflicts: list[Conflict] = []
        self._fact_waiters: dict[str, set[str]] = {}

    def publish(self, key: str, value: Any, source_task_id: str) -> Conflict | None:
        incoming = Fact(key=key, value=value, source_task_id=source_task_id)
        existing = self._facts.get(key)
        if existing is not None and existing.value != value:
            conflict = Conflict(key=key, existing=existing, incoming=incoming)
            self._conflicts.append(conflict)
            return conflict
        self._facts[key] = incoming
        return None

    def get(self, key: str) -> Any | None:
        fact = self._facts.get(key)
        return fact.value if fact else None

    def has(self, key: str) -> bool:
        return key in self._facts

    def subscribe(self, key: str, task_id: str) -> None:
        self._fact_waiters.setdefault(key, set()).add(task_id)

    def remove_task_waits(self, task_id: str) -> None:
        empty_keys: list[str] = []
        for key, waiters in self._fact_waiters.items():
            waiters.discard(task_id)
            if not waiters:
                empty_keys.append(key)
        for key in empty_keys:
            self._fact_waiters.pop(key, None)

    def drain_waiters(self, key: str) -> list[str]:
        waiters = self._fact_waiters.pop(key, set())
        return sorted(waiters)

    def conflict_count(self) -> int:
        return len(self._conflicts)

    def view(self) -> SharedStateView:
        return SharedStateView(
            facts=dict(self._facts),
            conflicts=list(self._conflicts),
        )
