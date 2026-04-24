from __future__ import annotations

import json
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from ...tools.specs import get_tool_spec
from ..task import Task
from ..types import Action, TaskDecision, TaskSpec, ToolRequest
from .actions import allowed_actions_for_task
from .plan_spec import validate_root_decomposition

TASK_NAME_MAX_CHARS = 30


def truncate_task_name(text: str, max_chars: int = TASK_NAME_MAX_CHARS) -> str:
    """Trim and shorten task_name at the parsing boundary.

    Trailing underscores are stripped after slicing so the result does not end
    with ``_`` (invalid per task_name rules).
    """
    s = text.strip()
    if len(s) <= max_chars:
        return s
    return s[:max_chars].rstrip("_")


class _ToolRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)


class _TaskSpecPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    task_name: str
    tool_hint: str = ""
    depends_on_siblings: list[int] = Field(default_factory=list)
    query_unit_ids: list[int] = Field(default_factory=list)

    @field_validator("task_name")
    @classmethod
    def validate_task_name(cls, value: str) -> str:
        text = truncate_task_name(value)
        if not text:
            raise ValueError("task_name is required")
        if text.startswith("_") or text.endswith("_") or "__" in text:
            raise ValueError(
                "task_name must not start or end with '_' or contain repeated '_'"
            )
        if not all(char.isalnum() or char == "_" for char in text):
            raise ValueError("task_name must use only letters, digits, and underscores")
        return text

    @field_validator("query_unit_ids")
    @classmethod
    def validate_query_unit_ids(cls, value: list[int]) -> list[int]:
        normalized: list[int] = []
        for item in value:
            if item < 0:
                raise ValueError("query_unit_ids must be non-negative integers")
            if item not in normalized:
                normalized.append(item)
        return normalized


class StepIntentPayload(BaseModel):
    """LLM step JSON: fields may combine; runtime maps to a single Action (§6)."""

    # LLM payloads may include legacy fields (e.g. reason); ignore at boundary.
    model_config = ConfigDict(extra="ignore")

    action: Action | None = None
    children: list[_TaskSpecPayload] = Field(default_factory=list)
    tool_request: _ToolRequestPayload | None = None
    wait_for: list[str] = Field(default_factory=list)
    output: Any = None
    facts: dict[str, Any] = Field(default_factory=dict)


def normalize_decision_raw(raw: dict[str, Any]) -> dict[str, Any]:
    # LLM JSON often names aggregate/decompose while filling wait_* fields; align action before Pydantic (boundary-only normalize per CLAUDE.md).
    out = dict(raw)
    action = out.get("action")
    if isinstance(action, Action):
        action_token = action.value
    elif action is None:
        return out
    else:
        action_token = str(action).strip().lower()

    children = out.get("children")
    has_children = isinstance(children, list) and len(children) > 0

    wf = out.get("wait_for")
    wf_list = wf if isinstance(wf, list) else []
    has_wait_targets = bool(wf_list)
    tool_request = out.get("tool_request")
    has_tool_request = isinstance(tool_request, dict) and bool(
        str(tool_request.get("tool_name") or "").strip()
    )

    output = out.get("output")
    facts = out.get("facts")
    has_aggregate_payload = output is not None or (
        isinstance(facts, dict) and bool(facts)
    )

    if action_token == Action.AGGREGATE.value:
        if not has_aggregate_payload and has_tool_request:
            out["action"] = Action.EXECUTE.value
        elif not has_aggregate_payload and has_wait_targets:
            out["action"] = Action.WAIT.value
    elif action_token == Action.DECOMPOSE.value:
        if not has_children and has_wait_targets:
            out["action"] = Action.WAIT.value
    return out


def has_structural_intent(intent: StepIntentPayload) -> bool:
    return (
        intent.tool_request is not None
        or bool(intent.children)
        or bool(intent.wait_for)
        or intent.output is not None
        or bool(intent.facts)
    )


def _invalid_task_decision(message: str, raw_for_error: dict[str, Any]) -> ValueError:
    return ValueError(
        "invalid task decision payload: "
        f"{message}; raw_payload={json.dumps(raw_for_error, ensure_ascii=False, default=str)}"
    )


def map_intent_to_task_decision(
    task: Task,
    intent: StepIntentPayload,
    _allowed: frozenset[Action],
    *,
    raw_for_error: dict[str, Any],
) -> TaskDecision:
    has_wait = bool(intent.wait_for)
    has_tool = intent.tool_request is not None
    has_children = bool(intent.children)
    has_facts = bool(intent.facts)
    has_output = intent.output is not None
    has_publish = has_output or has_facts

    def _ensure_allowed(action: Action) -> None:
        if action in _allowed:
            return
        allowed_tokens = ", ".join(sorted(item.value for item in _allowed))
        raise _invalid_task_decision(
            f"action is not allowed for this task; requested={action.value}; "
            f"allowed=[{allowed_tokens}]",
            raw_for_error,
        )

    if intent.action is Action.FAIL:
        return TaskDecision(action=Action.FAIL, output=intent.output)

    if intent.action is Action.EXECUTE:
        if not has_tool:
            raise _invalid_task_decision("execute action requires tool_request", raw_for_error)
        _ensure_allowed(Action.EXECUTE)
        tr = intent.tool_request
        assert tr is not None
        return TaskDecision(
            action=Action.EXECUTE,
            children=(),
            tool_request=ToolRequest(
                tool_name=tr.tool_name,
                args=dict(tr.args),
            ),
            wait_for=(),
            output=None,
            facts={},
        )

    if intent.action is Action.DECOMPOSE:
        if not has_children:
            output, facts = task.implicit_aggregate_payload()
            if output is not None or facts:
                return TaskDecision(
                    action=Action.AGGREGATE,
                    children=(),
                    tool_request=None,
                    wait_for=(),
                    output=output,
                    facts=facts,
                )
            raise _invalid_task_decision("decompose action requires children", raw_for_error)
        _ensure_allowed(Action.DECOMPOSE)
        children = tuple(
            TaskSpec(
                description=child.description,
                task_name=child.task_name,
                tool_hint=child.tool_hint,
                depends_on_siblings=list(child.depends_on_siblings),
                query_unit_ids=list(child.query_unit_ids),
            )
            for child in intent.children
        )
        if task.parent_id is None:
            root_err = validate_root_decomposition(children)
            if root_err is not None:
                raise _invalid_task_decision(root_err, raw_for_error)
        return TaskDecision(
            action=Action.DECOMPOSE,
            children=children,
            tool_request=None,
            wait_for=(),
            output=None,
            facts={},
        )

    if intent.action is Action.WAIT:
        if not has_wait:
            raise _invalid_task_decision("wait action requires wait_for", raw_for_error)
        return TaskDecision(
            action=Action.WAIT,
            children=(),
            tool_request=None,
            wait_for=tuple(intent.wait_for),
            output=None,
            facts={},
        )

    if intent.action is Action.FINALIZE:
        if task.parent_id is not None:
            raise _invalid_task_decision(
                "finalize is only allowed for root tasks",
                raw_for_error,
            )
        if not has_output:
            raise _invalid_task_decision("finalize action requires output", raw_for_error)
        _ensure_allowed(Action.FINALIZE)
        return TaskDecision(
            action=Action.FINALIZE,
            children=(),
            tool_request=None,
            wait_for=(),
            output=intent.output,
            facts={},
        )

    if intent.action is Action.AGGREGATE:
        if not has_publish:
            output, facts = task.implicit_aggregate_payload()
            if output is None and not facts:
                raise _invalid_task_decision(
                    "aggregate action requires output or facts",
                    raw_for_error,
                )
            return TaskDecision(
                action=Action.AGGREGATE,
                children=(),
                tool_request=None,
                wait_for=(),
                output=output,
                facts=facts,
            )
        return TaskDecision(
            action=Action.AGGREGATE,
            children=(),
            tool_request=None,
            wait_for=(),
            output=intent.output,
            facts=dict(intent.facts),
        )

    if has_wait:
        return TaskDecision(
            action=Action.WAIT,
            children=(),
            tool_request=None,
            wait_for=tuple(intent.wait_for),
            output=None,
            facts={},
        )

    if has_tool:
        _ensure_allowed(Action.EXECUTE)
        tr = intent.tool_request
        assert tr is not None
        return TaskDecision(
            action=Action.EXECUTE,
            children=(),
            tool_request=ToolRequest(
                tool_name=tr.tool_name,
                args=dict(tr.args),
            ),
            wait_for=(),
            output=None,
            facts={},
        )

    if has_children:
        _ensure_allowed(Action.DECOMPOSE)
        return TaskDecision(
            action=Action.DECOMPOSE,
            children=tuple(
                TaskSpec(
                    description=child.description,
                    task_name=child.task_name,
                    tool_hint=child.tool_hint,
                    depends_on_siblings=list(child.depends_on_siblings),
                    query_unit_ids=list(child.query_unit_ids),
                )
                for child in intent.children
            ),
            tool_request=None,
            wait_for=(),
            output=None,
            facts={},
        )

    if has_publish:
        return TaskDecision(
            action=Action.AGGREGATE,
            children=(),
            tool_request=None,
            wait_for=(),
            output=intent.output,
            facts=dict(intent.facts),
        )

    if intent.action is None:
        raise _invalid_task_decision(
            "missing action and no structured fields (tool_request, children, wait_for, output, facts)",
            raw_for_error,
        )

    raise _invalid_task_decision(
        f"{intent.action.value} action could not be mapped to a task decision",
        raw_for_error,
    )


def _validate_tool_and_build_request(
    payload: _ToolRequestPayload,
    raw: dict[str, Any],
) -> ToolRequest:
    normalized_tool_args: dict[str, Any] | None = None
    try:
        spec = get_tool_spec(payload.tool_name)
    except RuntimeError:
        normalized_tool_args = dict(payload.args)
    else:
        try:
            normalized_tool_args = spec.validate_args(payload.args)
        except ValueError as exc:
            raise ValueError(
                "invalid task decision payload: "
                f"{exc}; raw_payload={json.dumps(raw, ensure_ascii=False, default=str)}"
            ) from exc
    return ToolRequest(
        tool_name=payload.tool_name,
        args=(
            normalized_tool_args
            if normalized_tool_args is not None
            else dict(payload.args)
        ),
    )


def _intent_parse_candidates(initial: dict[str, Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    # Salvage-merged payloads first so embedded tool_request/children win over action-only stubs.
    for cand in salvage_decision_candidates(initial) + [initial]:
        normalized = normalize_decision_raw(dict(cand))
        key = json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(normalized)
    return out


def parse_decision(
    task: Task,
    raw: dict[str, Any],
    *,
    allow_decompose: bool = True,
) -> TaskDecision:
    allowed = frozenset(allowed_actions_for_task(task, allow_decompose=allow_decompose))
    validated: list[tuple[dict[str, Any], StepIntentPayload]] = []
    first_error: ValidationError | None = None
    for normalized in _intent_parse_candidates(dict(raw)):
        try:
            validated.append((normalized, StepIntentPayload.model_validate(normalized)))
        except ValidationError as exc:
            if first_error is None:
                first_error = exc
    if not validated:
        raise ValueError(
            "invalid task decision payload: "
            f"{first_error}; raw_payload={json.dumps(raw, ensure_ascii=False, default=str)}"
        ) from first_error
    intent: StepIntentPayload | None = None
    raw_work: dict[str, Any] | None = None
    for normalized, it in validated:
        if has_structural_intent(it):
            raw_work = normalized
            intent = it
            break
    if intent is None:
        raw_work, intent = validated[0]
    raw = raw_work
    decision = map_intent_to_task_decision(task, intent, allowed, raw_for_error=raw)
    if decision.tool_request is None:
        return decision

    tr = _validate_tool_and_build_request(
        _ToolRequestPayload(
            tool_name=decision.tool_request.tool_name,
            args=dict(decision.tool_request.args),
        ),
        raw,
    )
    return TaskDecision(
        action=decision.action,
        children=decision.children,
        tool_request=tr,
        wait_for=decision.wait_for,
        output=decision.output,
        facts=decision.facts,
    )


def salvage_decision_candidates(raw: dict[str, Any]) -> list[dict[str, Any]]:
    merged = dict(raw)
    merged_changed = False
    candidates: list[dict[str, Any]] = []
    raw_action = raw.get("action")

    for value in raw.values():
        if not isinstance(value, str):
            continue
        for embedded in embedded_json_objects(value):
            embedded_action = embedded.get("action")
            if embedded_action is not None and (
                raw_action is None or embedded_action == raw_action
            ):
                candidates.append(dict(embedded))

            for key in (
                "children",
                "tool_request",
                "wait_for",
                "output",
                "facts",
            ):
                if key in merged or key not in embedded:
                    continue
                merged[key] = embedded[key]
                merged_changed = True

            if (
                raw_action == Action.EXECUTE.value
                and "tool_request" not in merged
                and "tool_name" in embedded
                and "args" in embedded
            ):
                merged["tool_request"] = embedded
                merged_changed = True

    if merged_changed:
        candidates.append(merged)

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = json.dumps(candidate, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def embedded_json_objects(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(candidate, dict):
            continue
        key = json.dumps(candidate, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        objects.append(candidate)
    return objects
