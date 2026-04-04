from __future__ import annotations

import pytest

from valuator.tools.domain_tool import DomainTool


class FakeGeminiClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def bind_usage_writer(self, _usage_writer: object | None) -> None:
        return None

    async def generate(
        self,
        *,
        prompt: str,
        system_prompt: str,
        trace_method: str,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "trace_method": trace_method,
            }
        )
        return "analysis"


@pytest.mark.asyncio
async def test_domain_tool_rejects_empty_context_in_grounded_mode() -> None:
    tool = DomainTool()
    tool.client = FakeGeminiClient()

    result = await tool.execute(
        query="current Iran situation",
        grounding_mode="grounded_required",
        context="",
    )

    assert result.success is False
    assert result.error == "grounded_required mode requires non-empty context"


@pytest.mark.asyncio
async def test_domain_tool_includes_temporal_contract_in_prompt() -> None:
    tool = DomainTool()
    fake_client = FakeGeminiClient()
    tool.client = fake_client

    result = await tool.execute(
        query="future Hormuz scenarios",
        grounding_mode="synthesis_only",
        as_of_utc="2026-03-30T00:00:00Z",
        time_scope="future",
        target_start="2026-04-01",
        target_end="2026-09-30",
        context="[GROUNDING_FACTS]\n- oil_price [grounded=True]: 80",
    )

    assert result.success is True
    assert result.metadata["grounding_mode"] == "synthesis_only"
    assert result.result["time_scope"] == "future"
    prompt = fake_client.calls[0]["prompt"]
    assert "[AS_OF_UTC]\n2026-03-30T00:00:00Z" in prompt
    assert "[GROUNDING_MODE]\nsynthesis_only" in prompt
    assert "[TARGET_PERIOD]\n2026-04-01..2026-09-30" in prompt
