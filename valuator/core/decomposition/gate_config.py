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

    enabled: bool = True
    weights: PenaltyWeights = field(default_factory=PenaltyWeights)
    initial_threshold: float = -0.05
    learning_rate: float = 0.05
    max_depth: int = 3
    max_children: int = 8
    accept_bound: float = -0.01
    reject_bound: float = -0.45
    static_weight: float = 0.4
    critic_weight: float = 0.6


def validate_gate_config(
    *,
    accept_bound: float,
    reject_bound: float,
    static_weight: float,
    critic_weight: float,
    max_depth: int,
    max_children: int,
    **_ignored: float,
) -> None:
    if accept_bound <= reject_bound:
        raise ValueError("decomposition gate requires accept_bound > reject_bound")
    if static_weight + critic_weight <= 0:
        raise ValueError(
            "decomposition gate requires static_weight + critic_weight > 0"
        )
    if max_depth < 1:
        raise ValueError("decomposition gate requires max_depth >= 1")
    if max_children < 2:
        raise ValueError("decomposition gate requires max_children >= 2")
