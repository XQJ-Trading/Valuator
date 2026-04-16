from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Fact:
    key: str
    value: Any
    source_task_id: str
    query_unit_ids: tuple[int, ...] = ()
    grounded: bool = False
    as_of_kst: str = ""
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


def _subtree_prefix(task_id: str) -> str:
    """Branch key: first two path segments (e.g. root.0.1.2 -> root.0)."""
    parts = task_id.split(".")
    if len(parts) <= 1:
        return ""
    return ".".join(parts[:2])


def _ancestry_prefixes(task_id: str) -> frozenset[str]:
    parts = task_id.split(".")
    if len(parts) <= 1:
        return frozenset()
    return frozenset(".".join(parts[:i]) for i in range(1, len(parts)))


def _source_in_subtree(*, source_task_id: str, subtree_prefix: str) -> bool:
    if not subtree_prefix:
        return False
    return source_task_id == subtree_prefix or source_task_id.startswith(
        subtree_prefix + "."
    )


def _is_relevant(
    fact: Fact,
    *,
    task_id: str,
    unit_set: set[int],
) -> bool:
    if not fact.query_unit_ids:
        return True
    if unit_set.intersection(fact.query_unit_ids):
        return True
    subtree_prefix = _subtree_prefix(task_id)
    if _source_in_subtree(source_task_id=fact.source_task_id, subtree_prefix=subtree_prefix):
        return True
    if fact.source_task_id in _ancestry_prefixes(task_id):
        return True
    return False


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
        query_unit_ids: tuple[int, ...] = (),
        grounded: bool = False,
        as_of_kst: str = "",
        time_scope: str = "",
        target_start: str = "",
        target_end: str = "",
        source_urls: tuple[str, ...] = (),
    ) -> Conflict | None:
        incoming = Fact(
            key=key,
            value=value,
            source_task_id=source_task_id,
            query_unit_ids=tuple(query_unit_ids),
            grounded=grounded,
            as_of_kst=as_of_kst,
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

    def view_for(
        self,
        *,
        task_id: str,
        query_unit_ids: list[int],
    ) -> SharedStateView:
        if task_id == "root":
            return SharedStateView(
                facts=dict(self._facts),
                conflicts=list(self._conflicts),
            )
        unit_set = set(query_unit_ids)
        relevant = {
            k: f
            for k, f in self._facts.items()
            if _is_relevant(f, task_id=task_id, unit_set=unit_set)
        }
        return SharedStateView(facts=relevant, conflicts=list(self._conflicts))
