"""Web search tool for AI Agent."""

from __future__ import annotations

import asyncio
from typing import Any

from ..utils.config import config
from ..utils.llm_usage import TokenUsage
from ..utils.logger import logger
from ..utils.time_utils import Measurement
from .base import ReActBaseTool, ToolResult
from .web_search_providers import SearchIntent, WebSearchProvider

RAG_SOURCE_POLICY_MARKER = "[valuator_rag_source_policy]"
_RAG_BROKER_EXCLUSION_TAIL = (
    f"\n\n{RAG_SOURCE_POLICY_MARKER} "
    "Exclude sell-side/broker equity research unless the user explicitly asks for it; "
)
_VALID_INTENTS = {"general", "deep", "financial"}


def _effective_search_query_for_rag(raw: str) -> str:
    """웹 검색 API에 넘길 문자열. 브로커 리서치 제외는 도구 경계에서 한 번만 붙인다."""
    query = raw.strip()
    if not config.web_search_rag_exclude_broker_research:
        return query
    if RAG_SOURCE_POLICY_MARKER in query:
        return query
    return query + _RAG_BROKER_EXCLUSION_TAIL


class WebSearchTool(ReActBaseTool):
    def __init__(self, provider: WebSearchProvider, usage_writer: Any | None = None):
        super().__init__(
            name="web_search_tool",
            description=(
                "Search the web for current information. "
                "Provides real-time web results with citations."
            ),
        )
        self.provider = provider
        self.usage_writer = usage_writer
        self.available = provider.available

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        self.usage_writer = usage_writer

    async def execute(
        self,
        query: str | None = None,
        queries: list[str] | None = None,
        search_intent: str | None = None,
        **kwargs,
    ) -> ToolResult:
        del kwargs
        intent = (search_intent or "general").strip().lower()
        if intent not in _VALID_INTENTS:
            return ToolResult(
                success=False,
                result=None,
                error=(
                    "search_intent must be one of: " + ", ".join(sorted(_VALID_INTENTS))
                ),
            )
        if queries is not None:
            if not queries:
                return ToolResult(
                    success=False,
                    result=None,
                    error="queries must be a non-empty list",
                )
            if any(not isinstance(item, str) or not item.strip() for item in queries):
                return ToolResult(
                    success=False,
                    result=None,
                    error="queries must be non-empty strings",
                )
            return await self._execute_batch_search(queries, intent=intent)
        if not isinstance(query, str) or not query.strip():
            return ToolResult(
                success=False,
                result=None,
                error="query or queries is required",
            )
        return await self._execute_single_search(query, intent=intent)

    async def _execute_single_search(
        self,
        query: str,
        *,
        intent: SearchIntent,
    ) -> ToolResult:
        if not self.available:
            return ToolResult(
                success=False,
                result=None,
                error=f"{self.provider.name} provider not available.",
            )

        max_retries = max(int(config.web_search_retry_count), 0)
        base_delay = float(config.web_search_retry_base_delay)
        effective_query = _effective_search_query_for_rag(query)

        for attempt in range(max_retries + 1):
            measurement = Measurement.start()
            try:
                logger.info(
                    "Searching with %s: %s (intent=%s)",
                    self.provider.name,
                    effective_query,
                    intent,
                )
                result = await self.provider.search(effective_query, intent=intent)
                latency_seconds = measurement.latency_seconds()
                if self.usage_writer is not None:
                    self.usage_writer.append_call(
                        method="web_search_tool._execute_single_search",
                        model=self.provider.model_name,
                        usage=TokenUsage.from_raw(result.usage_meta),
                        latency_seconds=latency_seconds,
                        started_at=measurement.started_at,
                    )
                return ToolResult(
                    success=True,
                    result={
                        "query": query,
                        "findings": result.answer,
                        "sources": result.sources,
                    },
                    metadata={
                        "search_type": f"{self.provider.name}_web",
                        "model": self.provider.model_name,
                        "search_intent": intent,
                        "usage": result.usage_meta,
                        "effective_query": effective_query,
                    },
                )
            except Exception as exc:
                latency_seconds = measurement.latency_seconds()
                if attempt < max_retries:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        "%s search attempt %s failed (%s), retrying in %ss",
                        self.provider.name,
                        attempt + 1,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                if self.usage_writer is not None:
                    self.usage_writer.append_call(
                        method="web_search_tool._execute_single_search.error",
                        model=self.provider.model_name,
                        usage=TokenUsage(),
                        latency_seconds=latency_seconds,
                        started_at=measurement.started_at,
                    )
                logger.error("%s search failed: %s", self.provider.name, exc)
                return ToolResult(
                    success=False,
                    result=None,
                    error=f"Search failed: {exc}",
                )

    async def _execute_batch_search(
        self,
        queries: list[str],
        *,
        intent: SearchIntent,
    ) -> ToolResult:
        if not self.available:
            return ToolResult(
                success=False,
                result=None,
                error=f"{self.provider.name} provider not available.",
            )
        results = await asyncio.gather(
            *(self._execute_single_search(query, intent=intent) for query in queries)
        )
        if any(not result.success for result in results):
            return ToolResult(
                success=False,
                result=[result.model_dump() for result in results],
                error="One or more searches failed",
            )
        findings_parts = [
            result.result["findings"].strip()
            for result in results
            if result.result["findings"].strip()
        ]
        findings_text = "\n\n".join(findings_parts)
        if not findings_text:
            findings_text = f"batch search completed: {len(results)} queries"
        return ToolResult(
            success=True,
            result={
                "findings": findings_text,
                "results": [result.model_dump() for result in results],
            },
            metadata={
                "search_type": f"{self.provider.name}_web_batch",
                "count": len(results),
                "search_intent": intent,
            },
        )
