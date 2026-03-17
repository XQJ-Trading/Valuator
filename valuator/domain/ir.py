from __future__ import annotations

from ast import literal_eval
from typing import Any

from .types import DomainModule, IrConfig, IrFieldSpec


def build_domain_artifact_fields(
    *,
    tool_name: str,
    raw_result: Any,
    metadata: dict[str, Any] | None = None,
    module: DomainModule | None = None,
    fallback_domain_id: str = "",
) -> dict[str, Any]:
    """Project a tool result into execution-artifact domain fields."""

    if not isinstance(raw_result, dict):
        return {}

    meta = metadata or {}
    domain_id = (
        module.id
        if module is not None
        else str(meta.get("domain") or "").strip() or fallback_domain_id.strip()
    )
    ir_config = module.ir_config if module is not None else None
    if ir_config is not None and domain_id:
        return _project_from_ir_config(
            raw_result=raw_result,
            domain_id=domain_id,
            ir_config=ir_config,
        )
    if not domain_id:
        return {}
    return {
        "domain_id": domain_id,
        "domain_summary": _default_summary(raw_result),
        "domain_key_values": {},
        "domain_payload": {"tool_name": tool_name, "raw_result": raw_result},
    }


def _project_from_ir_config(
    *,
    raw_result: dict[str, Any],
    domain_id: str,
    ir_config: IrConfig,
) -> dict[str, Any]:
    summary_value = _extract_path(raw_result, ir_config.summary_path)
    summary = _stringify_summary(summary_value) or _default_summary(raw_result)
    key_values: dict[str, str] = {}
    for key, spec in ir_config.key_values.items():
        rendered = _render_field(raw_result, spec)
        if rendered is None:
            continue
        key_values[key] = rendered

    payload: dict[str, Any] = {}
    for key, path in ir_config.payload_paths.items():
        value = _extract_path(raw_result, path)
        if value is None:
            continue
        payload[key] = value

    return {
        "domain_id": domain_id,
        "domain_summary": summary,
        "domain_key_values": key_values,
        "domain_payload": payload,
    }


def _render_field(raw_result: dict[str, Any], spec: IrFieldSpec) -> str | None:
    value = _extract_path(raw_result, spec.path)
    if value is None:
        value = spec.default
    if value is None:
        return None
    try:
        return spec.format.format(value)
    except Exception:
        return str(value)


def _extract_path(data: Any, path: str) -> Any:
    if not path:
        return _normalize_value(data)
    current = data
    for part in path.split("."):
        current = _normalize_value(current)
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
            continue
        if isinstance(current, list):
            try:
                idx = int(part)
            except ValueError:
                return None
            if idx < 0 or idx >= len(current):
                return None
            current = current[idx]
            continue
        return None
    return _normalize_value(current)


def _normalize_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        parsed = literal_eval(text)
    except (ValueError, SyntaxError):
        return value
    if isinstance(parsed, (dict, list, tuple)):
        return parsed
    return value


def _stringify_summary(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _default_summary(raw_result: dict[str, Any]) -> str:
    return _stringify_summary(
        raw_result.get("findings") or raw_result.get("summary") or ""
    )
