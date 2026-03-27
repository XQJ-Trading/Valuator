from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping

from domain.company import Company, Listing, Subject, representative_listing
from domain.query import QueryIntent


class SubjectIdentityLevel(str, Enum):
    COMPANY = "company"
    LISTING = "listing"


@dataclass(frozen=True)
class SubjectRequirement:
    identity_level: SubjectIdentityLevel | None = None
    market: str = ""

    def accepts(self, intent: QueryIntent) -> bool:
        return (
            project_subject_for_tool(
                subjects=intent.subjects,
                requirement=self,
            )
            is not None
        )


@dataclass(frozen=True)
class SubjectProjection:
    company: Company | None = None
    listing: Listing | None = None

    @property
    def company_name(self) -> str:
        if self.company is None:
            return ""
        return self.company.company_name

    @property
    def security_code(self) -> str:
        if self.listing is None:
            return ""
        return self.listing.security_code

    @property
    def ticker(self) -> str:
        if self.listing is None:
            return ""
        return self.listing.yahoo_symbol

    @property
    def market(self) -> str:
        if self.listing is None:
            return ""
        return self.listing.legacy_market


def project_subject_for_tool(
    *,
    subjects: tuple[Subject, ...],
    requirement: SubjectRequirement,
) -> SubjectProjection | None:
    if not subjects:
        if requirement.identity_level is None:
            return SubjectProjection()
        return None

    if len(subjects) != 1:
        if requirement.identity_level is None:
            return SubjectProjection()
        return None

    subject = subjects[0]
    projection = SubjectProjection(
        company=subject.company,
        listing=representative_listing(subject),
    )
    if requirement.market and projection.market != requirement.market:
        return None
    if (
        requirement.identity_level is SubjectIdentityLevel.LISTING
        and projection.listing is None
    ):
        return None
    return projection


@dataclass(frozen=True)
class ToolExecutionContext:
    intent: QueryIntent
    reference_year: int
    query: str
    unit_query: str

    def values(self, projection: SubjectProjection) -> dict[str, Any]:
        query_text = self.unit_query.strip() or self.query.strip()
        company_name = projection.company_name
        return {
            "ticker": projection.ticker,
            "security_code": projection.security_code,
            "company_name": company_name,
            "corp": company_name,
            "year": self.reference_year,
            "query": query_text,
            "context": query_text,
            "summary": query_text,
            "code": "# placeholder",
        }


@dataclass(frozen=True)
class ToolSpec:
    name: str
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    capability: str = ""
    arg_sources: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    subject_requirement: SubjectRequirement = field(default_factory=SubjectRequirement)

    def args_text(self) -> str:
        required = ", ".join(self.required)
        optional = ", ".join(f"{key}?" for key in self.optional)
        if required and optional:
            return f"{required}, {optional}"
        return required or optional or "-"

    def accepts(self, intent: QueryIntent) -> bool:
        return self.subject_requirement.accepts(intent)

    def build_args(self, context: ToolExecutionContext) -> dict[str, Any]:
        projection = project_subject_for_tool(
            subjects=context.intent.subjects,
            requirement=self.subject_requirement,
        )
        if projection is None:
            raise ValueError(f"subject requirement not satisfied for {self.name}")
        values = context.values(projection)
        args: dict[str, Any] = {}
        for key in (*self.required, *self.optional):
            sources = self.arg_sources.get(key, (key,))
            for source in sources:
                value = values.get(source)
                if not _present(value):
                    continue
                args[key] = value
                break
        missing = [key for key in self.required if key not in args]
        if missing:
            raise ValueError(f"missing required args for {self.name}: {missing}")
        return args


def _present(value: Any) -> bool:
    if value is None:
        return False
    return value != ""


TOOL_SPECS: dict[str, ToolSpec] = {
    "web_search_tool": ToolSpec(
        name="web_search_tool",
        required=("query",),
        optional=("search_mode",),
        capability="web/academic/sec grounded search",
    ),
    "sec_tool": ToolSpec(
        name="sec_tool",
        required=("ticker", "year", "query"),
        capability="year-specific 10-K extraction",
        subject_requirement=SubjectRequirement(
            identity_level=SubjectIdentityLevel.LISTING,
            market="USA",
        ),
    ),
    "yfinance_balance_sheet": ToolSpec(
        name="yfinance_balance_sheet",
        required=("ticker",),
        optional=("year",),
        capability=(
            "Single-year financial statements plus valuation/pricing. "
            "Call once per year for multi-year trend analysis. "
            "Returns: balance sheet, income, cashflow, derived ratios, market data."
        ),
        subject_requirement=SubjectRequirement(
            identity_level=SubjectIdentityLevel.LISTING
        ),
    ),
    "code_execute_tool": ToolSpec(
        name="code_execute_tool",
        required=("code",),
        capability="deterministic calculations",
    ),
    "domain_tool": ToolSpec(
        name="domain_tool",
        optional=(
            "corp",
            "company_name",
            "ticker",
            "query",
            "context",
            "domain_guide",
            "domain_persona",
            "domain_rubric",
            "domain_format",
            "domain_id",
        ),
        capability="aspect-guided domain analysis via persona/rubric/format",
    ),
}


def get_tool_spec(tool_name: str) -> ToolSpec:
    try:
        return TOOL_SPECS[tool_name]
    except KeyError as exc:
        raise RuntimeError(f"unknown tool spec: {tool_name}") from exc


def filter_tool_names(
    tool_names: Iterable[str],
    *,
    intent: QueryIntent,
) -> list[str]:
    return sorted(
        name
        for name in tool_names
        if name in TOOL_SPECS and TOOL_SPECS[name].accepts(intent)
    )


def registered_tool_names() -> list[str]:
    return sorted(TOOL_SPECS)
