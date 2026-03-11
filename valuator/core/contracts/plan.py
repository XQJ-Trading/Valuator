from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ...domain.query import QueryAnalysis

TaskType = Literal["leaf", "module", "merge"]


@dataclass(slots=True)
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Task:
    id: str
    task_type: TaskType = "leaf"
    query_unit_ids: list[int] = field(default_factory=list)
    deps: list[str] = field(default_factory=list)
    tool: ToolCall | None = None
    domain_id: str = ""
    output: str = ""
    description: str = ""
    node_goal: str = ""
    depth: int = 0
    merge_instruction: str = ""


@dataclass(slots=True)
class Plan:
    query: str
    analysis: QueryAnalysis
    root_task_id: str | None = None
    tasks: list[Task] = field(default_factory=list)

    @property
    def query_units(self) -> list:
        return self.analysis.units

    @property
    def requirements(self) -> list:
        return self.analysis.requirements


@dataclass(slots=True)
class ExecutionArtifact:
    task_id: str
    path: str
    content: str = ""
    raw_result: dict[str, Any] | None = None
    domain_id: str = ""
    domain_summary: str = ""
    domain_key_values: dict[str, str] = field(default_factory=dict)
    domain_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReportMaterial:
    source: str
    content: str = ""
    facts: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TaskReport:
    task_id: str
    markdown: str


@dataclass(slots=True)
class DomainCoverage:
    final_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExecutionResult:
    completed_leaf_task_ids: list[str] = field(default_factory=list)
    artifacts: list[ExecutionArtifact] = field(default_factory=list)


@dataclass(slots=True)
class AggregationResult:
    final_markdown: str = ""
    root_task_id: str = ""
    aggregated_query_unit_ids: list[int] = field(default_factory=list)
    final_included_query_unit_ids: list[int] = field(default_factory=list)
    missing_requirement_ids: list[str] = field(default_factory=list)
    covered_requirement_ids: list[str] = field(default_factory=list)
    domain_coverage: DomainCoverage = field(default_factory=DomainCoverage)
    aggregation_error: str = ""


@dataclass(slots=True)
class ReviewResult:
    actions: list[dict[str, Any]] = field(default_factory=list)
    coverage_feedback: dict[str, Any] = field(default_factory=dict)
    now_utc: str = ""
    quant_axes: dict[str, Any] = field(default_factory=dict)
    status: str = "pass"


def evaluate_contract(
    requirements: list,
    markdown: str,
    *,
    covered_item_ids: list[str] | None = None,
) -> list[str]:
    covered = set(parse_contract_coverage(markdown) if covered_item_ids is None else covered_item_ids)
    if covered_item_ids is None:
        text = markdown or ""
        for item in requirements:
            if f"[{item.id}]" in text:
                covered.add(item.id)

    missing: list[str] = []
    for item in requirements:
        if not item.required:
            continue
        if item.id in covered:
            continue
        missing.append(item.id)
    return missing


def parse_contract_coverage(markdown: str) -> list[str]:
    marker = "[CONTRACT_COVERAGE]"
    for raw_line in (markdown or "").splitlines():
        line = raw_line.strip()
        if not line.startswith(marker):
            continue
        payload = line[len(marker):].strip()
        if payload.startswith(":"):
            payload = payload[1:].strip()
        return _split_ids(payload)
    return []


def _split_ids(payload: str) -> list[str]:
    normalized = payload
    for token in (",", ";", "|"):
        normalized = normalized.replace(token, " ")
    ids = [part.strip() for part in normalized.split() if part.strip()]
    return list(dict.fromkeys(ids))
