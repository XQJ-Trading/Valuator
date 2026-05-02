from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _select_choice(value: Any, choices: tuple[str, ...]) -> str | None:
    if isinstance(value, str):
        selected = value.strip().lower()
        if selected in choices:
            return selected
        tokens = [
            token.strip().lower()
            for token in (
                value.replace(",", " ").replace("|", " ").replace("/", " ").split()
            )
            if token.strip()
        ]
    elif isinstance(value, (list, tuple, set)):
        tokens = [str(item).strip().lower() for item in value if str(item).strip()]
    else:
        return None
    if len(tokens) < 2:
        return None
    valid_tokens = [token for token in tokens if token in choices]
    if not valid_tokens:
        return None
    if "web" in valid_tokens and "web" in choices:
        return "web"
    return valid_tokens[0]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    capability: str = ""
    arg_choices: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    param_descriptions: Mapping[str, str] = field(default_factory=dict)
    param_properties: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    schema_extra_keys: tuple[str, ...] = ()
    llm_required: tuple[str, ...] | None = None

    def args_text(self) -> str:
        required = ", ".join(self._arg_label(key) for key in self.required)
        optional = ", ".join(
            self._arg_label(key, optional=True) for key in self.optional
        )
        if required and optional:
            return f"{required}, {optional}"
        return required or optional or "-"

    def _arg_label(self, key: str, *, optional: bool = False) -> str:
        label = f"{key}?" if optional else key
        choices = self.arg_choices.get(key)
        if choices:
            label += "{" + "|".join(choices) + "}"
        return label

    def to_llm_schema(self, description: str) -> dict[str, Any]:
        required = self.llm_required if self.llm_required is not None else self.required
        seen: set[str] = set()
        keys: list[str] = []
        for key in (*self.required, *self.optional, *self.schema_extra_keys):
            if key not in seen:
                seen.add(key)
                keys.append(key)
        properties: dict[str, Any] = {}
        for key in keys:
            prop: dict[str, Any] = dict(
                self.param_properties.get(key) or {"type": "string"}
            )
            desc = self.param_descriptions.get(key)
            if desc and "description" not in prop:
                prop["description"] = desc
            properties[key] = prop
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": list(required),
                },
            },
        }

    def validate_args(self, args: Mapping[str, Any]) -> dict[str, Any]:
        normalized = dict(args)
        missing = [key for key in self.required if key not in normalized]
        if missing:
            raise ValueError(f"missing required args for {self.name}: {missing}")
        for key, choices in self.arg_choices.items():
            if key not in normalized:
                continue
            value = normalized[key]
            selected = _select_choice(value, choices)
            if selected is None and isinstance(value, str):
                selected = value.strip().lower()
            if selected not in choices:
                allowed = ", ".join(choices)
                raise ValueError(
                    f"invalid arg for {self.name}: {key} must be one of: {allowed}; "
                    f"received={value!r}"
                )
            normalized[key] = selected
        return normalized


TOOL_SPECS: dict[str, ToolSpec] = {
    "web_search_tool": ToolSpec(
        name="web_search_tool",
        required=("query",),
        optional=("search_intent",),
        arg_choices={"search_intent": ("general", "deep")},
        capability="general/deep grounded search",
        llm_required=(),
        schema_extra_keys=("queries",),
        param_descriptions={
            "query": "Search query for current non-financial web information. Do not request financial statements, filings, segment revenue, order backlog, valuation multiples, prices, or other reported financial facts; use opendart_financial_tool or yfinance_balance_sheet for those.",
            "search_intent": "Provider-neutral web search intent",
            "queries": "Parallel non-financial search queries",
        },
        param_properties={
            "search_intent": {
                "type": "string",
                "enum": ["general", "deep"],
            },
            "queries": {"type": "array", "items": {"type": "string"}},
        },
    ),
    "sec_tool": ToolSpec(
        name="sec_tool",
        required=("ticker", "year", "query"),
        capability="year-specific 10-K extraction",
        param_descriptions={
            "query": "Focused retrieval query for 10-K content",
            "ticker": "Ticker symbol (e.g., AMZN, TSLA)",
            "year": "Target filing year",
        },
        param_properties={
            "year": {"type": "integer"},
        },
    ),
    "yfinance_balance_sheet": ToolSpec(
        name="yfinance_balance_sheet",
        required=("ticker", "start_year", "end_year"),
        capability=(
            "Multi-year financial statements plus valuation/pricing for the given "
            "[start_year, end_year] inclusive. Returns per-year rows: balance sheet, "
            "income, cashflow, derived ratios, market data. Call once per ticker for "
            "the full range; do not split by year."
        ),
        param_descriptions={
            "ticker": "Market ticker for the target listing. Use US tickers like 'AAPL' for US listings. For Korean listings use the market/vendor ticker understood by yfinance, not the OpenDART corp field.",
            "start_year": "First fiscal year to fetch (inclusive). Read from [TEMPORAL_CONTRACT].",
            "end_year": "Last fiscal year to fetch (inclusive). Read from [TEMPORAL_CONTRACT]. Equal to start_year for a single year.",
        },
        param_properties={
            "start_year": {"type": "integer"},
            "end_year": {"type": "integer"},
        },
    ),
    "opendart_financial_tool": ToolSpec(
        name="opendart_financial_tool",
        required=("corp", "start_year", "end_year"),
        optional=("fs_div",),
        capability=(
            "Korean company financial statements (BS/IS/CF) from DART filings, "
            "fetched for every year in [start_year, end_year] inclusive. Call once "
            "per company for the full range; do not split by year."
        ),
        param_descriptions={
            "corp": "Korean issuer only. Pass the Korean company name or the 6-digit KRX stock_code (e.g., '삼성전자', '005930'). Never pass a US ticker here.",
            "start_year": "First fiscal year to fetch (inclusive). Read from [TEMPORAL_CONTRACT].",
            "end_year": "Last fiscal year to fetch (inclusive). Read from [TEMPORAL_CONTRACT]. Equal to start_year for a single year.",
            "fs_div": "'CFS' (consolidated, default) or 'OFS' (separate)",
        },
        param_properties={
            "start_year": {"type": "integer"},
            "end_year": {"type": "integer"},
            "fs_div": {"type": "string", "enum": ["CFS", "OFS"]},
        },
    ),
    "code_execute_tool": ToolSpec(
        name="code_execute_tool",
        required=("code",),
        optional=("timeout",),
        capability="deterministic calculations",
        param_descriptions={
            "code": "Python code to execute",
            "timeout": "Execution timeout in seconds",
        },
        param_properties={
            "timeout": {"type": "integer"},
        },
    ),
}


def get_tool_spec(tool_name: str) -> ToolSpec:
    try:
        return TOOL_SPECS[tool_name]
    except KeyError as exc:
        raise RuntimeError(f"unknown tool spec: {tool_name}") from exc
