"""Boundary: resolve KRX listings from OpenDart corpCode when the static index misses."""

from __future__ import annotations

import io
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import requests

from domain.company import Listing, name_key
from valuator.utils.config import get_opendart_api_key

from .types import ListingSeed

OPENDART_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
OPENDART_COMPANY_URL = "https://opendart.fss.or.kr/api/company.json"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
KRX_SECURITIES_PATH = DATA_DIR / "krx_securities.json"

_FUZZY_THRESHOLD = 0.7
_STOCK_CODE_RE = re.compile(r"^\d{6}$")

_CORP_CLS_EXCHANGE = {"Y": "KOSPI", "K": "KOSDAQ", "N": "KONEX"}
_CORP_CLS_YAHOO_SUFFIX = {"Y": ".KS", "K": ".KQ", "N": ".KN"}

_corp_records_cache: list[dict[str, str]] | None = None
_corp_cls_cache: dict[str, str] = {}


def clear_cache() -> None:
    """Test hook: drop in-process KRX record cache."""
    global _corp_records_cache
    _corp_records_cache = None
    _corp_cls_cache.clear()


def load_seeds() -> list[ListingSeed]:
    records = _load_json_records(KRX_SECURITIES_PATH)
    seeds: list[ListingSeed] = []
    for record in records:
        listing_record = _listing_record_from_json(dict(record))
        listing = Listing(
            listing_id=str(listing_record["listing_id"]),
            company_id=str(listing_record["listing_id"]),
            security_code=str(listing_record["security_code"]),
            exchange=str(listing_record["exchange"]),
            vendor_symbols=dict(listing_record["vendor_symbols"]),
            corp_code=str(listing_record["corp_code"]),
        )
        seeds.append(
            ListingSeed(
                company_id=listing.company_id,
                company_name=str(listing_record["issuer_name"]),
                company_aliases=tuple(listing_record["aliases"]),
                listing=listing,
            )
        )
    return seeds


def fetch_records(*, force_remote: bool = False) -> list[dict[str, str]]:
    """Load OpenDart corp codes; cache per process after first remote fetch."""
    global _corp_records_cache
    if not force_remote and _corp_records_cache is not None:
        return _corp_records_cache
    api_key = get_opendart_api_key()
    if not api_key:
        return []
    response = requests.get(
        OPENDART_CORP_CODE_URL,
        params={"crtfc_key": api_key},
        timeout=60,
    )
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        xml_name = next((n for n in zf.namelist() if n.lower().endswith(".xml")), None)
        if xml_name is None:
            return []
        xml_bytes = zf.read(xml_name)
    root = ET.fromstring(xml_bytes)
    records = [
        {child.tag: (child.text or "").strip() for child in item}
        for item in root.findall("list")
    ]
    listed = [r for r in records if r.get("stock_code")]
    _corp_records_cache = listed
    return listed


def _fetch_corp_cls(corp_code: str, api_key: str) -> str:
    if corp_code in _corp_cls_cache:
        return _corp_cls_cache[corp_code]
    response = requests.get(
        OPENDART_COMPANY_URL,
        params={"crtfc_key": api_key, "corp_code": corp_code},
        timeout=10,
    )
    response.raise_for_status()
    corp_cls = str(response.json().get("corp_cls") or "")
    _corp_cls_cache[corp_code] = corp_cls
    return corp_cls


def _listing_seed_from_record(record: dict[str, str], corp_cls: str) -> ListingSeed:
    listing_record = build_record(record, corp_cls=corp_cls)
    stock_code = str(listing_record["security_code"])
    corp_name = str(listing_record["issuer_name"])
    listing = Listing(
        listing_id=str(listing_record["listing_id"]),
        company_id=str(listing_record["listing_id"]),
        security_code=stock_code,
        exchange=str(listing_record["exchange"]),
        vendor_symbols=dict(listing_record["vendor_symbols"]),
        corp_code=str(listing_record["corp_code"]),
    )
    return ListingSeed(
        company_id=listing.listing_id,
        company_name=corp_name,
        company_aliases=tuple(listing_record["aliases"]),
        listing=listing,
    )


def _seed_from_record(record: dict[str, str], api_key: str) -> tuple[ListingSeed, ...]:
    corp_code = record.get("corp_code", "")
    corp_cls = _fetch_corp_cls(corp_code, api_key) if corp_code else ""
    return (_listing_seed_from_record(record, corp_cls),)


def _match_by_stock_code(
    records: list[dict[str, str]], surface_upper: str
) -> dict[str, Any] | None:
    if not _STOCK_CODE_RE.match(surface_upper):
        return None
    for record in records:
        if record.get("stock_code", "").upper() == surface_upper:
            return record
    return None


def _match_by_exact_name(
    records: list[dict[str, str]], key: str
) -> dict[str, Any] | None:
    if not key:
        return None
    matches = [r for r in records if name_key(r.get("corp_name", "")) == key]
    return matches[0] if len(matches) == 1 else None


def _match_by_fuzzy_name(
    records: list[dict[str, str]], key: str
) -> dict[str, Any] | None:
    if not key:
        return None
    best_score = 0.0
    best_rows: list[dict[str, Any]] = []
    for record in records:
        candidate_key = name_key(record.get("corp_name", ""))
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
    return best_rows[0] if len(best_rows) == 1 else None


def resolve_seeds(surface_form: str) -> tuple[ListingSeed, ...]:
    """Return listing seeds for a surface form using a live OpenDart corp code table."""
    surface = surface_form.strip()
    if not surface:
        return ()
    api_key = get_opendart_api_key()
    if not api_key:
        return ()
    records = fetch_records()
    surface_upper = surface.upper()

    record = _match_by_stock_code(records, surface_upper)
    if record is not None:
        return _seed_from_record(record, api_key)

    key = name_key(surface)
    record = _match_by_exact_name(records, key)
    if record is not None:
        return _seed_from_record(record, api_key)

    record = _match_by_fuzzy_name(records, key)
    if record is not None:
        return _seed_from_record(record, api_key)

    return ()


def krx_on_miss(surface_form: str) -> tuple[ListingSeed, ...]:
    """Callable for ``resolve_subjects(..., on_miss=...)``."""
    return resolve_seeds(surface_form)


def resolve_corp_code(surface_form: str) -> str:
    surface = surface_form.strip()
    if not surface:
        raise ValueError("'corp' is required")

    local_seed = _match_local_listing_seed(load_seeds(), surface)
    if local_seed is not None:
        corp_code = local_seed.listing.corp_code.strip()
        if corp_code:
            return corp_code

    seeds = resolve_seeds(surface)
    if len(seeds) == 1:
        corp_code = seeds[0].listing.corp_code.strip()
        if corp_code:
            return corp_code
    raise ValueError(f"unknown KRX corp_code: {surface}")


def build_record(
    record: dict[str, str],
    *,
    corp_cls: str,
) -> dict[str, Any]:
    stock_code = str(record.get("stock_code") or "").strip().upper()
    corp_name = str(record.get("corp_name") or "").strip()
    corp_code = str(record.get("corp_code") or "").strip()
    exchange = _CORP_CLS_EXCHANGE.get(corp_cls, "KRX")
    yahoo_suffix = _CORP_CLS_YAHOO_SUFFIX.get(corp_cls, ".KS")
    aliases = [corp_name]
    if corp_name and not corp_name.endswith("(주)"):
        aliases.append(f"{corp_name}(주)")
    return {
        "issuer_name": corp_name,
        "security_code": stock_code,
        "exchange": exchange,
        "listing_id": f"KRX:{stock_code}",
        "vendor_symbols": {"yahoo": f"{stock_code}{yahoo_suffix}"},
        "aliases": list(dict.fromkeys(alias for alias in aliases if alias)),
        "corp_code": corp_code,
    }


def build_record_from_api(
    record: dict[str, str],
    *,
    api_key: str,
) -> dict[str, Any]:
    corp_code = str(record.get("corp_code") or "").strip()
    corp_cls = _fetch_corp_cls(corp_code, api_key) if corp_code else ""
    return build_record(record, corp_cls=corp_cls)


def _match_local_listing_seed(
    seeds: list[ListingSeed],
    surface_form: str,
) -> ListingSeed | None:
    surface_upper = surface_form.strip().upper()
    if not surface_upper:
        return None

    for seed in seeds:
        if seed.listing.security_code == surface_upper:
            return seed

    key = name_key(surface_form)
    exact_matches = [
        seed
        for seed in seeds
        if any(name_key(alias) == key for alias in _seed_aliases(seed))
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        return None

    best_score = 0.0
    best_seed: ListingSeed | None = None
    duplicate_best = False
    for seed in seeds:
        alias_scores = [
            SequenceMatcher(None, key, name_key(alias)).ratio()
            for alias in _seed_aliases(seed)
            if name_key(alias)
        ]
        if not alias_scores:
            continue
        score = max(alias_scores)
        if score < _FUZZY_THRESHOLD:
            continue
        if score > best_score:
            best_score = score
            best_seed = seed
            duplicate_best = False
        elif score == best_score:
            duplicate_best = True
    if duplicate_best:
        return None
    return best_seed


def _seed_aliases(seed: ListingSeed) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            alias
            for alias in (seed.company_name, *seed.company_aliases)
            if alias.strip()
        )
    )


def _listing_record_from_json(record: dict[str, Any]) -> dict[str, Any]:
    company_name = str(record.get("issuer_name") or "").strip()
    aliases = list(
        dict.fromkeys(
            alias
            for alias in (
                company_name,
                *(str(item).strip() for item in record.get("aliases") or []),
            )
            if alias
        )
    )
    vendor_symbols = {
        str(vendor): str(symbol).strip().upper()
        for vendor, symbol in dict(record.get("vendor_symbols") or {}).items()
        if str(symbol).strip()
    }
    return {
        "issuer_name": company_name,
        "security_code": str(record.get("security_code") or "").strip().upper(),
        "exchange": str(record.get("exchange") or "").strip().upper(),
        "listing_id": str(record.get("listing_id") or "").strip().upper(),
        "vendor_symbols": vendor_symbols,
        "aliases": aliases,
        "corp_code": str(record.get("corp_code") or "").strip(),
    }


def _load_json_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [dict(record) for record in payload]
