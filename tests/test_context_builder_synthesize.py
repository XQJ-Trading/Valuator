"""Context builder synthesize tests — fact-layer filtering removed.

After removing the fact layer, SharedState.view_for() always returns an
empty view.  The test verifies that build_task_context still succeeds
in SYNTHESIZE phase and returns an empty shared view.
"""

from __future__ import annotations

from domain.query import QueryAnalysis, QueryUnit
from valuator.core.agent.context_builder import build_task_context
from valuator.core.scheduler import Scheduler
from valuator.core.shared_state import SharedState
from valuator.core.task import ComplexTask
from valuator.core.types import TaskWorkPhase
from valuator.tools.base import ToolRegistry


def test_synthesize_phase_returns_empty_shared_view() -> None:
    shared = SharedState()
    scheduler = Scheduler(max_steps_per_task=10, concurrency=1)
    parent = ComplexTask(id="root", description="parent", query_unit_ids=[0])
    parent.work_phase = TaskWorkPhase.SYNTHESIZE
    parent.child_outputs = {
        "root.0": {
            "status": "facts_only",
            "facts": {"entity_a": {"x": 1}},
        }
    }
    scheduler.register(parent)

    ctx = build_task_context(
        task=parent,
        query="q",
        scheduler=scheduler,
        analysis=QueryAnalysis(allowed_tools=["web_search_tool"]),
        shared=shared,
        tools=ToolRegistry(),
    )

    assert ctx.shared.facts == {}
    assert ctx.child_outputs == parent.child_outputs


def test_build_task_context_narrows_tools_from_task_execution_tool() -> None:
    shared = SharedState()
    scheduler = Scheduler(max_steps_per_task=10, concurrency=1)
    task = ComplexTask(
        id="root.0",
        description="official financials",
        execution_tool="opendart_financial_tool",
        query_unit_ids=[0],
    )
    scheduler.register(task)

    ctx = build_task_context(
        task=task,
        query="q",
        scheduler=scheduler,
        analysis=QueryAnalysis(
            units=[
                QueryUnit(
                    id="u0",
                    objective="collect official financials",
                    retrieval_query="q",
                )
            ],
            allowed_tools=[
                "opendart_financial_tool",
                "web_search_tool",
                "yfinance_balance_sheet",
            ],
        ),
        shared=shared,
        tools=ToolRegistry(),
    )

    assert ctx.available_tools == ["opendart_financial_tool"]


def test_build_task_context_keeps_task_tool_across_multiple_units() -> None:
    shared = SharedState()
    scheduler = Scheduler(max_steps_per_task=10, concurrency=1)
    task = ComplexTask(
        id="root.0",
        description="compatible units",
        execution_tool="opendart_financial_tool",
        query_unit_ids=[0, 1],
    )
    scheduler.register(task)

    ctx = build_task_context(
        task=task,
        query="q",
        scheduler=scheduler,
        analysis=QueryAnalysis(
            units=[
                QueryUnit(
                    id="u0",
                    objective="financials",
                    retrieval_query="q0",
                ),
                QueryUnit(
                    id="u1",
                    objective="more financials",
                    retrieval_query="q1",
                ),
            ],
            allowed_tools=[
                "opendart_financial_tool",
                "web_search_tool",
                "yfinance_balance_sheet",
            ],
        ),
        shared=shared,
        tools=ToolRegistry(),
    )

    assert ctx.available_tools == ["opendart_financial_tool"]


def test_build_task_context_has_no_tool_when_selected_tool_unavailable() -> None:
    shared = SharedState()
    scheduler = Scheduler(max_steps_per_task=10, concurrency=1)
    task = ComplexTask(
        id="root.0",
        description="official financials",
        execution_tool="opendart_financial_tool",
        query_unit_ids=[0],
    )
    scheduler.register(task)

    ctx = build_task_context(
        task=task,
        query="q",
        scheduler=scheduler,
        analysis=QueryAnalysis(
            units=[
                QueryUnit(
                    id="u0",
                    objective="official financials",
                    retrieval_query="q",
                )
            ],
            allowed_tools=["web_search_tool"],
        ),
        shared=shared,
        tools=ToolRegistry(),
    )

    assert ctx.available_tools == []


def test_build_task_context_leaves_tools_open_without_task_execution_tool() -> None:
    shared = SharedState()
    scheduler = Scheduler(max_steps_per_task=10, concurrency=1)
    task = ComplexTask(
        id="root.0",
        description="mixed units",
        query_unit_ids=[0, 1],
    )
    scheduler.register(task)

    ctx = build_task_context(
        task=task,
        query="q",
        scheduler=scheduler,
        analysis=QueryAnalysis(
            units=[
                QueryUnit(
                    id="u0",
                    objective="official financials",
                    retrieval_query="q0",
                ),
                QueryUnit(
                    id="u1",
                    objective="news",
                    retrieval_query="q1",
                ),
            ],
            allowed_tools=["opendart_financial_tool", "web_search_tool"],
        ),
        shared=shared,
        tools=ToolRegistry(),
    )

    assert ctx.available_tools == ["opendart_financial_tool", "web_search_tool"]
