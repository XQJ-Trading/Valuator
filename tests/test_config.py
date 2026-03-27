from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

config_module = importlib.import_module("valuator.utils.config")


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

    loaded = config_module.load_config()

    assert loaded.agent_model == config_module.DEFAULT_AGENT_MODEL
    assert loaded.supported_models == (config_module.DEFAULT_AGENT_MODEL,)
    assert loaded.log_level == "INFO"
    assert loaded.mongodb_enabled is False
    assert loaded.mongodb_database == "valuator"
    assert loaded.mongodb_collection == "sessions"
    assert loaded.agent_step_repair_retries == 2
    assert loaded.agent_max_invalid_decisions_per_task == 5
    assert loaded.agent_max_steps_per_task == 30
    assert loaded.agent_concurrency == 4
    assert loaded.decomposition_gate_enabled is True
    assert loaded.decomposition_gate_initial_threshold == 0.0
    assert loaded.decomposition_gate_learning_rate == 0.1
    assert loaded.decomposition_gate_accept_bound == 0.4
    assert loaded.decomposition_gate_reject_bound == -0.3
    assert loaded.decomposition_gate_max_depth == 4
    assert loaded.decomposition_gate_max_children == 8
    assert loaded.decomposition_gate_weight_depth == 0.3
    assert loaded.decomposition_gate_weight_breadth == 0.2
    assert loaded.decomposition_gate_weight_tool == 0.3
    assert loaded.decomposition_gate_weight_token_pressure == 0.2
    assert loaded.decomposition_gate_static_weight == 0.4
    assert loaded.decomposition_gate_critic_weight == 0.6


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
    monkeypatch.setenv("DECOMPOSITION_GATE_ENABLED", "false")
    monkeypatch.setenv("DECOMPOSITION_GATE_INITIAL_THRESHOLD", "0.2")
    monkeypatch.setenv("DECOMPOSITION_GATE_LEARNING_RATE", "0.25")
    monkeypatch.setenv("DECOMPOSITION_GATE_ACCEPT_BOUND", "0.6")
    monkeypatch.setenv("DECOMPOSITION_GATE_REJECT_BOUND", "-0.2")
    monkeypatch.setenv("DECOMPOSITION_GATE_MAX_DEPTH", "6")
    monkeypatch.setenv("DECOMPOSITION_GATE_MAX_CHILDREN", "12")
    monkeypatch.setenv("DECOMPOSITION_GATE_WEIGHT_DEPTH", "0.4")
    monkeypatch.setenv("DECOMPOSITION_GATE_WEIGHT_BREADTH", "0.1")
    monkeypatch.setenv("DECOMPOSITION_GATE_WEIGHT_TOOL", "0.35")
    monkeypatch.setenv("DECOMPOSITION_GATE_WEIGHT_TOKEN_PRESSURE", "0.15")
    monkeypatch.setenv("DECOMPOSITION_GATE_STATIC_WEIGHT", "0.3")
    monkeypatch.setenv("DECOMPOSITION_GATE_CRITIC_WEIGHT", "0.7")

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
    assert loaded.decomposition_gate_enabled is False
    assert loaded.decomposition_gate_initial_threshold == 0.2
    assert loaded.decomposition_gate_learning_rate == 0.25
    assert loaded.decomposition_gate_accept_bound == 0.6
    assert loaded.decomposition_gate_reject_bound == -0.2
    assert loaded.decomposition_gate_max_depth == 6
    assert loaded.decomposition_gate_max_children == 12
    assert loaded.decomposition_gate_weight_depth == 0.4
    assert loaded.decomposition_gate_weight_breadth == 0.1
    assert loaded.decomposition_gate_weight_tool == 0.35
    assert loaded.decomposition_gate_weight_token_pressure == 0.15
    assert loaded.decomposition_gate_static_weight == 0.3
    assert loaded.decomposition_gate_critic_weight == 0.7


def test_load_config_validates_decomposition_gate_bounds(monkeypatch) -> None:
    config_module.load_project_env.cache_clear()
    monkeypatch.setattr(
        config_module,
        "load_dotenv",
        lambda *, dotenv_path: False,
    )
    monkeypatch.setenv("DECOMPOSITION_GATE_ACCEPT_BOUND", "-0.3")
    monkeypatch.setenv("DECOMPOSITION_GATE_REJECT_BOUND", "-0.3")

    try:
        config_module.load_config()
    except ValueError as exc:
        assert "accept_bound > reject_bound" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid decomposition gate bounds")
