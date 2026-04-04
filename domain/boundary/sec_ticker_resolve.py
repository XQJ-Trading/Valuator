"""Boundary: resolve US listings from SEC company_tickers when the static index misses."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

import requests

from domain.company import ListingSeed, listing_seed_from_sec_record, normalized_name_key

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Valuator/1.0; contact: research@example.com)",
    "Accept-Encoding": "gzip, deflate",
}

_FUZZY_THRESHOLD = 0.7
_TICKER_LIKE = re.compile(r"^[A-Z0-9.\-]{1,8}$")

_records_cache: list[dict[str, Any]] | None = None


def clear_sec_records_cache() -> None:
    """Test hook: drop in-process SEC record cache."""
    global _records_cache
    _records_cache = None


def _parse_sec_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        return [dict(v) for v in payload.values()]
    if isinstance(payload, list):
        return [dict(r) for r in payload]
    return []


def fetch_sec_ticker_records(*, force_remote: bool = False) -> list[dict[str, Any]]:
    """Load SEC company_tickers; cache per process after first remote fetch."""
    global _records_cache
    if not force_remote and _records_cache is not None:
        return _records_cache
    response = requests.get(
        SEC_TICKERS_URL,
        headers=SEC_HEADERS,
        timeout=60,
    )
    response.raise_for_status()
    records = _parse_sec_payload(response.json())
    _records_cache = records
    return records


def _normalize_ticker_token(text: str) -> str:
    return text.strip().upper().replace(".", "-")


def _seed_from_record(record: dict[str, Any]) -> tuple[ListingSeed, ...]:
    seed = listing_seed_from_sec_record(dict(record))
    return (seed,) if seed is not None else ()


def _match_by_ticker(records: list[dict[str, Any]], surface_upper: str) -> tuple[ListingSeed, ...]:
    if not _TICKER_LIKE.match(surface_upper):
        return ()
    want = _normalize_ticker_token(surface_upper)
    for record in records:
        t = str(record.get("ticker") or "").strip().upper().replace(".", "-")
        if t == want:
            return _seed_from_record(record)
    return ()


def _match_by_exact_title_key(
    records: list[dict[str, Any]],
    key: str,
) -> tuple[ListingSeed, ...]:
    if not key:
        return ()
    matches: list[dict[str, Any]] = []
    for record in records:
        title = str(record.get("title") or "")
        if normalized_name_key(title) == key:
            matches.append(record)
    if len(matches) != 1:
        return ()
    return _seed_from_record(matches[0])


def _match_by_fuzzy_title(
    records: list[dict[str, Any]],
    key: str,
) -> tuple[ListingSeed, ...]:
    if not key:
        return ()
    best_score = 0.0
    best_rows: list[dict[str, Any]] = []
    for record in records:
        title = str(record.get("title") or "")
        candidate_key = normalized_name_key(title)
        if not candidate_key:
            continue
        score = SequenceMatcher(None, key, candidate_key).ratio()
        if score < _FUZZY_THRESHOLD:
            continue
        if score > best_score:
            best_score = score
            best_rows = [record]
        elif score == best_score:
            best_rows.append(record)
    if len(best_rows) != 1:
        return ()
    return _seed_from_record(best_rows[0])


def resolve_sec_listing_seeds(surface_form: str) -> tuple[ListingSeed, ...]:
    """Return listing seeds for a surface form using a live SEC ticker table."""
    surface = surface_form.strip()
    if not surface:
        return ()
    records = fetch_sec_ticker_records()
    surface_upper = surface.upper()

    by_ticker = _match_by_ticker(records, surface_upper)
    if by_ticker:
        return by_ticker

    key = normalized_name_key(surface)
    exact = _match_by_exact_title_key(records, key)
    if exact:
        return exact

    fuzzy = _match_by_fuzzy_title(records, key)
    if fuzzy:
        return fuzzy

    return ()


def sec_on_miss(surface_form: str) -> tuple[ListingSeed, ...]:
    """Callable for ``resolve_subjects(..., on_miss=...)``."""
    return resolve_sec_listing_seeds(surface_form)
