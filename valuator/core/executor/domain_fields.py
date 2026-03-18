from __future__ import annotations

from typing import Any


def build_domain_artifact_fields(
    *,
    tool_name: str,
    raw_result: Any,
    metadata: dict[str, Any] | None = None,
    fallback_domain_id: str = "",
) -> dict[str, Any]:
    if not isinstance(raw_result, dict):
        return {}
    domain_id = str((metadata or {}).get("domain") or fallback_domain_id).strip()
    if not domain_id:
        return {}
    return {
        "domain_id": domain_id,
        "domain_summary": _summary(raw_result),
        "domain_key_values": {},
        "domain_payload": {"tool_name": tool_name, "raw_result": raw_result},
    }


def _summary(raw_result: dict[str, Any]) -> str:
    value = raw_result.get("findings") or raw_result.get("summary") or ""
    return str(value).strip()
