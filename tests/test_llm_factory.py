from __future__ import annotations

from types import SimpleNamespace

import pytest

from valuator.models.factory import create_llm_client
from valuator.models.protocol import LlmClient


class _DummyGeminiClient:
    def __init__(self, *, model: str, usage_writer: object | None = None) -> None:
        self.model = model
        self.usage_writer = usage_writer

    def bind_usage_writer(self, usage_writer: object | None) -> None:
        self.usage_writer = usage_writer

    async def get_or_create_explicit_cache(
        self,
        *,
        cache_key: str,
        contents: object | None = None,
        system_prompt: str = "",
        ttl_seconds: int | None = None,
        display_name: str | None = None,
        trace_method: str = "llm.cache.create",
    ) -> str | None:
        del (
            cache_key,
            contents,
            system_prompt,
            ttl_seconds,
            display_name,
            trace_method,
        )
        return None

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        response_mime_type: str | None = None,
        response_json_schema: dict[str, object] | None = None,
        trace_method: str = "llm.generate",
        max_output_tokens: int | None = None,
        cached_content: str | None = None,
    ) -> str:
        del (
            prompt,
            system_prompt,
            response_mime_type,
            response_json_schema,
            trace_method,
            max_output_tokens,
            cached_content,
        )
        return "ok"

    async def generate_json(
        self,
        *,
        prompt: str,
        system_prompt: str = "",
        response_json_schema: dict[str, object],
        trace_method: str,
        max_response_chars: int | None = None,
        max_output_tokens: int | None = None,
        cached_content: str | None = None,
    ) -> dict[str, object]:
        del (
            prompt,
            system_prompt,
            response_json_schema,
            trace_method,
            max_response_chars,
            max_output_tokens,
            cached_content,
        )
        return {}


class _DummyOpenRouterClient(_DummyGeminiClient):
    pass


def test_create_llm_client_uses_gemini_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "valuator.models.factory.config",
        SimpleNamespace(
            agent_model="gemini-3-flash-preview",
            llm_backend="google_genai",
            openrouter_api_key=None,
        ),
    )
    monkeypatch.setattr(
        "valuator.models.gemini_direct.GeminiClient",
        _DummyGeminiClient,
    )

    client = create_llm_client(model="gemini-3-pro-preview")

    assert isinstance(client, _DummyGeminiClient)
    assert client.model == "gemini-3-pro-preview"


def test_create_llm_client_falls_back_from_openrouter_model_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "valuator.models.factory.config",
        SimpleNamespace(
            agent_model="gemini-3-flash-preview",
            llm_backend="google_genai",
            openrouter_api_key=None,
        ),
    )
    monkeypatch.setattr(
        "valuator.models.gemini_direct.GeminiClient",
        _DummyGeminiClient,
    )

    client = create_llm_client(model="google/gemini-2.5-flash")

    assert isinstance(client, _DummyGeminiClient)
    assert client.model == "gemini-3-flash-preview"


def test_create_llm_client_preserves_gemini_31_flash_model_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "valuator.models.factory.config",
        SimpleNamespace(
            agent_model="gemini-3-flash-preview",
            llm_backend="google_genai",
            openrouter_api_key=None,
        ),
    )
    monkeypatch.setattr(
        "valuator.models.gemini_direct.GeminiClient",
        _DummyGeminiClient,
    )

    client = create_llm_client(model="gemini-3.1-flash")

    assert isinstance(client, _DummyGeminiClient)
    assert client.model == "gemini-3.1-flash"


def test_create_llm_client_uses_openrouter_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "valuator.models.factory.config",
        SimpleNamespace(
            agent_model="google/gemini-2.5-flash",
            llm_backend="openrouter",
            openrouter_api_key="test-key",
        ),
    )
    monkeypatch.setattr(
        "valuator.models.openrouter.OpenRouterClient",
        _DummyOpenRouterClient,
    )

    client = create_llm_client(model="google/gemini-2.5-flash")

    assert isinstance(client, _DummyOpenRouterClient)
    assert client.model == "google/gemini-2.5-flash"


def test_create_llm_client_preserves_openrouter_vendor_model_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "valuator.models.factory.config",
        SimpleNamespace(
            agent_model="openrouter/auto",
            llm_backend="openrouter",
            openrouter_api_key="test-key",
        ),
    )
    monkeypatch.setattr(
        "valuator.models.openrouter.OpenRouterClient",
        _DummyOpenRouterClient,
    )

    client = create_llm_client(model="anthropic/claude-3.5-sonnet")

    assert isinstance(client, _DummyOpenRouterClient)
    assert client.model == "anthropic/claude-3.5-sonnet"


def test_llm_protocol_accepts_gemini_and_openrouter_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "valuator.models.gemini_direct.ensure_supported_google_genai_runtime",
        lambda: "test-runtime",
    )
    from valuator.models.gemini_direct import GeminiClient
    from valuator.models.openrouter import OpenRouterClient

    class _DummyModels:
        def generate_content(
            self, *, model: str, contents: str, config: object
        ) -> object:
            del model, contents, config
            return SimpleNamespace(text="ok", usage_metadata=None)

    gemini = GeminiClient(
        model="gemini-3-flash-preview",
        api_key="test-key",
        client=SimpleNamespace(models=_DummyModels()),
    )
    openrouter = OpenRouterClient(
        model="google/gemini-2.5-flash",
        api_key="test-key",
        client=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=None))
        ),
    )

    assert isinstance(gemini, LlmClient)
    assert isinstance(openrouter, LlmClient)
