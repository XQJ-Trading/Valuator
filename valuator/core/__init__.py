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
    "Fact",
    "FactAddress",
    "FactValue",
    "FailedAttempt",
    "NumericValue",
    "Scheduler",
    "SharedState",
    "SharedStateView",
    "StepPlanner",
    "Task",
    "TaskDecision",
    "TaskSpec",
    "TaskState",
    "TextValue",
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
    "Fact": (".shared_state", "Fact"),
    "FactAddress": (".ontology", "FactAddress"),
    "FactValue": (".ontology", "FactValue"),
    "FailedAttempt": (".types", "FailedAttempt"),
    "NumericValue": (".ontology", "NumericValue"),
    "Scheduler": (".scheduler", "Scheduler"),
    "SharedState": (".shared_state", "SharedState"),
    "SharedStateView": (".shared_state", "SharedStateView"),
    "StepPlanner": (".planning", "StepPlanner"),
    "Task": (".task", "Task"),
    "TaskDecision": (".types", "TaskDecision"),
    "TaskSpec": (".types", "TaskSpec"),
    "TaskState": (".types", "TaskState"),
    "TextValue": (".ontology", "TextValue"),
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
