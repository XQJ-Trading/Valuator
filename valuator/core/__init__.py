from __future__ import annotations

from importlib import import_module

__all__ = [
    "Aggregation",
    "Engine",
    "Executor",
    "GeminiClient",
    "GeminiSession",
    "Plan",
    "Planner",
    "Review",
    "Task",
    "ToolCall",
    "Workspace",
]

_LAZY_EXPORTS = {
    "Aggregation": (".aggregator.service", "Aggregation"),
    "Engine": (".orchestrator.engine", "Engine"),
    "Executor": (".executor.service", "Executor"),
    "GeminiClient": ("..models.gemini_direct", "GeminiClient"),
    "GeminiSession": ("..models.gemini_direct", "GeminiSession"),
    "Plan": (".contracts.plan", "Plan"),
    "Planner": (".planner.service", "Planner"),
    "Review": (".reviewer.service", "Review"),
    "Task": (".contracts.plan", "Task"),
    "ToolCall": (".contracts.plan", "ToolCall"),
    "Workspace": (".workspace.service", "Workspace"),
}


def __getattr__(name: str):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(name)
    module_name, attr_name = _LAZY_EXPORTS[name]
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
