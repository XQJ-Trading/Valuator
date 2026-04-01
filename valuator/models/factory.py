from __future__ import annotations

from typing import Any

from valuator.models.naming import is_openrouter_model_name

from ..utils.config import config, resolve_llm_model_name
from .protocol import LlmClient


def create_llm_client(
    model: str | None = None,
    usage_writer: Any | None = None,
) -> LlmClient:
    openrouter_enabled = config.llm_backend == "openrouter" and bool(
        config.openrouter_api_key
    )
    resolved_model = resolve_llm_model_name(
        (model or config.agent_model).strip(),
        openrouter_backend=openrouter_enabled,
    )
    if not openrouter_enabled and is_openrouter_model_name(resolved_model):
        resolved_model = config.agent_model

    if openrouter_enabled:
        from .openrouter import OpenRouterClient

        return OpenRouterClient(
            model=resolved_model,
            usage_writer=usage_writer,
        )

    from .gemini_direct import GeminiClient

    return GeminiClient(
        model=resolved_model,
        usage_writer=usage_writer,
    )
