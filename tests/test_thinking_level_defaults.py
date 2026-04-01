from __future__ import annotations

import asyncio

from server.services.task_rewrite.service import TaskRewriteService


class _DummyTaskRewriteRepository:
    async def save_rewrite(self, history):
        return history.rewrite_id


class _DummyTaskRewriteLLMClient:
    def __init__(self):
        self.calls: list[dict[str, str | None]] = []

    async def rewrite_task(
        self,
        *,
        task: str,
        custom_prompt: str | None,
        model: str,
        thinking_level: str | None,
    ) -> str:
        self.calls.append(
            {
                "task": task,
                "custom_prompt": custom_prompt,
                "model": model,
                "thinking_level": thinking_level,
            }
        )
        return "rewritten"


def test_task_rewrite_service_uses_default_thinking_level_when_missing() -> None:
    llm_client = _DummyTaskRewriteLLMClient()
    service = TaskRewriteService(
        repository=_DummyTaskRewriteRepository(),
        llm_client=llm_client,
    )

    history = asyncio.run(
        service.rewrite_task(
            task="rewrite me",
            model="gemini-3-flash-preview",
        )
    )

    assert history.rewritten_task == "rewritten"
    assert llm_client.calls == [
        {
            "task": "rewrite me",
            "custom_prompt": None,
            "model": "gemini-3-flash-preview",
            "thinking_level": "low",
        }
    ]
