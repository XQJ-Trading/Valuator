"""Shared state — stub retained for interface compatibility.

The fact layer has been removed. Tasks communicate results through
child_outputs (parent-child) and siblings (TaskSummary.output).
This module provides empty types so that callers compile without
breaking during the transition.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SharedStateView:
    """Read-only view — always empty after fact layer removal."""

    facts: dict = field(default_factory=dict)
    conflicts: list = field(default_factory=list)
    resolved_conflicts: list = field(default_factory=list)


class SharedState:
    """No-op shared state. Publish/view calls are retained but do nothing."""

    def __init__(self) -> None:
        pass

    def publish(self, *_args, **_kwargs) -> None:
        return None

    def view(self) -> SharedStateView:
        return SharedStateView()

    def view_for(self, **_kwargs) -> SharedStateView:
        return SharedStateView()

    def relevant_fact_keys_for(self, **_kwargs) -> frozenset[str]:
        return frozenset()

    @property
    def exposures(self) -> list:
        return []

    @property
    def resolved_conflicts(self) -> list:
        return []

    def conflict_count(self) -> int:
        return 0


# Legacy type stubs for test compatibility
@dataclass(frozen=True)
class Fact:
    address: object = None
    value: object = None
    source_task_id: str = ""
    query_unit_ids: tuple = ()
    grounded: bool = False
    as_of_kst: str = ""
    source_urls: tuple = ()
    source_tier: int = -1

    @property
    def key(self) -> str:
        return ""


@dataclass(frozen=True)
class Conflict:
    key: str = ""
    existing: object = None
    incoming: object = None


@dataclass(frozen=True)
class ResolvedConflict:
    key: str = ""
    existing: object = None
    incoming: object = None
    selected: object = None
    discarded: object = None
    reason: str = ""


@dataclass(frozen=True)
class FactExposure:
    task_id: str = ""
    fact_keys: tuple = ()
