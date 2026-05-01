"""Boundary: fetch financial statements from OpenDART fnlttSinglAcntAll API."""

from __future__ import annotations

from typing import Any

import requests

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


def fetch_opendart_financial(
    corp_code: str,
    year: int,
    reprt_code: str = REPRT_CODES["annual"],
    fs_div: str = "CFS",
) -> tuple[dict[str, float | None] | None, str | None]:
    """OpenDART 재무제표 단일 호출 -> canonical dict 변환."""
    api_key = get_opendart_api_key()
    if not api_key:
        return None, "OPENDART_API_KEY is not set"

    cache_key = f"fs:{corp_code}:{year}:{reprt_code}:{fs_div}"
    if cache_key in _fs_cache:
        return _fs_cache[cache_key], None

    response = requests.get(
        OPENDART_FINSTATE_URL,
        params={
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": reprt_code,
            "fs_div": fs_div,
        },
        timeout=5,
    )
    response.raise_for_status()

    body = response.json()
    status = body.get("status")
    if status != "000":
        message = str(body.get("message") or "").strip()
        if message:
            return None, f"DART API: {message}"
        return None, f"DART API status={status!r} (not success)"

    items = body.get("list", [])
    if not items:
        return None, "DART returned no line items for this corp/year/report/fs_div"

    result = _parse_items(items)
    _backfill_operating_income(result)
    _fs_cache[cache_key] = result
    return result, None


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


def _backfill_operating_income(result: dict[str, float | None]) -> None:
    # 일부 보고서는 영업이익을 별도 라인으로 제공하지 않아 매출총이익-판관비로 보정한다.
    if result.get("operating_income") is not None:
        return
    gross_profit = result.get("gross_profit")
    sga_expense = result.get("sga_expense")
    if gross_profit is not None and sga_expense is not None:
        result["operating_income"] = gross_profit - sga_expense
