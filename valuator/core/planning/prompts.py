from __future__ import annotations

import json
from typing import Any

from domain.query import summarize_temporal_contract

from ...tools.specs import get_tool_spec
from ..context import TaskContext, TaskSummary
from ..task import Task
from ..types import Action, TaskState


def build_system_prompt(
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
        as_of_utc=ctx.as_of_utc,
        units=ctx.query_units,
    )
    as_of_utc = temporal.as_of_utc or "(unknown)"
    lines = [
        f"As-of UTC timestamp: {as_of_utc}",
        "",
        "You are the step function of a recursive valuation agent.",
        "Write markdown in Korean for output and facts. Keep numbers, tickers, proper nouns, and quotes as in sources.",
        "Return JSON for the next step. Fill only the structural fields needed for the next transition.",
        "Do not include action. The runtime infers the transition from tool_request, children, wait_for, output, or facts.",
        "Treat [QUERY_UNITS] as the execution contract. Preserve as_of_utc and target period exactly.",
        "",
    ]
    if Action.EXECUTE in allowed:
        lines.extend(
            [
                "EXECUTE: a SINGLE tool call. MUST include tool_request with tool_name and args.",
                "  - Use ONLY when you can name EXACTLY ONE tool and its args.",
            ]
        )
    if Action.DECOMPOSE in allowed:
        lines.extend(
            [
                "DECOMPOSE: break the task into smaller children. Requires at least one child.",
                "  - Use when the task is too broad for a single tool call.",
                "  - Each child MUST include description.",
                f"  - task_name is optional; if you provide it, keep it concise, <= {task_name_max_chars} chars, and use only letters/digits/underscores.",
                "  - If a likely execution tool is obvious, include tool_hint.",
                "  - Never return children as an empty list. If you cannot name concrete children now, use EXECUTE, WAIT, AGGREGATE, or FAIL.",
            ]
        )
        if task.query_unit_ids:
            lines.append(
                "  - query_unit_ids must use the numeric prefixes shown in [QUERY_UNITS] exactly (zero-based)."
            )
        if len(task.query_unit_ids) > 1:
            lines.append(
                "  - This task spans multiple query units. Every child MUST include query_unit_ids."
            )
    if Action.WAIT in allowed:
        lines.extend(
            [
                "WAIT: suspend until a sibling or dependency task is complete.",
                "  - Requires wait_for (task ids).",
                "  - Never wait on your own task id.",
                "  - If the needed dependency is already done, or you already have enough tool/child output, use AGGREGATE instead.",
            ]
        )
    if Action.AGGREGATE in allowed:
        lines.extend(
            [
                "AGGREGATE: collect child outputs and complete this task. Must include output or facts.",
                "  - AGGREGATE 전에 [REQUIREMENTS]를 대조하라. 미충족 항목이 있고 추가 child로 해결 가능하면 DECOMPOSE를 먼저 하라.",
                "  - 추가 tool 호출이 필요하면 AGGREGATE에 tool_request를 붙이지 말고 EXECUTE를 사용하라.",
                "  - 동일 지표가 여러 child에 연도별로 분산되어 있으면, 하나의 Markdown 표로 join하라.",
                "  - child별로 나열하지 마라. 주제별로 결합하라.",
                "  - 결합 시 원본 수치를 보존하라.",
                "  - child output에 status='facts_only'가 있거나 미검증/공백이 표시되면, 그 불확실성을 유지하라.",
                "  - child들이 facts_only 결과만 냈다면, 빈 aggregate를 반환하지 말고 그 내용을 output 또는 facts에 담아라.",
                "  - 검증 실패나 data gap을 확인된 사실처럼 승격하지 마라.",
            ]
        )
    if Action.FINALIZE in allowed:
        lines.extend(
            [
                f"FINALIZE: produce the final report (root_task={root_only} only). Must include output.",
                "  - Trading/investment decision framing comes first; full structure is in [FINALIZE_GUIDANCE] when child outputs are available.",
            ]
        )
    if Action.FAIL in allowed:
        lines.append(
            "FAIL: stop the task when it cannot continue with the available tools or facts."
        )
    lines.extend(
        [
            "",
            "Use web_search_tool with search_mode='sec' for latest filing search, 10-Q, 8-K, DEF 14A, proxy, or EDGAR lookup tasks.",
            "Market rule: Korean-listed companies (KRX/KOSPI/KOSDAQ/KONEX) use opendart_tool for financial statements and disclosures.",
            "Market rule: US-listed stocks use yfinance_balance_sheet by default for financials and ratios.",
            "Use sec_tool only when you specifically need data from a specific US 10-K.",
            "Do not use opendart_tool for US equities, and do not use yfinance_balance_sheet for Korean listings, unless the preferred market tool already failed.",
            "Use sec_tool only for extracting data from a specific year's 10-K.",
            "For web_search_tool, pass query only; the runtime will inject as_of_utc/time_scope/target period.",
            # "Use domain_tool with grounding_mode='grounded_required' for current/historical/mixed tasks.",
            # "Use domain_tool with grounding_mode='synthesis_only' only for future-only scenario synthesis.",
            "Prefer WAIT over inventing missing facts.",
            "",
            "[REQUIREMENTS]는 분석이 충족해야 할 조건이다.",
            "AGGREGATE/FINALIZE 전에 child outputs가 requirements를 커버하는지 확인하라.",
            "미충족 requirement가 있고 추가 데이터 수집이 가능하면 DECOMPOSE를 선택하라.",
            "수집 불가한 requirement는 output에서 gap으로 명시하라.",
            "",
            "재무 추이 분석(성장률, CAGR, 마진 변동)이 필요하면 "
            "yfinance_balance_sheet를 연도별로 분리 호출하되, 반드시 하나의 부모 태스크로 묶어라. "
            "단일 연도 데이터로 추세를 주장하지 마라.",
            "한국 상장사의 연도별 재무제표도 opendart_tool을 연도별로 분리 호출해 같은 방식으로 집계하라.",
            "",
            "포괄적 밸류에이션을 위해, 분해 시 다음 차원을 커버하라:",
            "  - 비용 구조: SBC, CapEx, 영업 레버리지",
            "  - 경쟁 포지셔닝: 동종업체 비교, 시장 점유율, 상대 멀티플",
            "  - 매출 세분화: 제품/지역별, 부문별 성장률",
        ]
    )
    if task.last_tool_success is True:
        lines.append(
            "This task already has a successful tool result. You must not return EXECUTE."
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
    if Action.EXECUTE in allowed and Action.DECOMPOSE in allowed:
        lines.extend(
            [
                "If the task needs multiple tool calls, use DECOMPOSE instead.",
                "If you cannot name a specific tool and args, you MUST use DECOMPOSE, not EXECUTE.",
                "Prefer shallow decomposition when one tool call plus AGGREGATE is enough.",
            ]
        )
    if Action.FINALIZE not in allowed:
        lines.append("FINALIZE is only allowed for the root task.")
    if not allow_decompose:
        lines.append("Do not return DECOMPOSE on this retry.")
    if task.blocked_tools and Action.EXECUTE in allowed:
        lines.append(
            "The following tools are blocked for this task after repeated consecutive "
            "failures: "
            + ", ".join(sorted(task.blocked_tools))
            + ". Use a different tool or DECOMPOSE."
        )
    if task.tool_hint:
        lines.append(f"Prefer tool_hint={task.tool_hint} when EXECUTE is appropriate.")
    return "\n".join(lines)


def build_step_prompt(
    *,
    task: Task,
    ctx: TaskContext,
    allowed_actions: list[Action],
    max_prompt_chars: int,
    prompt_child_output_budget_chars: int,
    prompt_value_preview_chars: int,
    prompt_query_chars: int,
    tool_spec_preview_chars: int = 300,
    child_output_budget: int | None = None,
    sibling_preview_chars: int | None = None,
) -> str:
    co_budget = child_output_budget or prompt_child_output_budget_chars
    sib_preview = sibling_preview_chars or tool_spec_preview_chars

    sections = [
        f"[TASK_ID]\n{task.id}",
        f"[TASK]\n{task.description}",
        f"[STATE]\nstep_count={ctx.step_count}\nstatus={task.state.value}",
        "[ALLOWED_ACTIONS]\n" + ", ".join(action.value for action in allowed_actions),
        "[TEMPORAL_CONTRACT]\n" + temporal_contract_text(ctx),
    ]
    if ctx.query_units:
        sections.append("[QUERY_UNITS]\n" + query_units_text(task, ctx))
    subjects = subjects_text(ctx)
    if subjects:
        sections.append("[SUBJECTS]\n" + subjects)
    if task.tool_hint:
        sections.append(f"[TOOL_HINT]\n{task.tool_hint}")
    if task.blocked_tools:
        sections.append("[BLOCKED_TOOLS]\n" + ", ".join(sorted(task.blocked_tools)))
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
            f"{preview_json(latest.result, max_chars=prompt_value_preview_chars)}"
        )
    if task.last_tool_request is not None:
        sections.append(
            "[LAST_TOOL_REQUEST]\n"
            f"{task.last_tool_request.tool_name} "
            f"{preview_json(task.last_tool_request.args, max_chars=prompt_value_preview_chars)}"
        )
    if task.last_tool_success is not None:
        sections.append(f"[LAST_TOOL_SUCCESS]\n{task.last_tool_success}")
    if ctx.child_outputs:
        per_child = co_budget // len(ctx.child_outputs)
        child_lines = [
            f"{child_id}: {preview_json(output, max_chars=per_child)}"
            for child_id, output in ctx.child_outputs.items()
        ]
        sections.append("[CHILD_OUTPUTS]\n" + "\n".join(child_lines))
    if ctx.current_children:
        failed = [s for s in ctx.current_children if s.state == TaskState.FAILED]
        sections.append(
            "[CURRENT_CHILDREN]\n"
            + "\n".join(
                task_summary_line(summary, output_preview_chars=sib_preview)
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
            shared_fact_line(
                key=key,
                fact=fact,
                prompt_value_preview_chars=prompt_value_preview_chars,
            )
            for key, fact in ctx.shared.facts.items()
        ]
        sections.append("[SHARED_FACTS]\n" + "\n".join(fact_lines))
    if ctx.shared.conflicts:
        conflict_lines = [
            f"{conflict.key}: {preview_json(conflict.existing.value, max_chars=prompt_value_preview_chars)}"
            f" vs {preview_json(conflict.incoming.value, max_chars=prompt_value_preview_chars)}"
            for conflict in ctx.shared.conflicts
        ]
        sections.append("[CONFLICTS]\n" + "\n".join(conflict_lines))
    if ctx.siblings:
        sibling_lines = [
            task_summary_line(summary, output_preview_chars=sib_preview)
            for summary in ctx.siblings.values()
        ]
        sections.append("[SIBLINGS]\n" + "\n".join(sibling_lines))
    if ctx.ancestry:
        sections.append(
            "[ANCESTRY]\n" + " -> ".join(summary.id for summary in ctx.ancestry)
        )

    requirements = requirements_for_task(ctx)
    if requirements:
        req_lines = [f"  {req.id}: {req.acceptance}" for req in requirements]
        sections.append("[REQUIREMENTS]\n" + "\n".join(req_lines))
    if Action.FINALIZE in allowed_actions and ctx.child_outputs:
        sections.append("[FINALIZE_GUIDANCE]\n" + finalize_guidance_text())

    sections.append("[AVAILABLE_TOOLS]\n" + available_tools_text(ctx))
    sections.append("Return valid JSON only.")
    prompt = "\n\n".join(sections)

    if len(prompt) > max_prompt_chars and ctx.child_outputs:
        overhead = len(prompt) - co_budget
        reduced_co_budget = max(
            max_prompt_chars - overhead,
            len(ctx.child_outputs) * 200,
        )
        reduced_sib_preview = min(sib_preview, 150)
        if reduced_co_budget < co_budget:
            return build_step_prompt(
                task=task,
                ctx=ctx,
                allowed_actions=allowed_actions,
                max_prompt_chars=max_prompt_chars,
                prompt_child_output_budget_chars=prompt_child_output_budget_chars,
                prompt_value_preview_chars=prompt_value_preview_chars,
                prompt_query_chars=prompt_query_chars,
                tool_spec_preview_chars=tool_spec_preview_chars,
                child_output_budget=reduced_co_budget,
                sibling_preview_chars=reduced_sib_preview,
            )
    return prompt


def finalize_guidance_text() -> str:
    return "\n".join(
        [
            "Child outputs are your structured data layer. FINALIZE must deliver a trading- and investment-actionable conclusion first, then layered evidence.",
            "",
            "[PRIORITY — TRADING / INVESTMENT DECISION FIRST]",
            "- Open with a decision-oriented summary: what the evidence implies for 매수·보유·축소·관망 (or equivalent) at as_of_utc, only when child outputs support it; otherwise state uncertainty explicitly.",
            "- Near the top, include when data allows: (1) market price or valuation snapshot vs thesis, (2) scenario-level upside/downside direction, (3) the shortest list of reasons that drive the action view.",
            "- Do not lead with DCF alone or end on intrinsic value only. DCF/fair value is supporting evidence, not the sole headline.",
            "",
            "[DATA PRESERVATION]",
            "- Every number, ratio, and factual finding from child outputs MUST appear in the report.",
            "- Do NOT summarize away detail. The final report must be MORE comprehensive than any single child.",
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
            "- facts_only, unverified, data gap, could not verify 성격의 정보는 확정 사실처럼 쓰지 마라.",
            "",
            "[TEMPORAL SEPARATION]",
            "- Separate historical facts, current assessment, and future scenarios into distinct sentences or sections.",
            "- Use absolute dates: historical claims should stay inside the target period, and current claims should be anchored to as_of_utc.",
            "- grounded=false or unverified information must remain uncertainty, not present-tense fact.",
            "",
            "[SCENARIOS — BULL / BASE / BEAR + TRADING HOOKS]",
            "- Bull / Base / Bear with quantified reasoning (target metrics, not just narratives).",
            "- Key assumptions that differentiate each scenario.",
            "- Rank uncertainties by magnitude of impact on valuation.",
            "- 각 시나리오에 정량적 진입/이탈 조건: 목표가 구간, 멀티플 상·하단, 실적·성장률 trigger, 관찰 가능한 촉매/리스크 이벤트.",
            "- 어떤 관찰 가능 지표가 변하면 시나리오 간 전환이 일어나는지 명시하라.",
            "- Where child outputs lack price data, say so and still give multiple- and scenario-based hooks.",
            "",
            "[COVERAGE]",
            "- [REQUIREMENTS]의 모든 항목이 보고서 어딘가에서 충족되어야 한다.",
            "- 충족 불가한 항목은 [INFORMATION GAPS]에서 사유와 투자 판단에 미치는 영향을 명시하라.",
            "- 섹션 구조는 분석 흐름에 따라 자유롭게 구성하라 (requirement별 섹션 강제 아님).",
            "",
            "Be comprehensive — length is not a constraint.",
            "Write the final report markdown in Korean.",
        ]
    )


def available_tools_text(ctx: TaskContext) -> str:
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


def requirements_for_task(ctx: TaskContext) -> list[Any]:
    if not ctx.query_units:
        return list(ctx.query_analysis.requirements)
    relevant_unit_ids = {
        index
        for index, unit in enumerate(ctx.query_analysis.units)
        if unit in ctx.query_units
    }
    requirements = [
        requirement
        for requirement in ctx.query_analysis.requirements
        if relevant_unit_ids.intersection(requirement.unit_ids)
    ]
    return requirements or list(ctx.query_analysis.requirements)


def temporal_contract_text(ctx: TaskContext) -> str:
    temporal = summarize_temporal_contract(
        as_of_utc=ctx.as_of_utc,
        units=ctx.query_units,
    )
    lines = [f"as_of_utc={temporal.as_of_utc or '(unknown)'}"]
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
        lines.append(
            f"{index}: id={unit.id}; objective={unit.objective}; "
            f"retrieval_query={unit.retrieval_query}; "
            f"time_scope={unit.time_scope or '(none)'}; "
            f"target_start={unit.target_start or '(none)'}; "
            f"target_end={unit.target_end or '(none)'}"
        )
    return "\n".join(lines) or "(none)"


def subjects_text(ctx: TaskContext) -> str:
    subjects = ctx.query_analysis.query_intent.subjects
    if not subjects:
        return ""

    lines: list[str] = []
    for subject in subjects:
        company = subject.company.company_name
        listing = subject.listing
        if listing is None:
            lines.append(f"{company}: market=unknown; preferred_tool=web_search_tool")
            continue

        market = listing.legacy_market
        if market == "KRX":
            tool = "opendart_tool"
        elif market == "USA":
            tool = "yfinance_balance_sheet"
        else:
            tool = "web_search_tool"
        lines.append(
            f"{company}: exchange={listing.exchange}; "
            f"security_code={listing.security_code}; "
            f"market={market}; preferred_tool={tool}"
        )
    return "\n".join(lines)


def shared_fact_line(*, key: str, fact: Any, prompt_value_preview_chars: int) -> str:
    meta = [f"from {fact.source_task_id}", f"grounded={fact.grounded}"]
    if fact.time_scope:
        meta.append(f"time_scope={fact.time_scope}")
    if fact.target_start or fact.target_end:
        meta.append(
            "target=" f"{fact.target_start or '(open)'}..{fact.target_end or '(open)'}"
        )
    if fact.source_urls:
        meta.append(f"sources={len(fact.source_urls)}")
    return f"{key}: {preview_json(fact.value, max_chars=prompt_value_preview_chars)} ({', '.join(meta)})"


def preview_json(value: Any, *, max_chars: int) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return text
    return truncate_preserving_tables(text, max_chars)


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


def task_summary_line(summary: TaskSummary, *, output_preview_chars: int) -> str:
    line = f"{summary.id}: {summary.state.value} - {summary.description}"
    if summary.output is not None:
        line += (
            f" | output={preview_json(summary.output, max_chars=output_preview_chars)}"
        )
    return line


def truncate_preserving_tables(text: str, limit: int) -> str:
    table_blocks: list[tuple[int, int]] = []
    lines = text.split("\\n")
    i = 0
    pos = 0
    while i < len(lines):
        line = lines[i]
        line_start = pos
        pos += len(line) + 2
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
