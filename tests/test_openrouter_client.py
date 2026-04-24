from __future__ import annotations

from types import SimpleNamespace

import pytest

from valuator.models.openrouter import OpenRouterClient
from valuator.utils.llm_usage import TokenUsage


class _Writer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.logged_calls: list[dict[str, object]] = []

    def append_call(
        self,
        *,
        method: str,
        model: str,
        usage: TokenUsage,
        latency_seconds: float,
        started_at: str,
        cache_source: str | None = None,
        cache_storage_hours: float = 0.0,
    ) -> None:
        self.calls.append(
            {
                "method": method,
                "model": model,
                "usage": usage,
                "latency_seconds": latency_seconds,
                "started_at": started_at,
                "cache_source": cache_source,
                "cache_storage_hours": cache_storage_hours,
            }
        )

    def log_llm_call(self, **kwargs: object) -> None:
        self.logged_calls.append(kwargs)


class _Responses:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _response(text: object, *, usage: object = None) -> object:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=usage,
    )


@pytest.mark.asyncio
async def test_openrouter_generate_records_usage_and_text() -> None:
    writer = _Writer()
    completions = _Responses(
        [
            _response(
                '{"answer":"ok"}',
                usage=SimpleNamespace(
                    prompt_tokens=11,
                    completion_tokens=7,
                    total_tokens=18,
                ),
            )
        ]
    )
    client = OpenRouterClient(
        model="google/gemini-2.5-flash",
        api_key="test-key",
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        usage_writer=writer,
        retry_count=0,
    )

    text = await client.generate(
        prompt="return json",
        system_prompt="system",
        response_mime_type="application/json",
        response_json_schema={"type": "object"},
        trace_method="test.generate",
        max_output_tokens=256,
    )

    assert text == '{"answer":"ok"}'
    assert completions.calls[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "response",
            "strict": True,
            "schema": {"type": "object"},
        },
    }
    assert completions.calls[0]["max_tokens"] == 256
    assert writer.calls[0]["method"] == "test.generate"
    assert writer.calls[0]["usage"] == TokenUsage(
        prompt_tokens=11,
        completion_tokens=7,
        total_tokens=18,
    )
    assert writer.logged_calls[0]["response_text"] == '{"answer":"ok"}'


@pytest.mark.asyncio
async def test_openrouter_generate_raises_on_empty_response() -> None:
    client = OpenRouterClient(
        model="google/gemini-2.5-flash",
        api_key="test-key",
        client=SimpleNamespace(
            chat=SimpleNamespace(completions=_Responses([_response("   ")]))
        ),
        retry_count=0,
    )

    with pytest.raises(ValueError, match="Empty response from OpenRouter"):
        await client.generate(prompt="hello")


@pytest.mark.asyncio
async def test_openrouter_generate_json_recovers_embedded_object() -> None:
    client = OpenRouterClient(
        model="google/gemini-2.5-flash",
        api_key="test-key",
        client=SimpleNamespace(
            chat=SimpleNamespace(
                completions=_Responses([_response('```json\n{"answer":"ok"}\n```')])
            )
        ),
        retry_count=0,
    )

    payload = await client.generate_json(
        prompt="return json",
        response_json_schema={"type": "object"},
        trace_method="test.generate_json",
    )

    assert payload == {"answer": "ok"}


@pytest.mark.asyncio
async def test_openrouter_generate_json_rejects_oversized_payload() -> None:
    client = OpenRouterClient(
        model="google/gemini-2.5-flash",
        api_key="test-key",
        client=SimpleNamespace(
            chat=SimpleNamespace(completions=_Responses([_response('{"answer":"ok"}')]))
        ),
        retry_count=0,
    )

    with pytest.raises(ValueError, match="returned oversized JSON"):
        await client.generate_json(
            prompt="return json",
            response_json_schema={"type": "object"},
            trace_method="test.generate_json",
            max_response_chars=5,
        )
