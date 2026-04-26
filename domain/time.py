"""Domain time types.

`YearRange` is the canonical fiscal-year range. Created at the temporal
boundary (`summarize_temporal_contract`) and consumed by financial tools
without further parsing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True, slots=True)
class YearRange:
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(
                f"YearRange start ({self.start}) must not exceed end ({self.end})"
            )

    def years(self) -> Iterator[int]:
        return iter(range(self.start, self.end + 1))

    def is_single(self) -> bool:
        return self.start == self.end

    def __iter__(self) -> Iterator[int]:
        return self.years()

    def __contains__(self, year: int) -> bool:
        return self.start <= year <= self.end

    def __str__(self) -> str:
        return str(self.start) if self.is_single() else f"{self.start}-{self.end}"


def year_range_from_iso_dates(start_iso: str, end_iso: str) -> YearRange | None:
    """Build a YearRange from ISO date strings (YYYY-MM-DD).

    Returns None if either side is empty. Raises ValueError on malformed input.
    """
    if not start_iso or not end_iso:
        return None
    return YearRange(start=int(start_iso[:4]), end=int(end_iso[:4]))
