from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from valuator.tools.web_search_providers import PerplexityProvider, TavilyProvider
from valuator.tools.web_search_tool import RAG_SOURCE_POLICY_MARKER, WebSearchTool


class _Message:
    def __init__(self, content: str):
        self.content = content


class _FakeChatPerplexity:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def ainvoke(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return SimpleNamespace(
            content="answer",
            response_metadata={},
            additional_kwargs={},
            usage_metadata={},
        )


class _FakeTavilyClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "answer": "answer",
            "results": [{"url": "https://example.com", "content": "content"}],
            "response_time": 0.5,
            "request_id": "req-1",
            "usage": {"credits": 2},
            "query": kwargs["query"],
        }


@pytest.mark.asyncio
async def test_perplexity_provider_maps_financial_intent_to_sec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_module = importlib.import_module("valuator.utils.config")
    from valuator.tools import web_search_providers as module

    chat = _FakeChatPerplexity()

    def fake_init_client(self, api_key: str):
        assert api_key == "test-key"
        self._HumanMessage = _Message
        self._SystemMessage = _Message
        return chat

    monkeypatch.setattr(
        config_module, "config", SimpleNamespace(perplexity_api_key="test-key")
    )
    monkeypatch.setattr(module.PerplexityProvider, "_init_client", fake_init_client)

    provider = PerplexityProvider()
    result = await provider.search("latest Amazon filing", intent="financial")

    assert provider.available is True
    assert result.answer == "answer"
    assert chat.calls[0]["kwargs"] == {
        "extra_body": {"web_search_options": {"search_mode": "sec"}}
    }


@pytest.mark.asyncio
async def test_tavily_provider_maps_deep_intent_to_advanced_general(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_module = importlib.import_module("valuator.utils.config")
    from valuator.tools import web_search_providers as module

    client = _FakeTavilyClient()
    monkeypatch.setattr(
        config_module, "config", SimpleNamespace(tavily_api_key="test-key")
    )
    monkeypatch.setattr(
        module.TavilyProvider, "_init_client", lambda self, api_key: client
    )

    provider = TavilyProvider()
    result = await provider.search("market share", intent="deep")

    assert provider.available is True
    assert result.sources == ["https://example.com"]
    assert result.usage_meta["provider"] == "tavily"
    assert client.calls[0]["topic"] == "general"
    assert client.calls[0]["search_depth"] == "advanced"
    assert client.calls[0]["chunks_per_source"] == 3
    assert client.calls[0]["time_range"] == "month"


@pytest.mark.asyncio
async def test_tavily_provider_truncates_duplicate_sources_heading_from_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_module = importlib.import_module("valuator.utils.config")
    from valuator.tools import web_search_providers as module

    class _Client:
        async def search(self, **kwargs):
            return {
                "answer": (
                    "본문입니다.\n\n## sources\n\n"
                    "- https://duplicate.example/from-prose"
                ),
                "results": [{"url": "https://structured.example", "content": "c"}],
            }

    monkeypatch.setattr(
        config_module, "config", SimpleNamespace(tavily_api_key="test-key")
    )
    monkeypatch.setattr(
        module.TavilyProvider, "_init_client", lambda self, api_key: _Client()
    )

    provider = TavilyProvider()
    result = await provider.search("q", intent="general")

    assert result.answer == "본문입니다."
    assert result.sources == ["https://structured.example"]


@pytest.mark.asyncio
async def test_tavily_provider_sorts_by_published_date_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_module = importlib.import_module("valuator.utils.config")
    from valuator.tools import web_search_providers as module

    class _Client:
        async def search(self, **kwargs):
            return {
                "answer": "",
                "results": [
                    {
                        "url": "https://older.example",
                        "content": "older",
                        "published_date": "2024-06-01",
                    },
                    {
                        "url": "https://newer.example",
                        "content": "newer",
                        "published_date": "2025-01-15",
                    },
                ],
            }

    monkeypatch.setattr(
        config_module, "config", SimpleNamespace(tavily_api_key="test-key")
    )
    monkeypatch.setattr(
        module.TavilyProvider, "_init_client", lambda self, api_key: _Client()
    )

    provider = TavilyProvider()
    result = await provider.search("q", intent="general")

    assert result.sources == ["https://newer.example", "https://older.example"]
    assert "newer" in result.answer and "older" in result.answer
    assert result.answer.index("newer") < result.answer.index("older")


@pytest.mark.asyncio
async def test_web_search_tool_appends_rag_source_policy_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from valuator.tools import web_search_tool as module

    calls: list[dict[str, object]] = []

    class FakeProvider:
        name = "fake"
        model_name = "fake-model"
        available = True

        async def search(self, query: str, *, intent: str):
            calls.append({"query": query, "intent": intent})
            return SimpleNamespace(
                answer="answer",
                sources=["https://example.com"],
                usage_meta={},
            )

    monkeypatch.setattr(
        module,
        "config",
        SimpleNamespace(
            web_search_retry_count=0,
            web_search_retry_base_delay=2.0,
            web_search_rag_exclude_broker_research=True,
        ),
    )

    tool = WebSearchTool(provider=FakeProvider())
    result = await tool.execute(query="Samsung revenue", search_intent="general")

    assert result.success is True
    assert result.metadata["search_intent"] == "general"
    assert result.result == {"query": "Samsung revenue", "findings": "answer"}
    assert result.metadata["sources"] == ["https://example.com"]
    assert RAG_SOURCE_POLICY_MARKER in calls[0]["query"]
    assert "sell-side" in calls[0]["query"].lower()


@pytest.mark.asyncio
async def test_web_search_tool_rejects_invalid_search_intent() -> None:
    class FakeProvider:
        name = "fake"
        model_name = "fake-model"
        available = True

        async def search(self, query: str, *, intent: str):
            return SimpleNamespace(answer=query, sources=[], usage_meta={})

    tool = WebSearchTool(provider=FakeProvider())
    result = await tool.execute(query="Samsung revenue", search_intent="unknown")

    assert result.success is False
    assert result.error == "search_intent must be one of: deep, financial, general"
