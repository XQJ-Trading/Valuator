from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from .query import QueryAnalysis, QueryIntent


@dataclass(slots=True)
class RubricAspect:
    id: str
    label: str
    description: str
    priority: str = "medium"


class AcceptanceCheck(BaseModel):
    """Minimal contract check for module outputs."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    requires: list[str] = Field(default_factory=list)


class DomainModule(BaseModel):
    """Single domain module definition loaded from YAML."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    persona: str = ""
    rubric: list[RubricAspect] = Field(default_factory=list)
    format_spec: str = ""
    contract: list[AcceptanceCheck] = Field(default_factory=list)
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
