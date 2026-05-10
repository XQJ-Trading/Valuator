from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..context import TaskContext
from ..task import Task
from ..types import Action, TaskDecision
from . import prompts
from .parser import TASK_NAME_MAX_CHARS, StepIntentPayload, parse_decision

_PLANNER_SYSTEM_CACHE_KEY = "planner:system-prefix:v1"
# Gemini explicit cache forbids system_instruction on GenerateContent; fold per-call system into user text.
_STEP_PLANNER_CACHED_CONTEXT_TAG = "[STEP_PLANNER_CONTEXT]"


class StepPlanner:
    """Boundary adapter: TaskContext -> LLM JSON -> TaskDecision."""

    _decision_max_response_chars = 100_000
    _decision_max_output_tokens = 8_192
    _max_prompt_chars = 150_000

    def __init__(
        self,
        llm_client: Any,
        repair_retries: int | None = None,
    ) -> None:
        from ...utils.config import config

        self._llm = llm_client
        configured_retries = (
            config.agent_step_repair_retries
            if repair_retries is None
            else repair_retries
        )
        self._repair_retries = max(int(configured_retries), 0)

    async def decide(self, task: Task, ctx: TaskContext) -> TaskDecision:
        allow_decompose = True
        allowed = self._allowed_actions(task, allow_decompose=allow_decompose)
        system_prompt, cached_content = await self._planner_prompt_config(
            task=task,
            ctx=ctx,
            allow_decompose=allow_decompose,
            allowed_actions=allowed,
        )
        base_prompt = prompts.build_step_prompt(
            task=task,
            ctx=ctx,
            allowed_actions=allowed,
            max_prompt_chars=self._max_prompt_chars,
            prompt_value_preview_chars=600,
            prompt_query_chars=3_000,
        )
        return await self._generate_decision(
            task=task,
            base_prompt=base_prompt,
            system_prompt=system_prompt,
            cached_content=cached_content,
            schema=self._decision_schema(task, allow_decompose=allow_decompose),
            allow_decompose=allow_decompose,
        )

    async def requery_without_decompose(
        self,
        task: Task,
        ctx: TaskContext,
        rejection_reason: str,
    ) -> TaskDecision:
        allowed = self._allowed_actions(task, allow_decompose=False)
        system_prompt, cached_content = await self._planner_prompt_config(
            task=task,
            ctx=ctx,
            allow_decompose=False,
            allowed_actions=allowed,
        )
        base_prompt = prompts.build_step_prompt(
            task=task,
            ctx=ctx,
            allowed_actions=allowed,
            max_prompt_chars=self._max_prompt_chars,
            prompt_value_preview_chars=600,
            prompt_query_chars=3_000,
        )
        decision = await self._generate_decision(
            task=task,
            base_prompt="\n\n".join(
                [base_prompt, "[DECOMPOSITION_REJECTED]", rejection_reason]
            ),
            system_prompt=system_prompt,
            cached_content=cached_content,
            schema=self._decision_schema(task, allow_decompose=False),
            allow_decompose=True,
        )
        if decision.action is Action.DECOMPOSE:
            raise ValueError("requery_without_decompose returned decompose")
        return decision

    async def _generate_decision(
        self,
        *,
        task: Task,
        base_prompt: str,
        system_prompt: str,
        cached_content: str | None,
        schema: dict[str, Any],
        allow_decompose: bool = True,
    ) -> TaskDecision:
        def llm_prompt(*, user_body: str) -> tuple[str, str]:
            if cached_content:
                sections = [
                    _STEP_PLANNER_CACHED_CONTEXT_TAG,
                    system_prompt.strip(),
                    user_body,
                ]
                return "", "\n\n".join(section for section in sections if section)
            return system_prompt, user_body

        llm_system, prompt = llm_prompt(user_body=base_prompt)
        last_error: ValueError | None = None

        for attempt in range(self._repair_retries + 1):
            try:
                invalid_payload = await self._llm.generate_json(
                    prompt=prompt,
                    system_prompt=llm_system,
                    response_json_schema=schema,
                    trace_method=f"agent.step.{task.id}",
                    max_response_chars=self._decision_max_response_chars,
                    max_output_tokens=self._decision_max_output_tokens,
                    cached_content=cached_content,
                )
                decision = parse_decision(
                    task, invalid_payload, allow_decompose=allow_decompose
                )
                self._validate_decision_contract(decision)
                return decision
            except ValueError as exc:
                last_error = exc
                if attempt >= self._repair_retries:
                    break
                repair_body = "\n\n".join(
                    [
                        base_prompt,
                        "[VALIDATION_ERROR]",
                        str(exc),
                        "Fix only the contract violation above while preserving intent.",
                        "Return corrected JSON only.",
                    ]
                )
                llm_system, prompt = llm_prompt(user_body=repair_body)

        if last_error is None:
            raise ValueError("step planner produced no decision")
        raise last_error

    async def _planner_prompt_config(
        self,
        *,
        task: Task,
        ctx: TaskContext,
        allow_decompose: bool,
        allowed_actions: list[Action],
    ) -> tuple[str, str | None]:
        dynamic_suffix = prompts.build_system_prompt_suffix(
            task=task,
            ctx=ctx,
            allow_decompose=allow_decompose,
            task_name_max_chars=TASK_NAME_MAX_CHARS,
            allowed_actions=allowed_actions,
        )
        cached_content = await self._llm.get_or_create_explicit_cache(
            cache_key=_PLANNER_SYSTEM_CACHE_KEY,
            system_prompt=prompts.static_system_prefix(),
            display_name="planner-system-prefix",
            trace_method="agent.step.cache.planner",
        )
        if cached_content:
            return dynamic_suffix, cached_content
        return (
            prompts.build_system_prompt(
                task=task,
                ctx=ctx,
                allow_decompose=allow_decompose,
                task_name_max_chars=TASK_NAME_MAX_CHARS,
                allowed_actions=allowed_actions,
            ),
            None,
        )

    def _validate_decision_contract(self, decision: TaskDecision) -> None:
        for child in decision.children:
            if len(child.task_name) > TASK_NAME_MAX_CHARS:
                raise ValueError(
                    f"task_name must be <= {TASK_NAME_MAX_CHARS} characters"
                )

    def _allowed_actions(
        self,
        task: Task,
        *,
        allow_decompose: bool = True,
    ) -> list[Action]:
        from .actions import allowed_actions_for_task

        return allowed_actions_for_task(task, allow_decompose=allow_decompose)

    def _decision_schema(
        self,
        task: Task,
        *,
        allow_decompose: bool = True,
    ) -> dict[str, Any]:
        schema = deepcopy(StepIntentPayload.model_json_schema())
        schema["$defs"]["Action"]["enum"] = [
            action.value
            for action in self._allowed_actions(task, allow_decompose=allow_decompose)
        ]
        return schema
