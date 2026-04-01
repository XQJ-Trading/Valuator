from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FilterVerdict(Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class StaticBreakdown:
    depth_cost: float
    breadth_cost: float
    token_pressure: float


@dataclass(frozen=True)
class FilterResult:
    verdict: FilterVerdict
    static_score: float
    breakdown: StaticBreakdown
    reason: str


@dataclass(frozen=True)
class CriticVerdict:
    allow: bool
    single_tool_possible: bool
    redundant_pairs: list[tuple[int, int]]
    coverage_pct: int
    min_children: int
    reason: str


@dataclass(frozen=True)
class GateDecision:
    net_score: float
    threshold: float
    rejected: bool
    used_critic: bool
    reason: str
    static_result: FilterResult
    critic_verdict: CriticVerdict | None = None


@dataclass
class DecompositionOutcome:
    task_id: str
    predicted_score: float
    child_count: int
    depth: int
    used_critic: bool
    actual_efficiency: float = 0.0
