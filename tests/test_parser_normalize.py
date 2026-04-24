from __future__ import annotations

from valuator.core.planning.parser import (
    TASK_NAME_MAX_CHARS,
    normalize_decision_raw,
    parse_decision,
    truncate_task_name,
)
from valuator.core.task import AtomicTask, ComplexTask
from valuator.core.types import Action, ToolResult


def test_truncate_task_name_respects_max_and_strips_trailing_underscore() -> None:
    assert (
        len(truncate_task_name("a" * (TASK_NAME_MAX_CHARS + 1))) == TASK_NAME_MAX_CHARS
    )
    assert truncate_task_name("  child_task  ") == "child_task"
    assert (
        truncate_task_name("x" * (TASK_NAME_MAX_CHARS + 5)) == "x" * TASK_NAME_MAX_CHARS
    )
    padded = "a" * (TASK_NAME_MAX_CHARS + 1)
    assert len(padded) == TASK_NAME_MAX_CHARS + 1
    assert truncate_task_name(padded) == "a" * TASK_NAME_MAX_CHARS


def test_normalize_aggregate_with_wait_for_becomes_wait() -> None:
    raw = {
        "action": "aggregate",
        "reason": "need more",
        "wait_for": ["root.0", "root.1"],
    }
    out = normalize_decision_raw(raw)
    assert out["action"] == Action.WAIT.value


def test_normalize_aggregate_with_output_unchanged() -> None:
    raw = {
        "action": "aggregate",
        "output": {"summary": "x"},
        "wait_for": ["root.1"],
    }
    out = normalize_decision_raw(raw)
    assert out["action"] == Action.AGGREGATE.value


def test_normalize_aggregate_with_nonempty_facts_unchanged() -> None:
    raw = {
        "action": "aggregate",
        "facts": {"k": {"value": 1}},
        "wait_for": ["root.1"],
    }
    out = normalize_decision_raw(raw)
    assert out["action"] == Action.AGGREGATE.value


def test_normalize_aggregate_with_tool_request_becomes_execute() -> None:
    raw = {
        "action": "aggregate",
        "tool_request": {
            "tool_name": "unknown_tool",
            "args": {"query": "alpha"},
        },
    }
    out = normalize_decision_raw(raw)
    assert out["action"] == Action.EXECUTE.value


def test_normalize_decompose_without_children_with_wait_becomes_wait() -> None:
    raw = {
        "action": "decompose",
        "wait_for": ["root.0"],
        "reason": "split later",
    }
    out = normalize_decision_raw(raw)
    assert out["action"] == Action.WAIT.value


def test_parse_decision_aggregate_wait_mix_produces_wait() -> None:
    task = AtomicTask(
        id="root.3.2",
        description="val",
        tool_hint="",
    )
    decision = parse_decision(
        task,
        {
            "action": "aggregate",
            "reason": "siblings failed",
            "wait_for": ["root.3.0", "root.3.1"],
        },
    )
    assert decision.action is Action.WAIT
    assert list(decision.wait_for) == ["root.3.0", "root.3.1"]


def test_parse_decision_decompose_wait_mix_produces_wait() -> None:
    task = AtomicTask(id="root.1", description="x", tool_hint="")
    decision = parse_decision(
        task,
        {
            "action": "decompose",
            "wait_for": ["root.0"],
            "reason": "need facts first",
        },
    )
    assert decision.action is Action.WAIT
    assert list(decision.wait_for) == ["root.0"]


def test_parse_decision_wait_without_action_uses_mapper() -> None:
    task = AtomicTask(id="root.0", description="x", tool_hint="")
    decision = parse_decision(
        task,
        {"wait_for": ["root.1"], "reason": "need sibling output"},
    )
    assert decision.action is Action.WAIT
    assert list(decision.wait_for) == ["root.1"]


def test_parse_decision_rejects_decompose_when_disallowed() -> None:
    task = AtomicTask(id="root", description="x", tool_hint="")
    try:
        parse_decision(
            task,
            {
                "children": [
                    {
                        "description": "child",
                        "task_name": "child_task",
                    }
                ],
                "reason": "split",
            },
            allow_decompose=False,
        )
    except ValueError as exc:
        assert "action is not allowed for this task" in str(exc)
        assert "requested=decompose" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_parse_decision_rejects_execute_after_successful_tool() -> None:
    task = AtomicTask(id="root.0", description="x", tool_hint="")
    task.last_tool_success = True
    try:
        parse_decision(
            task,
            {
                "tool_request": {
                    "tool_name": "unknown_tool",
                    "args": {},
                },
                "reason": "retry tool",
            },
        )
    except ValueError as exc:
        assert "action is not allowed for this task" in str(exc)
        assert "requested=execute" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_parse_decision_prefers_explicit_execute_over_stray_wait_for() -> None:
    task = AtomicTask(id="root.0", description="x", tool_hint="web_search_tool")

    decision = parse_decision(
        task,
        {
            "action": "execute",
            "tool_request": {
                "tool_name": "unknown_tool",
                "args": {"query": "alpha"},
            },
            "wait_for": ["root.1"],
        },
    )

    assert decision.action is Action.EXECUTE
    assert decision.tool_request is not None
    assert decision.tool_request.args == {"query": "alpha"}
    assert decision.wait_for == ()


def test_parse_decision_aggregate_with_tool_request_recovers_to_execute() -> None:
    task = AtomicTask(id="root.0", description="need one more tool call", tool_hint="dummy_tool")

    decision = parse_decision(
        task,
        {
            "action": "aggregate",
            "reason": "need a tool call before summarizing",
            "tool_request": {
                "tool_name": "unknown_tool",
                "args": {"value": "alpha"},
            },
        },
    )

    assert decision.action is Action.EXECUTE
    assert decision.tool_request is not None
    assert decision.tool_request.args == {"value": "alpha"}


def test_parse_decision_implicit_aggregate_merges_facts_only_child_outputs() -> None:
    task = ComplexTask(id="root.0", description="aggregate child facts")
    task.child_outputs = {
        "root.0.0": {
            "status": "facts_only",
            "facts": {"alpha": "ready"},
            "source_task_id": "root.0.0",
        },
        "root.0.1": {
            "status": "facts_only",
            "facts": {"beta": "ready"},
            "source_task_id": "root.0.1",
        },
    }

    decision = parse_decision(
        task,
        {
            "action": "aggregate",
            "reason": "children are done",
        },
    )

    assert decision.action is Action.AGGREGATE
    assert decision.output is None
    assert decision.facts == {"alpha": "ready", "beta": "ready"}


def test_parse_decision_implicit_aggregate_uses_last_tool_result_when_available() -> None:
    task = AtomicTask(id="root.0", description="summarize tool result")
    task.last_tool_success = True
    task.tool_results.append(
        ToolResult(success=True, result={"summary": "tool output"})
    )

    decision = parse_decision(
        task,
        {
            "action": "aggregate",
            "reason": "tool result is enough",
        },
    )

    assert decision.action is Action.AGGREGATE
    assert decision.output == {"summary": "tool output"}
    assert decision.facts == {}


def test_parse_decision_empty_decompose_recovers_to_aggregate_from_tool_result() -> None:
    task = AtomicTask(id="root.0", description="summarize tool result")
    task.last_tool_success = True
    task.tool_results.append(
        ToolResult(success=True, result={"summary": "tool output"})
    )

    decision = parse_decision(
        task,
        {
            "action": "decompose",
            "reason": "split later",
        },
    )

    assert decision.action is Action.AGGREGATE
    assert decision.output == {"summary": "tool output"}
    assert decision.facts == {}
