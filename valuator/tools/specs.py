from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping

from ..domain.query import QueryIntent

class SubjectIdentityLevel(str, Enum):
    NAME = "name"
    CANONICAL = "canonical"
    VENDOR_SYMBOL = "vendor_symbol"


@dataclass(frozen=True)
class SubjectRequirement:
    identity_level: SubjectIdentityLevel | None = None
    market: str = ""

    def accepts(self, intent: QueryIntent) -> bool:
        company = intent.company
        if company is None:
            return self.identity_level is None
        if self.market and company.legacy_market != self.market:
            return False
        if self.identity_level is None:
            return True
        if self.identity_level is SubjectIdentityLevel.NAME:
            return bool(company.issuer_name)
        if self.identity_level is SubjectIdentityLevel.CANONICAL:
            return True
        return bool(company.yahoo_symbol)


@dataclass(frozen=True)
class ToolExecutionContext:
    intent: QueryIntent
    reference_year: int
    query: str
    unit_query: str

    def values(self) -> dict[str, Any]:
        company = self.intent.company
        ticker = ""
        security_code = ""
        company_name = ""
        if company is not None:
            ticker = company.yahoo_symbol
            security_code = company.security_code
            company_name = company.issuer_name
        query_text = self.unit_query.strip() or self.query.strip()
        return {
            "ticker": ticker,
            "security_code": security_code,
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
        values = context.values()
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
        capability="current news/facts/sources",
    ),
    "sec_tool": ToolSpec(
        name="sec_tool",
        required=("ticker", "year", "query"),
        capability="10-K filings and disclosures",
        subject_requirement=SubjectRequirement(
            identity_level=SubjectIdentityLevel.CANONICAL,
            market="USA",
        ),
    ),
    "yfinance_balance_sheet": ToolSpec(
        name="yfinance_balance_sheet",
        required=("ticker",),
        optional=("year",),
        capability=(
            "financial statements plus valuation/pricing coordinates "
            "(market_cap, price, PE, PBR)"
        ),
        subject_requirement=SubjectRequirement(
            identity_level=SubjectIdentityLevel.VENDOR_SYMBOL
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
        subject_requirement=SubjectRequirement(identity_level=SubjectIdentityLevel.NAME),
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
