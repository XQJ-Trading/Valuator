from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FilterVerdict(Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class PenaltyWeights:
    depth: float = 0.3
    breadth: float = 0.2
    tool_resolvability: float = 0.3
    token_pressure: float = 0.2


@dataclass(frozen=True)
class GateConfig:
    enabled: bool = True
    weights: PenaltyWeights = field(default_factory=PenaltyWeights)
    initial_threshold: float = 0.0
    learning_rate: float = 0.1
    max_depth: int = 4
    max_children: int = 8
    accept_bound: float = 0.4
    reject_bound: float = -0.3
    static_weight: float = 0.4
    critic_weight: float = 0.6


@dataclass(frozen=True)
class StaticBreakdown:
    depth_cost: float
    breadth_cost: float
    tool_resolvability: float
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
