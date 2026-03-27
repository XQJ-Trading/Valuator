from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT_DIR / ".env"
DEFAULT_AGENT_MODEL = "gemini-3-flash-preview"

MODEL_ALIASES = {
    "gemini-2.5-flash": "gemini-3-flash-preview",
    "gemini-flash-latest": "gemini-3-flash-preview",
    "gemini-2.5-pro": "gemini-3-pro-preview",
    "gemini-pro-latest": "gemini-3-pro-preview",
}


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
    google_api_key: str | None
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
    agent_max_steps_per_task: int
    agent_concurrency: int
    decomposition_gate_enabled: bool
    decomposition_gate_initial_threshold: float
    decomposition_gate_learning_rate: float
    decomposition_gate_accept_bound: float
    decomposition_gate_reject_bound: float
    decomposition_gate_max_depth: int
    decomposition_gate_max_children: int
    decomposition_gate_weight_depth: float
    decomposition_gate_weight_breadth: float
    decomposition_gate_weight_tool: float
    decomposition_gate_weight_token_pressure: float
    decomposition_gate_static_weight: float
    decomposition_gate_critic_weight: float
    agent_llm_retry_count: int
    agent_llm_retry_base_delay: float


def canonical_model_name(value: str) -> str:
    name = value.strip()
    return MODEL_ALIASES.get(name, name)


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


def get_env(name: str, *, required: bool = False) -> str:
    value = read_env(name, "")
    if value or not required:
        return value
    raise RuntimeError(f"{name} not set")


def get_opendart_api_key(*, required: bool = False) -> str:
    return get_env("OPENDART_API_KEY", required=required)


def _validate_decomposition_gate_config(
    *,
    accept_bound: float,
    reject_bound: float,
    static_weight: float,
    critic_weight: float,
    max_depth: int,
    max_children: int,
) -> None:
    if accept_bound <= reject_bound:
        raise ValueError("decomposition gate requires accept_bound > reject_bound")
    if static_weight + critic_weight <= 0:
        raise ValueError(
            "decomposition gate requires static_weight + critic_weight > 0"
        )
    if max_depth < 1:
        raise ValueError("decomposition gate requires max_depth >= 1")
    if max_children < 2:
        raise ValueError("decomposition gate requires max_children >= 2")


def load_config() -> Config:
    model = canonical_model_name(
        read_env("AGENT_MODEL", DEFAULT_AGENT_MODEL) or DEFAULT_AGENT_MODEL
    )
    supported = normalize_supported_models(
        _split_csv(read_env("SUPPORTED_MODELS"))
        or (
            model,
            DEFAULT_AGENT_MODEL,
        )
    )
    decomposition_gate_accept_bound = _as_float(
        read_env("DECOMPOSITION_GATE_ACCEPT_BOUND"),
        default=0.4,
    )
    decomposition_gate_reject_bound = _as_float(
        read_env("DECOMPOSITION_GATE_REJECT_BOUND"),
        default=-0.3,
    )
    decomposition_gate_static_weight = _as_float(
        read_env("DECOMPOSITION_GATE_STATIC_WEIGHT"),
        default=0.4,
    )
    decomposition_gate_critic_weight = _as_float(
        read_env("DECOMPOSITION_GATE_CRITIC_WEIGHT"),
        default=0.6,
    )
    decomposition_gate_max_depth = _as_int(
        read_env("DECOMPOSITION_GATE_MAX_DEPTH"),
        default=4,
    )
    decomposition_gate_max_children = _as_int(
        read_env("DECOMPOSITION_GATE_MAX_CHILDREN"),
        default=8,
    )
    _validate_decomposition_gate_config(
        accept_bound=decomposition_gate_accept_bound,
        reject_bound=decomposition_gate_reject_bound,
        static_weight=decomposition_gate_static_weight,
        critic_weight=decomposition_gate_critic_weight,
        max_depth=decomposition_gate_max_depth,
        max_children=decomposition_gate_max_children,
    )

    return Config(
        agent_model=model,
        google_api_key=read_env("GOOGLE_API_KEY"),
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
        code_execution_timeout=_as_int(read_env("CODE_EXECUTION_TIMEOUT"), default=10),
        code_execution_allowed_imports=_split_csv(
            read_env("CODE_EXECUTION_ALLOWED_IMPORTS")
        ),
        agent_step_repair_retries=_as_int(
            read_env("AGENT_STEP_REPAIR_RETRIES"), default=2
        ),
        agent_max_invalid_decisions_per_task=_as_int(
            read_env("AGENT_MAX_INVALID_DECISIONS_PER_TASK"), default=5
        ),
        agent_max_steps_per_task=_as_int(
            read_env("AGENT_MAX_STEPS_PER_TASK"), default=100
        ),
        agent_concurrency=_as_int(read_env("AGENT_CONCURRENCY"), default=8),
        decomposition_gate_enabled=_as_bool(
            read_env("DECOMPOSITION_GATE_ENABLED"),
            default=True,
        ),
        decomposition_gate_initial_threshold=_as_float(
            read_env("DECOMPOSITION_GATE_INITIAL_THRESHOLD"),
            default=0.0,
        ),
        decomposition_gate_learning_rate=_as_float(
            read_env("DECOMPOSITION_GATE_LEARNING_RATE"),
            default=0.1,
        ),
        decomposition_gate_accept_bound=decomposition_gate_accept_bound,
        decomposition_gate_reject_bound=decomposition_gate_reject_bound,
        decomposition_gate_max_depth=decomposition_gate_max_depth,
        decomposition_gate_max_children=decomposition_gate_max_children,
        decomposition_gate_weight_depth=_as_float(
            read_env("DECOMPOSITION_GATE_WEIGHT_DEPTH"),
            default=0.3,
        ),
        decomposition_gate_weight_breadth=_as_float(
            read_env("DECOMPOSITION_GATE_WEIGHT_BREADTH"),
            default=0.3,
        ),
        decomposition_gate_weight_tool=_as_float(
            read_env("DECOMPOSITION_GATE_WEIGHT_TOOL"),
            default=0.2,
        ),
        decomposition_gate_weight_token_pressure=_as_float(
            read_env("DECOMPOSITION_GATE_WEIGHT_TOKEN_PRESSURE"),
            default=0.2,
        ),
        decomposition_gate_static_weight=decomposition_gate_static_weight,
        decomposition_gate_critic_weight=decomposition_gate_critic_weight,
        agent_llm_retry_count=_as_int(
            read_env("AGENT_LLM_RETRY_COUNT"), default=3
        ),
        agent_llm_retry_base_delay=_as_float(
            read_env("AGENT_LLM_RETRY_BASE_DELAY"), default=2.0
        ),
    )


config = load_config()
