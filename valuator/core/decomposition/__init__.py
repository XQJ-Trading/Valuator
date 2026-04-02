from __future__ import annotations

from importlib import import_module

__all__ = [
    "BackpropagationTracker",
    "CriticVerdict",
    "DecompositionCritic",
    "DecompositionOutcome",
    "FilterResult",
    "FilterVerdict",
    "GateConfig",
    "GateController",
    "GateDecision",
    "PenaltyWeights",
    "StaticBreakdown",
    "combine",
    "pre_filter",
    "validate_gate_config",
    "static_rejects_minimal_decomposition",
]

_LAZY_EXPORTS = {
    "BackpropagationTracker": (".gate", "BackpropagationTracker"),
    "CriticVerdict": (".types", "CriticVerdict"),
    "DecompositionCritic": (".critic", "DecompositionCritic"),
    "DecompositionOutcome": (".types", "DecompositionOutcome"),
    "FilterResult": (".types", "FilterResult"),
    "FilterVerdict": (".types", "FilterVerdict"),
    "GateConfig": (".gate_config", "GateConfig"),
    "GateController": (".controller", "GateController"),
    "GateDecision": (".types", "GateDecision"),
    "PenaltyWeights": (".gate_config", "PenaltyWeights"),
    "StaticBreakdown": (".types", "StaticBreakdown"),
    "combine": (".gate", "combine"),
    "pre_filter": (".gate", "pre_filter"),
    "validate_gate_config": (".gate_config", "validate_gate_config"),
    "static_rejects_minimal_decomposition": (
        ".gate",
        "static_rejects_minimal_decomposition",
    ),
}


def __getattr__(name: str):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _LAZY_EXPORTS[name]
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
