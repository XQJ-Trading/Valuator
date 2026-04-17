from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from time import perf_counter
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def kst_isoformat(value: datetime | str | None = None) -> str:
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return value
        if s.endswith("Z"):
            parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            try:
                parsed = datetime.fromisoformat(s)
            except ValueError:
                return value
        return kst_isoformat(parsed)

    if value is None:
        dt = datetime.now(KST)
    elif value.tzinfo is None:
        dt = value.replace(tzinfo=dt_timezone.utc)
    else:
        dt = value
    return dt.astimezone(KST).isoformat(timespec="milliseconds")


def kst_as_of_format(value: datetime | None = None) -> str:
    if value is None:
        dt = datetime.now(KST)
    elif value.tzinfo is None:
        dt = value.replace(tzinfo=dt_timezone.utc)
    else:
        dt = value
    return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")


def compact_kst_timestamp(value: datetime | str | None = None) -> str:
    text = kst_isoformat(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return "".join(ch for ch in text if ch.isdigit())[:20]
    return parsed.astimezone(KST).strftime("%Y%m%d_%H%M%S_%f")


@dataclass(frozen=True)
class Measurement:
    started_at: str
    started_perf: float

    @classmethod
    def start(cls) -> Measurement:
        return cls(started_at=kst_isoformat(), started_perf=perf_counter())

    def latency_seconds(self) -> float:
        return perf_counter() - self.started_perf
