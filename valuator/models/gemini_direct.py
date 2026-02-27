import asyncio
import json
import queue
import threading
import uuid
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

from google import genai
from google.genai import chats, types

from ..utils.config import config

_STREAM_DONE = object()

if TYPE_CHECKING:
    from ..core.llm_usage import LLMUsageWriter


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
        usage_writer: "LLMUsageWriter | None" = None,
    ):
        key = api_key or config.google_api_key
        if not key:
            raise ValueError("Missing GOOGLE_API_KEY")
        self.model = model or config.agent_model
        self.client = client or genai.Client(api_key=key)
        self.usage_writer = usage_writer

    def bind_usage_writer(self, usage_writer: "LLMUsageWriter | None") -> None:
        self.usage_writer = usage_writer

    def format_messages(self, system_prompt: str) -> dict[str, str]:
        return {"system_prompt": system_prompt}

    def start_chat_session(
        self,
        messages: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        response_mime_type: str | None = None,
        response_schema: dict[str, Any] | None = None,
        response_json_schema: dict[str, Any] | None = None,
    ) -> GeminiSession:
        system_prompt = ""
        if messages:
            system_prompt = str(messages.get("system_prompt") or "").strip()
        chat_config = self._build_config(
            system_prompt=system_prompt,
            response_mime_type=response_mime_type,
            response_schema=response_schema,
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
        response_schema: dict[str, Any] | None = None,
        response_json_schema: dict[str, Any] | None = None,
        trace_method: str = "gemini.generate",
    ) -> str:
        config_obj = self._build_config(
            system_prompt=system_prompt,
            response_mime_type=response_mime_type,
            response_schema=response_schema,
            response_json_schema=response_json_schema,
        )
        from ..core.llm_usage import start_measurement

        writer = self.usage_writer
        measurement = start_measurement()
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model,
                contents=prompt,
                config=config_obj,
            )
            latency_seconds = measurement.latency_seconds()

            usage_metadata = getattr(response, "usage_metadata", None)
            if hasattr(usage_metadata, "model_dump"):
                usage_metadata = usage_metadata.model_dump()
            if not isinstance(usage_metadata, dict):
                usage_metadata = None

            if writer is not None:
                writer.append_call(
                    method=trace_method,
                    model=self.model,
                    usage=usage_metadata,
                    latency_seconds=latency_seconds,
                    started_at=measurement.started_at,
                )
            return self._extract_text(response)
        except Exception:
            if writer is not None:
                writer.append_call(
                    method=f"{trace_method}.error",
                    model=self.model,
                    usage={
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                    latency_seconds=measurement.latency_seconds(),
                    started_at=measurement.started_at,
                )
            raise

    async def generate_json(
        self,
        *,
        prompt: str,
        system_prompt: str = "",
        response_json_schema: dict[str, Any],
        trace_method: str,
    ) -> dict[str, Any]:
        raw = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            response_mime_type="application/json",
            response_json_schema=response_json_schema,
            trace_method=trace_method,
        )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{trace_method} returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{trace_method} expected JSON object")
        return data

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str = "",
        response_mime_type: str | None = None,
        response_schema: dict[str, Any] | None = None,
        response_json_schema: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        config_obj = self._build_config(
            system_prompt=system_prompt,
            response_mime_type=response_mime_type,
            response_schema=response_schema,
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
    def _extract_text(response: Any) -> str:
        text = (getattr(response, "text", "") or "").strip()
        if not text:
            raise ValueError("Empty response from Gemini")
        return text

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
        response_schema: dict[str, Any] | None,
        response_json_schema: dict[str, Any] | None,
    ) -> types.GenerateContentConfig | None:
        if response_schema and response_json_schema:
            raise ValueError(
                "Only one of response_schema or response_json_schema is allowed"
            )

        raw_config = {
            "system_instruction": system_prompt or None,
            "response_mime_type": response_mime_type,
            "response_schema": response_schema,
            "response_json_schema": response_json_schema,
        }
        config_data = {
            key: value for key, value in raw_config.items() if value is not None
        }

        if not config_data:
            return None
        return types.GenerateContentConfig(**config_data)
