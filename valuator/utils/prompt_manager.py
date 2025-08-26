import os
import threading
from typing import Any, Dict

import yaml

_cache_lock = threading.Lock()
_yaml_cache: Dict[str, Dict[str, Any]] = {}


def _prompts_root() -> str:
    current_dir = os.path.dirname(os.path.dirname(__file__))
    # prompts directory located at valuator/prompts
    return os.path.join(current_dir, "prompts")


def _load_yaml_file(file_path: str) -> Dict[str, Any]:
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _get_namespace_path(namespace: str) -> str:
    # namespace like "analysis", "fill_out_form", "utils"
    return os.path.join(_prompts_root(), f"{namespace}.yaml")


def _safe_key_format(template: str, values: Dict[str, Any]) -> str:
    # Replace only exact {key} occurrences to avoid interfering with JSON braces
    if not values:
        return template
    formatted = template
    for key, val in values.items():
        formatted = formatted.replace("{" + key + "}", str(val))
    return formatted


def get_prompt(namespace: str, key: str, **kwargs) -> str:
    """
    Load a prompt by namespace and key from YAML, with safe key-only formatting.

    YAML file: valuator/prompts/{namespace}.yaml
    Structure: { key: "prompt template with {placeholders}" }
    """
    ns_path = _get_namespace_path(namespace)
    with _cache_lock:
        if ns_path not in _yaml_cache:
            _yaml_cache[ns_path] = _load_yaml_file(ns_path)
        data = _yaml_cache[ns_path]

    template = data.get(key, "")
    if not isinstance(template, str):
        raise KeyError(f"Prompt '{key}' in namespace '{namespace}' is not a string")
    return _safe_key_format(template, kwargs)


def refresh_cache(namespace: str | None = None) -> None:
    """Clear cache for a namespace or all."""
    with _cache_lock:
        if namespace is None:
            _yaml_cache.clear()
        else:
            ns_path = _get_namespace_path(namespace)
            if ns_path in _yaml_cache:
                del _yaml_cache[ns_path]
