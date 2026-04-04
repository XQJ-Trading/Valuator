from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Fact:
    key: str
    value: Any
    source_task_id: str
    grounded: bool = False
    as_of_utc: str = ""
    time_scope: str = ""
    target_start: str = ""
    target_end: str = ""
    source_urls: tuple[str, ...] = ()


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

    def publish(
        self,
        key: str,
        value: Any,
        source_task_id: str,
        *,
        grounded: bool = False,
        as_of_utc: str = "",
        time_scope: str = "",
        target_start: str = "",
        target_end: str = "",
        source_urls: tuple[str, ...] = (),
    ) -> Conflict | None:
        incoming = Fact(
            key=key,
            value=value,
            source_task_id=source_task_id,
            grounded=grounded,
            as_of_utc=as_of_utc,
            time_scope=time_scope,
            target_start=target_start,
            target_end=target_end,
            source_urls=tuple(source_urls),
        )
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

    def conflict_count(self) -> int:
        return len(self._conflicts)

    def view(self) -> SharedStateView:
        return SharedStateView(
            facts=dict(self._facts),
            conflicts=list(self._conflicts),
        )
