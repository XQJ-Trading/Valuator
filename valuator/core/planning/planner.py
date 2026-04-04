from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..context import TaskContext
from ..decomposition.gate import static_rejects_minimal_decomposition
from ..decomposition.gate_config import GateConfig
from ..task import Task
from ..types import Action, TaskDecision
from . import prompts
from .parser import StepIntentPayload, parse_decision

TASK_NAME_MAX_CHARS = 30


class StepPlanner:
    """Boundary adapter: TaskContext -> LLM JSON -> TaskDecision."""

    _decision_max_response_chars = 100_000
    _decision_max_output_tokens = 8_192
    _prompt_value_preview_chars = 600
    _prompt_query_chars = 3_000
    _prompt_child_output_budget_chars = 50_000
    _max_prompt_chars = 150_000

    def __init__(
        self,
        llm_client: Any,
        repair_retries: int | None = None,
        *,
        gate_config: GateConfig | None = None,
        max_steps_per_task: int | None = None,
    ) -> None:
        from ...utils.config import config

        self._llm = llm_client
        configured_retries = (
            config.agent_step_repair_retries
            if repair_retries is None
            else repair_retries
        )
        self._repair_retries = max(int(configured_retries), 0)
        self._gate_config = gate_config
        self._max_steps_per_task = (
            int(max_steps_per_task)
            if max_steps_per_task is not None
            else int(config.agent_max_steps_per_task)
        )

    async def decide(self, task: Task, ctx: TaskContext) -> TaskDecision:
        gate_cfg = self._gate_config or GateConfig()
        allow_decompose = True
        if gate_cfg.enabled and static_rejects_minimal_decomposition(
            task_depth=len(ctx.ancestry),
            max_steps_per_task=self._max_steps_per_task,
            config=gate_cfg,
        ):
            allow_decompose = False

        allowed = self._allowed_actions(task, allow_decompose=allow_decompose)
        base_prompt = prompts.build_step_prompt(
            task=task,
            ctx=ctx,
            allowed_actions=allowed,
            max_prompt_chars=self._max_prompt_chars,
            prompt_child_output_budget_chars=self._prompt_child_output_budget_chars,
            prompt_value_preview_chars=self._prompt_value_preview_chars,
            prompt_query_chars=self._prompt_query_chars,
        )
        return await self._generate_decision(
            task=task,
            base_prompt=base_prompt,
            system_prompt=prompts.build_system_prompt(
                task=task,
                ctx=ctx,
                allow_decompose=allow_decompose,
                task_name_max_chars=TASK_NAME_MAX_CHARS,
                allowed_actions=allowed,
            ),
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
        base_prompt = prompts.build_step_prompt(
            task=task,
            ctx=ctx,
            allowed_actions=allowed,
            max_prompt_chars=self._max_prompt_chars,
            prompt_child_output_budget_chars=self._prompt_child_output_budget_chars,
            prompt_value_preview_chars=self._prompt_value_preview_chars,
            prompt_query_chars=self._prompt_query_chars,
        )
        decision = await self._generate_decision(
            task=task,
            base_prompt="\n\n".join(
                [base_prompt, "[DECOMPOSITION_REJECTED]", rejection_reason]
            ),
            system_prompt=prompts.build_system_prompt(
                task=task,
                ctx=ctx,
                allow_decompose=False,
                task_name_max_chars=TASK_NAME_MAX_CHARS,
                allowed_actions=allowed,
            ),
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
        schema: dict[str, Any],
        allow_decompose: bool = True,
    ) -> TaskDecision:
        prompt = base_prompt
        last_error: ValueError | None = None

        for attempt in range(self._repair_retries + 1):
            try:
                invalid_payload = await self._llm.generate_json(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    response_json_schema=schema,
                    trace_method=f"agent.step.{task.id}",
                    max_response_chars=self._decision_max_response_chars,
                    max_output_tokens=self._decision_max_output_tokens,
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
                prompt = "\n\n".join(
                    [
                        base_prompt,
                        "[VALIDATION_ERROR]",
                        str(exc),
                        "Fix only the contract violation above while preserving intent.",
                        "Return corrected JSON only.",
                    ]
                )

        if last_error is None:
            raise ValueError("step planner produced no decision")
        raise last_error

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
