from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..tools.specs import get_tool_spec
from ..utils.config import config
from .context import TaskContext, TaskSummary
from .task import Task
from .types import Action, TaskDecision, TaskSpec, TaskState, ToolRequest


class _ToolRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)


class _TaskSpecPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    tool_hint: str = ""
    depends_on_siblings: list[int] = Field(default_factory=list)


class _TaskDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Action
    children: list[_TaskSpecPayload] = Field(default_factory=list)
    tool_request: _ToolRequestPayload | None = None
    wait_for: list[str] = Field(default_factory=list)
    wait_for_facts: list[str] = Field(default_factory=list)
    output: Any = None
    facts: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="", max_length=600)

    @model_validator(mode="after")
    def validate_action_contract(self) -> "_TaskDecisionPayload":
        if self.action is Action.DECOMPOSE and not self.children:
            raise ValueError("decompose action requires children")
        if self.action is Action.EXECUTE and self.tool_request is None:
            raise ValueError("execute action requires tool_request")
        if self.action is Action.WAIT and not self.wait_for and not self.wait_for_facts:
            raise ValueError("wait action requires wait_for or wait_for_facts")
        if self.action is Action.AGGREGATE and self.output is None and not self.facts:
            raise ValueError("aggregate action requires output or facts")
        if self.action is Action.FINALIZE and self.output is None:
            raise ValueError("finalize action requires output")
        return self


class StepPlanner:
    """Boundary adapter: TaskContext -> LLM JSON -> TaskDecision."""

    _decision_max_response_chars = 100_000
    _prompt_value_preview_chars = 600
    _prompt_query_chars = 3_000
    _prompt_child_output_budget_chars = 50_000
    _max_prompt_chars = 150_000

    def __init__(self, llm_client: Any, repair_retries: int | None = None) -> None:
        self._llm = llm_client
        configured_retries = (
            config.agent_step_repair_retries
            if repair_retries is None
            else repair_retries
        )
        self._repair_retries = max(int(configured_retries), 0)

    async def decide(self, task: Task, ctx: TaskContext) -> TaskDecision:
        base_prompt = self._build_step_prompt(task, ctx)
        return await self._generate_decision(
            task=task,
            base_prompt=base_prompt,
            system_prompt=self._system_prompt(task, ctx),
            schema=self._decision_schema(task),
        )

    async def requery_without_decompose(
        self,
        task: Task,
        ctx: TaskContext,
        rejection_reason: str,
    ) -> TaskDecision:
        decision = await self._generate_decision(
            task=task,
            base_prompt=self._build_requery_prompt(task, ctx, rejection_reason),
            system_prompt=self._system_prompt(task, ctx, allow_decompose=False),
            schema=self._decision_schema(task, allow_decompose=False),
        )
        if decision.action is Action.DECOMPOSE:
            raise ValueError("requery_without_decompose returned decompose")
        return decision

    def _system_prompt(
        self,
        task: Task,
        ctx: TaskContext,
        *,
        allow_decompose: bool = True,
    ) -> str:
        root_only = "yes" if task.parent_id is None else "no"
        allowed_actions = self._allowed_actions(task, allow_decompose=allow_decompose)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            f"Current date and time: {now}",
            "",
            "You are the step function of a recursive valuation agent.",
            "Return the SINGLE best next action as JSON.",
            "",
        ]
        if Action.EXECUTE in allowed_actions:
            lines.extend(
                [
                    "EXECUTE: a SINGLE tool call. MUST include tool_request with tool_name and args.",
                    "  - Use ONLY when you can name EXACTLY ONE tool and its args.",
                ]
            )
        if Action.DECOMPOSE in allowed_actions:
            lines.extend(
                [
                    "DECOMPOSE: break the task into smaller children. Requires at least one child.",
                    "  - Use when the task is too broad for a single tool call.",
                ]
            )
        if Action.WAIT in allowed_actions:
            lines.extend(
                [
                    "WAIT: suspend until a sibling result or shared fact is available.",
                    "  - Requires wait_for (task ids) or wait_for_facts (fact keys).",
                ]
            )
        if Action.AGGREGATE in allowed_actions:
            lines.extend(
                [
                    "AGGREGATE: collect child outputs and complete this task. Must include output or facts.",
                    "  - AGGREGATE 전에 [REQUIREMENTS]를 대조하라. 미충족 항목이 있고 추가 child로 해결 가능하면 DECOMPOSE를 먼저 하라.",
                    "  - 동일 지표가 여러 child에 연도별로 분산되어 있으면, 하나의 Markdown 표로 join하라.",
                    "  - child별로 나열하지 마라. 주제별로 결합하라.",
                    "  - 결합 시 원본 수치를 보존하라.",
                ]
            )
        if Action.FINALIZE in allowed_actions:
            lines.extend(
                [
                    f"FINALIZE: produce the final investment report (root_task={root_only} only). Must include output.",
                    "",
                    "  Child outputs are your structured data layer. FINALIZE adds the analytical layer on top.",
                    "",
                    "  [DATA PRESERVATION]",
                    "  - Every number, ratio, and factual finding from child outputs MUST appear in the report.",
                    "  - Do NOT summarize away detail. The final report must be MORE comprehensive than any single child.",
                    "",
                    "  [QUANTITATIVE ANALYSIS — your analytical value-add]",
                    "  - Valuation context: implied multiples (EV/EBITDA, P/E, P/FCF), how they compare to sector and history.",
                    "  - Margin trajectory: segment-level margin trends, inflection points, structural vs cyclical drivers.",
                    "  - Growth decomposition: organic vs inorganic, volume vs price, sustainable vs one-off.",
                    "  - Capital efficiency: ROIC vs WACC, incremental returns on capex, FCF conversion rate.",
                    "  - Cash flow quality: operating cash flow vs net income divergence, capex intensity, working capital dynamics.",
                    "",
                    "  [DOMAIN INSIGHT — your perspective]",
                    "  - Competitive positioning: moat durability, market share trajectory, pricing power evidence.",
                    "  - Asymmetric risk/opportunity vs market consensus: what the market may be underpricing or overpricing.",
                    "  - Cross-segment dynamics: how segments interact (subsidize, cannibalize, reinforce each other).",
                    "  - Regulatory and macro sensitivity: quantify exposure where possible.",
                    "",
                    "  [INFORMATION GAPS — investment impact]",
                    "  - For each gap, state what investment conclusion it blocks or weakens.",
                    "  - Distinguish between gaps that are resolvable (with more data) and structural unknowns.",
                    "",
                    "  [SCENARIOS]",
                    "  - Bull / Base / Bear with quantified reasoning (target metrics, not just narratives).",
                    "  - Key assumptions that differentiate each scenario.",
                    "  - Rank uncertainties by magnitude of impact on valuation.",
                    "  - 각 시나리오에 정량적 진입/이탈 조건을 명시하라: 목표가, 멀티플 임계값, 성장률 trigger.",
                    "  - 어떤 관찰 가능 지표가 변하면 시나리오 간 전환이 일어나는지 명시하라.",
                    "",
                    "  [COVERAGE]",
                    "  - [REQUIREMENTS]의 모든 항목이 보고서 어딘가에서 충족되어야 한다.",
                    "  - 충족 불가한 항목은 [INFORMATION GAPS]에서 사유와 투자 판단에 미치는 영향을 명시하라.",
                    "  - 섹션 구조는 분석 흐름에 따라 자유롭게 구성하라 (requirement별 섹션 강제 아님).",
                    "",
                    "Write Markdown in Korean. Be comprehensive — length is not a constraint.",
                ]
            )
        if Action.FAIL in allowed_actions:
            lines.append(
                "FAIL: stop the task when it cannot continue with the available tools or facts."
            )
        lines.extend(
            [
                "",
                "Use web_search_tool with search_mode='sec' for latest filing search, 10-Q, 8-K, DEF 14A, proxy, or EDGAR lookup tasks.",
                "Use sec_tool only for extracting data from a specific year's 10-K.",
                "Prefer WAIT over inventing missing facts.",
                "Keep reason concise: one or two sentences, no chain-of-thought.",
                "",
                "[REQUIREMENTS]는 분석이 충족해야 할 조건이다.",
                "AGGREGATE/FINALIZE 전에 child outputs가 requirements를 커버하는지 확인하라.",
                "미충족 requirement가 있고 추가 데이터 수집이 가능하면 DECOMPOSE를 선택하라.",
                "수집 불가한 requirement는 output에서 gap으로 명시하라.",
                "",
                "재무 추이 분석(성장률, CAGR, 마진 변동)이 필요하면 "
                "yfinance_balance_sheet를 연도별로 분리 호출하되, 반드시 하나의 부모 태스크로 묶어라. "
                "단일 연도 데이터로 추세를 주장하지 마라.",
                "",
                "포괄적 밸류에이션을 위해, 분해 시 다음 차원을 커버하라:",
                "  - 비용 구조: SBC, CapEx, 영업 레버리지",
                "  - 경쟁 포지셔닝: 동종업체 비교, 시장 점유율, 상대 멀티플",
                "  - 매출 세분화: 제품/지역별, 부문별 성장률",
            ]
        )
        if task.last_tool_success is not None:
            lines.append(
                "This task already has a tool result. You must not return EXECUTE."
            )
        if ctx.current_children:
            lines.append(
                "This task already has children. Prefer WAIT or AGGREGATE. "
                "Only DECOMPOSE if you are adding genuinely new, non-overlapping children."
            )
        if Action.EXECUTE in allowed_actions and Action.DECOMPOSE in allowed_actions:
            lines.extend(
                [
                    "If the task needs multiple tool calls, use DECOMPOSE instead.",
                    "If you cannot name a specific tool and args, you MUST use DECOMPOSE, not EXECUTE.",
                    "Prefer shallow decomposition when one tool call plus AGGREGATE is enough.",
                ]
            )
        if Action.FINALIZE not in allowed_actions:
            lines.append("FINALIZE is only allowed for the root task.")
        if not allow_decompose:
            lines.append("Do not return DECOMPOSE on this retry.")
        if task.tool_hint:
            lines.append(
                f"Prefer tool_hint={task.tool_hint} when EXECUTE is appropriate."
            )
        lines.append(f"Original query: {self._prompt_query(ctx.query)}")
        return "\n".join(lines)

    def _build_step_prompt(
        self,
        task: Task,
        ctx: TaskContext,
        child_output_budget: int | None = None,
        sibling_preview_chars: int | None = None,
    ) -> str:
        co_budget = child_output_budget or self._prompt_child_output_budget_chars
        sib_preview = sibling_preview_chars or 300

        sections = [
            f"[TASK_ID]\n{task.id}",
            f"[TASK]\n{task.description}",
            f"[STATE]\nstep_count={ctx.step_count}\nstatus={task.state.value}",
            "[ALLOWED_ACTIONS]\n"
            + ", ".join(action.value for action in self._allowed_actions(task)),
        ]
        if task.tool_hint:
            sections.append(f"[TOOL_HINT]\n{task.tool_hint}")
        if task.last_invalid_error:
            sections.append(
                "[PREVIOUS_REJECTION]\n"
                f"invalid_decision_count={task.invalid_decision_count}\n"
                f"{task.last_invalid_error}"
            )
        if ctx.tool_results:
            latest = ctx.tool_results[-1]
            sections.append(
                "[LAST_TOOL_RESULT]\n"
                f"success={latest.success}\n"
                f"{self._preview_json(latest.result)}"
            )
        if task.last_tool_request is not None:
            sections.append(
                "[LAST_TOOL_REQUEST]\n"
                f"{task.last_tool_request.tool_name} "
                f"{self._preview_json(task.last_tool_request.args)}"
            )
        if task.last_tool_success is not None:
            sections.append(f"[LAST_TOOL_SUCCESS]\n{task.last_tool_success}")
        if ctx.child_outputs:
            per_child = co_budget // len(ctx.child_outputs)
            child_lines = [
                f"{child_id}: {self._preview_json(output, max_chars=per_child)}"
                for child_id, output in ctx.child_outputs.items()
            ]
            sections.append("[CHILD_OUTPUTS]\n" + "\n".join(child_lines))
        if ctx.current_children:
            failed = [s for s in ctx.current_children if s.state == TaskState.FAILED]
            sections.append(
                "[CURRENT_CHILDREN]\n"
                + "\n".join(
                    self._task_summary_line(summary, output_preview_chars=sib_preview)
                    for summary in ctx.current_children
                )
            )
            if failed:
                sections.append(
                    "[FAILED_CHILDREN]\n"
                    + "\n".join(f"{s.id}: {s.description}" for s in failed)
                    + "\nSome children failed. Aggregate available results and note gaps."
                )
        if ctx.shared.facts:
            fact_lines = [
                f"{key}: {self._preview_json(fact.value)}"
                f" (from {fact.source_task_id})"
                for key, fact in ctx.shared.facts.items()
            ]
            sections.append("[SHARED_FACTS]\n" + "\n".join(fact_lines))
        if ctx.shared.conflicts:
            conflict_lines = [
                f"{conflict.key}: {self._preview_json(conflict.existing.value)}"
                f" vs {self._preview_json(conflict.incoming.value)}"
                for conflict in ctx.shared.conflicts
            ]
            sections.append("[CONFLICTS]\n" + "\n".join(conflict_lines))
        if ctx.siblings:
            sibling_lines = [
                self._task_summary_line(summary, output_preview_chars=sib_preview)
                for summary in ctx.siblings.values()
            ]
            sections.append("[SIBLINGS]\n" + "\n".join(sibling_lines))
        if ctx.ancestry:
            sections.append(
                "[ANCESTRY]\n" + " -> ".join(summary.id for summary in ctx.ancestry)
            )
        if ctx.query_analysis.requirements:
            req_lines = [
                f"  {req.id}: {req.acceptance}"
                for req in ctx.query_analysis.requirements
            ]
            sections.append("[REQUIREMENTS]\n" + "\n".join(req_lines))
        sections.append("[AVAILABLE_TOOLS]\n" + self._available_tools_text(ctx))
        sections.append("Return valid JSON only.")

        prompt = "\n\n".join(sections)

        # Budget enforcement: if prompt exceeds limit, rebuild with reduced budgets
        if len(prompt) > self._max_prompt_chars and ctx.child_outputs:
            overhead = len(prompt) - co_budget  # non-child-output portion
            reduced_co_budget = max(
                self._max_prompt_chars - overhead,
                len(ctx.child_outputs) * 200,  # minimum per child
            )
            reduced_sib_preview = min(sib_preview, 150)
            if reduced_co_budget < co_budget:
                return self._build_step_prompt(
                    task,
                    ctx,
                    child_output_budget=reduced_co_budget,
                    sibling_preview_chars=reduced_sib_preview,
                )

        return prompt

    def _available_tools_text(self, ctx: TaskContext) -> str:
        if not ctx.available_tools:
            return "(none)"

        lines: list[str] = []
        for tool_name in ctx.available_tools:
            try:
                spec = get_tool_spec(tool_name)
            except RuntimeError:
                lines.append(tool_name)
                continue
            lines.append(
                f"{tool_name}: args={spec.args_text()}; capability={spec.capability or '-'}"
            )
        return "\n".join(lines)

    def _build_repair_prompt(
        self,
        *,
        task: Task,
        base_prompt: str,
        invalid_payload: dict[str, Any] | None,
        error: str,
    ) -> str:
        sections = [
            "[TASK_ID]",
            task.id,
            "[REPAIR]",
            "Your previous response was invalid. Return one corrected JSON object only.",
            "Keep reason under 600 characters.",
            "If EXECUTE is still the right action, include tool_request.tool_name and tool_request.args.",
            "If you cannot choose a valid tool call, switch to DECOMPOSE, WAIT, AGGREGATE, or FAIL.",
            "[VALIDATION_ERROR]",
            error,
        ]
        if invalid_payload is not None:
            sections.extend(
                [
                    "[PREVIOUS_JSON]",
                    json.dumps(invalid_payload, ensure_ascii=False, default=str),
                ]
            )
        sections.extend(["[ORIGINAL_STEP_PROMPT]", base_prompt])
        return "\n\n".join(sections)

    def _build_requery_prompt(
        self,
        task: Task,
        ctx: TaskContext,
        rejection_reason: str,
    ) -> str:
        return "\n\n".join(
            [
                self._build_step_prompt(task, ctx),
                "[DECOMPOSITION_REJECTED]",
                rejection_reason,
            ]
        )

    def _salvage_decision_candidates(
        self,
        raw: dict[str, Any],
    ) -> list[dict[str, Any]]:
        merged = dict(raw)
        merged_changed = False
        candidates: list[dict[str, Any]] = []
        raw_action = raw.get("action")

        for value in raw.values():
            if not isinstance(value, str):
                continue
            for embedded in self._embedded_json_objects(value):
                embedded_action = embedded.get("action")
                if embedded_action is not None and (
                    raw_action is None or embedded_action == raw_action
                ):
                    candidates.append(embedded)

                for key in (
                    "children",
                    "tool_request",
                    "wait_for",
                    "wait_for_facts",
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
            key = json.dumps(
                candidate,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)
        return unique

    def _embedded_json_objects(self, text: str) -> list[dict[str, Any]]:
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
            key = json.dumps(
                candidate,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            if key in seen:
                continue
            seen.add(key)
            objects.append(candidate)
        return objects

    def _parse_decision(self, task: Task, raw: dict[str, Any]) -> TaskDecision:
        payload: _TaskDecisionPayload | None = None
        try:
            payload = _TaskDecisionPayload.model_validate(raw)
        except ValidationError as exc:
            for candidate in self._salvage_decision_candidates(raw):
                try:
                    payload = _TaskDecisionPayload.model_validate(candidate)
                except ValidationError:
                    continue
                raw = candidate
                break
            if payload is None:
                raise ValueError(
                    "invalid task decision payload: "
                    f"{exc}; raw_payload={json.dumps(raw, ensure_ascii=False, default=str)}"
                ) from exc
        if payload.action is Action.FINALIZE and task.parent_id is not None:
            raise ValueError(
                "invalid task decision payload: finalize is only allowed for root tasks; "
                f"raw_payload={json.dumps(raw, ensure_ascii=False, default=str)}"
            )

        return TaskDecision(
            action=payload.action,
            children=[
                TaskSpec(
                    description=child.description,
                    tool_hint=child.tool_hint,
                    depends_on_siblings=list(child.depends_on_siblings),
                )
                for child in payload.children
            ],
            tool_request=(
                ToolRequest(
                    tool_name=payload.tool_request.tool_name,
                    args=dict(payload.tool_request.args),
                )
                if payload.tool_request is not None
                else None
            ),
            wait_for=list(payload.wait_for),
            wait_for_facts=list(payload.wait_for_facts),
            output=payload.output,
            facts=dict(payload.facts),
            reason=payload.reason,
        )

    async def _generate_decision(
        self,
        *,
        task: Task,
        base_prompt: str,
        system_prompt: str,
        schema: dict[str, Any],
    ) -> TaskDecision:
        prompt = base_prompt
        last_error: ValueError | None = None

        for attempt in range(self._repair_retries + 1):
            invalid_payload: dict[str, Any] | None = None
            try:
                invalid_payload = await self._llm.generate_json(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    response_json_schema=schema,
                    trace_method=f"agent.step.{task.id}",
                    max_response_chars=self._decision_max_response_chars,
                )
                return self._parse_decision(task, invalid_payload)
            except ValueError as exc:
                last_error = exc
                if attempt >= self._repair_retries:
                    break
                prompt = self._build_repair_prompt(
                    task=task,
                    base_prompt=base_prompt,
                    invalid_payload=invalid_payload,
                    error=str(exc),
                )

        if last_error is None:
            raise ValueError("step planner produced no decision")
        raise last_error

    def _preview_json(self, value: Any, *, max_chars: int | None = None) -> str:
        text = json.dumps(value, ensure_ascii=False, default=str)
        limit = max_chars or self._prompt_value_preview_chars
        if len(text) <= limit:
            return text
        return _truncate_preserving_tables(text, limit)

    def _prompt_query(self, query: str) -> str:
        filtered: list[str] = []
        skipping_thinking_level = False
        for line in query.splitlines():
            stripped = line.strip()
            is_header = stripped.startswith("[") and stripped.endswith("]")
            if skipping_thinking_level and is_header:
                skipping_thinking_level = False
            if stripped == "[THINKING_LEVEL]":
                skipping_thinking_level = True
                continue
            if skipping_thinking_level:
                continue
            filtered.append(line)

        text = "\n".join(filtered).strip()
        if len(text) <= self._prompt_query_chars:
            return text
        return text[: self._prompt_query_chars - 3] + "..."

    def _task_summary_line(
        self, summary: TaskSummary, output_preview_chars: int = 300
    ) -> str:
        line = f"{summary.id}: {summary.state.value} - {summary.description}"
        if summary.output is not None:
            line += f" | output={self._preview_json(summary.output, max_chars=output_preview_chars)}"
        return line

    def _allowed_actions(
        self,
        task: Task,
        *,
        allow_decompose: bool = True,
    ) -> list[Action]:
        actions = list(Action)
        if not allow_decompose:
            actions = [action for action in actions if action is not Action.DECOMPOSE]
        if task.last_tool_success is not None:
            actions = [action for action in actions if action is not Action.EXECUTE]
        if task.parent_id is not None:
            actions = [action for action in actions if action is not Action.FINALIZE]
        return actions

    def _decision_schema(
        self,
        task: Task,
        *,
        allow_decompose: bool = True,
    ) -> dict[str, Any]:
        schema = deepcopy(_TaskDecisionPayload.model_json_schema())
        schema["$defs"]["Action"]["enum"] = [
            action.value
            for action in self._allowed_actions(task, allow_decompose=allow_decompose)
        ]
        return schema


def _truncate_preserving_tables(text: str, limit: int) -> str:
    """Truncate text but preserve complete markdown table blocks."""
    table_blocks: list[tuple[int, int]] = []
    lines = text.split("\\n")
    i = 0
    pos = 0
    while i < len(lines):
        line = lines[i]
        line_start = pos
        pos += len(line) + 2  # \\n literal in JSON string
        if line.lstrip().startswith("|"):
            block_start = line_start
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                block_end = pos
                i += 1
                if i < len(lines):
                    pos += len(lines[i]) + 2
            table_blocks.append((block_start, block_end))
        else:
            i += 1

    if not table_blocks:
        return text[: limit - 3] + "..."

    preserved: list[str] = []
    table_chars = sum(end - start for start, end in table_blocks)
    prose_budget = max(limit - table_chars - 50, limit // 4)

    prev_end = 0
    for start, end in table_blocks:
        prose = text[prev_end:start]
        if len(prose) > prose_budget // max(len(table_blocks), 1):
            chunk = prose_budget // max(len(table_blocks), 1)
            prose = prose[:chunk] + "..."
        preserved.append(prose)
        preserved.append(text[start:end])
        prev_end = end

    trailing = text[prev_end:]
    remaining = limit - sum(len(p) for p in preserved)
    if remaining > 10 and trailing:
        preserved.append(trailing[:remaining])
    elif trailing:
        preserved.append("...")

    result = "".join(preserved)
    if len(result) > limit:
        return result[: limit - 3] + "..."
    return result
