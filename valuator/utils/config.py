from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from valuator.models.naming import canonical_model_name, is_openrouter_model_name

ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT_DIR / ".env"
DEFAULT_SESSION_FILES_ROOT = "logs/local"
DEFAULT_AGENT_MODEL = "gemini-3-flash-preview"
DEFAULT_GEMINI_THINKING_LEVEL = "low"
DEFAULT_LLM_BACKEND = "google_genai"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_CODE_EXECUTION_ALLOWED_IMPORTS = ("json",)
DEFAULT_OPENROUTER_AUTO_ALLOWED_MODELS = (
    "xiaomi/mimo-v2-pro",
    "minimax/minimax-m2.7",
    "deepseek/deepseek-v3.2",
    "moonshotai/kimi-k2.5",
)


def resolve_llm_model_name(value: str, *, openrouter_backend: bool) -> str:
    name = value.strip()
    if openrouter_backend:
        return name
    return canonical_model_name(name)


def _split_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _as_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    agent_model: str
    llm_backend: str
    gemini_thinking_level: str
    google_api_key: str | None
    openrouter_api_key: str | None
    openrouter_base_url: str
    openrouter_auto_allowed_models: tuple[str, ...]
    opendart_api_key: str | None
    perplexity_api_key: str | None
    supported_models: tuple[str, ...]
    log_level: str
    mongodb_enabled: bool
    mongodb_uri: str | None
    mongodb_database: str
    mongodb_collection: str
    domain_arch_enabled: bool
    event_layer_enabled: bool
    code_execution_timeout: int
    code_execution_allowed_imports: tuple[str, ...]
    agent_step_repair_retries: int
    agent_max_invalid_decisions_per_task: int
    agent_max_consecutive_tool_failures: int
    agent_max_steps_per_task: int
    agent_concurrency: int
    agent_llm_retry_count: int
    agent_llm_retry_base_delay: float
    web_search_retry_count: int
    web_search_retry_base_delay: float


def normalize_supported_models(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(canonical_model_name(item) for item in values if item.strip())
    )


@lru_cache(maxsize=1)
def load_project_env() -> None:
    load_dotenv(dotenv_path=ENV_FILE)


def read_env(name: str, default: str | None = None) -> str | None:
    load_project_env()
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip()


def session_files_root() -> Path:
    # Env selects deploy layout (e.g. logs/server_history); default is logs/local.
    load_project_env()
    raw = read_env("VALUATOR_SESSION_FILES_ROOT", DEFAULT_SESSION_FILES_ROOT)
    text = (raw or DEFAULT_SESSION_FILES_ROOT).strip() or DEFAULT_SESSION_FILES_ROOT
    path = Path(text)
    if path.is_absolute():
        return path.resolve()
    return (ROOT_DIR / path).resolve()


def get_env(name: str, *, required: bool = False) -> str:
    value = read_env(name, "")
    if value or not required:
        return value
    raise RuntimeError(f"{name} not set")


def get_opendart_api_key(*, required: bool = False) -> str:
    return get_env("OPENDART_API_KEY", required=required)


def load_config() -> Config:
    llm_backend = (
        (read_env("LLM_BACKEND", DEFAULT_LLM_BACKEND) or DEFAULT_LLM_BACKEND)
        .strip()
        .lower()
    )
    if llm_backend not in {"google_genai", "openrouter"}:
        raise ValueError("LLM_BACKEND must be one of: google_genai, openrouter")
    openrouter_api_key = read_env("OPENROUTER_API_KEY")
    openrouter_enabled = llm_backend == "openrouter" and bool(openrouter_api_key)

    raw_agent_model = (
        read_env("AGENT_MODEL", DEFAULT_AGENT_MODEL) or DEFAULT_AGENT_MODEL
    )
    requested_model = resolve_llm_model_name(
        raw_agent_model, openrouter_backend=openrouter_enabled
    )
    model = requested_model
    if not openrouter_enabled and is_openrouter_model_name(model):
        model = DEFAULT_AGENT_MODEL

    supported_items = _split_csv(read_env("SUPPORTED_MODELS")) or (
        requested_model,
        DEFAULT_AGENT_MODEL,
    )
    filtered_models: list[str] = []
    for item in supported_items:
        normalized = resolve_llm_model_name(item, openrouter_backend=openrouter_enabled)
        if not normalized:
            continue
        if not openrouter_enabled and is_openrouter_model_name(normalized):
            continue
        filtered_models.append(normalized)
    supported = tuple(dict.fromkeys(filtered_models))
    if not supported:
        supported = (model,)
    elif model not in supported:
        supported = tuple(dict.fromkeys((model, *supported)))

    return Config(
        agent_model=model,
        llm_backend=llm_backend,
        gemini_thinking_level=(
            read_env("GEMINI_THINKING_LEVEL", DEFAULT_GEMINI_THINKING_LEVEL)
            or DEFAULT_GEMINI_THINKING_LEVEL
        ).lower(),
        google_api_key=read_env("GOOGLE_API_KEY"),
        openrouter_api_key=openrouter_api_key,
        openrouter_base_url=(
            read_env("OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE_URL)
            or DEFAULT_OPENROUTER_BASE_URL
        ),
        openrouter_auto_allowed_models=_split_csv(
            read_env("OPENROUTER_AUTO_ALLOWED_MODELS")
        )
        or DEFAULT_OPENROUTER_AUTO_ALLOWED_MODELS,
        opendart_api_key=read_env("OPENDART_API_KEY"),
        perplexity_api_key=read_env("PPLX_API_KEY"),
        supported_models=supported,
        log_level=(read_env("LOG_LEVEL", "INFO") or "INFO").upper(),
        mongodb_enabled=_as_bool(read_env("MONGODB_ENABLED"), default=False),
        mongodb_uri=read_env("MONGODB_URI"),
        mongodb_database=read_env("MONGODB_DATABASE", "valuator") or "valuator",
        mongodb_collection=read_env("MONGODB_COLLECTION", "sessions") or "sessions",
        domain_arch_enabled=_as_bool(
            read_env("VALUATOR_DOMAIN_ARCH_ENABLED"), default=True
        ),
        event_layer_enabled=_as_bool(
            read_env("VALUATOR_EVENT_LAYER_ENABLED"), default=False
        ),
        code_execution_timeout=_as_int(read_env("CODE_EXECUTION_TIMEOUT"), default=3),
        code_execution_allowed_imports=_split_csv(
            read_env("CODE_EXECUTION_ALLOWED_IMPORTS")
        )
        or DEFAULT_CODE_EXECUTION_ALLOWED_IMPORTS,
        agent_step_repair_retries=_as_int(
            read_env("AGENT_STEP_REPAIR_RETRIES"), default=2
        ),
        agent_max_invalid_decisions_per_task=_as_int(
            read_env("AGENT_MAX_INVALID_DECISIONS_PER_TASK"), default=5
        ),
        agent_max_consecutive_tool_failures=_as_int(
            read_env("AGENT_MAX_CONSECUTIVE_TOOL_FAILURES"), default=3
        ),
        agent_max_steps_per_task=_as_int(
            read_env("AGENT_MAX_STEPS_PER_TASK"), default=30
        ),
        agent_concurrency=_as_int(read_env("AGENT_CONCURRENCY"), default=10),
        agent_llm_retry_count=_as_int(read_env("AGENT_LLM_RETRY_COUNT"), default=2),
        agent_llm_retry_base_delay=_as_float(
            read_env("AGENT_LLM_RETRY_BASE_DELAY"), default=2.0
        ),
        web_search_retry_count=_as_int(read_env("WEB_SEARCH_RETRY_COUNT"), default=2),
        web_search_retry_base_delay=_as_float(
            read_env("WEB_SEARCH_RETRY_BASE_DELAY"), default=2.0
        ),
    )


config = load_config()
