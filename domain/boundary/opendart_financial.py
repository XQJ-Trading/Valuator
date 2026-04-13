"""Boundary: fetch financial statements from OpenDART fnlttSinglAcntAll API."""

from __future__ import annotations

from typing import Any

import requests

from domain.boundary.krx_ticker_resolve import fetch_krx_corp_records
from domain.knowledge.financial import OPENDART_ACCOUNT_MAP
from valuator.utils.config import get_opendart_api_key

OPENDART_FINSTATE_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"

REPRT_CODES: dict[str, str] = {
    "annual": "11011",
    "half": "11012",
    "q1": "11013",
    "q3": "11014",
}

_fs_cache: dict[str, dict[str, float | None]] = {}


def clear_opendart_financial_cache() -> None:
    """Test hook."""
    _fs_cache.clear()


def resolve_corp_code(stock_code: str) -> str | None:
    """stock_code(6자리) -> 8자리 DART corp_code. 순수 lookup, API 호출 없음."""
    surface = stock_code.strip()
    if not surface:
        return None
    surface_upper = surface.upper()
    for record in fetch_krx_corp_records():
        if record.get("stock_code", "").upper() == surface_upper:
            return record.get("corp_code") or None
        if record.get("corp_name", "").strip() == surface:
            return record.get("corp_code") or None
    return None


def fetch_opendart_financial(
    corp_code: str,
    year: int,
    reprt_code: str = REPRT_CODES["annual"],
    fs_div: str = "CFS",
) -> dict[str, float | None] | None:
    """
    OpenDART 재무제표 단일 호출 -> canonical dict 변환.

    실패 시 None 반환. 네트워크/HTTP 오류는 전파한다.
    """
    api_key = get_opendart_api_key()
    if not api_key:
        return None

    cache_key = f"fs:{corp_code}:{year}:{reprt_code}:{fs_div}"
    if cache_key in _fs_cache:
        return _fs_cache[cache_key]

    response = requests.get(
        OPENDART_FINSTATE_URL,
        params={
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": reprt_code,
            "fs_div": fs_div,
        },
        timeout=30,
    )
    response.raise_for_status()

    body = response.json()
    if body.get("status") != "000":
        return None

    items = body.get("list", [])
    if not items:
        return None

    result = _parse_items(items)
    _fs_cache[cache_key] = result
    return result


def _parse_items(items: list[dict[str, Any]]) -> dict[str, float | None]:
    """OpenDART response list -> canonical dict."""
    result: dict[str, float | None] = {}
    for item in items:
        canonical = OPENDART_ACCOUNT_MAP.get(str(item.get("account_nm") or ""))
        if not canonical:
            continue
        raw_amount = str(item.get("thstrm_amount") or "").strip()
        if not raw_amount or raw_amount == "-":
            continue
        result[canonical] = float(raw_amount.replace(",", ""))
    return result
