from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .requirement import PlanContract

TaskType = Literal["leaf", "merge"]


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    task_type: TaskType = "leaf"
    query_unit_ids: list[int] = Field(default_factory=list)
    deps: list[str] = Field(default_factory=list)
    tool: ToolCall | None = None
    output: str = ""
    description: str = ""
    merge_instruction: str = ""


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    query_units: list[str] = Field(default_factory=list)
    contract: PlanContract | None = None
    root_task_id: str | None = None
    tasks: list[Task] = Field(default_factory=list)
