from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

from domain.query import summarize_temporal_contract

from ...tools.specs import get_tool_spec
from ..context import TaskContext, TaskSummary
from ..ontology import schema_for_prompt
from ..task import Task
from ..types import Action, TaskState

_TEMPORAL_ARG_KEYS = frozenset(
    {"as_of_kst", "time_scope", "target_start", "target_end"}
)
_LAST_TOOL_RESULT_MAX_CHARS = 4_000
_CHILD_OUTPUT_MAX_CHARS = 6_000
_CHILD_OUTPUT_SECTION_MAX_CHARS = 18_000
_CURRENT_CHILD_OUTPUT_MAX_CHARS = 800
_EVIDENCE_SUMMARY_MAX_CHARS = 280


def _compact_tool_args_for_prompt(args: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in args.items() if k not in _TEMPORAL_ARG_KEYS}


_STATIC_SYSTEM_PREFIX = """\
You are the step function of a recursive valuation agent.
Write markdown in Korean for output and facts. Keep numbers, tickers, proper nouns, and quotes as in sources.
Return JSON for the next step. Fill only the structural fields needed for the next transition.
Do not include action. The runtime infers the transition from tool_request, children, wait_for, output, or facts.
Treat [QUERY_UNITS] as the execution contract. Preserve as_of_kst and target period exactly.

EXECUTE: a SINGLE tool call. MUST include tool_request with tool_name and args.
  - Use ONLY when you can name EXACTLY ONE tool and its args.
  - If [AVAILABLE_TOOLS] is (none), do not EXECUTE.
DECOMPOSE: break the task into smaller children. Requires at least one child.
  - Use when the task is too broad for a single tool call.
  - Check [EVIDENCE] before creating children.
  - Do not create children that re-collect satisfied evidence already available in [EVIDENCE].
  - Do not repeat failed requests listed in [EVIDENCE] or [FAILED_ATTEMPTS].
  - Each child MUST include description.
  - If a likely execution tool is obvious, include tool_hint.
  - If a child must use exactly one tool, include execution_tool. This is a hard runtime constraint, not a suggestion.
  - Never return children as an empty list. If you cannot name concrete children now, use EXECUTE, WAIT, AGGREGATE, or FAIL.
WAIT: suspend until a sibling or dependency task is complete.
  - Requires wait_for (task ids).
  - Never wait on your own task id.
  - If the needed dependency is already done, or you already have enough tool/child output, use AGGREGATE instead.
AGGREGATE: collect child outputs and complete this task. Must include output or facts.
  - AGGREGATE 전에 [REQUIREMENTS]를 대조하라. 미충족 항목이 있고 추가 child로 해결 가능하면 DECOMPOSE를 먼저 하라.
  - 추가 tool 호출이 필요하면 AGGREGATE에 tool_request를 붙이지 말고 EXECUTE를 사용하라.
  - 동일 지표가 여러 child에 연도별로 분산되어 있으면, 하나의 Markdown 표로 join하라.
  - child별로 나열하지 마라. 주제별로 결합하라.
  - 결합 시 원본 수치를 보존하라.
  - child output에 status='facts_only'가 있거나 미검증/공백이 표시되면, 그 불확실성을 유지하라.
  - child들이 facts_only 결과만 냈다면, 빈 aggregate를 반환하지 말고 그 내용을 output 또는 facts에 담아라.
  - 검증 실패나 data gap을 확인된 사실처럼 승격하지 마라.
  - 상충하는 데이터가 있으면: 출처의 신뢰도(공시 > 거래소 > IR > 뉴스 > 증권사 > 커뮤니티)를 기준으로 판단하라.
  - 공식 재무 도구(opendart_financial_tool, yfinance_balance_sheet)의 확정 재무제표와 거래소/시장 데이터 기반 multiple은 web_search_tool 값으로 덮어쓰지 마라.
  - PER는 단일 정의를 사용한다: 기준일 주가 ÷ 확정 EPS. 한국 회사의 연도별 PER/PBR은 연도말 KRX 시장 데이터 기준이며, 현재가 snapshot을 과거 연도 주가처럼 취급하지 마라. 컨센서스·예상 EPS 기반의 forward PER을 만들지 마라. 자체 가정한 EPS·성장률로 PER을 합성하지 마라.
  - 동일 신뢰도에서 값이 다르면 정보 공백(information gap)으로 분류하라.
FAIL: stop the task when it cannot continue with the available tools or facts.

Use sec_tool only for extracting data from a specific year's 10-K.
For web_search_tool, pass query only; the runtime will inject as_of_kst/time_scope/target period.
Prefer WAIT over inventing missing facts.

[REQUIREMENTS]는 분석이 충족해야 할 조건이다.
AGGREGATE/FINALIZE 전에 child outputs가 requirements를 커버하는지 확인하라.
미충족 requirement가 있고 추가 데이터 수집이 가능하면 DECOMPOSE를 선택하라.
수집 불가한 requirement는 output에서 gap으로 명시하라.

재무 수치(보고 재무제표, 실적 EPS·EBITDA, 거래소/시장 데이터 기반 multiple, 성장률·CAGR·마진 등 확정 수치 기반 지표)는 한국 회사는 opendart_financial_tool, 그 외는 yfinance_balance_sheet로만 수집하라. 분석 대상 기업뿐 아니라 peer 그룹에도 동일하게 적용된다. 두 도구 모두 start_year, end_year(정수, inclusive)를 받아 한 번의 호출로 다년치 결과를 반환한다. [TEMPORAL_CONTRACT]의 target_period에서 연도를 읽어 그대로 넘겨라. 연도별로 호출을 쪼개지 마라. 단일 연도면 start_year=end_year로 설정하라. 단일 연도 데이터로 추세를 주장하지 마라.

web_search_tool은 공식 재무 도구가 제공할 수 없는 정보에만 사용하라: peer 후보 식별, 뉴스·이벤트·정성 정보, 규제·정책·거버넌스 등 비수치 정보. 확정 재무 수치는 물론, 컨센서스·forward EPS·목표가·애널리스트 적용 멀티플 같은 시장 기대치 수치도 web_search_tool로 가져와 분석에 사용하지 마라. 멀티플(PER, EV/EBITDA 등)은 확정 재무·현재가에서 계산한 값만 사용한다.

포괄적 밸류에이션을 위해, 분해 시 다음 차원을 커버하라:
  - 비용 구조: SBC, CapEx, 영업 레버리지
  - 경쟁 포지셔닝: 동종업체 비교, 시장 점유율, 상대 멀티플
  - 매출 세분화: 제품/지역별, 부문별 성장률
  - 재무·현금흐름 리스크: 레버리지, 유동성, 이자·부채 만기, FCF 전환·품질
  - 지배구조·거버넌스 리스크: 통제·의결권, 이사회 독립성, 특수관계자·이해상충
  - 하방·전이: 규제·매크로·경쟁 충격이 손익·현금흐름으로 이어지는 경로와 주요 downside 촉매

If the task needs multiple tool calls, use DECOMPOSE instead.
If you cannot name a specific tool and args, you MUST use DECOMPOSE, not EXECUTE.
Prefer shallow decomposition when one tool call plus AGGREGATE is enough."""


def static_system_prefix() -> str:
    return _STATIC_SYSTEM_PREFIX


def build_system_prompt_suffix(
    *,
    task: Task,
    ctx: TaskContext,
    allow_decompose: bool,
    task_name_max_chars: int,
    allowed_actions: list[Action],
) -> str:
    allowed = set(allowed_actions)
    root_only = "yes" if task.parent_id is None else "no"
    temporal = summarize_temporal_contract(
        as_of_kst=ctx.as_of_kst,
        units=ctx.query_units,
    )
    as_of_kst = temporal.as_of_kst or "(unknown)"

    # --- dynamic suffix: everything that varies per call ---
    lines: list[str] = [
        f"As-of KST timestamp: {as_of_kst}",
        f"Allowed actions: {', '.join(a.value for a in allowed_actions)}",
    ]
    if Action.DECOMPOSE in allowed:
        lines.append(
            f"  - task_name is optional; if you provide it, keep it concise, <= {task_name_max_chars} chars, and use only letters/digits/underscores."
        )
        if task.query_unit_ids:
            lines.append(
                "  - query_unit_ids must use the numeric prefixes shown in [QUERY_UNITS] exactly (zero-based)."
            )
        if len(task.query_unit_ids) > 1:
            lines.append(
                "  - This task spans multiple query units. Every child MUST include query_unit_ids."
            )
    if Action.FINALIZE in allowed:
        lines.append(
            f"FINALIZE: produce the final report (root_task={root_only} only). Must include output."
        )
        lines.append(
            "  - Trading/investment decision framing comes first; full structure is in [FINALIZE_GUIDANCE] when child outputs are available."
        )
    if Action.FINALIZE not in allowed:
        lines.append("FINALIZE is only allowed for the root task.")
    if task.last_tool_success is True:
        lines.extend(
            [
                "This task already has a successful tool result. You must not return EXECUTE.",
                "Extract key numeric values from the tool result into the facts dict as key-value pairs.",
                "For financial tool results, include valuation metrics such as per whenever present.",
                schema_for_prompt(),
                "Put interpretation and context in output; keep facts to numbers (and minimal labels) only.",
            ]
        )
    elif task.last_tool_success is False and Action.EXECUTE in allowed:
        lines.append(
            "The previous tool call failed. You may try a different EXECUTE or DECOMPOSE, "
            "but do not repeat the same failed tool request."
        )
    if ctx.current_children:
        lines.append(
            "This task already has children. Prefer WAIT or AGGREGATE. "
            "Only DECOMPOSE if you are adding genuinely new, non-overlapping children."
        )
    if not allow_decompose:
        lines.append("Do not return DECOMPOSE on this retry.")
    if task.blocked_tools and Action.EXECUTE in allowed:
        lines.append(
            "The following tools are blocked for this task after repeated consecutive "
            "failures: "
            + ", ".join(sorted(task.blocked_tools))
            + ". Use a different tool or DECOMPOSE."
        )
    if not ctx.available_tools and Action.EXECUTE in allowed:
        lines.append(
            "No execution tool is available for this task. If the query units require "
            "different tools, use DECOMPOSE to split them into tool-compatible children."
        )
    if task.execution_tool and Action.EXECUTE in allowed:
        lines.append(
            f"This task is constrained to execution_tool={task.execution_tool}. "
            "Any EXECUTE tool_request must use that exact tool."
        )
    if task.tool_hint:
        lines.append(f"Prefer tool_hint={task.tool_hint} when EXECUTE is appropriate.")
    return "\n".join(lines)


def build_system_prompt(
    *,
    task: Task,
    ctx: TaskContext,
    allow_decompose: bool,
    task_name_max_chars: int,
    allowed_actions: list[Action],
) -> str:
    suffix = build_system_prompt_suffix(
        task=task,
        ctx=ctx,
        allow_decompose=allow_decompose,
        task_name_max_chars=task_name_max_chars,
        allowed_actions=allowed_actions,
    )
    if not suffix:
        return _STATIC_SYSTEM_PREFIX
    return _STATIC_SYSTEM_PREFIX + "\n\n" + suffix


def build_step_prompt(
    *,
    task: Task,
    ctx: TaskContext,
    allowed_actions: list[Action],
    max_prompt_chars: int,
    prompt_value_preview_chars: int,
    prompt_query_chars: int,
) -> str:
    del prompt_value_preview_chars, prompt_query_chars

    sections: list[tuple[str, str]] = [
        ("[TASK_ID]", task.id),
        ("[TASK]", task.description),
        ("[STATE]", f"step_count={ctx.step_count}\nstatus={task.state.value}"),
        ("[ALLOWED_ACTIONS]", ", ".join(action.value for action in allowed_actions)),
        ("[TEMPORAL_CONTRACT]", temporal_contract_text(ctx)),
    ]
    if ctx.query_units:
        sections.append(("[QUERY_UNITS]", query_units_text(task, ctx)))
    if task.tool_hint:
        sections.append(("[TOOL_HINT]", task.tool_hint))
    if task.execution_tool:
        sections.append(("[EXECUTION_TOOL]", task.execution_tool))
    if task.blocked_tools:
        sections.append(("[BLOCKED_TOOLS]", ", ".join(sorted(task.blocked_tools))))
    if task.last_invalid_error:
        sections.append(
            (
                "[PREVIOUS_REJECTION]",
                "invalid_decision_count="
                f"{task.invalid_decision_count}\n{task.last_invalid_error}",
            )
        )
    if task.failed_attempts:
        sections.append(("[FAILED_ATTEMPTS]", failed_attempts_text(task)))
    if ctx.tool_results:
        latest = ctx.tool_results[-1]
        sections.append(
            (
                "[LAST_TOOL_RESULT]",
                f"success={latest.success}\n"
                f"{render_prompt_value_limited(latest.result, max_chars=_LAST_TOOL_RESULT_MAX_CHARS)}",
            )
        )
    if task.last_tool_request is not None:
        compact_args = _compact_tool_args_for_prompt(task.last_tool_request.args)
        sections.append(
            (
                "[LAST_TOOL_REQUEST]",
                f"{task.last_tool_request.tool_name}\n"
                f"{render_prompt_value(compact_args)}",
            )
        )
    if ctx.child_outputs:
        child_blocks = [
            f"{child_id}\n"
            f"{render_prompt_value_limited(output, max_chars=_CHILD_OUTPUT_MAX_CHARS)}"
            for child_id, output in ctx.child_outputs.items()
        ]
        sections.append(
            (
                "[CHILD_OUTPUTS]",
                limit_text(
                    "\n\n".join(child_blocks),
                    max_chars=_CHILD_OUTPUT_SECTION_MAX_CHARS,
                ),
            )
        )
    if ctx.current_children:
        failed = [s for s in ctx.current_children if s.state == TaskState.FAILED]
        sections.append(
            (
                "[CURRENT_CHILDREN]",
                "\n".join(
                    task_summary_line(summary) for summary in ctx.current_children
                ),
            )
        )
        if failed:
            sections.append(
                (
                    "[FAILED_CHILDREN]",
                    "\n".join(f"{s.id}: {s.description}" for s in failed)
                    + "\nSome children failed. Aggregate available results and note gaps.",
                )
            )
    if ctx.evidence and (
        Action.EXECUTE in allowed_actions or Action.DECOMPOSE in allowed_actions
    ):
        sections.append(("[EVIDENCE]", evidence_text(ctx, task_id=task.id)))
    subject_text = subject_context_text(ctx)
    if subject_text:
        sections.append(("[SUBJECTS]", subject_text))
    requirements = requirements_for_task(ctx)
    if requirements:
        req_lines = [f"  {req.id}: {req.acceptance}" for req in requirements]
        sections.append(("[REQUIREMENTS]", "\n".join(req_lines)))
    if Action.FINALIZE in allowed_actions and ctx.child_outputs:
        sections.append(("[FINALIZE_GUIDANCE]", finalize_guidance_text(ctx)))

    sections.append(
        (
            "[AVAILABLE_TOOLS]",
            available_tools_text(ctx, compact=Action.EXECUTE not in allowed_actions),
        )
    )
    sections.append(("", "Return valid JSON only."))
    prompt = render_sections(sections)
    if len(prompt) <= max_prompt_chars:
        return prompt

    for title in (
        "[AVAILABLE_TOOLS]",
        "[EVIDENCE]",
        "[SUBJECTS]",
        "[FAILED_CHILDREN]",
        "[CURRENT_CHILDREN]",
        "[CONFLICTS]",
        "[LAST_TOOL_REQUEST]",
        "[FAILED_ATTEMPTS]",
        "[BLOCKED_TOOLS]",
        "[PREVIOUS_REJECTION]",
        "[FINALIZE_GUIDANCE]",
    ):
        filtered = [section for section in sections if section[0] != title]
        if len(filtered) == len(sections):
            continue
        sections = filtered
        prompt = render_sections(sections)
        if len(prompt) <= max_prompt_chars:
            return prompt
    return prompt


def finalize_guidance_text(ctx: TaskContext) -> str:
    as_of = ctx.as_of_kst.strip() or "(unknown)"
    lines = [
        "Child outputs are your structured data layer. FINALIZE must deliver a trading- and investment-actionable conclusion first, then layered evidence.",
        "",
        "[PRIORITY — TRADING / INVESTMENT DECISION FIRST]",
        f"- Open with a decision-oriented summary: what the evidence implies for 매수·보유·축소·관망 (or equivalent) at as_of_kst={as_of}, only when child outputs support it; otherwise state uncertainty explicitly.",
        f"- Near the top (as_of_kst={as_of}), include when data allows: (1) market price or valuation snapshot vs thesis, (2) scenario-level upside/downside direction, (3) the shortest list of reasons that drive the action view.",
        "- Do not lead with DCF alone or end on intrinsic value only. DCF/fair value is supporting evidence, not the sole headline.",
        "",
        "[DATA PRESERVATION]",
        "- Every number, ratio, and factual finding from child outputs MUST appear in the report.",
        "- Do NOT summarize away detail. The final report must be MORE comprehensive than any single child.",
        "- PER is defined as current price divided by reported EPS from official financial tools. Do not introduce forward/consensus PER. Do not synthesize PER from assumed EPS or growth rates.",
        "",
        "[EVIDENCE — MULTIPLES, INTRINSIC, AND SCENARIOS]",
        "- Multiples: implied EV/EBITDA, P/E, P/FCF (or sector-appropriate), vs peers and vs own history where child data allows.",
        "- Intrinsic / DCF: fair value or range when computed; tie it to multiples and scenarios (consistency or tension).",
        "- Margin trajectory: segment-level margin trends, inflection points, structural vs cyclical drivers.",
        "- Growth decomposition: organic vs inorganic, volume vs price, sustainable vs one-off.",
        "- Capital efficiency: ROIC vs WACC, incremental returns on capex, FCF conversion rate.",
        "- Cash flow quality: operating cash flow vs net income divergence, capex intensity, working capital dynamics.",
        "",
        "[DOMAIN INSIGHT — your perspective]",
        "- Competitive positioning: moat durability, market share trajectory, pricing power evidence.",
        "- Asymmetric risk/opportunity vs market consensus: what the market may be underpricing or overpricing.",
        "- Cross-segment dynamics: how segments interact (subsidize, cannibalize, reinforce each other).",
        "- Regulatory and macro sensitivity: quantify exposure where possible.",
        "",
        "[INFORMATION GAPS — investment impact]",
        "- For each gap, state what investment conclusion it blocks or weakens.",
        "- Distinguish between gaps that are resolvable (with more data) and structural unknowns.",
        "- facts_only, unverified, data gap, grounded=false, could not verify 성격의 정보는 확정 사실로 쓰지 마라.",
    ]
    lines.extend(
        [
            "",
            "[TEMPORAL SEPARATION]",
            "- Separate historical facts, current assessment, and future scenarios into distinct sentences or sections.",
            "- Use absolute dates: historical claims should stay inside the target period, and current claims should be anchored to as_of_kst.",
            "- grounded=false or unverified information must remain uncertainty, not present-tense fact.",
            "",
            "[SCENARIOS — BULL / BASE / BEAR]",
            "- Bull / Base / Bear는 정성적 촉매·리스크와 그 발생 시 사업·재무에 미치는 방향성으로 서술하라.",
            "- 시나리오별 목표 주가, 적용 PER, forward EPS·성장률 가정 등 자체 합성 정량값을 제시하지 마라. 컨센서스·forward 기반 정량 추정은 이 파이프라인에서 생산하지 않는다.",
            "- 관찰 가능한 트리거(계약 공시, 규제 결정, 분기 실적의 정성적 방향)와 그것이 시나리오 간 전환을 유발하는 조건을 명시하라.",
            "- Key assumptions that differentiate each scenario.",
            "- Rank uncertainties by magnitude of impact on the thesis.",
            "",
            "[COVERAGE]",
            "- [REQUIREMENTS]의 모든 항목이 보고서 어딘가에서 충족되어야 한다.",
            "- 충족 불가한 항목은 [INFORMATION GAPS]에서 사유와 투자 판단에 미치는 영향을 명시하라.",
            "- 섹션 구조는 분석 흐름에 따라 자유롭게 구성하라 (requirement별 섹션 강제 아님).",
            "",
            "Be comprehensive — Soften the overall tone and simplify the language while maintaining the original meaning.",
            "Write the final report markdown in Korean.",
        ]
    )
    return "\n".join(lines)

def available_tools_text(ctx: TaskContext, *, compact: bool = False) -> str:
    if not ctx.available_tools:
        return "(none)"
    if compact:
        return ", ".join(ctx.available_tools)
    lines: list[str] = []
    for tool_name in ctx.available_tools:
        try:
            spec = get_tool_spec(tool_name)
        except RuntimeError:
            lines.append(tool_name)
            continue
        line = (
            f"{tool_name}: args={spec.args_text()}; capability={spec.capability or '-'}"
        )
        if spec.param_descriptions:
            params = ", ".join(
                f"{key}: {description}"
                for key, description in spec.param_descriptions.items()
            )
            line += f"; params={params}"
        lines.append(line)
    return "\n".join(lines)


def subject_context_text(ctx: TaskContext) -> str:
    subjects = ctx.query_analysis.query_intent.subjects
    if not subjects:
        return ""
    lines: list[str] = []
    for subject in subjects:
        listing = subject.listing
        prefix = f"role={subject.role.value}; "
        if listing is None:
            lines.append(f"{prefix}company_name={subject.company.company_name}")
            continue
        if listing.market == "KRX":
            line = (
                f"{prefix}company_name={subject.company.company_name}; exchange={listing.exchange}; "
                f"corp={subject.company.company_name}; stock_code={listing.security_code}; "
                f"yahoo_symbol={listing.yahoo_symbol}"
            )
            ref = subject.company.reference_stock_price
            if ref is not None:
                line += f"; stock_price={ref.krw:,}원 (as_of={ref.as_of.isoformat()}, 거래소 종가)"
            lines.append(line)
            continue
        lines.append(
            f"{prefix}company_name={subject.company.company_name}; exchange={listing.exchange}; "
            f"ticker={listing.security_code}; yahoo_symbol={listing.yahoo_symbol}"
        )
    return "\n".join(lines)


def requirements_for_task(ctx: TaskContext) -> list[Any]:
    if not ctx.query_units:
        return list(ctx.query_analysis.requirements)
    relevant_unit_ids = {
        index
        for index, unit in enumerate(ctx.query_analysis.units)
        if unit in ctx.query_units
    }
    return [
        requirement
        for requirement in ctx.query_analysis.requirements
        if relevant_unit_ids.intersection(requirement.unit_ids)
    ]


def temporal_contract_text(ctx: TaskContext) -> str:
    temporal = summarize_temporal_contract(
        as_of_kst=ctx.as_of_kst,
        units=ctx.query_units,
    )
    lines = [f"as_of_kst={temporal.as_of_kst or '(unknown)'}"]
    if temporal.time_scope:
        lines.append(f"time_scope={temporal.time_scope}")
    if temporal.target_start or temporal.target_end:
        lines.append(
            "target_period="
            f"{temporal.target_start or '(open)'}..{temporal.target_end or '(open)'}"
        )
    return "\n".join(lines)


def query_units_text(task: Task, ctx: TaskContext) -> str:
    lines: list[str] = []
    parent_ids = list(task.query_unit_ids)
    for index, unit in enumerate(ctx.query_analysis.units):
        if parent_ids and index not in parent_ids:
            continue
        if unit not in ctx.query_units and ctx.query_units:
            continue
        lines.append(f"{index}: {unit.objective}")
    return "\n".join(lines) or "(none)"




def evidence_text(ctx: TaskContext, *, task_id: str, max_items: int = 8) -> str:
    grouped = [
        row
        for status in ("satisfied", "failed", "empty")
        for row in ctx.evidence
        if row.status == status
    ]
    selected = grouped[:max_items]
    lines = [evidence_line(row, current_task_id=task_id) for row in selected]
    remaining = len(grouped) - len(selected)
    if remaining > 0:
        lines.append(f"... and {remaining} more evidence rows")
    return "\n".join(lines)


def evidence_line(row: Any, *, current_task_id: str = "") -> str:
    args = _compact_tool_args_for_prompt(row.stable_args)
    args_text = ", ".join(f"{key}={json_arg(args[key])}" for key in sorted(args))
    line = f"{row.tool_name}({args_text}): {row.status}"
    if row.value_summary:
        summary = limit_single_line_text(
            row.value_summary,
            max_chars=_EVIDENCE_SUMMARY_MAX_CHARS,
        )
        line += f' - "{summary}"'
    if row.task_id and row.task_id != current_task_id:
        line += f" [task={row.task_id}]"
    return line


def failed_attempts_text(task: Task, *, max_items: int = 8) -> str:
    selected = task.failed_attempts[-max_items:]
    lines = [
        (
            f"{attempt.tool_name}({', '.join(f'{key}={json_arg(attempt.args[key])}' for key in sorted(attempt.args))})"
            f": {attempt.kind} - {attempt.error}"
        )
        for attempt in selected
    ]
    if len(task.failed_attempts) > len(selected):
        lines.insert(
            0,
            f"... {len(task.failed_attempts) - len(selected)} older attempts omitted ...",
        )
    return "\n".join(lines)


def json_arg(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def preview_json(value: Any, *, max_chars: int) -> str:
    return render_prompt_value_limited(value, max_chars=max_chars)


def prompt_query(query: str, *, prompt_query_chars: int) -> str:
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
    if len(text) <= prompt_query_chars:
        return text
    return text[: prompt_query_chars - 3] + "..."


def task_summary_line(summary: TaskSummary) -> str:
    line = f"{summary.id}: {summary.state.value} - {summary.description}"
    if summary.output is not None:
        line += " | output=" + render_prompt_value_limited(
            summary.output,
            max_chars=_CURRENT_CHILD_OUTPUT_MAX_CHARS,
        )
    return line


def limit_text(text: str, *, max_chars: int, suffix: str = "\n... [truncated]") -> str:
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    keep = max(max_chars - len(suffix), 0)
    if keep == 0:
        return suffix.lstrip()
    return stripped[:keep].rstrip() + suffix


def limit_single_line_text(text: str, *, max_chars: int) -> str:
    return limit_text(
        " ".join(text.split()),
        max_chars=max_chars,
        suffix="...",
    )


def render_prompt_value_limited(value: Any, *, max_chars: int) -> str:
    return limit_text(
        render_prompt_value(value), max_chars=max_chars, suffix="\n... [truncated]"
    )


def render_sections(sections: list[tuple[str, str]]) -> str:
    blocks: list[str] = []
    for title, body in sections:
        if not body.strip():
            continue
        blocks.append(f"{title}\n{body}" if title else body)
    return "\n\n".join(blocks)


def render_prompt_value(value: Any, heading_level: int = 2) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        lines: list[str] = []
        for key, item in value.items():
            rendered = render_prompt_value(item, min(heading_level + 1, 6)).strip()
            if not rendered:
                continue
            label = str(key).replace("_", " ").strip()
            if "\n" not in rendered and not rendered.startswith("- "):
                lines.append(f"- **{label}**: {rendered}")
            else:
                lines.extend([f"{'#' * heading_level} {label}", "", rendered, ""])
        return "\n".join(lines).strip()
    if isinstance(value, list):
        if all(not isinstance(item, (Mapping, list)) for item in value):
            return "\n".join(
                f"- {text}" for text in (str(item).strip() for item in value) if text
            ).strip()
        lines = []
        for index, item in enumerate(value, start=1):
            rendered = render_prompt_value(item, min(heading_level + 1, 6)).strip()
            if rendered:
                lines.extend([f"{'#' * heading_level} Item {index}", "", rendered, ""])
        return "\n".join(lines).strip()
    return str(value).strip()
