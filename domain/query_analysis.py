"""LLM-based query analysis for domain module selection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Iterable

from valuator.utils.config import config

from .boundary.query_analysis_payload import (
    QueryAnalysisPayload,
    QueryEntityPayload,
    QueryIntentPayload,
    QueryRequirementPayload,
    QueryUnitPayload,
    _build_query_analysis,
    _company_surfaces_fully_resolved,
    _merge_ticker_enrichment_payload,
    _response_schema,
)
from .company import ListingSeed
from .query import QueryAnalysis
from .types import DomainIndex, DomainModule

if TYPE_CHECKING:
    from valuator.models.gemini_direct import GeminiClient

_SYSTEM_PROMPT = (
    "Return concise JSON only. No markdown. "
    "Do not include any keys except the requested schema."
)
_QUERY_ANALYSIS_RULES = (
    "- Return query_intent, domain_ids, entities, units, requirements, intent_tags, rationale.",
    "- query_intent must contain company_names and tickers. company_names: concrete company/security names or aliases. For Korean-listed companies, use the Korean name as commonly known (for example, '삼성전자', '현대모비스'). For overseas issuers, use the official English company name. tickers: stock ticker symbols for every company mentioned (for example, 'NOW' for ServiceNow, '005930' for 삼성전자). Always populate tickers when the company is identifiable. If no concrete subject is named, use empty arrays for both.",
    "- entities are for non-security items such as business units, products, CEOs, themes, or macro variables. Use entity kind `company`/`ticker`/`security` only for concrete issuers or securities explicitly present or clearly recoverable.",
    "- units must be semantic retrieval units, not formatting instructions.",
    "- Every unit must include id, objective, retrieval_query, domain_ids, entity_ids, time_scope.",
    "- Every requirement must include acceptance, unit_ids, entity_ids, provenance. Requirements are for analytical content only, not formatting preferences or table styles.",
    "- requirement unit_ids may refer to units by zero-based position, one-based position, or unit id string.",
    "- Preserve the user's response intent and constraints, such as recommendation, screening, comparison, requested market, count, style lens, and actionability, instead of rewriting the query into a generic valuation essay.",
    "- If the query does not name a concrete company/security, do not invent placeholder company entities such as 'investment candidates'.",
    "- If the query is valuation/investment-related, prefer selecting all relevant modules rather than omitting needed domains.",
    "- For valuation or investment-related queries, shape requirements so the downstream report can be trading- and investment-first: include acceptance criteria that imply decision framing, market price vs thesis where data allows, relative multiples (vs peers or history), bull/base/bear (or equivalent) scenarios, and quantitative entry/exit or re-evaluation triggers. Do not emit a DCF-only or intrinsic-value-only requirement set unless the user explicitly restricts the task to DCF or intrinsic value alone.",
    "- When a requirement calls for intrinsic value or DCF, add complementary requirements for relative multiples and scenario differentiation unless the user explicitly forbids one of them.",
)


def _module_summaries(
    index: DomainIndex,
    modules: dict[str, DomainModule],
) -> dict[str, str]:
    summaries = dict(index.module_summaries)
    for module_id in index.modules:
        if module_id in summaries or module_id not in modules:
            continue
        summaries[module_id] = modules[module_id].description or module_id
    return summaries


def _analysis_prompt(
    *,
    index: DomainIndex,
    modules: dict[str, DomainModule],
    query: str,
) -> str:
    scope = (
        index.valuation_scope.strip()
        or "Apply all modules for valuation-related queries."
    )
    exclusion = index.exclusion_signals.strip() or "None."
    selective = index.selective_signals.strip() or "None."
    summaries = _module_summaries(index, modules)
    module_lines = "\n".join(
        f"  - {module_id}: {summaries.get(module_id, module_id)}"
        for module_id in index.modules
    )
    rules = "\n".join(_QUERY_ANALYSIS_RULES)
    return (
        "Analyze the user query into a canonical specification for downstream agent steps "
        "(evidence gathering, valuation, and trading/investment synthesis).\n\n"
        "[VALUATION_SCOPE]\n"
        f"{scope}\n\n"
        "[EXCLUSION_SIGNALS]\n"
        f"{exclusion}\n\n"
        "[SELECTIVE_SIGNALS]\n"
        f"{selective}\n\n"
        "[AVAILABLE_MODULES]\n"
        f"{module_lines}\n\n"
        "Rules:\n"
        f"{rules}\n\n"
        f"[QUERY]\n{query}\n"
    )


class QueryAnalyzer:
    """Analyzes the raw user query into the canonical query spec."""

    def __init__(
        self,
        client: GeminiClient | None = None,
        on_miss: Callable[[str], Iterable[ListingSeed]] | None = None,
    ) -> None:
        if client is None:
            from valuator.models.gemini_direct import (
                GeminiClient as RuntimeGeminiClient,
            )

            client = RuntimeGeminiClient(config.agent_model)
        self.client = client
        self._on_miss = on_miss

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        self.client.bind_usage_writer(usage_writer)

    async def analyze(
        self,
        *,
        query: str,
        index: DomainIndex,
        modules: dict[str, DomainModule],
        as_of_utc: str = "",
    ) -> QueryAnalysis:
        valid_ids = set(index.modules)
        if not valid_ids:
            raise ValueError("domain index must include at least one module")

        payload = await self.client.generate_json(
            prompt=_analysis_prompt(index=index, modules=modules, query=query),
            system_prompt=_SYSTEM_PROMPT,
            response_json_schema=_response_schema(list(index.modules)),
            trace_method="query_analysis.analyze",
        )
        return _build_query_analysis(
            payload,
            query=query,
            valid_domain_ids=valid_ids,
            on_miss=self._on_miss,
            as_of_utc=as_of_utc,
        )
