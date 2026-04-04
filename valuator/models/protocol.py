from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..utils.llm_usage import TokenUsage


@runtime_checkable
class UsageWriter(Protocol):
    def append_call(
        self,
        *,
        method: str,
        model: str,
        usage: TokenUsage,
        latency_seconds: float,
        started_at: str,
    ) -> None:
        ...

    def log_llm_call(
        self,
        *,
        trace_method: str,
        model: str,
        prompt: str,
        system_prompt: str,
        response_mime_type: str | None,
        response_json_schema: dict[str, Any] | None,
        response_text: str | None,
        usage: dict[str, Any] | None,
        latency_ms: float,
        started_at: str,
        error: str | None = None,
    ) -> None:
        ...


@runtime_checkable
class LlmClient(Protocol):
    model: str

    def bind_usage_writer(self, usage_writer: UsageWriter | None) -> None:
        ...

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        response_mime_type: str | None = None,
        response_json_schema: dict[str, Any] | None = None,
        trace_method: str = "llm.generate",
        max_output_tokens: int | None = None,
    ) -> str:
        ...

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
        ...
