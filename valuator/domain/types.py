from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .query import QueryAnalysis, QueryIntent


class DomainTool(BaseModel):
    """Tool configuration declared by a domain module."""

    model_config = ConfigDict(extra="allow")

    tool: str
    enabled: bool = True


class DomainReportRequirement(BaseModel):
    """Human-readable report requirement for a domain module."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)


class DomainTask(BaseModel):
    """Task definition within a domain module."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = ""


@dataclass(slots=True)
class StageOutput:
    """Pipeline stage result produced at the execution boundary."""

    raw: Any
    text: str


class PipelineStage(BaseModel):
    """Single pipeline.yaml stage declaration."""

    model_config = ConfigDict(extra="forbid")

    id: str
    action: Literal["llm", "llm_json", "code_execute"]
    user_prompt: str = ""
    system_prompt_content: str = ""
    output_schema_content: dict[str, Any] | None = None
    code_content: str = ""
    inject_vars: dict[str, str] = Field(default_factory=dict)
    output_key: str = ""


class PipelineConfig(BaseModel):
    """Parsed immutable pipeline declaration."""

    model_config = ConfigDict(extra="forbid")

    stages: list[PipelineStage]
    result_mapping: dict[str, str] = Field(default_factory=dict)


class IrFieldSpec(BaseModel):
    """Declarative projection rule for a single IR field."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    format: str = "{}"
    default: Any | None = None


class IrConfig(BaseModel):
    """Declarative IR extraction config for a domain module."""

    model_config = ConfigDict(extra="forbid")

    summary_path: str = ""
    key_values: dict[str, IrFieldSpec] = Field(default_factory=dict)
    payload_paths: dict[str, str] = Field(default_factory=dict)


class DomainModule(BaseModel):
    """Single domain module definition loaded from YAML."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    tools: list[str] = Field(default_factory=list)
    domain_tools: list[DomainTool] = Field(default_factory=list)
    tasks: list[DomainTask] = Field(default_factory=list)
    prompt_fragment: str = ""
    prompt_file: str | None = None
    pipeline_config: PipelineConfig | None = None
    ir_config: IrConfig | None = None
    report_contract: list[DomainReportRequirement] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class DomainIndex(BaseModel):
    """Top-level index for domain modules."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    modules: list[str] = Field(default_factory=list)
    default_behavior: str = "all"
    valuation_scope: str = ""
    exclusion_signals: str = ""
    selective_signals: str = ""
    module_summaries: dict[str, str] = Field(default_factory=dict)


@dataclass(slots=True)
class DomainModuleContext:
    """Runtime context: which modules are active for this session."""

    module_ids: list[str] = field(default_factory=list)
    modules: dict[str, DomainModule] = field(default_factory=dict)
    query_intent: QueryIntent | None = None
    query_analysis: QueryAnalysis | None = None
