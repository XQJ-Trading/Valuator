from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from valuator.models.naming import canonical_model_name

from .config import config


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    cached_prompt_tokens: int = 0
    completion_tokens: int = 0
    thought_tokens: int = 0
    total_tokens: int = 0
    cache_write_tokens: int = 0

    @classmethod
    def from_raw(cls, usage: Mapping[str, int] | None) -> TokenUsage:
        if usage is None:
            return cls()
        prompt_tokens = int(
            usage.get("prompt_tokens", usage.get("prompt_token_count", 0)) or 0
        )
        cached_prompt_tokens = int(
            usage.get(
                "cached_prompt_tokens",
                usage.get("cached_content_token_count", 0),
            )
            or 0
        )
        if cached_prompt_tokens > prompt_tokens:
            raise ValueError(
                "cached_prompt_tokens cannot exceed prompt_tokens "
                f"({cached_prompt_tokens} > {prompt_tokens})"
            )
        return cls(
            prompt_tokens=prompt_tokens,
            cached_prompt_tokens=cached_prompt_tokens,
            completion_tokens=int(
                usage.get("completion_tokens", usage.get("candidates_token_count", 0))
                or 0
            ),
            thought_tokens=int(
                usage.get("thought_tokens", usage.get("thoughts_token_count", 0)) or 0
            ),
            total_tokens=int(
                usage.get("total_tokens", usage.get("total_token_count", 0)) or 0
            ),
            cache_write_tokens=int(
                usage.get("cache_write_tokens", usage.get("cache_creation_input_tokens", 0))
                or 0
            ),
        )

    @property
    def uncached_prompt_tokens(self) -> int:
        return self.prompt_tokens - self.cached_prompt_tokens

    @property
    def output_tokens(self) -> int:
        return self.completion_tokens + self.thought_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            cached_prompt_tokens=self.cached_prompt_tokens + other.cached_prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            thought_tokens=self.thought_tokens + other.thought_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "uncached_prompt_tokens": self.uncached_prompt_tokens,
            "cached_prompt_tokens": self.cached_prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "thought_tokens": self.thought_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cache_write_tokens": self.cache_write_tokens,
        }


@dataclass(frozen=True)
class ModelPrice:
    prompt_usd_per_1m: float
    completion_usd_per_1m: float
    cache_write_usd_per_1m: float = 0.0
    cache_storage_usd_per_1m_hour: float = 0.0
    request_usd_per_call: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "prompt_usd_per_1m": self.prompt_usd_per_1m,
            "completion_usd_per_1m": self.completion_usd_per_1m,
            "cache_write_usd_per_1m": self.cache_write_usd_per_1m,
            "cache_storage_usd_per_1m_hour": self.cache_storage_usd_per_1m_hour,
            "request_usd_per_call": self.request_usd_per_call,
        }


MODEL_PRICES: dict[str, ModelPrice] = {
    "gemini-3-flash-preview": ModelPrice(0.50, 3.00, 0.05, 1.00),
    "gemini-3.5-flash": ModelPrice(1.50, 9.00, 0.15, 1.00),
    "gemini-3-pro-preview": ModelPrice(2.00, 12.00, 0.20, 4.50),
    "gemini-3.1-pro-preview": ModelPrice(2.00, 12.00, 0.20, 4.50),
    "gemini-3.1-flash-lite-preview": ModelPrice(0.25, 1.50, 0.025, 1.00),
    "gemini-2.5-flash": ModelPrice(0.30, 2.50, 0.03, 1.00),
    "gemini-2.5-pro": ModelPrice(1.25, 10.00, 0.125, 4.50),
    "google/gemini-2.5-flash": ModelPrice(0.50, 3.00),
    "sonar": ModelPrice(1.00, 1.00, request_usd_per_call=0.005),
}


def register_model_price(model: str, price: ModelPrice) -> None:
    MODEL_PRICES[canonical_model_name(model)] = price


def get_model_price(model: str) -> ModelPrice | None:
    return MODEL_PRICES.get(canonical_model_name(model))


@dataclass
class LLMUsage:
    method: str
    model: str
    usage: TokenUsage
    latency_ms: float
    started_at: str
    cache_source: str | None = None
    cache_storage_hours: float = 0.0

    @classmethod
    def from_call(
        cls,
        *,
        method: str,
        model: str,
        usage: TokenUsage,
        latency_ms: float,
        started_at: str,
        cache_source: str | None = None,
        cache_storage_hours: float = 0.0,
    ) -> "LLMUsage":
        return cls(
            method=method,
            model=model,
            usage=usage,
            latency_ms=latency_ms,
            started_at=started_at,
            cache_source=cache_source,
            cache_storage_hours=cache_storage_hours,
        )

    def to_dict(
        self,
        *,
        cost_usd: float | None = None,
        cost_breakdown: Mapping[str, float] | None = None,
    ) -> dict[str, object]:
        price = get_model_price(self.model)
        details = dict(cost_breakdown or self.cost_breakdown())
        return {
            "method": self.method,
            "model": self.model,
            "cache_source": self.cache_source,
            "cache_storage_hours": round(self.cache_storage_hours, 6),
            "cost_usd": self.cost_usd() if cost_usd is None else cost_usd,
            "cost_breakdown": details,
            "usage": self.usage.to_dict(),
            "pricing": price.to_dict() if price is not None else None,
            "latency_ms": self.latency_ms,
            "started_at": self.started_at,
        }

    def cost_breakdown(self) -> dict[str, float]:
        price = get_model_price(self.model)
        if price is None:
            return {
                "billable_prompt_tokens": 0.0,
                "billable_output_tokens": 0.0,
                "prompt_cost_usd": 0.0,
                "output_cost_usd": 0.0,
                "cache_write_cost_usd": 0.0,
                "cache_storage_cost_usd": 0.0,
                "request_cost_usd": 0.0,
            }

        if self.cache_source == "explicit":
            billable_prompt_tokens = self.usage.uncached_prompt_tokens
        elif (
            self.cache_source == "implicit"
            and config.gemini_implicit_cache_cost_mode == "bill_uncached_only"
        ):
            billable_prompt_tokens = self.usage.uncached_prompt_tokens
        else:
            billable_prompt_tokens = self.usage.prompt_tokens

        billable_output_tokens = self.usage.output_tokens
        prompt_cost_usd = (
            billable_prompt_tokens * price.prompt_usd_per_1m / 1_000_000.0
        )
        output_cost_usd = (
            billable_output_tokens * price.completion_usd_per_1m / 1_000_000.0
        )
        cache_write_cost_usd = (
            self.usage.cache_write_tokens * price.cache_write_usd_per_1m / 1_000_000.0
        )
        cache_storage_cost_usd = (
            self.usage.cache_write_tokens
            * price.cache_storage_usd_per_1m_hour
            * self.cache_storage_hours
            / 1_000_000.0
        )
        return {
            "billable_prompt_tokens": float(billable_prompt_tokens),
            "billable_output_tokens": float(billable_output_tokens),
            "prompt_cost_usd": round(prompt_cost_usd, 9),
            "output_cost_usd": round(output_cost_usd, 9),
            "cache_write_cost_usd": round(cache_write_cost_usd, 9),
            "cache_storage_cost_usd": round(cache_storage_cost_usd, 9),
            "request_cost_usd": round(price.request_usd_per_call, 9),
        }

    def cost_usd(self) -> float:
        details = self.cost_breakdown()
        return (
            details["prompt_cost_usd"]
            + details["output_cost_usd"]
            + details["cache_write_cost_usd"]
            + details["cache_storage_cost_usd"]
            + details["request_cost_usd"]
        )


class LLMUsageWriter:
    def __init__(self, path: Path, *, session_started_at: str):
        self.path = path
        self.session_started_at = session_started_at
        self._lock = threading.RLock()
        self._usage_total = TokenUsage()
        self._latency_ms_total = 0.0
        self._cost_usd_total = 0.0
        self._cost_breakdown_total = {
            "billable_prompt_tokens": 0.0,
            "billable_output_tokens": 0.0,
            "prompt_cost_usd": 0.0,
            "output_cost_usd": 0.0,
            "cache_write_cost_usd": 0.0,
            "cache_storage_cost_usd": 0.0,
            "request_cost_usd": 0.0,
        }
        self._total_written = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def append_call(
        self,
        *,
        method: str,
        model: str,
        usage: TokenUsage,
        latency_seconds: float,
        started_at: str,
        cache_source: str | None = None,
        cache_storage_hours: float = 0.0,
    ) -> None:
        row = LLMUsage.from_call(
            method=method,
            model=model,
            usage=usage,
            latency_ms=latency_seconds * 1000.0,
            started_at=started_at,
            cache_source=cache_source,
            cache_storage_hours=cache_storage_hours,
        )
        with self._lock:
            cost_breakdown = row.cost_breakdown()
            self._append_row(row, cost_breakdown=cost_breakdown)
            self._usage_total = self._usage_total + row.usage
            self._latency_ms_total += row.latency_ms
            self._cost_usd_total += row.cost_usd()
            for key, value in cost_breakdown.items():
                self._cost_breakdown_total[key] += value

    def append_total(self) -> None:
        with self._lock:
            if self._total_written:
                return
            row = LLMUsage(
                method="TOTAL",
                model="ALL",
                usage=self._usage_total,
                latency_ms=self._latency_ms_total,
                started_at=self.session_started_at,
            )
            self._append_row(
                row,
                cost_usd=self._cost_usd_total,
                cost_breakdown=self._cost_breakdown_total,
            )
            self._total_written = True

    def _append_row(
        self,
        row: LLMUsage,
        *,
        cost_usd: float | None = None,
        cost_breakdown: Mapping[str, float] | None = None,
    ) -> None:
        payload = row.to_dict(cost_usd=cost_usd, cost_breakdown=cost_breakdown)
        with self.path.open("a", encoding="utf-8") as file_obj:
            file_obj.write(json.dumps(payload, ensure_ascii=False) + "\n")
            file_obj.flush()
