from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .context import TaskContext
from .decomposition_types import CriticVerdict
from .task import Task
from .types import TaskDecision


class _CriticPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow: bool
    single_tool_possible: bool
    redundant_pairs: list[list[int]] = Field(default_factory=list)
    coverage_pct: int = Field(ge=0, le=100)
    min_children: int = Field(ge=0)
    reason: str


class DecompositionCritic:
    def __init__(self, llm_client: Any) -> None:
        self._llm = llm_client

    async def evaluate(
        self,
        task: Task,
        decision: TaskDecision,
        ctx: TaskContext,
    ) -> CriticVerdict:
        prompt = self._build_prompt(task, decision, ctx)
        raw = await self._llm.generate_json(
            prompt=prompt,
            system_prompt=self._system_prompt(is_root=not ctx.ancestry),
            response_json_schema=_CriticPayload.model_json_schema(),
            trace_method=f"agent.gate.critic.{task.id}",
            max_response_chars=20_000,
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
                f"{summary.id}: {summary.description}"
                for summary in ctx.ancestry
            ]
            sections.append("[ANCESTRY]\n" + "\n".join(ancestry_lines))
        else:
            sections.append("[ANCESTRY]\n(root)")
            qa = ctx.query_analysis
            subject_lines = []
            for subject in qa.query_intent.subjects:
                line = subject.company.company_name
                if subject.listing:
                    line += f" ({subject.listing.exchange}: {subject.listing.security_code})"
                subject_lines.append(line)
            if subject_lines:
                sections.append("[SUBJECTS]\n" + "\n".join(subject_lines))
            if qa.intent_tags:
                sections.append("[INTENT_TAGS]\n" + ", ".join(qa.intent_tags))
            if qa.domain_ids:
                sections.append("[ACTIVE_DOMAINS]\n" + ", ".join(qa.domain_ids))

        child_lines = [
            f"{index}. description={child.description}; tool_hint={child.tool_hint or '-'}"
            for index, child in enumerate(decision.children)
        ]
        sections.append("[PROPOSED_CHILDREN]\n" + "\n".join(child_lines))
        if ctx.current_children:
            current_children_lines = [
                f"{summary.id}: {summary.state.value} - {summary.description}"
                for summary in ctx.current_children
            ]
            sections.append("[CURRENT_CHILDREN]\n" + "\n".join(current_children_lines))

        available_tools = "\n".join(ctx.available_tools) if ctx.available_tools else "(none)"
        sections.append(f"[AVAILABLE_TOOLS]\n{available_tools}")
        sections.append(
            "[TASK_CONTEXT]\n"
            f"query={ctx.query}\n"
            f"step_count={ctx.step_count}\n"
            f"last_reason={json.dumps(decision.reason, ensure_ascii=False, default=str)}"
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
                    "- Do any tracks overlap or could they be consolidated?",
                    "Set allow=false if the plan fundamentally mismatches the subject.",
                    "Return JSON only.",
                ]
            )
        return "\n".join(
            [
                "You are a decomposition gate critic.",
                "Evaluate the proposed decomposition before expansion.",
                "Judge whether one tool call could solve the parent task, whether children overlap,",
                "how much the children cover the parent goal, the minimum children actually needed,",
                "and whether this decomposition should be allowed.",
                "If a proposed child substantially overlaps an existing current child, reject it as redundant.",
                "Return JSON only.",
            ]
        )

    def _to_verdict(self, payload: _CriticPayload) -> CriticVerdict:
        return CriticVerdict(
            allow=payload.allow,
            single_tool_possible=payload.single_tool_possible,
            redundant_pairs=[
                (pair[0], pair[1])
                for pair in payload.redundant_pairs
                if len(pair) >= 2
            ],
            coverage_pct=payload.coverage_pct,
            min_children=payload.min_children,
            reason=payload.reason,
        )
