from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiohttp

from ..utils.config import config
from ..utils.llm_usage import (
    ModelPrice,
    TokenUsage,
    get_model_price,
    register_model_price,
)
from ..utils.time_utils import Measurement

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .protocol import UsageWriter


_prices_fetched = False

_OPENROUTER_PRICE_CACHE = "openrouter_model_prices.json"


def _openrouter_price_cache_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent / "data" / _OPENROUTER_PRICE_CACHE
    )


def _write_openrouter_price_cache(body: dict[str, Any]) -> None:
    out: dict[str, dict[str, float]] = {}
    for item in body.get("data", []):
        model_id = item.get("id")
        price = _parse_model_price(item)
        if model_id and price:
            out[model_id] = {
                "prompt_usd_per_1m": price.prompt_usd_per_1m,
                "completion_usd_per_1m": price.completion_usd_per_1m,
            }
    if not out:
        return
    path = _openrouter_price_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_openrouter_price_cache() -> int:
    path = _openrouter_price_cache_path()
    if not path.is_file():
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("OpenRouter price cache unreadable: %s", exc)
        return 0
    if not isinstance(raw, dict):
        return 0
    count = 0
    for model_id, entry in raw.items():
        if not isinstance(model_id, str) or not isinstance(entry, dict):
            continue
        try:
            p = float(entry.get("prompt_usd_per_1m", 0))
            c = float(entry.get("completion_usd_per_1m", 0))
        except (TypeError, ValueError):
            continue
        if p == 0.0 and c == 0.0:
            continue
        register_model_price(model_id, ModelPrice(p, c))
        count += 1
    return count


def _register_prices_from_models_body(body: dict[str, Any]) -> int:
    count = 0
    for item in body.get("data", []):
        model_id = item.get("id")
        price = _parse_model_price(item)
        if model_id and price:
            register_model_price(model_id, price)
            count += 1
    return count


class OpenRouterClient:
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any | None = None,
        usage_writer: "UsageWriter | None" = None,
        retry_count: int | None = None,
        retry_base_delay: float | None = None,
    ):
        key = api_key or config.openrouter_api_key
        if not key:
            raise ValueError("Missing OPENROUTER_API_KEY")
        self._api_key = key
        self._base_url = base_url or config.openrouter_base_url
        if client is None:
            try:
                from openai import AsyncOpenAI
            except (
                ImportError
            ) as exc:  # pragma: no cover - environment-dependent import
                raise RuntimeError(
                    "openai is not installed. Install dependencies from requirements.txt."
                ) from exc
            client = AsyncOpenAI(
                api_key=key,
                base_url=self._base_url,
            )
        self.model = model or config.agent_model
        self.usage_writer = usage_writer
        self._retry_count = (
            retry_count if retry_count is not None else config.agent_llm_retry_count
        )
        self._retry_base_delay = (
            retry_base_delay
            if retry_base_delay is not None
            else config.agent_llm_retry_base_delay
        )
        self._client = client

    def bind_usage_writer(self, usage_writer: "UsageWriter | None") -> None:
        self.usage_writer = usage_writer

    async def get_or_create_explicit_cache(
        self,
        *,
        cache_key: str,
        contents: Any | None = None,
        system_prompt: str = "",
        ttl_seconds: int | None = None,
        display_name: str | None = None,
        trace_method: str = "llm.cache.create",
    ) -> str | None:
        del (
            cache_key,
            contents,
            system_prompt,
            ttl_seconds,
            display_name,
            trace_method,
        )
        return None

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        response_mime_type: str | None = None,
        response_json_schema: dict[str, Any] | None = None,
        trace_method: str = "openrouter.generate",
        max_output_tokens: int | None = None,
        cached_content: str | None = None,
    ) -> str:
        del cached_content
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if max_output_tokens is not None:
            kwargs["max_tokens"] = max_output_tokens
        if response_json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": response_json_schema,
                },
            }
        elif response_mime_type == "application/json":
            kwargs["response_format"] = {"type": "json_object"}

        writer = self.usage_writer
        await self._ensure_prices_loaded()

        for attempt in range(self._retry_count + 1):
            measurement = Measurement.start()
            try:
                response = await self._client.chat.completions.create(**kwargs)
                latency_seconds = measurement.latency_seconds()
                text = self._response_text(response)
                usage = self._token_usage(getattr(response, "usage", None))
                resolved_model = self._resolved_response_model(response)
                await self._ensure_model_price(resolved_model)

                if writer is not None:
                    self._record_success_call(
                        writer=writer,
                        method=trace_method,
                        model=resolved_model,
                        usage=usage,
                        latency_seconds=latency_seconds,
                        started_at=measurement.started_at,
                        prompt=prompt,
                        system_prompt=system_prompt,
                        response_mime_type=response_mime_type,
                        response_json_schema=response_json_schema,
                        response_text=text,
                    )
                return text
            except Exception as exc:
                if writer is not None:
                    retry_suffix = (
                        f".retry{attempt}" if attempt < self._retry_count else ""
                    )
                    error_method = f"{trace_method}.error{retry_suffix}"
                    self._record_error_call(
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
        cached_content: str | None = None,
    ) -> dict[str, Any]:
        raw = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            response_mime_type="application/json",
            response_json_schema=response_json_schema,
            trace_method=trace_method,
            max_output_tokens=max_output_tokens,
            cached_content=cached_content,
        )
        if max_response_chars is not None and len(raw) > max_response_chars:
            raise ValueError(
                f"{trace_method} returned oversized JSON ({len(raw)} chars > {max_response_chars})"
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
        response_text: str | None,
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
    ) -> None:
        self._record_call(
            writer=writer,
            method=method,
            model=model,
            usage=TokenUsage(),
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
    def _token_usage(raw_usage: Any) -> TokenUsage:
        if raw_usage is None:
            return TokenUsage()
        return TokenUsage(
            prompt_tokens=int(getattr(raw_usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(raw_usage, "completion_tokens", 0) or 0),
            total_tokens=int(getattr(raw_usage, "total_tokens", 0) or 0),
        )

    def _resolved_response_model(self, response: Any) -> str:
        response_model = getattr(response, "model", None)
        if not isinstance(response_model, str):
            return self.model
        model_name = response_model.strip()
        if not model_name:
            return self.model
        return model_name

    @staticmethod
    def _response_text(response: Any) -> str:
        message_content = response.choices[0].message.content
        if isinstance(message_content, list):
            text = "".join(
                str(part.get("text") or "")
                for part in message_content
                if isinstance(part, dict)
            ).strip()
        else:
            text = str(message_content or "").strip()
        if not text:
            raise ValueError("Empty response from OpenRouter")
        return text

    # --- pricing fetch ---

    async def _ensure_prices_loaded(self) -> None:
        global _prices_fetched
        if _prices_fetched:
            return
        _prices_fetched = True
        try:
            await self._fetch_all_model_prices()
        except Exception as exc:
            logger.warning("Failed to fetch OpenRouter model prices: %s", exc)

    async def _fetch_all_model_prices(self) -> None:
        cache_path = _openrouter_price_cache_path()
        from_cache = _load_openrouter_price_cache()
        if from_cache:
            logger.info(
                "Loaded %d model prices from cache %s",
                from_cache,
                cache_path,
            )

        try:
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    f"{self._base_url}/models",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                ) as resp:
                    if resp.status != 200:
                        logger.warning("OpenRouter /models returned %d", resp.status)
                        return
                    body = await resp.json()
        except Exception as exc:
            logger.warning("OpenRouter /models request failed: %s", exc)
            return

        count = _register_prices_from_models_body(body)
        if count:
            _write_openrouter_price_cache(body)
        logger.info("Refreshed %d model prices from OpenRouter API", count)

    async def _ensure_model_price(self, model_id: str) -> None:
        if get_model_price(model_id) is not None:
            return
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url}/models/{model_id}",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                ) as resp:
                    if resp.status != 200:
                        return
                    body = await resp.json()
            price = _parse_model_price(body)
            if price:
                register_model_price(model_id, price)
                logger.info("Fetched price for model %s", model_id)
        except Exception as exc:
            logger.debug("Failed to fetch price for %s: %s", model_id, exc)


def _parse_model_price(data: dict[str, Any]) -> ModelPrice | None:
    pricing = data.get("pricing")
    if not pricing:
        return None
    try:
        prompt_per_token = float(pricing.get("prompt", "0"))
        completion_per_token = float(pricing.get("completion", "0"))
    except (ValueError, TypeError):
        return None
    if prompt_per_token == 0.0 and completion_per_token == 0.0:
        return None
    return ModelPrice(
        prompt_usd_per_1m=prompt_per_token * 1_000_000,
        completion_usd_per_1m=completion_per_token * 1_000_000,
    )
