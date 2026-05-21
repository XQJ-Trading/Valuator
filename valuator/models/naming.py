from __future__ import annotations

# Boundary: only for LLM_BACKEND=google_genai — legacy names in .env/payloads → stable GenAI ids.
# OpenRouter (including openrouter/auto) passes strings through unchanged; no alias table.
MODEL_ALIASES: dict[str, str] = {
    "gemini-2.5-flash": "gemini-3-flash-preview",
    "gemini-2.5-pro": "gemini-3-pro-preview",
    "google/gemini-3-flash-preview-20251217": "gemini-3-flash-preview",
}


def canonical_model_name(value: str) -> str:
    name = value.strip()
    return MODEL_ALIASES.get(name, name)


def is_openrouter_model_name(value: str) -> bool:
    """Wire-format vendor ids (provider/model). Invalid when LLM_BACKEND is google_genai."""
    return "/" in value.strip()
