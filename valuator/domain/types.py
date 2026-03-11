from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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


class DcfSummary(BaseModel):
    """IR extracted from a DCF calculation result."""

    model_config = ConfigDict(extra="forbid")

    enterprise_value: float
    pv_explicit: float
    terminal_value: float
    terminal_pv: float
    scenarios: dict[str, Any] = Field(default_factory=dict)
    sensitivity: dict[str, Any] = Field(default_factory=dict)
    most_impactful_variable: str = ""


class CeoSummary(BaseModel):
    """IR for CEO & leadership analysis."""

    model_config = ConfigDict(extra="forbid")

    rating: str = Field(default="")
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    capital_allocation_style: str = Field(default="")
    culture_themes: list[str] = Field(default_factory=list)


class RiskTransmissionItem(BaseModel):
    """Single risk -> transmission -> impact row."""

    model_config = ConfigDict(extra="forbid")

    factor: str = Field(min_length=1)
    path: str = Field(min_length=1)
    impact: str = Field(min_length=1)
    trigger: str = Field(min_length=1)


class RiskTransmissionSummary(BaseModel):
    """IR for risk transmission across P&L/FCF."""

    model_config = ConfigDict(extra="forbid")

    items: list[RiskTransmissionItem] = Field(default_factory=list)


class BalanceSheetComponent(BaseModel):
    """Single balance-sheet line item."""

    model_config = ConfigDict(extra="forbid")

    item: str = Field(min_length=1)
    value: str = Field(min_length=1)


class BalanceSheetSection(BaseModel):
    """Assets / Liabilities / Equity section."""

    model_config = ConfigDict(extra="forbid")

    total: str = Field(default="N/A")
    components: list[BalanceSheetComponent] = Field(default_factory=list)


class BalanceSheetSummary(BaseModel):
    """Normalized balance-sheet snapshot for reporting."""

    model_config = ConfigDict(extra="forbid")

    assets: BalanceSheetSection
    liabilities: BalanceSheetSection
    equity: BalanceSheetSection
    units: str = Field(default="")
    as_of: str | None = None
