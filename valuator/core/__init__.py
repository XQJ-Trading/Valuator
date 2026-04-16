from __future__ import annotations

from importlib import import_module

__all__ = [
    "Action",
    "Agent",
    "AgentEvent",
    "AtomicTask",
    "ComplexTask",
    "Conflict",
    "EventType",
    "FailedAttempt",
    "Fact",
    "Scheduler",
    "SharedState",
    "SharedStateView",
    "StepPlanner",
    "Task",
    "TaskDecision",
    "TaskSpec",
    "TaskState",
    "ToolRequest",
    "ToolResult",
]

_LAZY_EXPORTS = {
    "Action": (".types", "Action"),
    "Agent": (".agent", "Agent"),
    "AgentEvent": (".types", "AgentEvent"),
    "AtomicTask": (".task", "AtomicTask"),
    "ComplexTask": (".task", "ComplexTask"),
    "Conflict": (".shared_state", "Conflict"),
    "EventType": (".types", "EventType"),
    "FailedAttempt": (".types", "FailedAttempt"),
    "Fact": (".shared_state", "Fact"),
    "Scheduler": (".scheduler", "Scheduler"),
    "SharedState": (".shared_state", "SharedState"),
    "SharedStateView": (".shared_state", "SharedStateView"),
    "StepPlanner": (".planning", "StepPlanner"),
    "Task": (".task", "Task"),
    "TaskDecision": (".types", "TaskDecision"),
    "TaskSpec": (".types", "TaskSpec"),
    "TaskState": (".types", "TaskState"),
    "ToolRequest": (".types", "ToolRequest"),
    "ToolResult": (".types", "ToolResult"),
}


def __getattr__(name: str):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _LAZY_EXPORTS[name]
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
