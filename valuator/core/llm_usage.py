from __future__ import annotations

import json
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import ClassVar, Mapping


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_raw(cls, usage: Mapping[str, int] | None) -> "TokenUsage":
        if usage is None:
            return cls()
        return cls(
            prompt_tokens=usage.get(
                "prompt_tokens",
                usage.get("prompt_token_count", 0),
            ),
            completion_tokens=usage.get(
                "completion_tokens",
                usage.get("candidates_token_count", 0),
            ),
            total_tokens=usage.get(
                "total_tokens",
                usage.get("total_token_count", 0),
            ),
        )

    def add(self, other: "TokenUsage") -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class Measurement:
    started_at: str
    started_perf: float

    def latency_seconds(self) -> float:
        return perf_counter() - self.started_perf


def start_measurement() -> Measurement:
    return Measurement(
        started_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        started_perf=perf_counter(),
    )


@dataclass
class LLMUsage:
    method: str
    model: str
    usage: TokenUsage
    latency_ms: float
    started_at: str
    # PRICING 구조:
    #   key: 모델 이름 (예: "gemini-3-flash-preview")
    #   value: (prompt_per_1m, completion_per_1m, request_per_call)
    #       - prompt_per_1m: 프롬프트 토큰 100만 개당 USD 가격
    #       - completion_per_1m: 생성(완성) 토큰 100만 개당 USD 가격
    #       - request_per_call: 요청 1회당 고정 비용(USD, per-call surcharge)
    PRICING: ClassVar[dict[str, tuple[float, float, float]]] = {
        "gemini-3-flash-preview": (0.50, 3.00, 0.0),
        "gemini-3-pro-preview": (2.00, 12.00, 0.0),
        "sonar": (1.00, 1.00, 0.005),
    }

    @classmethod
    def from_call(
        cls,
        *,
        method: str,
        model: str,
        usage: TokenUsage | Mapping[str, int] | None,
        latency_ms: float,
        started_at: str,
    ) -> "LLMUsage":
        return cls(
            method=method,
            model=model,
            usage=usage if isinstance(usage, TokenUsage) else TokenUsage.from_raw(usage),
            latency_ms=latency_ms,
            started_at=started_at,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method,
            "model": self.model,
            "cost_usd": self.cost_usd(),
            "usage": self.usage.to_dict(),
            "latency_ms": self.latency_ms,
            "started_at": self.started_at,
        }

    def cost_usd(self) -> float:
        price = self.PRICING.get(self.model)
        if price is None:
            return 0.0
        prompt_per_1m, completion_per_1m, request_per_call = price
        prompt_cost = self.usage.prompt_tokens * prompt_per_1m / 1_000_000.0
        completion_cost = self.usage.completion_tokens * completion_per_1m / 1_000_000.0
        return prompt_cost + completion_cost + request_per_call


class LLMUsageWriter:
    def __init__(self, path: Path, *, session_started_at: str):
        self.path = path
        self.session_started_at = session_started_at
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
        usage: TokenUsage | Mapping[str, int] | None,
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
        self._append_row(row)
        self._usage_total.add(row.usage)
        self._latency_ms_total += row.latency_ms
        self._cost_usd_total += row.cost_usd()

    def append_total(self) -> None:
        if self._total_written:
            return
        row = LLMUsage(
            method="TOTAL",
            model="ALL",
            usage=TokenUsage(
                prompt_tokens=self._usage_total.prompt_tokens,
                completion_tokens=self._usage_total.completion_tokens,
                total_tokens=self._usage_total.total_tokens,
            ),
            latency_ms=self._latency_ms_total,
            started_at=self.session_started_at,
        )
        self._append_row(row, cost_usd=self._cost_usd_total)
        self._total_written = True

    def _append_row(self, row: LLMUsage, *, cost_usd: float | None = None) -> None:
        payload = row.to_dict()
        if cost_usd is not None:
            payload["cost_usd"] = cost_usd
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
