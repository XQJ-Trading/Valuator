from __future__ import annotations

from dataclasses import dataclass, field

from .ontology import FactAddress, FactValue


@dataclass(frozen=True)
class Fact:
    address: FactAddress
    value: FactValue
    source_task_id: str
    query_unit_ids: tuple[int, ...] = ()
    grounded: bool = False
    as_of_kst: str = ""
    source_urls: tuple[str, ...] = ()
    source_tier: int = -1

    @property
    def key(self) -> str:
        return self.address.canonical_key


@dataclass(frozen=True)
class Conflict:
    key: str
    existing: Fact
    incoming: Fact


@dataclass(frozen=True)
class ResolvedConflict:
    key: str
    existing: Fact
    incoming: Fact
    selected: Fact
    discarded: Fact
    reason: str


@dataclass(frozen=True)
class SharedStateView:
    facts: dict[str, Fact]
    conflicts: list[Conflict]
    resolved_conflicts: list[ResolvedConflict] = field(default_factory=list)

    def get(self, key: str) -> FactValue | None:
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


@dataclass(frozen=True)
class FactExposure:
    task_id: str
    fact_keys: tuple[str, ...]


def _resolve_conflict(existing: Fact, incoming: Fact) -> ResolvedConflict | None:
    if existing.source_tier < 0 and incoming.source_tier < 0:
        return None
    if existing.source_tier == incoming.source_tier:
        return None
    if existing.source_tier > incoming.source_tier:
        return ResolvedConflict(
            key=existing.key,
            existing=existing,
            incoming=incoming,
            selected=existing,
            discarded=incoming,
            reason=(
                "higher source priority preferred "
                f"({existing.source_tier} > {incoming.source_tier})"
            ),
        )
    return ResolvedConflict(
        key=existing.key,
        existing=existing,
        incoming=incoming,
        selected=incoming,
        discarded=existing,
        reason=(
            "higher source priority preferred "
            f"({incoming.source_tier} > {existing.source_tier})"
        ),
    )


def _is_resolution_relevant(
    resolution: ResolvedConflict,
    *,
    task_id: str,
    unit_set: set[int],
) -> bool:
    return any(
        _is_relevant(fact, task_id=task_id, unit_set=unit_set)
        for fact in (resolution.existing, resolution.incoming, resolution.selected)
    )


class SharedState:
    def __init__(self) -> None:
        self._facts: dict[str, Fact] = {}
        self._conflicts: dict[str, Conflict] = {}
        self._resolved_conflicts: list[ResolvedConflict] = []
        self._exposures: list[FactExposure] = []

    def publish(self, fact: Fact) -> Conflict | None:
        key = fact.key
        existing = self._facts.get(key)
        if existing is None:
            self._facts[key] = fact
            return None
        if existing.value == fact.value:
            # same value — update metadata only
            self._facts[key] = fact
            return None
        resolution = _resolve_conflict(existing, fact)
        if resolution is not None:
            self._facts[key] = resolution.selected
            self._conflicts.pop(key, None)
            self._resolved_conflicts.append(resolution)
            return None
        conflict = Conflict(key=key, existing=existing, incoming=fact)
        self._conflicts[key] = conflict
        return conflict

    def get(self, key: str) -> FactValue | None:
        fact = self._facts.get(key)
        return fact.value if fact else None

    def has(self, key: str) -> bool:
        return key in self._facts

    def conflict_count(self) -> int:
        return len(self._conflicts)

    @property
    def exposures(self) -> list[FactExposure]:
        return list(self._exposures)

    @property
    def resolved_conflicts(self) -> list[ResolvedConflict]:
        return list(self._resolved_conflicts)

    def view(self) -> SharedStateView:
        return SharedStateView(
            facts=dict(self._facts),
            conflicts=list(self._conflicts.values()),
            resolved_conflicts=list(self._resolved_conflicts),
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
                conflicts=list(self._conflicts.values()),
                resolved_conflicts=list(self._resolved_conflicts),
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
        return SharedStateView(
            facts=relevant,
            conflicts=[
                conflict
                for conflict in self._conflicts.values()
                if _is_relevant(conflict.existing, task_id=task_id, unit_set=unit_set)
                or _is_relevant(conflict.incoming, task_id=task_id, unit_set=unit_set)
            ],
            resolved_conflicts=[
                resolution
                for resolution in self._resolved_conflicts
                if _is_resolution_relevant(
                    resolution,
                    task_id=task_id,
                    unit_set=unit_set,
                )
            ],
        )
