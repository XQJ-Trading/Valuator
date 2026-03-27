from __future__ import annotations

from typing import Any

import pytest

from domain.query import QueryAnalysis
from valuator.core.context import TaskContext, TaskSummary
from valuator.core.shared_state import SharedStateView
from valuator.core.step_planner import StepPlanner
from valuator.core.types import TaskState
from valuator.core.task import AtomicTask, ComplexTask


class ScriptedLLM:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def generate_json(
        self,
        *,
        prompt: str,
        system_prompt: str = "",
        response_json_schema: dict[str, Any],
        trace_method: str,
        max_response_chars: int | None = None,
    ) -> dict[str, Any]:
        del trace_method, max_response_chars
        self.calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "response_json_schema": response_json_schema,
            }
        )
        if not self._responses:
            raise AssertionError("no scripted response left")
        payload = self._responses.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload


def _context(*, available_tools: list[str]) -> TaskContext:
    return TaskContext(
        task_id="task",
        description="collect current facts",
        step_count=0,
        shared=SharedStateView({}, []),
        query="Amazon analysis",
        query_analysis=QueryAnalysis(),
        available_tools=available_tools,
    )


@pytest.mark.asyncio
async def test_step_planner_repairs_invalid_execute_payload() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "execute",
                "reason": "need current data",
            },
            {
                "action": "execute",
                "tool_request": {
                    "tool_name": "web_search_tool",
                    "args": {"query": "Amazon segment revenue 2024"},
                },
                "reason": "search current segment data",
            },
        ]
    )
    planner = StepPlanner(llm, repair_retries=1)
    task = AtomicTask(
        id="root.0",
        description="collect Amazon segment data",
        tool_hint="web_search_tool",
    )

    decision = await planner.decide(task, _context(available_tools=["web_search_tool"]))

    assert decision.action.value == "execute"
    assert decision.tool_request is not None
    assert decision.tool_request.tool_name == "web_search_tool"
    assert decision.tool_request.args == {"query": "Amazon segment revenue 2024"}
    assert len(llm.calls) == 2
    assert "[REPAIR]" in llm.calls[1]["prompt"]


@pytest.mark.asyncio
async def test_step_planner_salvages_tool_request_embedded_in_reason() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "execute",
                "reason": (
                    "Search current market data.\n"
                    '{"tool_name":"web_search_tool","args":{"query":"Amazon '
                    'competitive strategy","search_mode":"web"}}'
                ),
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = AtomicTask(
        id="root.0",
        description="collect Amazon segment data",
        tool_hint="web_search_tool",
    )

    decision = await planner.decide(task, _context(available_tools=["web_search_tool"]))

    assert decision.action.value == "execute"
    assert decision.tool_request is not None
    assert decision.tool_request.tool_name == "web_search_tool"
    assert decision.tool_request.args == {
        "query": "Amazon competitive strategy",
        "search_mode": "web",
    }


@pytest.mark.asyncio
async def test_step_planner_salvages_embedded_decompose_payload_from_reason() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "decompose",
                "reason": (
                    "Return this payload instead:\n"
                    '{"action":"decompose","children":[{"description":"collect '
                    'demand","tool_hint":"web_search_tool"},{"description":"summarize '
                    'results"}],"reason":"split work"}'
                ),
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = ComplexTask(id="root", description="root task")

    decision = await planner.decide(task, _context(available_tools=["web_search_tool"]))

    assert decision.action.value == "decompose"
    assert [child.description for child in decision.children] == [
        "collect demand",
        "summarize results",
    ]
    assert decision.children[0].tool_hint == "web_search_tool"


@pytest.mark.asyncio
async def test_step_planner_rejects_finalize_on_non_root_task() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "finalize",
                "output": "done",
                "reason": "complete",
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = ComplexTask(id="root.1", description="child task")
    task.parent_id = "root"

    with pytest.raises(
        ValueError,
        match="finalize is only allowed for root tasks",
    ):
        await planner.decide(task, _context(available_tools=["web_search_tool"]))


@pytest.mark.asyncio
async def test_step_planner_requery_without_decompose_adds_rejection_context() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "aggregate",
                "output": "done",
                "reason": "finish without decomposition",
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = ComplexTask(id="root", description="root task")

    decision = await planner.requery_without_decompose(
        task,
        _context(available_tools=["web_search_tool"]),
        "children overlap too much",
    )

    assert decision.action.value == "aggregate"
    assert "[DECOMPOSITION_REJECTED]" in llm.calls[0]["prompt"]
    assert "children overlap too much" in llm.calls[0]["prompt"]
    assert "DECOMPOSE: break the task into smaller children." not in llm.calls[0][
        "system_prompt"
    ]


@pytest.mark.asyncio
async def test_step_planner_requery_without_decompose_rejects_second_decompose() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "decompose",
                "children": [{"description": "still split"}],
                "reason": "try again",
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = ComplexTask(id="root", description="root task")

    with pytest.raises(
        ValueError,
        match="requery_without_decompose returned decompose",
    ):
        await planner.requery_without_decompose(
            task,
            _context(available_tools=["web_search_tool"]),
            "decomposition was rejected",
        )


@pytest.mark.asyncio
async def test_step_planner_rejects_aggregate_without_output_or_facts() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "aggregate",
                "reason": "done",
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = AtomicTask(id="root.0", description="child task")

    with pytest.raises(
        ValueError,
        match="aggregate action requires output or facts",
    ):
        await planner.decide(task, _context(available_tools=["web_search_tool"]))


@pytest.mark.asyncio
async def test_step_planner_prompt_includes_current_children_and_done_sibling_output() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "aggregate",
                "output": "done",
                "reason": "complete",
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = ComplexTask(id="root", description="root task")
    sibling = TaskSummary(
        id="root.1",
        description="sibling task",
        state=TaskState.DONE,
        output={"summary": "finished"},
    )
    child = TaskSummary(
        id="root.0",
        description="existing child",
        state=TaskState.WAITING,
    )
    ctx = TaskContext(
        task_id="root",
        description="root task",
        step_count=1,
        current_children=[child],
        siblings={"root.1": sibling},
        shared=SharedStateView({}, []),
        query="[THINKING_LEVEL]\nhigh\n\n[QUERY]\nAmazon analysis",
        query_analysis=QueryAnalysis(),
        available_tools=["web_search_tool"],
    )

    await planner.decide(task, ctx)

    prompt = llm.calls[0]["prompt"]
    assert "[CURRENT_CHILDREN]" in prompt
    assert "root.0: waiting - existing child" in prompt
    assert "[SIBLINGS]" in prompt
    assert 'output={"summary": "finished"}' in prompt
    assert "[THINKING_LEVEL]" not in llm.calls[0]["system_prompt"]


@pytest.mark.asyncio
async def test_step_planner_excludes_execute_after_successful_tool_result() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "aggregate",
                "output": "done",
                "reason": "tool result is already enough",
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = AtomicTask(
        id="root.0",
        description="summarize the tool result",
        tool_hint="web_search_tool",
    )
    task.last_tool_success = True

    decision = await planner.decide(task, _context(available_tools=["web_search_tool"]))

    assert decision.action.value == "aggregate"
    assert llm.calls[0]["response_json_schema"]["$defs"]["Action"]["enum"] == [
        "decompose",
        "wait",
        "aggregate",
        "finalize",
        "fail",
    ]
    assert "EXECUTE:" not in llm.calls[0]["system_prompt"]
    assert "This task already has a tool result." in llm.calls[0][
        "system_prompt"
    ]


@pytest.mark.asyncio
async def test_step_planner_repairs_invalid_json_error_from_llm() -> None:
    llm = ScriptedLLM(
        [
            ValueError("agent.step.root returned invalid JSON"),
            {
                "action": "aggregate",
                "output": "done",
                "reason": "repair succeeded",
            },
        ]
    )
    planner = StepPlanner(llm, repair_retries=1)
    task = AtomicTask(id="root", description="repair invalid response")

    decision = await planner.decide(task, _context(available_tools=["web_search_tool"]))

    assert decision.action.value == "aggregate"
    assert len(llm.calls) == 2
    assert "[REPAIR]" in llm.calls[1]["prompt"]
    assert "agent.step.root returned invalid JSON" in llm.calls[1]["prompt"]
    assert "[PREVIOUS_JSON]" not in llm.calls[1]["prompt"]


@pytest.mark.asyncio
async def test_finalize_prompt_includes_synthesis_guidance() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "finalize",
                "output": "final report",
                "reason": "all data collected",
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = ComplexTask(id="root", description="Amazon valuation")

    await planner.decide(task, _context(available_tools=["web_search_tool"]))

    system = llm.calls[0]["system_prompt"]
    assert "FINALIZE" in system
    assert "Bull / Base / Bear" in system
    assert "uncertainties" in system.lower()
    assert "INFORMATION GAPS" in system
