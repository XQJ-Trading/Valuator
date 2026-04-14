"""Boundary: resolve KRX listings from OpenDart corpCode when the static index misses."""

from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from typing import Any

import requests

from valuator.utils.hangul_fuzzy_key import jamo_fuzzy_key
from domain.company import Listing, ListingSeed, normalized_name_key
from valuator.utils.config import get_opendart_api_key

OPENDART_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
OPENDART_COMPANY_URL = "https://opendart.fss.or.kr/api/company.json"

_FUZZY_THRESHOLD = 0.7
_STOCK_CODE_RE = re.compile(r"^\d{6}$")

_CORP_CLS_EXCHANGE = {"Y": "KOSPI", "K": "KOSDAQ", "N": "KONEX"}
_CORP_CLS_YAHOO_SUFFIX = {"Y": ".KS", "K": ".KQ", "N": ".KN"}

_corp_records_cache: list[dict[str, str]] | None = None
_corp_cls_cache: dict[str, str] = {}


def clear_krx_records_cache() -> None:
    """Test hook: drop in-process KRX record cache."""
    global _corp_records_cache
    _corp_records_cache = None
    _corp_cls_cache.clear()


def fetch_krx_corp_records(*, force_remote: bool = False) -> list[dict[str, str]]:
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
    stock_code = record["stock_code"].upper()
    corp_name = record.get("corp_name", "")
    exchange = _CORP_CLS_EXCHANGE.get(corp_cls, "KRX")
    yahoo_suffix = _CORP_CLS_YAHOO_SUFFIX.get(corp_cls, ".KS")
    listing_id = f"KRX:{stock_code}"
    listing = Listing(
        listing_id=listing_id,
        company_id=listing_id,
        security_code=stock_code,
        exchange=exchange,
        vendor_symbols={"yahoo": f"{stock_code}{yahoo_suffix}"},
    )
    return ListingSeed(
        company_id=listing_id,
        company_name=corp_name,
        company_aliases=(corp_name,) if corp_name else (),
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
    matches = [r for r in records if normalized_name_key(r.get("corp_name", "")) == key]
    return matches[0] if len(matches) == 1 else None


def _match_by_fuzzy_name(
    records: list[dict[str, str]], surface_form: str
) -> dict[str, Any] | None:
    query_key = jamo_fuzzy_key(surface_form)
    if not query_key:
        return None
    best_score = 0.0
    best_rows: list[dict[str, Any]] = []
    for record in records:
        candidate_key = jamo_fuzzy_key(record.get("corp_name", ""))
        if not candidate_key:
            continue
        score = SequenceMatcher(None, query_key, candidate_key).ratio()
        if score < _FUZZY_THRESHOLD:
            continue
        if score > best_score:
            best_score = score
            best_rows = [record]
        elif score == best_score:
            best_rows.append(record)
    return best_rows[0] if len(best_rows) == 1 else None


def resolve_krx_corp_record(surface_form: str) -> dict[str, str] | None:
    """Resolve a KRX corp record from stock code or company name."""
    surface = surface_form.strip()
    if not surface:
        return None
    records = fetch_krx_corp_records()
    surface_upper = surface.upper()

    record = _match_by_stock_code(records, surface_upper)
    if record is not None:
        return record

    key = normalized_name_key(surface)
    record = _match_by_exact_name(records, key)
    if record is not None:
        return record

    record = _match_by_fuzzy_name(records, surface)
    if record is not None:
        return record

    return None


def resolve_krx_listing_seeds(surface_form: str) -> tuple[ListingSeed, ...]:
    """Return listing seeds for a surface form using a live OpenDart corp code table."""
    surface = surface_form.strip()
    if not surface:
        return ()
    api_key = get_opendart_api_key()
    if not api_key:
        return ()
    record = resolve_krx_corp_record(surface)
    if record is None:
        return ()
    return _seed_from_record(record, api_key)


def krx_on_miss(surface_form: str) -> tuple[ListingSeed, ...]:
    """Callable for ``resolve_subjects(..., on_miss=...)``."""
    return resolve_krx_listing_seeds(surface_form)
