from __future__ import annotations

from dataclasses import dataclass, field

from ..aggregator.materials import accumulate_execution_artifact
from ..contracts.plan import (
    ExecutionArtifact,
    ExecutionResult,
    Plan,
    ReportMaterial,
    Task,
    TaskReport,
)


@dataclass
class RoundState:
    task_map: dict[str, Task]
    pending_task_ids: set[str]
    reports: dict[str, TaskReport] = field(default_factory=dict)
    artifact_materials: dict[str, list[ReportMaterial]] = field(default_factory=dict)
    artifact_index: dict[str, list[ExecutionArtifact]] = field(default_factory=dict)
    execution_artifacts: list[ExecutionArtifact] = field(default_factory=list)
    completed_leaf_task_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_plan(cls, plan: Plan) -> "RoundState":
        task_map = {task.id: task for task in plan.tasks}
        return cls(task_map=task_map, pending_task_ids=set(task_map))

    @property
    def total_tasks(self) -> int:
        return len(self.task_map)

    def has_pending_tasks(self) -> bool:
        return bool(self.pending_task_ids)

    @property
    def completed_task_count(self) -> int:
        return len(self.reports)

    def ready_executable_task_ids(self) -> list[str]:
        return sorted(
            task_id
            for task_id in self.pending_task_ids
            if self.task_map[task_id].task_type != "merge"
            and self._dependencies_completed(task_id)
        )

    def ready_merge_task_ids(self) -> list[str]:
        return sorted(
            task_id
            for task_id in self.pending_task_ids
            if self.task_map[task_id].task_type == "merge"
            and self._dependencies_completed(task_id)
        )

    def record_execution_artifact(self, artifact: ExecutionArtifact) -> None:
        task = self.task_map[artifact.task_id]
        self.execution_artifacts.append(artifact)
        if task.task_type == "leaf":
            self.completed_leaf_task_ids.append(task.id)
        accumulate_execution_artifact(
            artifact,
            self.artifact_materials,
            self.artifact_index,
        )

    def record_task_report(self, report: TaskReport) -> None:
        self.reports[report.task_id] = report
        self.pending_task_ids.remove(report.task_id)

    def execution_result(self) -> ExecutionResult:
        return ExecutionResult(
            completed_leaf_task_ids=list(self.completed_leaf_task_ids),
            artifacts=list(self.execution_artifacts),
        )

    def _dependencies_completed(self, task_id: str) -> bool:
        task = self.task_map[task_id]
        return all(dep_id in self.reports for dep_id in task.deps)
