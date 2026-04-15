from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, runtime_checkable

from ..utils.logger import logger

SearchIntent = Literal["general", "deep", "financial"]


def _truncate_at_sources_markdown_heading(raw: str) -> str:
    # APIs often append a duplicate "## sources" block; URLs are carried in WebSearchResult.sources.
    current = raw.strip()
    while True:
        lines = current.splitlines()
        cut: int | None = None
        for i, line in enumerate(lines):
            if line.strip().lower() in ("## sources", "### sources"):
                cut = i
                break
        if cut is None:
            return current
        current = "\n".join(lines[:cut]).rstrip()


@dataclass(frozen=True)
class WebSearchResult:
    answer: str
    sources: list[str]
    usage_meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class WebSearchProvider(Protocol):
    name: str
    model_name: str
    available: bool

    async def search(self, query: str, *, intent: SearchIntent) -> WebSearchResult:
        ...


class _BaseProvider:
    name: str
    model_name: str
    _api_key_env: str
    available: bool = False

    def __init__(self) -> None:
        from ..utils.config import config

        try:
            api_key = getattr(config, self._api_key_env, None)
            if not api_key:
                raise ValueError(f"{self._api_key_env} not found in config")
            self._client = self._init_client(api_key)
            self.available = True
            logger.info("%s initialized", self.__class__.__name__)
        except Exception as exc:
            self._client = None
            self.available = False
            logger.warning("%s init failed: %s", self.__class__.__name__, exc)

    def _init_client(self, api_key: str) -> Any:
        raise NotImplementedError


class PerplexityProvider(_BaseProvider):
    name = "perplexity"
    model_name = "sonar"
    _api_key_env = "perplexity_api_key"
    _INTENT_TO_MODE: dict[SearchIntent, str] = {
        "general": "web",
        "deep": "academic",
        "financial": "sec",
    }

    def _init_client(self, api_key: str) -> Any:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_perplexity import ChatPerplexity

        self._HumanMessage = HumanMessage
        self._SystemMessage = SystemMessage
        return ChatPerplexity(model="sonar", temperature=0.1, pplx_api_key=api_key)

    async def search(self, query: str, *, intent: SearchIntent) -> WebSearchResult:
        response = await self._client.ainvoke(
            [
                self._SystemMessage(
                    content=(
                        "You are a comprehensive search assistant. "
                        "Provide detailed, accurate, and up-to-date information with sources. "
                        "Be thorough and analytical in your responses. "
                        "Write the full answer in Korean (한국어), including headings and explanations; "
                        "keep proper nouns, tickers, and direct quotes in their original form when needed."
                    )
                ),
                self._HumanMessage(content=query),
            ],
            extra_body={
                "web_search_options": {"search_mode": self._INTENT_TO_MODE[intent]}
            },
        )
        raw_answer = response.content
        if not isinstance(raw_answer, str):
            raw_answer = "" if raw_answer is None else str(raw_answer)
        meta = getattr(response, "response_metadata", {}) or {}
        extra = getattr(response, "additional_kwargs", {}) or {}
        usage_meta = getattr(response, "usage_metadata", {}) or {}
        if hasattr(usage_meta, "model_dump"):
            usage_meta = usage_meta.model_dump()
        if not isinstance(usage_meta, dict):
            usage_meta = {}
        usage = dict(usage_meta)
        usage["provider"] = self.name
        sources = (
            meta.get("citations")
            or meta.get("sources")
            or extra.get("citations")
            or extra.get("sources")
            or re.findall(r"https?://[^\s)]+", raw_answer)
            or [f"[{n}]" for n in sorted(set(re.findall(r"\[(\d+)\]", raw_answer)))]
        )
        answer = _truncate_at_sources_markdown_heading(raw_answer)
        return WebSearchResult(answer=answer, sources=sources, usage_meta=usage)


class TavilyProvider(_BaseProvider):
    name = "tavily"
    model_name = "tavily"
    _api_key_env = "tavily_api_key"
    _INTENT_TO_REQUEST: dict[SearchIntent, dict[str, Any]] = {
        "general": {"topic": "general", "search_depth": "basic"},
        "deep": {"topic": "general", "search_depth": "advanced"},
        "financial": {"topic": "finance", "search_depth": "advanced"},
    }
    _max_results = 5
    _include_answer: str | bool = "advanced"
    _include_usage = True
    _chunks_per_source = 3
    _timeout = 60.0
    _time_range: str | None = "month"
    _start_date: str | None = None
    _end_date: str | None = None
    _include_raw_content: bool | str | None = None
    _include_domains: tuple[str, ...] = ()
    _exclude_domains: tuple[str, ...] = ()
    _country: str | None = None

    def _init_client(self, api_key: str) -> Any:
        from tavily import AsyncTavilyClient

        return AsyncTavilyClient(api_key=api_key)

    async def search(self, query: str, *, intent: SearchIntent) -> WebSearchResult:
        request = {
            "query": query,
            **self._INTENT_TO_REQUEST[intent],
            "max_results": self._max_results,
            "include_answer": self._include_answer,
            "include_usage": self._include_usage,
            "timeout": self._timeout,
        }
        if request["search_depth"] == "advanced":
            request["chunks_per_source"] = self._chunks_per_source
        if self._time_range is not None:
            request["time_range"] = self._time_range
        if self._start_date is not None:
            request["start_date"] = self._start_date
        if self._end_date is not None:
            request["end_date"] = self._end_date
        if self._include_raw_content is not None:
            request["include_raw_content"] = self._include_raw_content
        if self._include_domains:
            request["include_domains"] = list(self._include_domains)
        if self._exclude_domains:
            request["exclude_domains"] = list(self._exclude_domains)
        if self._country is not None:
            request["country"] = self._country

        response = await self._client.search(**request)
        raw_results = response.get("results", [])
        results = self._sort_results_by_newest_first(
            [row for row in raw_results if isinstance(row, dict)]
        )
        answer = response.get("answer", "")
        if not answer:
            answer = "\n\n".join(
                row.get("content", "") for row in results if row.get("content")
            )
        if not isinstance(answer, str):
            answer = str(answer)
        sources = [row["url"] for row in results if row.get("url")]
        usage_meta: dict[str, Any] = {
            "provider": self.name,
            "request": {key: value for key, value in request.items() if key != "query"},
        }
        for key in ("response_time", "request_id", "usage", "query"):
            if key in response:
                usage_meta[key] = response[key]
        answer = _truncate_at_sources_markdown_heading(answer)
        return WebSearchResult(answer=answer, sources=sources, usage_meta=usage_meta)

    @staticmethod
    def _sort_results_by_newest_first(
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Tavily는 관련도 순으로만 돌려주므로, published_date가 있으면 최신순으로 재정렬한다."""
        if not results:
            return results
        if not any(row.get("published_date") for row in results):
            return results

        def _published_timestamp(row: dict[str, Any]) -> float:
            raw = row.get("published_date")
            if not isinstance(raw, str) or not raw.strip():
                return float("-inf")
            text = raw.strip().replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(text)
            except ValueError:
                return float("-inf")
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()

        return sorted(results, key=_published_timestamp, reverse=True)


_PROVIDER_TYPES = {
    "perplexity": PerplexityProvider,
    "tavily": TavilyProvider,
}


def create_web_search_provider(provider_name: str | None = None) -> WebSearchProvider:
    from ..utils.config import config

    selected = (provider_name or config.web_search_provider).strip().lower()
    try:
        provider_type = _PROVIDER_TYPES[selected]
    except KeyError as exc:
        raise ValueError(f"unsupported web search provider: {selected}") from exc
    return provider_type()


def available_web_search_providers() -> list[str]:
    available: list[str] = []
    for name, provider_type in _PROVIDER_TYPES.items():
        if provider_type().available:
            available.append(name)
    return available
