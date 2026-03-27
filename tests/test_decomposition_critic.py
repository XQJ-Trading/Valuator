from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from domain.company import Company, Listing, Subject
from domain.query import QueryAnalysis, QueryIntent
from valuator.core.context import TaskContext, TaskSummary
from valuator.core.decomposition_critic import DecompositionCritic
from valuator.core.shared_state import SharedStateView
from valuator.core.task import ComplexTask
from valuator.core.types import Action, TaskDecision, TaskSpec, TaskState


class ScriptedLLM:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
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
        del max_response_chars
        self.calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "schema": response_json_schema,
                "trace_method": trace_method,
            }
        )
        if not self._responses:
            raise AssertionError("no scripted response left")
        return self._responses.pop(0)


def _context() -> TaskContext:
    return TaskContext(
        task_id="root",
        description="root task",
        step_count=0,
        ancestry=[
            TaskSummary(
                id="ancestor",
                description="ancestor task",
                state=TaskState.WAITING,
            )
        ],
        shared=SharedStateView({}, []),
        query="Amazon analysis",
        query_analysis=QueryAnalysis(),
        available_tools=["dummy_tool", "web_search_tool"],
    )


@pytest.mark.asyncio
async def test_decomposition_critic_maps_json_to_verdict() -> None:
    llm = ScriptedLLM(
        [
            {
                "allow": True,
                "single_tool_possible": False,
                "redundant_pairs": [[0, 1]],
                "coverage_pct": 75,
                "min_children": 1,
                "reason": "covers the parent goal",
            }
        ]
    )
    critic = DecompositionCritic(llm)
    task = ComplexTask(id="root", description="collect current facts")
    decision = TaskDecision(
        action=Action.DECOMPOSE,
        children=[
            TaskSpec(description="collect revenue", tool_hint="dummy_tool"),
            TaskSpec(description="collect filings", tool_hint="web_search_tool"),
        ],
        reason="split the work",
    )

    verdict = await critic.evaluate(task, decision, _context())

    assert verdict.allow is True
    assert verdict.redundant_pairs == [(0, 1)]
    assert verdict.coverage_pct == 75
    assert llm.calls[0]["trace_method"] == "agent.gate.critic.root"


@pytest.mark.asyncio
async def test_decomposition_critic_raises_on_invalid_payload() -> None:
    llm = ScriptedLLM(
        [
            {
                "allow": True,
                "single_tool_possible": False,
                "redundant_pairs": [],
                "coverage_pct": 101,
                "min_children": 1,
                "reason": "invalid",
            }
        ]
    )
    critic = DecompositionCritic(llm)
    task = ComplexTask(id="root", description="collect current facts")
    decision = TaskDecision(
        action=Action.DECOMPOSE,
        children=[TaskSpec(description="collect revenue", tool_hint="dummy_tool")],
        reason="split the work",
    )

    with pytest.raises(ValidationError):
        await critic.evaluate(task, decision, _context())


@pytest.mark.asyncio
async def test_decomposition_critic_prompt_contains_required_context() -> None:
    llm = ScriptedLLM(
        [
            {
                "allow": False,
                "single_tool_possible": True,
                "redundant_pairs": [],
                "coverage_pct": 20,
                "min_children": 0,
                "reason": "single tool is enough",
            }
        ]
    )
    critic = DecompositionCritic(llm)
    task = ComplexTask(id="root", description="collect current facts")
    decision = TaskDecision(
        action=Action.DECOMPOSE,
        children=[
            TaskSpec(description="collect revenue", tool_hint="dummy_tool"),
            TaskSpec(description="collect filings", tool_hint="web_search_tool"),
        ],
        reason="split the work",
    )

    await critic.evaluate(task, decision, _context())

    prompt = llm.calls[0]["prompt"]
    assert "[PARENT_TASK]" in prompt
    assert "collect current facts" in prompt
    assert "[PROPOSED_CHILDREN]" in prompt
    assert "collect revenue" in prompt
    assert "[ANCESTRY]" in prompt
    assert "ancestor task" in prompt
    assert "[AVAILABLE_TOOLS]" in prompt
    assert "dummy_tool" in prompt


def _root_context() -> TaskContext:
    amazon = Company(company_id="SEC:1018724", company_name="Amazon.com", aliases=("AMZN",))
    listing = Listing(
        listing_id="USA:AMZN",
        company_id="SEC:1018724",
        security_code="AMZN",
        exchange="USA",
        vendor_symbols={"yahoo": "AMZN"},
    )
    subject = Subject(company=amazon, listing=listing)
    return TaskContext(
        task_id="root",
        description="root task",
        step_count=0,
        ancestry=[],
        shared=SharedStateView({}, []),
        query="Amazon valuation analysis",
        query_analysis=QueryAnalysis(
            query_intent=QueryIntent(
                query="Amazon valuation analysis",
                subjects=(subject,),
            ),
            domain_ids=["us_equity"],
            intent_tags=["valuation", "fundamental"],
        ),
        available_tools=["web_search_tool", "sec_tool"],
    )


def test_root_system_prompt_is_plan_critic() -> None:
    critic = DecompositionCritic(ScriptedLLM([]))
    prompt = critic._system_prompt(is_root=True)
    assert "plan critic" in prompt
    assert "analysis plan" in prompt
    assert "industry and business model" in prompt
    assert "decomposition gate critic" not in prompt


def test_non_root_system_prompt_is_gate_critic() -> None:
    critic = DecompositionCritic(ScriptedLLM([]))
    prompt = critic._system_prompt(is_root=False)
    assert "decomposition gate critic" in prompt
    assert "plan critic" not in prompt


@pytest.mark.asyncio
async def test_root_prompt_includes_subject_context() -> None:
    llm = ScriptedLLM(
        [
            {
                "allow": True,
                "single_tool_possible": False,
                "redundant_pairs": [],
                "coverage_pct": 80,
                "min_children": 2,
                "reason": "good plan",
            }
        ]
    )
    critic = DecompositionCritic(llm)
    task = ComplexTask(id="root", description="Amazon valuation analysis")
    decision = TaskDecision(
        action=Action.DECOMPOSE,
        children=[
            TaskSpec(description="revenue analysis", tool_hint="sec_tool"),
            TaskSpec(description="market position", tool_hint="web_search_tool"),
        ],
        reason="break into tracks",
    )

    await critic.evaluate(task, decision, _root_context())

    prompt = llm.calls[0]["prompt"]
    system = llm.calls[0]["system_prompt"]
    assert "[SUBJECTS]" in prompt
    assert "Amazon.com" in prompt
    assert "USA: AMZN" in prompt
    assert "[INTENT_TAGS]" in prompt
    assert "valuation" in prompt
    assert "[ACTIVE_DOMAINS]" in prompt
    assert "us_equity" in prompt
    assert "plan critic" in system


@pytest.mark.asyncio
async def test_non_root_prompt_excludes_subject_context() -> None:
    llm = ScriptedLLM(
        [
            {
                "allow": True,
                "single_tool_possible": False,
                "redundant_pairs": [],
                "coverage_pct": 80,
                "min_children": 1,
                "reason": "ok",
            }
        ]
    )
    critic = DecompositionCritic(llm)
    task = ComplexTask(id="root.0", description="revenue analysis")
    decision = TaskDecision(
        action=Action.DECOMPOSE,
        children=[TaskSpec(description="quarterly data", tool_hint="sec_tool")],
        reason="split further",
    )

    await critic.evaluate(task, decision, _context())

    prompt = llm.calls[0]["prompt"]
    system = llm.calls[0]["system_prompt"]
    assert "[SUBJECTS]" not in prompt
    assert "[INTENT_TAGS]" not in prompt
    assert "[ACTIVE_DOMAINS]" not in prompt
    assert "decomposition gate critic" in system
