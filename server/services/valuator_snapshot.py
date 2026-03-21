from __future__ import annotations

from typing import Any


def project_snapshot_plan(raw_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "query_units": _query_units(raw_plan),
        "contract": _contract(raw_plan),
        "tasks": _tasks(raw_plan),
        "root_task_id": _root_task_id(raw_plan),
    }


def _analysis(raw_plan: dict[str, Any]) -> dict[str, Any]:
    candidate = raw_plan.get("analysis")
    if isinstance(candidate, dict):
        return candidate
    return {}


def _query_units(raw_plan: dict[str, Any]) -> list[Any]:
    legacy_units = raw_plan.get("query_units")
    if isinstance(legacy_units, list):
        return list(legacy_units)

    analysis_units = _analysis(raw_plan).get("units")
    if isinstance(analysis_units, list):
        return list(analysis_units)
    return []


def _contract(raw_plan: dict[str, Any]) -> dict[str, Any] | None:
    legacy_contract = raw_plan.get("contract")
    if isinstance(legacy_contract, dict):
        return legacy_contract

    requirements = _analysis(raw_plan).get("requirements")
    if not isinstance(requirements, list):
        return None

    contract = {
        "items": [
            _contract_item(item) for item in requirements if isinstance(item, dict)
        ]
    }
    rationale = _analysis(raw_plan).get("rationale")
    if isinstance(rationale, str) and rationale.strip():
        contract["rationale"] = rationale
    return contract


def _contract_item(raw_item: dict[str, Any]) -> dict[str, Any]:
    unit_ids = _int_list(raw_item.get("unit_ids"))
    item = {
        "id": str(raw_item.get("id") or ""),
        "unit_id": _unit_id(raw_item.get("unit_id"), unit_ids),
        "unit_ids": unit_ids,
        "domain_ids": _string_list(raw_item.get("domain_ids")),
        "entity_ids": _string_list(raw_item.get("entity_ids")),
        "provenance": str(raw_item.get("provenance") or ""),
        "acceptance": str(raw_item.get("acceptance") or ""),
        "required": bool(raw_item.get("required", True)),
    }
    requirement_type = str(raw_item.get("requirement_type") or "").strip()
    if requirement_type:
        item["requirement_type"] = requirement_type
    return item


def _unit_id(raw_value: Any, unit_ids: list[int]) -> int:
    value = _to_int(raw_value)
    if value is not None:
        return value
    if unit_ids:
        return unit_ids[0]
    return 0


def _tasks(raw_plan: dict[str, Any]) -> list[Any]:
    raw_tasks = raw_plan.get("tasks")
    if isinstance(raw_tasks, list):
        return list(raw_tasks)
    return []


def _root_task_id(raw_plan: dict[str, Any]) -> str | None:
    raw_root_task_id = raw_plan.get("root_task_id")
    if raw_root_task_id is None:
        return None
    text = str(raw_root_task_id).strip()
    if not text:
        return None
    return text


def _string_list(raw_values: Any) -> list[str]:
    if not isinstance(raw_values, list):
        return []
    values: list[str] = []
    for raw_value in raw_values:
        if not isinstance(raw_value, str):
            continue
        text = raw_value.strip()
        if text:
            values.append(text)
    return values


def _int_list(raw_values: Any) -> list[int]:
    if not isinstance(raw_values, list):
        return []
    values: list[int] = []
    for raw_value in raw_values:
        value = _to_int(raw_value)
        if value is not None:
            values.append(value)
    return values


def _to_int(raw_value: Any) -> int | None:
    if isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, int):
        return raw_value
    if not isinstance(raw_value, str):
        return None
    text = raw_value.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None
