from __future__ import annotations

import asyncio
import json
import queue
import threading
import uuid
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

from google import genai
from google.genai import chats, types

from ..utils.config import config
from ..utils.llm_usage import TokenUsage
from ..utils.time_utils import Measurement

_STREAM_DONE = object()
if TYPE_CHECKING:
    from .protocol import UsageWriter


@lru_cache(maxsize=1)
def ensure_supported_google_genai_runtime() -> str:
    try:
        installed_version = version("google-genai")
    except PackageNotFoundError as exc:
        raise RuntimeError(
            "google-genai is not installed. Install dependencies from requirements.txt."
        ) from exc

    try:
        types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema={"type": "object"},
        )
    except Exception as exc:
        raise RuntimeError(
            "Unsupported google-genai runtime "
            f"({installed_version}). The project requires response_json_schema "
            "support and must run with the project environment."
        ) from exc
    return installed_version


class GeminiSession:
    def __init__(
        self,
        *,
        client: "GeminiClient",
        session_id: str,
        chat: chats.Chat,
        chat_config: types.GenerateContentConfig | None,
    ):
        self.client = client
        self.session_id = session_id
        self._chat = chat
        self._chat_config = chat_config
        self._history: list[dict[str, str]] = []

    def get_history(self) -> list[dict[str, str]]:
        return [dict(item) for item in self._history]

    def reset(self) -> None:
        self._chat = self.client._create_chat(self._chat_config)
        self._history = []

    async def send(self, prompt: str, track_history: bool = True) -> str:
        response = await asyncio.to_thread(self._chat.send_message, prompt)
        text = self.client._extract_text(response)
        if track_history:
            self._history.append({"role": "user", "content": prompt})
            self._history.append({"role": "assistant", "content": text})
        return text

    async def send_stream(
        self,
        prompt: str,
        track_history: bool = True,
    ) -> AsyncIterator[str]:
        chunks: list[str] = []
        async for chunk in self.client._stream_in_thread(
            lambda: self._chat.send_message_stream(prompt)
        ):
            chunks.append(chunk)
            yield chunk
        text = "".join(chunks).strip()
        if not text:
            raise ValueError("Empty response from Gemini")
        if track_history:
            self._history.append({"role": "user", "content": prompt})
            self._history.append({"role": "assistant", "content": text})

    async def send_message(self, prompt: str) -> str:
        return await self.send(prompt, track_history=True)

    async def send_message_stream(self, prompt: str) -> AsyncIterator[str]:
        async for chunk in self.send_stream(prompt, track_history=True):
            yield chunk


class GeminiClient:
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        client: genai.Client | None = None,
        usage_writer: "UsageWriter | None" = None,
        retry_count: int | None = None,
        retry_base_delay: float | None = None,
    ):
        key = api_key or config.google_api_key
        if not key:
            raise ValueError("Missing GOOGLE_API_KEY")
        self.model = model or config.agent_model
        self.client = client or genai.Client(api_key=key)
        self.usage_writer = usage_writer
        self._retry_count = (
            retry_count if retry_count is not None else config.agent_llm_retry_count
        )
        self._retry_base_delay = (
            retry_base_delay
            if retry_base_delay is not None
            else config.agent_llm_retry_base_delay
        )
        ensure_supported_google_genai_runtime()

    def bind_usage_writer(self, usage_writer: "UsageWriter | None") -> None:
        self.usage_writer = usage_writer

    def format_messages(self, system_prompt: str) -> dict[str, str]:
        return {"system_prompt": system_prompt}

    def start_chat_session(
        self,
        messages: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        response_mime_type: str | None = None,
        response_json_schema: dict[str, Any] | None = None,
    ) -> GeminiSession:
        system_prompt = ""
        if messages:
            system_prompt = str(messages.get("system_prompt") or "").strip()
        chat_config = self._build_config(
            system_prompt=system_prompt,
            response_mime_type=response_mime_type,
            response_json_schema=response_json_schema,
        )
        sid = session_id or f"gemini-{uuid.uuid4().hex[:12]}"
        return GeminiSession(
            client=self,
            session_id=sid,
            chat=self._create_chat(chat_config),
            chat_config=chat_config,
        )

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        response_mime_type: str | None = None,
        response_json_schema: dict[str, Any] | None = None,
        trace_method: str = "gemini.generate",
        max_output_tokens: int | None = None,
    ) -> str:
        config_obj = self._build_config(
            system_prompt=system_prompt,
            response_mime_type=response_mime_type,
            response_json_schema=response_json_schema,
            max_output_tokens=max_output_tokens,
        )
        writer = self.usage_writer

        for attempt in range(self._retry_count + 1):
            measurement = Measurement.start()
            usage = TokenUsage()
            try:
                response = await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=self.model,
                    contents=prompt,
                    config=config_obj,
                )
                latency_seconds = measurement.latency_seconds()
                usage = self._token_usage(getattr(response, "usage_metadata", None))
                response_text = self._extract_text(response)

                if writer is not None:
                    await asyncio.to_thread(
                        self._record_success_call,
                        writer=writer,
                        method=trace_method,
                        model=self.model,
                        usage=usage,
                        latency_seconds=latency_seconds,
                        started_at=measurement.started_at,
                        prompt=prompt,
                        system_prompt=system_prompt,
                        response_mime_type=response_mime_type,
                        response_json_schema=response_json_schema,
                        response_text=response_text,
                    )
                return response_text
            except Exception as exc:
                if writer is not None:
                    retry_suffix = (
                        f".retry{attempt}" if attempt < self._retry_count else ""
                    )
                    error_method = f"{trace_method}.error{retry_suffix}"
                    await asyncio.to_thread(
                        self._record_error_call,
                        writer=writer,
                        method=error_method,
                        model=self.model,
                        latency_seconds=measurement.latency_seconds(),
                        started_at=measurement.started_at,
                        prompt=prompt,
                        system_prompt=system_prompt,
                        response_mime_type=response_mime_type,
                        response_json_schema=response_json_schema,
                        error=str(exc),
                        usage=usage,
                    )
                if attempt >= self._retry_count:
                    raise
                await asyncio.sleep(self._retry_base_delay * (2**attempt))

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
        raw = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            response_mime_type="application/json",
            response_json_schema=response_json_schema,
            trace_method=trace_method,
            max_output_tokens=max_output_tokens,
        )
        if max_response_chars is not None and len(raw) > max_response_chars:
            raise ValueError(
                f"{trace_method} returned oversized JSON "
                f"({len(raw)} chars > {max_response_chars})"
            )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            decoder = json.JSONDecoder()
            data = None
            for index, char in enumerate(raw):
                if char != "{":
                    continue
                try:
                    candidate, _ = decoder.raw_decode(raw[index:])
                except json.JSONDecodeError:
                    continue
                if isinstance(candidate, dict):
                    data = candidate
                    break
            if data is None:
                raise ValueError(f"{trace_method} returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{trace_method} expected JSON object")
        return data

    def _record_success_call(
        self,
        *,
        writer: "UsageWriter",
        method: str,
        model: str,
        usage: TokenUsage,
        latency_seconds: float,
        started_at: str,
        prompt: str,
        system_prompt: str,
        response_mime_type: str | None,
        response_json_schema: dict[str, Any] | None,
        response_text: str,
    ) -> None:
        self._record_call(
            writer=writer,
            method=method,
            model=model,
            usage=usage,
            latency_seconds=latency_seconds,
            started_at=started_at,
            prompt=prompt,
            system_prompt=system_prompt,
            response_mime_type=response_mime_type,
            response_json_schema=response_json_schema,
            response_text=response_text,
            error=None,
        )

    def _record_error_call(
        self,
        *,
        writer: "UsageWriter",
        method: str,
        model: str,
        latency_seconds: float,
        started_at: str,
        prompt: str,
        system_prompt: str,
        response_mime_type: str | None,
        response_json_schema: dict[str, Any] | None,
        error: str,
        usage: TokenUsage | None = None,
    ) -> None:
        self._record_call(
            writer=writer,
            method=method,
            model=model,
            usage=usage if usage is not None else TokenUsage(),
            latency_seconds=latency_seconds,
            started_at=started_at,
            prompt=prompt,
            system_prompt=system_prompt,
            response_mime_type=response_mime_type,
            response_json_schema=response_json_schema,
            response_text=None,
            error=error,
        )

    def _record_call(
        self,
        *,
        writer: "UsageWriter",
        method: str,
        model: str,
        usage: TokenUsage,
        latency_seconds: float,
        started_at: str,
        prompt: str,
        system_prompt: str,
        response_mime_type: str | None,
        response_json_schema: dict[str, Any] | None,
        response_text: str | None,
        error: str | None,
    ) -> None:
        writer.append_call(
            method=method,
            model=model,
            usage=usage,
            latency_seconds=latency_seconds,
            started_at=started_at,
        )
        writer.log_llm_call(
            trace_method=method,
            model=model,
            prompt=prompt,
            system_prompt=system_prompt,
            response_mime_type=response_mime_type,
            response_json_schema=response_json_schema,
            response_text=response_text,
            usage=usage.to_dict(),
            latency_ms=latency_seconds * 1000.0,
            started_at=started_at,
            error=error,
        )

    @staticmethod
    def _token_usage(usage_metadata: Any) -> TokenUsage:
        if hasattr(usage_metadata, "model_dump"):
            usage_metadata = usage_metadata.model_dump()
        if not isinstance(usage_metadata, dict):
            return TokenUsage()
        return TokenUsage(
            prompt_tokens=int(
                usage_metadata.get(
                    "prompt_tokens",
                    usage_metadata.get("prompt_token_count", 0),
                )
                or 0
            ),
            completion_tokens=int(
                usage_metadata.get(
                    "completion_tokens",
                    usage_metadata.get("candidates_token_count", 0),
                )
                or 0
            ),
            total_tokens=int(
                usage_metadata.get(
                    "total_tokens",
                    usage_metadata.get("total_token_count", 0),
                )
                or 0
            ),
        )

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str = "",
        response_mime_type: str | None = None,
        response_json_schema: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        config_obj = self._build_config(
            system_prompt=system_prompt,
            response_mime_type=response_mime_type,
            response_json_schema=response_json_schema,
        )
        async for chunk in self._stream_in_thread(
            lambda: self.client.models.generate_content_stream(
                model=self.model,
                contents=prompt,
                config=config_obj,
            )
        ):
            yield chunk

    def _create_chat(
        self, chat_config: types.GenerateContentConfig | None
    ) -> chats.Chat:
        return self.client.chats.create(model=self.model, config=chat_config)

    @staticmethod
    def _raise_if_prompt_blocked(response: Any) -> None:
        prompt_feedback = getattr(response, "prompt_feedback", None)
        if prompt_feedback is None:
            return
        block_reason = getattr(prompt_feedback, "block_reason", None)
        if not block_reason:
            return
        msg = getattr(prompt_feedback, "block_reason_message", None) or ""
        detail = f"Gemini blocked prompt (safety): {block_reason}"
        if msg:
            detail = f"{detail}: {msg}"
        raise ValueError(detail)

    @staticmethod
    def _serialize_parsed(parsed: Any) -> str:
        if isinstance(parsed, dict):
            return json.dumps(parsed, ensure_ascii=False)
        dump_json = getattr(parsed, "model_dump_json", None)
        if callable(dump_json):
            return dump_json()
        return json.dumps(parsed, default=str, ensure_ascii=False)

    @staticmethod
    def _text_from_candidate_parts(response: Any) -> str:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return ""
        content = getattr(candidates[0], "content", None)
        if content is None:
            return ""
        parts = getattr(content, "parts", None) or []
        chunks: list[str] = []
        for part in parts:
            thought = getattr(part, "thought", None)
            if isinstance(thought, bool) and thought:
                continue
            t = getattr(part, "text", None)
            if isinstance(t, str) and t:
                chunks.append(t)
        return "".join(chunks).strip()

    @staticmethod
    def _empty_response_detail(response: Any) -> str:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return "no candidates"
        c0 = candidates[0]
        parts: list[str] = []
        finish_reason = getattr(c0, "finish_reason", None)
        if finish_reason is not None:
            parts.append(f"finish_reason={finish_reason}")
        finish_message = getattr(c0, "finish_message", None)
        if finish_message:
            parts.append(f"finish_message={finish_message}")
        return ", ".join(parts) if parts else "no extractable text in first candidate"

    @staticmethod
    def _extract_text(response: Any) -> str:
        GeminiClient._raise_if_prompt_blocked(response)
        raw_text = getattr(response, "text", None)
        text = (raw_text if isinstance(raw_text, str) else "") or ""
        text = text.strip()
        if text:
            return text
        parsed = getattr(response, "parsed", None)
        if parsed is not None:
            serialized = GeminiClient._serialize_parsed(parsed).strip()
            if serialized:
                return serialized
        fallback = GeminiClient._text_from_candidate_parts(response)
        if fallback:
            return fallback
        detail = GeminiClient._empty_response_detail(response)
        raise ValueError(f"Empty response from Gemini ({detail})")

    async def _stream_in_thread(self, factory: Callable[[], Any]) -> AsyncIterator[str]:
        items: "queue.Queue[object]" = queue.Queue()
        threading.Thread(
            target=self._stream_worker,
            args=(factory, items),
            daemon=True,
        ).start()

        while True:
            item = await asyncio.to_thread(items.get)
            if item is _STREAM_DONE:
                break
            if isinstance(item, Exception):
                raise item
            yield item

    @staticmethod
    def _stream_worker(
        factory: Callable[[], Any], items: "queue.Queue[object]"
    ) -> None:
        try:
            for chunk in factory():
                text = getattr(chunk, "text", "") or ""
                if text:
                    items.put(text)
        except Exception as exc:
            items.put(exc)
        finally:
            items.put(_STREAM_DONE)

    def _build_config(
        self,
        *,
        system_prompt: str,
        response_mime_type: str | None,
        response_json_schema: dict[str, Any] | None,
        max_output_tokens: int | None = None,
    ) -> types.GenerateContentConfig | None:
        config_data: dict[str, Any] = {}
        if system_prompt:
            config_data["system_instruction"] = system_prompt
        if response_mime_type:
            config_data["response_mime_type"] = response_mime_type
        if response_json_schema is not None:
            config_data["response_json_schema"] = response_json_schema
        if max_output_tokens is not None:
            config_data["max_output_tokens"] = max_output_tokens
        if not config_data:
            return None
        return types.GenerateContentConfig(**config_data)
