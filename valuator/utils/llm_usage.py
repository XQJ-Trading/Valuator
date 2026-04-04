from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from valuator.models.naming import canonical_model_name


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_raw(cls, usage: Mapping[str, int] | None) -> TokenUsage:
        if usage is None:
            return cls()
        return cls(
            prompt_tokens=int(
                usage.get("prompt_tokens", usage.get("prompt_token_count", 0)) or 0
            ),
            completion_tokens=int(
                usage.get("completion_tokens", usage.get("candidates_token_count", 0))
                or 0
            ),
            total_tokens=int(
                usage.get("total_tokens", usage.get("total_token_count", 0)) or 0
            ),
        )

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class ModelPrice:
    prompt_usd_per_1m: float
    completion_usd_per_1m: float
    request_usd_per_call: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "prompt_usd_per_1m": self.prompt_usd_per_1m,
            "completion_usd_per_1m": self.completion_usd_per_1m,
            "request_usd_per_call": self.request_usd_per_call,
        }

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens * self.prompt_usd_per_1m / 1_000_000.0
            + completion_tokens * self.completion_usd_per_1m / 1_000_000.0
            + self.request_usd_per_call
        )


MODEL_PRICES: dict[str, ModelPrice] = {
    "gemini-3-flash-preview": ModelPrice(0.50, 3.00),
    "gemini-3-pro-preview": ModelPrice(2.00, 12.00),
    "google/gemini-2.5-flash": ModelPrice(0.50, 3.00),
    "sonar": ModelPrice(1.00, 1.00, 0.005),
}


def register_model_price(model: str, price: ModelPrice) -> None:
    MODEL_PRICES[canonical_model_name(model)] = price


def get_model_price(model: str) -> ModelPrice | None:
    return MODEL_PRICES.get(canonical_model_name(model))


def build_pricing_summary() -> dict[str, dict[str, float]]:
    return {
        model: price.to_dict()
        for model, price in sorted(MODEL_PRICES.items())
    }


@dataclass
class LLMUsage:
    method: str
    model: str
    usage: TokenUsage
    latency_ms: float
    started_at: str

    @classmethod
    def from_call(
        cls,
        *,
        method: str,
        model: str,
        usage: TokenUsage,
        latency_ms: float,
        started_at: str,
    ) -> "LLMUsage":
        return cls(
            method=method,
            model=model,
            usage=usage,
            latency_ms=latency_ms,
            started_at=started_at,
        )

    def to_dict(self) -> dict[str, object]:
        price = get_model_price(self.model)
        return {
            "method": self.method,
            "model": self.model,
            "cost_usd": self.cost_usd(),
            "usage": self.usage.to_dict(),
            "pricing": price.to_dict() if price is not None else None,
            "latency_ms": self.latency_ms,
            "started_at": self.started_at,
        }

    def cost_usd(self) -> float:
        price = get_model_price(self.model)
        if price is None:
            return 0.0
        return price.cost(
            prompt_tokens=self.usage.prompt_tokens,
            completion_tokens=self.usage.completion_tokens,
        )


class LLMUsageWriter:
    def __init__(self, path: Path, *, session_started_at: str):
        self.path = path
        self.session_started_at = session_started_at
        self._lock = threading.RLock()
        self._usage_total = TokenUsage()
        self._latency_ms_total = 0.0
        self._cost_usd_total = 0.0
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
    ) -> None:
        row = LLMUsage.from_call(
            method=method,
            model=model,
            usage=usage,
            latency_ms=latency_seconds * 1000.0,
            started_at=started_at,
        )
        with self._lock:
            self._append_row(row)
            self._usage_total = self._usage_total + row.usage
            self._latency_ms_total += row.latency_ms
            self._cost_usd_total += row.cost_usd()

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
            self._append_row(row, cost_usd=self._cost_usd_total)
            self._total_written = True

    def _append_row(self, row: LLMUsage, *, cost_usd: float | None = None) -> None:
        payload = row.to_dict()
        if cost_usd is not None:
            payload["cost_usd"] = cost_usd
        with self.path.open("a", encoding="utf-8") as file_obj:
            file_obj.write(json.dumps(payload, ensure_ascii=False) + "\n")
            file_obj.flush()
