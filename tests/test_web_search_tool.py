from __future__ import annotations

from types import SimpleNamespace

import pytest

from valuator.tools.web_search_tool import PerplexitySearchTool


class _Message:
    def __init__(self, content: str):
        self.content = content


class FakeChatPerplexity:
    instances: list["FakeChatPerplexity"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls: list[dict[str, object]] = []
        type(self).instances.append(self)

    async def ainvoke(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return SimpleNamespace(
            content="answer",
            response_metadata={},
            additional_kwargs={},
            usage_metadata={},
        )


@pytest.mark.asyncio
async def test_web_search_tool_passes_sec_search_mode(monkeypatch) -> None:
    from valuator.tools import web_search_tool as module

    FakeChatPerplexity.instances.clear()
    monkeypatch.setattr(module, "ChatPerplexity", FakeChatPerplexity)
    monkeypatch.setattr(module, "HumanMessage", _Message)
    monkeypatch.setattr(module, "SystemMessage", _Message)
    monkeypatch.setattr(
        module,
        "config",
        SimpleNamespace(
            perplexity_api_key="test-key",
            web_search_retry_count=2,
            web_search_retry_base_delay=2.0,
        ),
    )

    tool = PerplexitySearchTool()
    result = await tool.execute(query="latest Amazon filing", search_mode="sec")

    assert result.success is True
    assert result.metadata["search_mode"] == "sec"
    assert len(FakeChatPerplexity.instances) == 1
    assert FakeChatPerplexity.instances[0].calls[0]["kwargs"] == {
        "extra_body": {"web_search_options": {"search_mode": "sec"}}
    }
