"""Data contracts for pipeline core types."""

from .plan import (
    AggregationResult,
    DomainCoverage,
    ExecutionArtifact,
    ExecutionResult,
    Plan,
    ReportMaterial,
    ReviewResult,
    Task,
    TaskReport,
    ToolCall,
    evaluate_contract,
    parse_contract_coverage,
)

__all__ = [
    "AggregationResult",
    "DomainCoverage",
    "ExecutionArtifact",
    "ExecutionResult",
    "Plan",
    "ReportMaterial",
    "ReviewResult",
    "Task",
    "TaskReport",
    "ToolCall",
    "evaluate_contract",
    "parse_contract_coverage",
]
