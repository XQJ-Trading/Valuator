from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from domain.query import QueryAnalysis
from valuator.core.decomposition_types import GateConfig
from valuator.core import Agent, AgentEvent, ComplexTask, Scheduler, SharedState, StepPlanner, TaskState
from valuator.tools.base import BaseTool, ToolRegistry, ToolResult
from valuator.utils.session_trace import SessionTraceWriter


class DummyTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(name="dummy_tool", description="dummy tool")
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        value = kwargs.get("value", "")
        self.calls.append(dict(kwargs))
        return ToolResult(
            success=True,
            result={"findings": f"value={value}"},
            metadata={"value": value},
        )

    def get_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"value": {"type": "string"}}}


class LatencyTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(name="latency_tool", description="tool with controlled delay")

    async def execute(self, **kwargs: Any) -> ToolResult:
        await asyncio.sleep(float(kwargs.get("delay", 0)))
        return ToolResult(
            success=True,
            result={"findings": f"delay={kwargs.get('delay', 0)}"},
        )

    def get_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"delay": {"type": "number"}},
        }


class ScriptedLLM:
    def __init__(self, responses: dict[str, list[Any]]) -> None:
        self._responses = {task_id: list(items) for task_id, items in responses.items()}
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
        del response_json_schema, max_response_chars
        self.calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "trace_method": trace_method,
            }
        )
        key = trace_method
        if key not in self._responses and trace_method.startswith("agent.step."):
            key = trace_method.removeprefix("agent.step.")
        queue = self._responses[key]
        if not queue:
            raise AssertionError(f"no scripted response left for {key}")
        payload = queue.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload


@pytest.mark.asyncio
async def test_agent_run_decomposes_waits_and_finalizes() -> None:
    registry = ToolRegistry()
    registry.register(DummyTool())

    llm = ScriptedLLM(
        {
            "root": [
                {
                    "action": "decompose",
                    "children": [
                        {"description": "collect alpha", "tool_hint": "dummy_tool"},
                        {"description": "consume alpha"},
                    ],
                    "reason": "split work",
                },
                {
                    "action": "wait",
                    "wait_for": ["root.1"],
                    "reason": "wait for remaining child",
                },
                {
                    "action": "finalize",
                    "output": "# Final\n\nalpha complete",
                    "reason": "all children complete",
                },
            ],
            "root.0": [
                {
                    "action": "execute",
                    "tool_request": {
                        "tool_name": "dummy_tool",
                        "args": {"value": "alpha"},
                    },
                    "reason": "run tool",
                },
                {
                    "action": "aggregate",
                    "output": "alpha collected",
                    "facts": {"alpha": "ready"},
                    "reason": "publish alpha",
                },
            ],
            "root.1": [
                {
                    "action": "wait",
                    "wait_for_facts": ["alpha"],
                    "reason": "need alpha fact",
                },
                {
                    "action": "aggregate",
                    "output": "alpha consumed",
                    "reason": "fact available",
                },
            ],
        }
    )
    agent = Agent(
        scheduler=Scheduler(max_steps_per_task=10, concurrency=4),
        shared_state=SharedState(),
        tool_registry=registry,
        llm_client=llm,  # type: ignore[arg-type]
        query_analysis=QueryAnalysis(allowed_tools=["dummy_tool"]),
        gate_config=GateConfig(enabled=False),
    )

    root = ComplexTask(id="root", description="root valuation task")
    output = await agent.run("alpha query", root)

    assert output == "# Final\n\nalpha complete"
    assert root.state is TaskState.DONE
    assert root.step_count == 3
    assert root.child_outputs == {
        "root.0": "alpha collected",
        "root.1": "alpha consumed",
    }


@pytest.mark.asyncio
async def test_invalid_decision_does_not_increment_step_count() -> None:
    llm = ScriptedLLM(
        {
            "root": [
                {
                    "action": "execute",
                    "reason": "missing tool request",
                },
                {
                    "action": "finalize",
                    "output": "done",
                    "reason": "complete",
                },
            ]
        }
    )
    events: list[AgentEvent] = []

    async def on_event(event: AgentEvent) -> None:
        events.append(event)

    agent = Agent(
        scheduler=Scheduler(max_steps_per_task=10, concurrency=1),
        shared_state=SharedState(),
        tool_registry=ToolRegistry(),
        llm_client=llm,  # type: ignore[arg-type]
        query_analysis=QueryAnalysis(),
        on_event=on_event,
        step_planner=StepPlanner(llm, repair_retries=0),
    )

    root = ComplexTask(id="root", description="root valuation task")
    output = await agent.run("alpha query", root)

    assert output == "done"
    assert root.step_count == 1
    assert root.invalid_decision_count == 1
    assert any(event.type == "step_invalid" for event in events)
    step_start_events = [event for event in events if event.type == "step_start"]
    assert [event.detail["global_seq"] for event in step_start_events] == [1, 2]
    assert [event.detail["step"] for event in step_start_events] == [1, 1]


@pytest.mark.asyncio
async def test_agent_blocks_duplicate_execute_after_successful_tool() -> None:
    registry = ToolRegistry()
    tool = DummyTool()
    registry.register(tool)

    llm = ScriptedLLM(
        {
            "root": [
                {
                    "action": "decompose",
                    "children": [
                        {"description": "collect alpha", "tool_hint": "dummy_tool"},
                    ],
                    "reason": "split work",
                },
                {
                    "action": "finalize",
                    "output": "done",
                    "reason": "all children complete",
                },
            ],
            "root.0": [
                {
                    "action": "execute",
                    "tool_request": {
                        "tool_name": "dummy_tool",
                        "args": {"value": "alpha"},
                    },
                    "reason": "run tool",
                },
                {
                    "action": "execute",
                    "tool_request": {
                        "tool_name": "dummy_tool",
                        "args": {"value": "beta"},
                    },
                    "reason": "retry tool again",
                },
                {
                    "action": "aggregate",
                    "output": "alpha collected",
                    "reason": "done after tool",
                },
            ],
        }
    )
    events: list[AgentEvent] = []

    async def on_event(event: AgentEvent) -> None:
        events.append(event)

    agent = Agent(
        scheduler=Scheduler(max_steps_per_task=10, concurrency=2),
        shared_state=SharedState(),
        tool_registry=registry,
        llm_client=llm,  # type: ignore[arg-type]
        query_analysis=QueryAnalysis(allowed_tools=["dummy_tool"]),
        on_event=on_event,
    )

    root = ComplexTask(id="root", description="root valuation task")
    output = await agent.run("alpha query", root)
    child = root.children()[0]

    assert output == "done"
    assert len(tool.calls) == 1
    assert child.step_count == 2
    assert child.invalid_decision_count == 1
    assert any(event.type == "step_invalid" for event in events)
    tool_events = [event for event in events if event.type == "tool_execute"]
    assert len(tool_events) == 1
    assert "duration_ms" in tool_events[0].detail
    child_calls = [
        call for call in llm.calls if call["trace_method"] == "agent.step.root.0"
    ]
    assert len(child_calls) == 3
    assert "[PREVIOUS_REJECTION]" in child_calls[2]["prompt"]
    assert (
        "execute action is not allowed after a successful tool result"
        in child_calls[2]["prompt"]
    )


@pytest.mark.asyncio
async def test_agent_streams_new_ready_tasks_while_siblings_are_still_running() -> None:
    registry = ToolRegistry()
    registry.register(LatencyTool())

    llm = ScriptedLLM(
        {
            "root": [
                {
                    "action": "decompose",
                    "children": [
                        {"description": "produce alpha", "tool_hint": "latency_tool"},
                        {"description": "slow sibling", "tool_hint": "latency_tool"},
                        {"description": "consume alpha"},
                    ],
                    "reason": "split work",
                },
                {
                    "action": "finalize",
                    "output": "done",
                    "reason": "all children complete",
                },
            ],
            "root.0": [
                {
                    "action": "execute",
                    "tool_request": {
                        "tool_name": "latency_tool",
                        "args": {"delay": 0.01},
                    },
                    "reason": "produce quickly",
                },
                {
                    "action": "aggregate",
                    "output": "alpha produced",
                    "facts": {"alpha": "ready"},
                    "reason": "publish fact",
                },
            ],
            "root.1": [
                {
                    "action": "execute",
                    "tool_request": {
                        "tool_name": "latency_tool",
                        "args": {"delay": 0.2},
                    },
                    "reason": "take longer",
                },
                {
                    "action": "aggregate",
                    "output": "slow work done",
                    "reason": "complete slow work",
                },
            ],
            "root.2": [
                {
                    "action": "wait",
                    "wait_for_facts": ["alpha"],
                    "reason": "need alpha",
                },
                {
                    "action": "aggregate",
                    "output": "alpha consumed",
                    "reason": "fact available",
                },
            ],
        }
    )
    events: list[AgentEvent] = []

    async def on_event(event: AgentEvent) -> None:
        events.append(event)

    agent = Agent(
        scheduler=Scheduler(max_steps_per_task=10, concurrency=3),
        shared_state=SharedState(),
        tool_registry=registry,
        llm_client=llm,  # type: ignore[arg-type]
        query_analysis=QueryAnalysis(allowed_tools=["latency_tool"]),
        on_event=on_event,
        gate_config=GateConfig(enabled=False),
    )

    output = await agent.run("alpha query", ComplexTask(id="root", description="root"))

    assert output == "done"
    event_order = [
        (event.type, event.task_id)
        for event in events
        if event.type in {"tool_execute", "task_done"}
    ]

    assert ("task_done", "root.0") in event_order
    assert ("tool_execute", "root.1") in event_order
    assert event_order.index(("task_done", "root.0")) < event_order.index(
        ("tool_execute", "root.1")
    )


@pytest.mark.asyncio
async def test_agent_writes_method_trace_without_sequence_collisions(
    tmp_path: Path,
) -> None:
    registry = ToolRegistry()
    registry.register(DummyTool())
    writer = SessionTraceWriter(
        session_id="S-agent-trace",
        query="alpha query",
        model="gemini-3-flash-preview",
        created_at="2026-03-21T02:31:05.577471Z",
        base_dir=tmp_path,
    )

    llm = ScriptedLLM(
        {
            "root": [
                {
                    "action": "decompose",
                    "children": [
                        {"description": "collect alpha", "tool_hint": "dummy_tool"},
                        {"description": "consume alpha"},
                    ],
                    "reason": "split work",
                },
                {
                    "action": "wait",
                    "wait_for": ["root.1"],
                    "reason": "wait for remaining child",
                },
                {
                    "action": "finalize",
                    "output": "# Final\n\nalpha complete",
                    "reason": "all children complete",
                },
            ],
            "root.0": [
                {
                    "action": "execute",
                    "tool_request": {
                        "tool_name": "dummy_tool",
                        "args": {"value": "alpha"},
                    },
                    "reason": "run tool",
                },
                {
                    "action": "aggregate",
                    "output": "alpha collected",
                    "facts": {"alpha": "ready"},
                    "reason": "publish alpha",
                },
            ],
            "root.1": [
                {
                    "action": "wait",
                    "wait_for_facts": ["alpha"],
                    "reason": "need alpha fact",
                },
                {
                    "action": "aggregate",
                    "output": "alpha consumed",
                    "reason": "fact available",
                },
            ],
        }
    )
    agent = Agent(
        scheduler=Scheduler(max_steps_per_task=10, concurrency=4),
        shared_state=SharedState(),
        tool_registry=registry,
        llm_client=llm,  # type: ignore[arg-type]
        query_analysis=QueryAnalysis(allowed_tools=["dummy_tool"]),
        trace_writer=writer,
        gate_config=GateConfig(enabled=False),
    )

    output = await agent.run("alpha query", ComplexTask(id="root", description="root"))
    rows = [
        json.loads(line)
        for line in (tmp_path / "session_S-agent-trace" / "output" / "method_calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert output == "# Final\n\nalpha complete"
    assert rows
    assert {row["category"] for row in rows} >= {"decision", "tool_execution", "task"}

    sequences = [row["sequence"] for row in rows]
    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences))


@pytest.mark.asyncio
async def test_agent_requeries_when_static_gate_rejects_decomposition() -> None:
    llm = ScriptedLLM(
        {
            "root": [
                {
                    "action": "decompose",
                    "children": [
                        {"description": "collect alpha"},
                        {"description": "collect beta"},
                    ],
                    "reason": "split work",
                },
                {
                    "action": "finalize",
                    "output": "done without decomposition",
                    "reason": "fallback decision",
                },
            ]
        }
    )
    events: list[AgentEvent] = []

    async def on_event(event: AgentEvent) -> None:
        events.append(event)

    agent = Agent(
        scheduler=Scheduler(max_steps_per_task=10, concurrency=1),
        shared_state=SharedState(),
        tool_registry=ToolRegistry(),
        llm_client=llm,  # type: ignore[arg-type]
        query_analysis=QueryAnalysis(),
        on_event=on_event,
        gate_config=GateConfig(accept_bound=0.5, reject_bound=-0.05),
    )

    root = ComplexTask(id="root", description="root valuation task")
    output = await agent.run("alpha query", root)
    gated = [event for event in events if event.type == "decomposition_gated"]

    assert output == "done without decomposition"
    assert root.step_count == 1
    assert root.children() == []
    assert agent._tracker.has_prediction("root") is False
    assert len(gated) == 1
    assert gated[0].detail["static_verdict"] == "reject"
    assert gated[0].detail["used_critic"] is False


@pytest.mark.asyncio
async def test_agent_allows_uncertain_decomposition_with_critic_and_updates_threshold() -> None:
    registry = ToolRegistry()
    tool = DummyTool()
    registry.register(tool)

    llm = ScriptedLLM(
        {
            "root": [
                {
                    "action": "decompose",
                    "children": [
                        {"description": "collect alpha", "tool_hint": "dummy_tool"},
                    ],
                    "reason": "split work",
                },
                {
                    "action": "aggregate",
                    "output": "root complete",
                    "reason": "child complete",
                },
            ],
            "root.0": [
                {
                    "action": "execute",
                    "tool_request": {
                        "tool_name": "dummy_tool",
                        "args": {"value": "alpha"},
                    },
                    "reason": "run tool",
                },
                {
                    "action": "aggregate",
                    "output": "alpha collected",
                    "reason": "done",
                },
            ],
            "agent.gate.critic.root": [
                {
                    "allow": True,
                    "single_tool_possible": False,
                    "redundant_pairs": [],
                    "coverage_pct": 0,
                    "min_children": 1,
                    "reason": "acceptable split",
                }
            ],
        }
    )
    agent = Agent(
        scheduler=Scheduler(max_steps_per_task=10, concurrency=2),
        shared_state=SharedState(),
        tool_registry=registry,
        llm_client=llm,  # type: ignore[arg-type]
        query_analysis=QueryAnalysis(allowed_tools=["dummy_tool"]),
        gate_config=GateConfig(accept_bound=0.5, reject_bound=-0.05),
    )

    output = await agent.run("alpha query", ComplexTask(id="root", description="root"))

    assert output == "root complete"
    assert len(tool.calls) == 1
    assert agent._tracker.current_threshold() == pytest.approx(-0.0208)


@pytest.mark.asyncio
async def test_agent_requeries_when_critic_rejects_uncertain_decomposition() -> None:
    llm = ScriptedLLM(
        {
            "root": [
                {
                    "action": "decompose",
                    "children": [
                        {"description": "collect alpha", "tool_hint": "dummy_tool"},
                    ],
                    "reason": "split work",
                },
                {
                    "action": "aggregate",
                    "output": "fallback",
                    "reason": "avoid decomposition",
                },
            ],
            "agent.gate.critic.root": [
                {
                    "allow": False,
                    "single_tool_possible": True,
                    "redundant_pairs": [],
                    "coverage_pct": 0,
                    "min_children": 0,
                    "reason": "single tool is enough",
                }
            ],
        }
    )
    events: list[AgentEvent] = []

    async def on_event(event: AgentEvent) -> None:
        events.append(event)

    agent = Agent(
        scheduler=Scheduler(max_steps_per_task=10, concurrency=1),
        shared_state=SharedState(),
        tool_registry=ToolRegistry(),
        llm_client=llm,  # type: ignore[arg-type]
        query_analysis=QueryAnalysis(allowed_tools=["dummy_tool"]),
        on_event=on_event,
        gate_config=GateConfig(accept_bound=0.5, reject_bound=-0.05),
    )

    output = await agent.run("alpha query", ComplexTask(id="root", description="root"))
    gated = [event for event in events if event.type == "decomposition_gated"]

    assert output == "fallback"
    assert len(gated) == 1
    assert gated[0].detail["static_verdict"] == "uncertain"
    assert gated[0].detail["used_critic"] is True
    assert gated[0].detail["static_score"] == pytest.approx(0.28)
    assert gated[0].detail["net_score"] == pytest.approx(-0.428)
    assert gated[0].detail["threshold"] == 0.0
    assert gated[0].detail["reason"] == "single tool is enough"
    assert agent._tracker.has_prediction("root") is False


@pytest.mark.asyncio
async def test_agent_falls_back_to_static_score_when_critic_fails() -> None:
    registry = ToolRegistry()
    tool = DummyTool()
    registry.register(tool)

    llm = ScriptedLLM(
        {
            "root": [
                {
                    "action": "decompose",
                    "children": [
                        {"description": "collect alpha", "tool_hint": "dummy_tool"},
                    ],
                    "reason": "split work",
                },
                {
                    "action": "aggregate",
                    "output": "root complete",
                    "reason": "child complete",
                },
            ],
            "root.0": [
                {
                    "action": "execute",
                    "tool_request": {
                        "tool_name": "dummy_tool",
                        "args": {"value": "alpha"},
                    },
                    "reason": "run tool",
                },
                {
                    "action": "aggregate",
                    "output": "alpha collected",
                    "reason": "done",
                },
            ],
            "agent.gate.critic.root": [RuntimeError("critic unavailable")],
        }
    )
    events: list[AgentEvent] = []

    async def on_event(event: AgentEvent) -> None:
        events.append(event)

    agent = Agent(
        scheduler=Scheduler(max_steps_per_task=10, concurrency=2),
        shared_state=SharedState(),
        tool_registry=registry,
        llm_client=llm,  # type: ignore[arg-type]
        query_analysis=QueryAnalysis(allowed_tools=["dummy_tool"]),
        on_event=on_event,
        gate_config=GateConfig(accept_bound=0.5, reject_bound=-0.05),
    )

    output = await agent.run("alpha query", ComplexTask(id="root", description="root"))

    assert output == "root complete"
    assert len(tool.calls) == 1
    assert agent._tracker.current_threshold() == pytest.approx(-0.022)
    assert not any(event.type == "decomposition_gated" for event in events)


@pytest.mark.asyncio
async def test_agent_rejects_duplicate_decomposition_against_existing_children() -> None:
    registry = ToolRegistry()
    tool = DummyTool()
    registry.register(tool)

    llm = ScriptedLLM(
        {
            "root": [
                {
                    "action": "decompose",
                    "children": [
                        {"description": "collect alpha", "tool_hint": "dummy_tool"},
                    ],
                    "reason": "split work",
                },
                {
                    "action": "decompose",
                    "children": [
                        {"description": " collect   alpha ", "tool_hint": "dummy_tool"},
                    ],
                    "reason": "split work again",
                },
                {
                    "action": "aggregate",
                    "output": "done",
                    "reason": "child complete",
                },
            ],
            "root.0": [
                {
                    "action": "execute",
                    "tool_request": {
                        "tool_name": "dummy_tool",
                        "args": {"value": "alpha"},
                    },
                    "reason": "run tool",
                },
                {
                    "action": "aggregate",
                    "output": "alpha collected",
                    "reason": "complete child",
                },
            ],
        }
    )
    events: list[AgentEvent] = []

    async def on_event(event: AgentEvent) -> None:
        events.append(event)

    agent = Agent(
        scheduler=Scheduler(max_steps_per_task=10, concurrency=2),
        shared_state=SharedState(),
        tool_registry=registry,
        llm_client=llm,  # type: ignore[arg-type]
        query_analysis=QueryAnalysis(allowed_tools=["dummy_tool"]),
        on_event=on_event,
    )

    root = ComplexTask(id="root", description="root")
    output = await agent.run("alpha query", root)

    assert output == "done"
    assert len(tool.calls) == 1
    assert len(root.children()) == 1
    assert root.step_count == 2
    assert root.invalid_decision_count == 1
    assert any(event.type == "step_invalid" and event.task_id == "root" for event in events)
    root_calls = [
        call for call in llm.calls if call["trace_method"] == "agent.step.root"
    ]
    assert len(root_calls) == 3
    assert "[CURRENT_CHILDREN]" in root_calls[1]["prompt"]
