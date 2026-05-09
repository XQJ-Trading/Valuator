from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PenaltyWeights:
    depth: float = 0.4
    breadth: float = 0.35
    token_pressure: float = 0.25


@dataclass(frozen=True)
class GateConfig:
    """MCTS-inspired decomposition gate (selection + backprop). Defaults are field defaults."""

    enabled: bool = False
    weights: PenaltyWeights = field(default_factory=PenaltyWeights)
    initial_threshold: float = -0.05
    learning_rate: float = 0.05
    max_depth: int = 4
    max_children: int = 8
    accept_bound: float = -0.01
    reject_bound: float = -0.45
    static_weight: float = 0.4
    critic_weight: float = 0.6

    def __post_init__(self) -> None:
        if self.accept_bound <= self.reject_bound:
            raise ValueError("decomposition gate requires accept_bound > reject_bound")
        if self.static_weight + self.critic_weight <= 0:
            raise ValueError(
                "decomposition gate requires static_weight + critic_weight > 0"
            )
        if self.max_depth < 1:
            raise ValueError("decomposition gate requires max_depth >= 1")
        if self.max_children < 2:
            raise ValueError("decomposition gate requires max_children >= 2")
