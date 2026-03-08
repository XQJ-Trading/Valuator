from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from ..domain.query import QueryIntent


@dataclass(frozen=True)
class SubjectRequirement:
    any_of: tuple[str, ...] = ()
    market: str = ""

    def accepts(self, intent: QueryIntent) -> bool:
        if self.market and intent.market.strip().upper() != self.market:
            return False
        if not self.any_of:
            return True
        return any(
            _present(_subject_field(intent, field_name))
            for field_name in self.any_of
        )


@dataclass(frozen=True)
class ToolExecutionContext:
    intent: QueryIntent
    reference_year: int
    query: str
    unit_query: str

    def values(self) -> dict[str, Any]:
        company_name = self.intent.company_name.strip()
        query_text = self.unit_query.strip() or self.query.strip()
        return {
            "ticker": self.intent.ticker.strip(),
            "security_code": self.intent.security_code.strip(),
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


def _subject_field(intent: QueryIntent, field_name: str) -> Any:
    if field_name == "company_name":
        return intent.company_name
    return getattr(intent, field_name, "")


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


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
        subject_requirement=SubjectRequirement(any_of=("ticker",), market="USA"),
    ),
    "yfinance_balance_sheet": ToolSpec(
        name="yfinance_balance_sheet",
        required=("ticker",),
        optional=("year",),
        capability=(
            "financial statements plus valuation/pricing coordinates "
            "(market_cap, price, PE, PBR)"
        ),
        arg_sources={"ticker": ("ticker", "security_code")},
        subject_requirement=SubjectRequirement(any_of=("ticker", "security_code")),
    ),
    "code_execute_tool": ToolSpec(
        name="code_execute_tool",
        required=("code",),
        capability="deterministic calculations",
    ),
    "ceo_analysis_tool": ToolSpec(
        name="ceo_analysis_tool",
        optional=("corp", "company_name", "ticker", "query", "context"),
        capability="CEO & leadership analysis for long-term investors",
        subject_requirement=SubjectRequirement(
            any_of=("company_name", "ticker", "security_code")
        ),
    ),
    "dcf_pipeline_tool": ToolSpec(
        name="dcf_pipeline_tool",
        optional=("corp", "company_name", "ticker", "query", "context"),
        capability="end-to-end DCF valuation pipeline",
        subject_requirement=SubjectRequirement(
            any_of=("company_name", "ticker", "security_code")
        ),
    ),
    "balance_sheet_extraction_tool": ToolSpec(
        name="balance_sheet_extraction_tool",
        required=("summary",),
        capability="normalize balance-sheet summary text into structured JSON",
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
