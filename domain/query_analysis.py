"""LLM-based query analysis into canonical QueryAnalysis."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Iterable

from valuator.utils.config import config

from .boundary.query_analysis_payload import (
    _build_query_analysis,
    _response_schema,
)
from .boundary import enrich_krx_subjects
from .company import ListingSeed
from .query import QueryAnalysis

if TYPE_CHECKING:
    from valuator.models.gemini_direct import GeminiClient

_SYSTEM_PROMPT = (
    "Return concise JSON only. No markdown. "
    "Do not include any keys except the requested schema."
)

_VALUATION_SCOPE = (
    "이 시스템은 밸류에이션·투자 분석을 위한 것이다.\n"
    "사용자 쿼리가 기업 분석, 밸류에이션, 투자 판단과 관련되면 그에 맞게 단계와 요구사항을 구성한다."
)
_EXCLUSION_SIGNALS = (
    "다음은 적용 예외에 가까운 요청: 뉴스 요약만, 특정 주가 시세만, 일반 QA(투자 무관)."
)
_SELECTIVE_SIGNALS = "특정 분석 초점만 요청된 경우 해당 초점을 반영한다."

_QUERY_ANALYSIS_RULES = (
    "- Return query_intent, entities, units, requirements, intent_tags, rationale.",
    "- query_intent must contain company_names, tickers, peer_company_names, peer_tickers. company_names/tickers hold the PRIMARY analysis subjects (the issuers the user is actually asking about). peer_company_names/peer_tickers hold COMPARABLE companies used as a relative-valuation benchmark (industry peers, direct competitors). Both groups follow the same naming/identifier rules: for Korean-listed companies, use the Korean company name (for example, '삼성전자') and the 6-digit stock_code (for example, '005930'); for overseas issuers, use the official English company name and the exchange ticker (for example, 'NOW' for ServiceNow). Always populate the ticker side when the company is identifiable. Do not invent Yahoo suffixes such as '.KS' or '.KQ' here. If a peer is also a primary subject, list it only under primary. If no concrete subject is named, use empty arrays.",
    "- entities are strictly for non-company items such as business units, products, CEOs, themes, or macro variables. Do not place issuers/securities in entities — primary subjects belong in company_names/tickers and peers belong in peer_company_names/peer_tickers.",
    "- units must be semantic retrieval units, not formatting instructions.",
    "- Every unit must include id, objective, retrieval_query, entity_ids, time_scope.",
    "- For reported financial data, filings, segment revenue/mix, order backlog, current price, EPS, PER/PBR/EV multiples, margins, and other disclosure-derived quantitative facts, downstream tasks must use opendart_financial_tool for Korean issuers and yfinance_balance_sheet for non-Korean issuers. Do not use web_search_tool for those units.",
    "- Use web_search_tool only for units whose evidence can validly come from general web sources: news, qualitative events, policy/regulatory context, product/project status, peer discovery, and other non-reported facts.",
    "- Every requirement must include acceptance, unit_ids, entity_ids, provenance. Requirements are for analytical content only, not formatting preferences or table styles.",
    "- requirement unit_ids may refer to units by zero-based position, one-based position, or each unit's id string (must match exactly; prefer copying ids from the units list).",
    "- If the query contains a markdown outline (headings like '# ...', '## ...', '### N) ...', or bullet lists), every leaf-level item (deepest heading or bullet) MUST become a requirement. Do not merge multiple leaves into one requirement unless they are truly inseparable; when you do merge, every merged leaf's text MUST appear verbatim in the acceptance field.",
    "- The outline is the user's execution contract. You MAY ADD requirements beyond the outline (e.g., as-of date precision, peer baseline, cross-cutting checks) but MUST NOT drop, summarize away, or abstract any outline leaf.",
    "- Preserve the user's response intent and constraints, such as recommendation, screening, comparison, requested market, count, style lens, and actionability, instead of rewriting the query into a generic valuation essay.",
    "- If the query does not name a concrete company/security, do not invent placeholder company entities such as 'investment candidates'.",
    "- If the query is valuation/investment-related, prefer comprehensive analysis rather than omitting needed aspects.",
    "- For valuation or investment-related queries, shape requirements so the downstream report can be trading- and investment-first: include acceptance criteria that imply decision framing, market price vs thesis where data allows, relative multiples (vs peers or history), bull/base/bear (or equivalent) scenarios, and quantitative entry/exit or re-evaluation triggers. Do not emit a DCF-only or intrinsic-value-only requirement set unless the user explicitly restricts the task to DCF or intrinsic value alone.",
    "- When a requirement calls for intrinsic value or DCF, add complementary requirements for relative multiples and scenario differentiation unless the user explicitly forbids one of them.",
)


def _analysis_prompt(*, query: str) -> str:
    rules = "\n".join(_QUERY_ANALYSIS_RULES)
    return (
        "Analyze the user query into a canonical specification for downstream agent steps "
        "(evidence gathering, valuation, and trading/investment synthesis).\n\n"
        "[VALUATION_SCOPE]\n"
        f"{_VALUATION_SCOPE}\n\n"
        "[EXCLUSION_SIGNALS]\n"
        f"{_EXCLUSION_SIGNALS}\n\n"
        "[SELECTIVE_SIGNALS]\n"
        f"{_SELECTIVE_SIGNALS}\n\n"
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
        as_of_kst: str = "",
    ) -> QueryAnalysis:
        payload = await self.client.generate_json(
            prompt=_analysis_prompt(query=query),
            system_prompt=_SYSTEM_PROMPT,
            response_json_schema=_response_schema(),
            trace_method="query_analysis.analyze",
        )
        analysis = _build_query_analysis(
            payload,
            query=query,
            on_miss=self._on_miss,
            as_of_kst=as_of_kst,
        )
        analysis.query_intent.subjects = enrich_krx_subjects(
            analysis.query_intent.subjects,
        )
        return analysis
