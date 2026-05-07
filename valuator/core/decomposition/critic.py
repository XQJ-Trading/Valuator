from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..context import TaskContext
from ..task import Task
from ..types import TaskDecision
from .types import CriticVerdict

_ROOT_CRITIC_CACHE_KEY = "critic:root-system:v1"
_NON_ROOT_CRITIC_CACHE_KEY = "critic:non-root-system:v1"


class _CriticPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow: bool
    single_tool_possible: bool
    redundant_pairs: list[list[int]] = Field(default_factory=list)
    coverage_pct: int = Field(ge=0, le=100)
    min_children: int = Field(ge=0)
    reason: str


class DecompositionCritic:
    _max_output_tokens = 2_048

    def __init__(self, llm_client: Any) -> None:
        self._llm = llm_client

    async def evaluate(
        self,
        task: Task,
        decision: TaskDecision,
        ctx: TaskContext,
    ) -> CriticVerdict:
        prompt = self._build_prompt(task, decision, ctx)
        system_prompt = self._system_prompt(is_root=not ctx.ancestry)
        cached_content = await self._llm.get_or_create_explicit_cache(
            cache_key=(
                _ROOT_CRITIC_CACHE_KEY if not ctx.ancestry else _NON_ROOT_CRITIC_CACHE_KEY
            ),
            system_prompt=system_prompt,
            display_name="critic-root" if not ctx.ancestry else "critic-non-root",
            trace_method="agent.gate.cache.critic",
        )
        raw = await self._llm.generate_json(
            prompt=prompt,
            system_prompt="" if cached_content else system_prompt,
            response_json_schema=_CriticPayload.model_json_schema(),
            trace_method=f"agent.gate.critic.{task.id}",
            max_response_chars=20_000,
            max_output_tokens=self._max_output_tokens,
            cached_content=cached_content,
        )
        payload = _CriticPayload.model_validate(raw)
        return self._to_verdict(payload)

    def _build_prompt(
        self,
        task: Task,
        decision: TaskDecision,
        ctx: TaskContext,
    ) -> str:
        sections = [
            f"[PARENT_TASK]\n{task.description}",
            f"[PARENT_TASK_ID]\n{task.id}",
        ]
        if ctx.ancestry:
            ancestry_lines = [
                f"{summary.id}: {summary.description}" for summary in ctx.ancestry
            ]
            sections.append("[ANCESTRY]\n" + "\n".join(ancestry_lines))
        else:
            sections.append("[ANCESTRY]\n(root)")
            qa = ctx.query_analysis
            subject_lines = []
            for subject in qa.query_intent.subjects:
                line = f"[{subject.role.value}] {subject.company.company_name}"
                if subject.listing:
                    line += f" ({subject.listing.exchange}: {subject.listing.security_code})"
                subject_lines.append(line)
            if subject_lines:
                sections.append("[SUBJECTS]\n" + "\n".join(subject_lines))
            if qa.intent_tags:
                sections.append("[INTENT_TAGS]\n" + ", ".join(qa.intent_tags))

        child_lines = [
            f"{index}. description={child.description}; tool_hint={child.tool_hint or '-'}; "
            f"execution_tool={child.execution_tool or '-'}; "
            f"depends_on_siblings={list(child.depends_on_siblings)}"
            for index, child in enumerate(decision.children)
        ]
        sections.append("[PROPOSED_CHILDREN]\n" + "\n".join(child_lines))
        if ctx.current_children:
            current_children_lines = [
                f"{summary.id}: {summary.state.value} - {summary.description}"
                for summary in ctx.current_children
            ]
            sections.append("[CURRENT_CHILDREN]\n" + "\n".join(current_children_lines))

        available_tools = (
            "\n".join(ctx.available_tools) if ctx.available_tools else "(none)"
        )
        sections.append(f"[AVAILABLE_TOOLS]\n{available_tools}")
        sections.append(
            "[TASK_CONTEXT]\n" f"query={ctx.query}\n" f"step_count={ctx.step_count}"
        )
        sections.append("Return valid JSON only.")
        return "\n\n".join(sections)

    def _system_prompt(self, *, is_root: bool = False) -> str:
        if is_root:
            return "\n".join(
                [
                    "You are the plan critic for a recursive valuation agent.",
                    "The root decomposition defines the analysis plan — each child becomes an independent research track.",
                    "Evaluate the plan as a whole:",
                    "- Are the proposed tracks appropriate for the subject's industry and business model?",
                    "  Reject tracks that assume inapplicable characteristics (e.g., supply-chain analysis for a pure-services company).",
                    "- Are important analytical perspectives missing given the subject?",
                    "  Lower coverage_pct when the plan omits relevant areas or includes irrelevant ones.",
                    "- Does the plan follow the two-phase pattern? Phase 1 = data collection by information type, Phase 2 = analysis by perspective with depends_on_siblings referencing Phase 1.",
                    "- Financial statements and PER/PBR/EV/EBITDA multiples (for the subject and for peers) must be collected via opendart_financial_tool (Korean) or yfinance_balance_sheet (others). Korean annual PER/PBR should use year-end KRX market data and explicit basis dates; current-price snapshots must not be treated as historical annual prices.",
                    "- Peer comparison plans must decompose into one financial-tool child per peer (one opendart_financial_tool or yfinance_balance_sheet call per company); reject plans that handle peer valuation through a single web_search_tool call. web_search_tool is only valid for peer identification, news, and qualitative information; it must not be used to fetch financial figures or consensus/forward valuation estimates.",
                    "- Reject if Phase 1 children overlap in data sources, or if Phase 2 children lack depends_on_siblings.",
                    "- Do any tracks overlap or could they be consolidated?",
                    "Set allow=false if the plan fundamentally mismatches the subject.",
                    "Return JSON only.",
                ]
            )
        return "\n".join(
            [
                "You are a decomposition gate critic.",
                "Evaluate the proposed decomposition before expansion.",
                "Judge whether one tool call could solve the parent task,",
                "how much the children cover the parent goal, the minimum children actually needed,",
                "and whether this decomposition should be allowed.",
                "Return JSON only.",
            ]
        )

    def _to_verdict(self, payload: _CriticPayload) -> CriticVerdict:
        return CriticVerdict(
            allow=payload.allow,
            single_tool_possible=payload.single_tool_possible,
            redundant_pairs=[
                (pair[0], pair[1]) for pair in payload.redundant_pairs if len(pair) >= 2
            ],
            coverage_pct=payload.coverage_pct,
            min_children=payload.min_children,
            reason=payload.reason,
        )
