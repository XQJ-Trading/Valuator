from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

config_module = importlib.import_module("valuator.utils.config")


def test_session_files_root_defaults_to_logs_local(monkeypatch) -> None:
    config_module.load_project_env.cache_clear()
    monkeypatch.setattr(
        config_module,
        "load_dotenv",
        lambda *, dotenv_path: False,
    )
    monkeypatch.delenv("VALUATOR_SESSION_FILES_ROOT", raising=False)

    root = config_module.session_files_root()

    assert root == config_module.ROOT_DIR / "logs" / "local"


def test_session_files_root_respects_env(monkeypatch) -> None:
    config_module.load_project_env.cache_clear()
    monkeypatch.setattr(
        config_module,
        "load_dotenv",
        lambda *, dotenv_path: False,
    )
    monkeypatch.setenv("VALUATOR_SESSION_FILES_ROOT", "logs/server_history")

    root = config_module.session_files_root()

    assert root == config_module.ROOT_DIR / "logs" / "server_history"


def test_load_project_env_uses_cached_dotenv_load(monkeypatch) -> None:
    calls: list[object] = []

    def fake_load_dotenv(*, dotenv_path):
        calls.append(dotenv_path)
        return True

    config_module.load_project_env.cache_clear()
    monkeypatch.setattr(config_module, "load_dotenv", fake_load_dotenv)

    config_module.load_project_env()
    config_module.load_project_env()

    assert calls == [config_module.ENV_FILE]


def test_load_config_defaults_to_flash_preview(monkeypatch) -> None:
    config_module.load_project_env.cache_clear()
    monkeypatch.setattr(
        config_module,
        "load_dotenv",
        lambda *, dotenv_path: False,
    )
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    monkeypatch.delenv("SUPPORTED_MODELS", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("MONGODB_ENABLED", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGODB_DATABASE", raising=False)
    monkeypatch.delenv("MONGODB_COLLECTION", raising=False)
    monkeypatch.delenv("AGENT_CONCURRENCY", raising=False)
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    loaded = config_module.load_config()

    assert loaded.agent_model == config_module.DEFAULT_AGENT_MODEL
    assert loaded.supported_models == (config_module.DEFAULT_AGENT_MODEL,)
    assert loaded.log_level == "INFO"
    assert (
        loaded.gemini_explicit_cache_ttl_seconds
        == config_module.DEFAULT_GEMINI_EXPLICIT_CACHE_TTL_SECONDS
    )
    assert (
        loaded.gemini_implicit_cache_cost_mode
        == config_module.DEFAULT_GEMINI_IMPLICIT_CACHE_COST_MODE
    )
    assert loaded.mongodb_enabled is False
    assert loaded.mongodb_database == "valuator"
    assert loaded.mongodb_collection == "sessions"
    assert loaded.agent_step_repair_retries == 2
    assert loaded.agent_max_invalid_decisions_per_task == 5
    assert loaded.agent_max_steps_per_task == 30
    assert loaded.agent_concurrency == 10
    assert loaded.web_search_provider == config_module.DEFAULT_WEB_SEARCH_PROVIDER
    assert loaded.tavily_api_key is None


def test_load_config_normalizes_supported_models(monkeypatch) -> None:
    config_module.load_project_env.cache_clear()
    monkeypatch.setattr(
        config_module,
        "load_dotenv",
        lambda *, dotenv_path: False,
    )
    monkeypatch.setenv("AGENT_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv(
        "SUPPORTED_MODELS",
        "gemini-2.5-flash, gemini-3-flash-preview, gemini-pro-latest",
    )
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("MONGODB_ENABLED", "true")
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017")
    monkeypatch.setenv("MONGODB_DATABASE", "custom-db")
    monkeypatch.setenv("MONGODB_COLLECTION", "custom-collection")
    monkeypatch.setenv("AGENT_STEP_REPAIR_RETRIES", "4")
    monkeypatch.setenv("AGENT_MAX_INVALID_DECISIONS_PER_TASK", "7")
    monkeypatch.setenv("AGENT_MAX_STEPS_PER_TASK", "45")
    monkeypatch.setenv("AGENT_CONCURRENCY", "8")
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-key")
    monkeypatch.setenv("GEMINI_EXPLICIT_CACHE_TTL_SECONDS", "7200")
    monkeypatch.setenv("GEMINI_IMPLICIT_CACHE_COST_MODE", "bill_uncached_only")

    loaded = config_module.load_config()

    assert loaded.agent_model == "gemini-3-flash-preview"
    assert loaded.supported_models == (
        "gemini-3-flash-preview",
        "gemini-3-pro-preview",
    )
    assert loaded.log_level == "DEBUG"
    assert loaded.mongodb_enabled is True
    assert loaded.mongodb_uri == "mongodb://localhost:27017"
    assert loaded.mongodb_database == "custom-db"
    assert loaded.mongodb_collection == "custom-collection"
    assert loaded.agent_step_repair_retries == 4
    assert loaded.agent_max_invalid_decisions_per_task == 7
    assert loaded.agent_max_steps_per_task == 45
    assert loaded.agent_concurrency == 8
    assert loaded.web_search_provider == "tavily"
    assert loaded.tavily_api_key == "tavily-key"
    assert loaded.gemini_explicit_cache_ttl_seconds == 7200
    assert loaded.gemini_implicit_cache_cost_mode == "bill_uncached_only"


def test_load_config_rejects_invalid_gemini_implicit_cache_cost_mode(
    monkeypatch,
) -> None:
    config_module.load_project_env.cache_clear()
    monkeypatch.setattr(
        config_module,
        "load_dotenv",
        lambda *, dotenv_path: False,
    )
    monkeypatch.setenv("GEMINI_IMPLICIT_CACHE_COST_MODE", "invalid")

    with pytest.raises(
        ValueError,
        match="GEMINI_IMPLICIT_CACHE_COST_MODE must be one of",
    ):
        config_module.load_config()


def test_load_config_rejects_non_positive_gemini_explicit_cache_ttl(
    monkeypatch,
) -> None:
    config_module.load_project_env.cache_clear()
    monkeypatch.setattr(
        config_module,
        "load_dotenv",
        lambda *, dotenv_path: False,
    )
    monkeypatch.setenv("GEMINI_EXPLICIT_CACHE_TTL_SECONDS", "0")

    with pytest.raises(
        ValueError,
        match="GEMINI_EXPLICIT_CACHE_TTL_SECONDS must be > 0",
    ):
        config_module.load_config()
