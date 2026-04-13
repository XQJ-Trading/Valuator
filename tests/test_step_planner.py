from __future__ import annotations

from typing import Any

import pytest

from domain.company import Company, Listing, Subject
from domain.query import QueryAnalysis, QueryIntent, QueryRequirement, QueryUnit
from valuator.core.context import TaskContext, TaskSummary
from valuator.core.shared_state import Fact, SharedStateView
from valuator.core.planning import StepPlanner
from valuator.core.planning.parser import TASK_NAME_MAX_CHARS, truncate_task_name
from valuator.core.types import Action, TaskState
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
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        del trace_method, max_response_chars
        self.calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "response_json_schema": response_json_schema,
                "max_output_tokens": max_output_tokens,
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
        as_of_utc="2026-03-30T00:00:00Z",
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
            },
            {
                "action": "execute",
                "tool_request": {
                    "tool_name": "web_search_tool",
                    "args": {"query": "Amazon segment revenue 2024"},
                },
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
    assert llm.calls[0]["max_output_tokens"] == 8192
    assert "Return corrected JSON only." in llm.calls[1]["prompt"]
    assert "[TASK]" in llm.calls[1]["prompt"]
    assert "collect Amazon segment data" in llm.calls[1]["prompt"]


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
async def test_step_planner_falls_back_invalid_web_search_mode_to_web() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "execute",
                "tool_request": {
                    "tool_name": "web_search_tool",
                    "args": {
                        "query": "Amazon competitive strategy",
                        "search_mode": "general",
                    },
                },
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
    assert decision.tool_request.args == {
        "query": "Amazon competitive strategy",
        "search_mode": "web",
    }
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_step_planner_salvages_embedded_decompose_payload_from_reason() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "decompose",
                "reason": (
                    "Return this payload instead:\n"
                    '{"action":"decompose","children":[{"description":"collect '
                    'demand","task_name":"collect_demand","tool_hint":"web_search_tool"},{"description":"summarize '
                    'results","task_name":"summarize_results"}],"reason":"split work"}'
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
    assert decision.children[0].task_name == "collect_demand"
    assert decision.children[0].tool_hint == "web_search_tool"


@pytest.mark.asyncio
async def test_step_planner_rejects_decompose_child_without_task_name() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "decompose",
                "children": [
                    {
                        "description": "collect demand",
                        "tool_hint": "web_search_tool",
                    }
                ],
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = ComplexTask(id="root", description="root task")

    with pytest.raises(ValueError, match="task_name"):
        await planner.decide(task, _context(available_tools=["web_search_tool"]))


@pytest.mark.asyncio
async def test_step_planner_truncates_long_decompose_child_task_name() -> None:
    raw_name = "collect_demand_for_this_region_eu"
    llm = ScriptedLLM(
        [
            {
                "action": "decompose",
                "children": [
                    {
                        "description": "collect demand",
                        "task_name": raw_name,
                        "tool_hint": "web_search_tool",
                    }
                ],
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = ComplexTask(id="root", description="root task")

    decision = await planner.decide(task, _context(available_tools=["web_search_tool"]))

    assert decision.action is Action.DECOMPOSE
    assert len(decision.children[0].task_name) == TASK_NAME_MAX_CHARS
    assert decision.children[0].task_name == truncate_task_name(raw_name)


@pytest.mark.asyncio
async def test_step_planner_rejects_finalize_on_non_root_task() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "finalize",
                "output": "done",
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
                "children": [
                    {
                        "description": "still split",
                        "task_name": "still_split",
                    }
                ],
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
async def test_step_planner_maps_fail_output() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "fail",
                "output": "upstream data source unavailable",
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = ComplexTask(id="root", description="root task")

    decision = await planner.decide(task, _context(available_tools=["web_search_tool"]))

    assert decision.action.value == "fail"
    assert decision.output == "upstream data source unavailable"


@pytest.mark.asyncio
async def test_step_planner_aggregate_with_output() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "aggregate",
                "output": "done",
                "reason": "summarize result",
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = ComplexTask(id="root", description="root task")

    decision = await planner.decide(task, _context(available_tools=["web_search_tool"]))

    assert decision.action.value == "aggregate"
    assert decision.output == "done"


@pytest.mark.asyncio
async def test_step_planner_execute_ignores_legacy_reason_field() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "execute",
                "tool_request": {
                    "tool_name": "web_search_tool",
                    "args": {"query": "Amazon"},
                },
                "reason": "search latest filing",
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = AtomicTask(id="root.0", description="child task", tool_hint="web_search_tool")

    decision = await planner.decide(task, _context(available_tools=["web_search_tool"]))

    assert decision.action.value == "execute"
    assert decision.tool_request is not None
    assert decision.tool_request.tool_name == "web_search_tool"


@pytest.mark.asyncio
async def test_step_planner_prompt_includes_current_children_and_done_sibling_output() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "aggregate",
                "output": "done",
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
async def test_step_planner_finalize_prompt_preserves_unverified_gaps() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "finalize",
                "output": "done",
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = ComplexTask(id="root", description="root task")
    ctx = TaskContext(
        task_id="root",
        description="root task",
        step_count=0,
        as_of_utc="2026-03-30T00:00:00Z",
        child_outputs={
            "root.0": {
                "status": "facts_only",
                "facts": {"price_uplift": "could not verify"},
            }
        },
        shared=SharedStateView({}, []),
        query="Amazon analysis",
        query_analysis=QueryAnalysis(),
        available_tools=["web_search_tool"],
    )

    await planner.decide(task, ctx)

    prompt = llm.calls[0]["prompt"]
    system_prompt = llm.calls[0]["system_prompt"]
    assert "[FINALIZE_GUIDANCE]" in prompt
    assert "facts_only, unverified, data gap, could not verify" in prompt
    assert "확정 사실처럼 쓰지 마라" in prompt
    assert "facts_only, unverified, data gap, could not verify" not in system_prompt


@pytest.mark.asyncio
async def test_step_planner_excludes_execute_after_successful_tool_result() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "aggregate",
                "output": "done",
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
    assert "This task already has a successful tool result." in llm.calls[0][
        "system_prompt"
    ]


@pytest.mark.asyncio
async def test_step_planner_keeps_execute_after_failed_tool_result() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "aggregate",
                "output": "done",
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = AtomicTask(
        id="root.0",
        description="recover after failed tool",
        tool_hint="web_search_tool",
    )
    task.last_tool_success = False

    decision = await planner.decide(task, _context(available_tools=["web_search_tool"]))

    assert decision.action.value == "aggregate"
    assert llm.calls[0]["response_json_schema"]["$defs"]["Action"]["enum"] == [
        "decompose",
        "execute",
        "wait",
        "aggregate",
        "finalize",
        "fail",
    ]
    assert "EXECUTE:" in llm.calls[0]["system_prompt"]
    assert "The previous tool call failed." in llm.calls[0]["system_prompt"]
    assert "Return JSON" in llm.calls[0]["system_prompt"]


@pytest.mark.asyncio
async def test_step_planner_repairs_invalid_json_error_from_llm() -> None:
    llm = ScriptedLLM(
        [
            ValueError("agent.step.root returned invalid JSON"),
            {
                "action": "aggregate",
                "output": "done",
            },
        ]
    )
    planner = StepPlanner(llm, repair_retries=1)
    task = AtomicTask(id="root", description="repair invalid response")

    decision = await planner.decide(task, _context(available_tools=["web_search_tool"]))

    assert decision.action.value == "aggregate"
    assert len(llm.calls) == 2
    assert "Return corrected JSON only." in llm.calls[1]["prompt"]
    assert "agent.step.root returned invalid JSON" in llm.calls[1]["prompt"]
    assert "[PREVIOUS_JSON]" not in llm.calls[1]["prompt"]


@pytest.mark.asyncio
async def test_finalize_prompt_includes_synthesis_guidance() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "finalize",
                "output": "final report",
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = ComplexTask(id="root", description="Amazon valuation")
    ctx = TaskContext(
        task_id="root",
        description="Amazon valuation",
        step_count=1,
        as_of_utc="2026-03-30T00:00:00Z",
        child_outputs={"root.0": {"summary": "segment analysis complete"}},
        shared=SharedStateView({}, []),
        query="Amazon analysis",
        query_analysis=QueryAnalysis(),
        available_tools=["web_search_tool"],
    )

    await planner.decide(task, ctx)

    system = llm.calls[0]["system_prompt"]
    prompt = llm.calls[0]["prompt"]
    assert "FINALIZE" in system
    assert "Original query:" not in system
    assert "Bull / Base / Bear" in prompt
    assert "uncertainties" in prompt.lower()
    assert "INFORMATION GAPS" in prompt


@pytest.mark.asyncio
async def test_step_planner_parses_child_query_unit_ids_without_subset_validation() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "decompose",
                "children": [
                    {
                        "description": "collect historical evidence",
                        "task_name": "collect_history",
                        "tool_hint": "web_search_tool",
                        "query_unit_ids": [1],
                    }
                ],
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = ComplexTask(id="root", description="root task", query_unit_ids=[0, 1])
    decision = await planner.decide(task, _context(available_tools=["web_search_tool"]))

    assert decision.action.value == "decompose"
    assert decision.children[0].query_unit_ids == [1]


@pytest.mark.asyncio
async def test_step_planner_prompt_includes_query_units_and_temporal_shared_facts() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "aggregate",
                "output": "done",
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = ComplexTask(id="root", description="root task", query_unit_ids=[0])
    ctx = TaskContext(
        task_id="root",
        description="root task",
        step_count=1,
        as_of_utc="2026-03-30T00:00:00Z",
        shared=SharedStateView(
            {
                "iran_enrichment_level@2024-01-01:2024-12-31": Fact(
                    key="iran_enrichment_level@2024-01-01:2024-12-31",
                    value={"percent": 60},
                    source_task_id="root.0",
                    grounded=True,
                    as_of_utc="2026-03-30T00:00:00Z",
                    time_scope="historical",
                    target_start="2024-01-01",
                    target_end="2024-12-31",
                    source_urls=("https://example.com/source",),
                )
            },
            [],
        ),
        query="2026-03-30 기준으로 2024년 이란 상황 분석",
        query_analysis=QueryAnalysis(
            as_of_utc="2026-03-30T00:00:00Z",
            units=[
                QueryUnit(
                    id="U-001",
                    objective="2024년 이란 상황 조사",
                    retrieval_query="Iran events in 2024",
                    domain_ids=["macro"],
                    time_scope="historical",
                    target_start="2024-01-01",
                    target_end="2024-12-31",
                )
            ],
            requirements=[
                QueryRequirement(
                    id="R-001",
                    acceptance="2024년 사건을 정리한다",
                    unit_ids=[0],
                    provenance="user query",
                )
            ],
        ),
        query_units=[
            QueryUnit(
                id="U-001",
                objective="2024년 이란 상황 조사",
                retrieval_query="Iran events in 2024",
                domain_ids=["macro"],
                time_scope="historical",
                target_start="2024-01-01",
                target_end="2024-12-31",
            )
        ],
        available_tools=["web_search_tool"],
    )

    await planner.decide(task, ctx)

    prompt = llm.calls[0]["prompt"]
    system_prompt = llm.calls[0]["system_prompt"]
    assert "[QUERY_UNITS]" in prompt
    assert "time_scope=historical" in prompt
    assert "target_period=2024-01-01..2024-12-31" in prompt
    assert "grounded=True" in prompt
    assert "sources=1" in prompt
    assert "As-of UTC timestamp: 2026-03-30T00:00:00Z" in system_prompt


@pytest.mark.asyncio
async def test_step_planner_prompt_exposes_korean_stock_code_and_us_ticker_rules() -> None:
    llm = ScriptedLLM(
        [
            {
                "action": "aggregate",
                "output": "done",
            }
        ]
    )
    planner = StepPlanner(llm, repair_retries=0)
    task = ComplexTask(id="root", description="mixed market identifier task")
    samsung = Subject(
        company=Company(company_id="KRX:005930", company_name="삼성전자", aliases=("Samsung Electronics",)),
        listing=Listing(
            listing_id="KRX:005930",
            company_id="KRX:005930",
            security_code="005930",
            exchange="KOSPI",
            vendor_symbols={"yahoo": "005930.KS"},
        ),
    )
    amazon = Subject(
        company=Company(company_id="SEC:1018724", company_name="Amazon.com", aliases=("AMZN",)),
        listing=Listing(
            listing_id="USA:AMZN",
            company_id="SEC:1018724",
            security_code="AMZN",
            exchange="USA",
            vendor_symbols={"yahoo": "AMZN"},
        ),
    )
    ctx = TaskContext(
        task_id="root",
        description="mixed market identifier task",
        step_count=0,
        as_of_utc="2026-03-30T00:00:00Z",
        shared=SharedStateView({}, []),
        query="삼성전자와 Amazon 재무 조회",
        query_analysis=QueryAnalysis(
            query_intent=QueryIntent(
                query="삼성전자와 Amazon 재무 조회",
                subjects=(samsung, amazon),
            )
        ),
        available_tools=[
            "opendart_financial_tool",
            "yfinance_balance_sheet",
            "sec_tool",
        ],
    )

    await planner.decide(task, ctx)

    prompt = llm.calls[0]["prompt"]
    system_prompt = llm.calls[0]["system_prompt"]
    assert "[SUBJECTS]" in prompt
    assert "company_name=삼성전자; exchange=KOSPI; corp=삼성전자; stock_code=005930; yahoo_symbol=005930.KS" in prompt
    assert "company_name=Amazon.com; exchange=USA; ticker=AMZN; yahoo_symbol=AMZN" in prompt
    assert "opendart_financial_tool: args=corp, year, fs_div?" in prompt
    assert "Korean issuer only." in prompt
    assert "Identifier contract:" in system_prompt
    assert "Do not pass ticker to OpenDART." in system_prompt
