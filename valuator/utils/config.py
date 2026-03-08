import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


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


@dataclass(frozen=True)
class Config:
    agent_model: str
    google_api_key: str | None
    perplexity_api_key: str | None
    supported_models: tuple[str, ...]
    domain_arch_enabled: bool
    event_layer_enabled: bool
    code_execution_timeout: int
    code_execution_allowed_imports: tuple[str, ...]


def load_config() -> Config:
    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")
    model = os.getenv("AGENT_MODEL", "gemini-3-flash-preview")
    supported = _split_csv(os.getenv("SUPPORTED_MODELS")) or (
        model,
        "gemini-3-pro-preview",
    )
    return Config(
        agent_model=model,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        perplexity_api_key=os.getenv("PPLX_API_KEY"),
        supported_models=tuple(dict.fromkeys(supported)),
        domain_arch_enabled=_as_bool(
            os.getenv("VALUATOR_DOMAIN_ARCH_ENABLED"), default=True
        ),
        event_layer_enabled=_as_bool(
            os.getenv("VALUATOR_EVENT_LAYER_ENABLED"), default=False
        ),
        code_execution_timeout=_as_int(
            os.getenv("CODE_EXECUTION_TIMEOUT"), default=10
        ),
        code_execution_allowed_imports=_split_csv(
            os.getenv("CODE_EXECUTION_ALLOWED_IMPORTS")
        ),
    )


config = load_config()
