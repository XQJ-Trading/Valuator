"""Boundary: resolve US listings from SEC company_tickers when the static index misses."""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import requests

from domain.company import Listing, name_key

from .types import ListingSeed

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Valuator/1.0; contact: research@example.com)",
    "Accept-Encoding": "gzip, deflate",
}
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
SEC_TICKERS_PATH = DATA_DIR / "sec_company_tickers.json"

_FUZZY_THRESHOLD = 0.7
_TICKER_LIKE = re.compile(r"^[A-Z0-9.\-]{1,8}$")
_SEC_PRIMARY_SUFFIXES = frozenset(
    {
        "ADR",
        "AG",
        "COM",
        "COMPANY",
        "CO",
        "CORP",
        "CORPORATION",
        "DE",
        "INC",
        "LIMITED",
        "LTD",
        "MN",
        "NV",
        "PLC",
        "SE",
        "SA",
    }
)
_SEC_SECONDARY_SUFFIXES = frozenset({"GROUP", "HOLDING", "HOLDINGS"})

_records_cache: list[dict[str, Any]] | None = None


def clear_cache() -> None:
    """Test hook: drop in-process SEC record cache."""
    global _records_cache
    _records_cache = None


def _parse_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        return [dict(v) for v in payload.values()]
    if isinstance(payload, list):
        return [dict(r) for r in payload]
    return []


def fetch_records(*, force_remote: bool = False) -> list[dict[str, Any]]:
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
    records = _parse_payload(response.json())
    _records_cache = records
    return records


def _ticker_key(text: str) -> str:
    return text.strip().upper().replace(".", "-")


def load_seeds() -> list[ListingSeed]:
    seeds: list[ListingSeed] = []
    for record in _load_json_records(SEC_TICKERS_PATH):
        seed = seed_from_record(dict(record))
        if seed is not None:
            seeds.append(seed)
    return seeds


def seed_from_record(record: dict[str, Any]) -> ListingSeed | None:
    ticker = str(record.get("ticker") or "").strip().upper()
    title = str(record.get("title") or "").strip()
    if not ticker:
        return None
    company_name = _sec_company_name(title, ticker)
    listing = Listing(
        listing_id=f"USA:{ticker}",
        company_id=_sec_company_id(record, ticker),
        security_code=ticker,
        exchange="USA",
        vendor_symbols={"yahoo": ticker},
    )
    return ListingSeed(
        company_id=listing.company_id,
        company_name=company_name,
        company_aliases=_sec_company_aliases(title, company_name),
        listing=listing,
    )


def _seed_from_record(record: dict[str, Any]) -> tuple[ListingSeed, ...]:
    seed = seed_from_record(dict(record))
    return (seed,) if seed is not None else ()


def _match_by_ticker(
    records: list[dict[str, Any]], surface_upper: str
) -> tuple[ListingSeed, ...]:
    if not _TICKER_LIKE.match(surface_upper):
        return ()
    want = _ticker_key(surface_upper)
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
        if name_key(title) == key:
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
        candidate_key = name_key(title)
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


def resolve_seeds(surface_form: str) -> tuple[ListingSeed, ...]:
    """Return listing seeds for a surface form using a live SEC ticker table."""
    surface = surface_form.strip()
    if not surface:
        return ()
    records = fetch_records()
    surface_upper = surface.upper()

    by_ticker = _match_by_ticker(records, surface_upper)
    if by_ticker:
        return by_ticker

    key = name_key(surface)
    exact = _match_by_exact_title_key(records, key)
    if exact:
        return exact

    fuzzy = _match_by_fuzzy_title(records, key)
    if fuzzy:
        return fuzzy

    return ()


def sec_on_miss(surface_form: str) -> tuple[ListingSeed, ...]:
    """Callable for ``resolve_subjects(..., on_miss=...)``."""
    return resolve_seeds(surface_form)


def _load_json_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [dict(record) for record in payload]


def _sec_company_id(record: dict[str, Any], ticker: str) -> str:
    cik = str(record.get("cik_str") or "").strip()
    if cik:
        return f"SEC:{cik}"
    return f"USA:{ticker}"


def _sec_company_name(title: str, ticker: str) -> str:
    if title and not title.isupper():
        return title
    trimmed_aliases = _sec_trimmed_aliases(title)
    if trimmed_aliases:
        return trimmed_aliases[0]
    if title:
        return _display_sec_name(title)
    return title or ticker


def _sec_company_aliases(title: str, company_name: str) -> tuple[str, ...]:
    aliases: list[str] = []
    if company_name:
        aliases.append(company_name)
    if title:
        aliases.append(_display_sec_name(title))
    aliases.extend(_sec_trimmed_aliases(title))
    return tuple(dict.fromkeys(alias for alias in aliases if alias))


def _sec_trimmed_aliases(title: str) -> tuple[str, ...]:
    aliases: list[str] = []
    words = _trim_trailing_words(_title_words(title), _SEC_PRIMARY_SUFFIXES)
    while words:
        aliases.append(_display_sec_name(" ".join(words)))
        if words[-1] not in _SEC_SECONDARY_SUFFIXES:
            break
        words = words[:-1]
    return tuple(dict.fromkeys(alias for alias in aliases if alias))


def _display_sec_name(alias: str) -> str:
    if not alias.isupper():
        return alias
    words = alias.split()
    return " ".join(word if len(word) <= 4 else word.capitalize() for word in words)


def _title_words(text: str) -> list[str]:
    cleaned = "".join(char if char.isalnum() else " " for char in text.strip().upper())
    return [word for word in cleaned.split() if word]


def _trim_trailing_words(words: list[str], suffixes: frozenset[str]) -> list[str]:
    trimmed = list(words)
    while trimmed and trimmed[-1] in suffixes:
        trimmed.pop()
    return trimmed
