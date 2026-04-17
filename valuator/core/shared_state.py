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


def _ancestry_prefixes(task_id: str) -> frozenset[str]:
    parts = task_id.split(".")
    if len(parts) <= 1:
        return frozenset()
    return frozenset(".".join(parts[:i]) for i in range(1, len(parts)))


def _is_relevant(
    fact: Fact,
    *,
    task_id: str,
    unit_set: set[int],
) -> bool:
    if fact.source_task_id == task_id:
        return True
    if not fact.query_unit_ids:
        return True
    if unit_set.intersection(fact.query_unit_ids):
        return True
    if fact.source_task_id in _ancestry_prefixes(task_id):
        return True
    return False


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for k, v in override.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


@dataclass(frozen=True)
class FactExposure:
    task_id: str
    fact_keys: tuple[str, ...]


class SharedState:
    def __init__(self) -> None:
        self._facts: dict[str, Fact] = {}
        self._conflicts: list[Conflict] = []
        self._exposures: list[FactExposure] = []

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
        if existing is None:
            self._facts[key] = incoming
            return None
        if isinstance(existing.value, dict) and isinstance(value, dict):
            merged_value = _deep_merge(existing.value, value)
            merged_units = tuple(
                sorted(set(existing.query_unit_ids) | set(tuple(query_unit_ids)))
            )
            self._facts[key] = Fact(
                key=key,
                value=merged_value,
                source_task_id=source_task_id,
                query_unit_ids=merged_units,
                grounded=grounded,
                as_of_kst=as_of_kst,
                time_scope=time_scope,
                target_start=target_start,
                target_end=target_end,
                source_urls=tuple(source_urls),
            )
            return None
        if existing.value != value:
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

    @property
    def exposures(self) -> list[FactExposure]:
        return list(self._exposures)

    def view(self) -> SharedStateView:
        return SharedStateView(
            facts=dict(self._facts),
            conflicts=list(self._conflicts),
        )

    def relevant_fact_keys_for(self, *, task_id: str, query_unit_ids: list[int]) -> frozenset[str]:
        if task_id == "root":
            return frozenset(self._facts.keys())
        unit_set = set(query_unit_ids)
        return frozenset(
            k
            for k, f in self._facts.items()
            if _is_relevant(f, task_id=task_id, unit_set=unit_set)
        )

    def view_for(
        self,
        *,
        task_id: str,
        query_unit_ids: list[int],
        include_fact_keys: frozenset[str] | None = None,
    ) -> SharedStateView:
        if task_id == "root":
            facts = dict(self._facts)
            if include_fact_keys is not None:
                facts = {k: v for k, v in facts.items() if k in include_fact_keys}
            exposed_keys = tuple(facts.keys())
            if exposed_keys:
                self._exposures.append(
                    FactExposure(task_id=task_id, fact_keys=exposed_keys)
                )
            return SharedStateView(
                facts=facts,
                conflicts=list(self._conflicts),
            )
        unit_set = set(query_unit_ids)
        relevant = {
            k: f
            for k, f in self._facts.items()
            if _is_relevant(f, task_id=task_id, unit_set=unit_set)
        }
        if include_fact_keys is not None:
            relevant = {k: f for k, f in relevant.items() if k in include_fact_keys}
        if relevant:
            self._exposures.append(
                FactExposure(task_id=task_id, fact_keys=tuple(relevant.keys()))
            )
        return SharedStateView(facts=relevant, conflicts=list(self._conflicts))
