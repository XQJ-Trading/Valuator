from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter


def utc_isoformat(value: datetime | str | None = None) -> str:
    if isinstance(value, str):
        if value.endswith("Z"):
            return value
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        return utc_isoformat(parsed)

    if value is None:
        value = datetime.now(timezone.utc)
    elif value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def compact_utc_timestamp(value: datetime | str | None = None) -> str:
    text = utc_isoformat(value)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed.strftime("%Y%m%d_%H%M%S_%f")


@dataclass(frozen=True)
class Measurement:
    started_at: str
    started_perf: float

    @classmethod
    def start(cls) -> Measurement:
        return cls(started_at=utc_isoformat(), started_perf=perf_counter())

    def latency_seconds(self) -> float:
        return perf_counter() - self.started_perf
