"""Boundary: fetch financial statements from OpenDART fnlttSinglAcntAll API."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import requests

from domain.knowledge.financial import OPENDART_ACCOUNT_ID_MAP, OPENDART_ACCOUNT_NM_MAP
from valuator.utils.config import get_opendart_api_key

OPENDART_FINSTATE_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"

REPRT_CODES: dict[str, str] = {
    "annual": "11011",
    "half": "11012",
    "q1": "11013",
    "q3": "11014",
}


@dataclass(frozen=True)
class OpenDartReport:
    rcept_no: str
    bsns_year: int
    fs_div: str
    thstrm: dict[str, float | None]
    frmtrm: dict[str, float | None]
    bfefrmtrm: dict[str, float | None]


class FetchOutcome(Enum):
    OK = "ok"
    NOT_FILED = "not_filed"
    ERROR = "error"


@dataclass(frozen=True)
class YearFinancials:
    values: dict[str, float | None]
    source_rcept_no: str
    source_bsns_year: int
    fs_div: str
    restated: bool


_report_cache: dict[str, OpenDartReport] = {}


def clear_opendart_financial_cache() -> None:
    """Test hook."""
    _report_cache.clear()


def fetch_opendart_report(
    corp_code: str,
    bsns_year: int,
    reprt_code: str = REPRT_CODES["annual"],
    fs_div: str = "CFS",
) -> tuple[OpenDartReport | None, FetchOutcome, str | None]:
    """Fetch one OpenDART report and parse all available period columns."""
    api_key = get_opendart_api_key()
    if not api_key:
        return None, FetchOutcome.ERROR, "OPENDART_API_KEY is not set"

    cache_key = f"report:{corp_code}:{bsns_year}:{reprt_code}:{fs_div}"
    if cache_key in _report_cache:
        return _report_cache[cache_key], FetchOutcome.OK, None

    response = requests.get(
        OPENDART_FINSTATE_URL,
        params={
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": str(bsns_year),
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
        if status == "013":
            return None, FetchOutcome.NOT_FILED, message or "DART report not filed"
        if message:
            return None, FetchOutcome.ERROR, f"DART API: {message}"
        return None, FetchOutcome.ERROR, f"DART API status={status!r} (not success)"

    items = body.get("list", [])
    if not items:
        return (
            None,
            FetchOutcome.NOT_FILED,
            "DART returned no line items for this corp/year/report/fs_div",
        )

    report = _parse_report(items, bsns_year=bsns_year, fs_div=fs_div)
    _backfill_operating_income(report.thstrm)
    _backfill_operating_income(report.frmtrm)
    _backfill_operating_income(report.bfefrmtrm)
    _report_cache[cache_key] = report
    return report, FetchOutcome.OK, None


def fetch_opendart_year(
    corp_code: str,
    year: int,
    fs_div: str = "CFS",
) -> tuple[YearFinancials | None, str | None]:
    """Fetch year Y using Y+1 restated prior-year data when available."""
    next_report, next_outcome, next_error = fetch_opendart_report(
        corp_code=corp_code,
        bsns_year=year + 1,
        fs_div=fs_div,
    )
    if next_outcome == FetchOutcome.OK:
        if next_report is None:
            return None, "DART returned OK without a report"
        return (
            YearFinancials(
                values=dict(next_report.frmtrm),
                source_rcept_no=next_report.rcept_no,
                source_bsns_year=next_report.bsns_year,
                fs_div=next_report.fs_div,
                restated=True,
            ),
            None,
        )
    if next_outcome == FetchOutcome.ERROR:
        return None, next_error

    current_report, current_outcome, current_error = fetch_opendart_report(
        corp_code=corp_code,
        bsns_year=year,
        fs_div=fs_div,
    )
    if current_outcome != FetchOutcome.OK:
        return None, current_error or next_error
    if current_report is None:
        return None, "DART returned OK without a report"
    return (
        YearFinancials(
            values=dict(current_report.thstrm),
            source_rcept_no=current_report.rcept_no,
            source_bsns_year=current_report.bsns_year,
            fs_div=current_report.fs_div,
            restated=False,
        ),
        None,
    )


def _parse_report(
    items: list[dict[str, Any]],
    *,
    bsns_year: int,
    fs_div: str,
) -> OpenDartReport:
    """OpenDART response list -> report with canonical dicts for all periods.

    account_id(K-IFRS element id)를 1차 키로, account_nm을 fallback으로 매핑.
    같은 canonical에 여러 row가 매칭되면 첫 row를 우선한다 — DART 응답은
    재무제표 본문이 보통 앞쪽, 부속/주석 표가 뒤쪽에 와서 첫 매칭이 본문일 확률이 높다.
    """
    rcept_no: str | None = None
    thstrm: dict[str, float | None] = {}
    frmtrm: dict[str, float | None] = {}
    bfefrmtrm: dict[str, float | None] = {}

    for item in items:
        row_rcept_no = str(item.get("rcept_no") or "").strip()
        if not row_rcept_no:
            raise ValueError("DART row is missing rcept_no")
        if rcept_no is None:
            rcept_no = row_rcept_no
        elif row_rcept_no != rcept_no:
            raise ValueError(
                f"DART response contains mixed rcept_no values: "
                f"{rcept_no!r} and {row_rcept_no!r}"
            )

        canonical = _resolve_canonical(item)
        if not canonical:
            continue

        _set_first(thstrm, canonical, item.get("thstrm_amount"))
        _set_first(frmtrm, canonical, item.get("frmtrm_amount"))
        _set_first(bfefrmtrm, canonical, item.get("bfefrmtrm_amount"))

    if rcept_no is None:
        raise ValueError("DART response contains no rows")

    return OpenDartReport(
        rcept_no=rcept_no,
        bsns_year=bsns_year,
        fs_div=fs_div,
        thstrm=thstrm,
        frmtrm=frmtrm,
        bfefrmtrm=bfefrmtrm,
    )


def _set_first(
    result: dict[str, float | None],
    canonical: str,
    raw_amount: Any,
) -> None:
    if canonical in result:
        return
    result[canonical] = _parse_amount(raw_amount)


def _parse_amount(raw_amount: Any) -> float | None:
    raw = str(raw_amount or "").strip()
    if not raw or raw == "-":
        return None
    return float(raw.replace(",", ""))


def _resolve_canonical(item: dict[str, Any]) -> str | None:
    sj_div = str(item.get("sj_div") or "")
    if not sj_div:
        return None
    account_id = str(item.get("account_id") or "")
    canonical = OPENDART_ACCOUNT_ID_MAP.get((account_id, sj_div))
    if canonical:
        return canonical
    return OPENDART_ACCOUNT_NM_MAP.get((str(item.get("account_nm") or ""), sj_div))


def _backfill_operating_income(result: dict[str, float | None]) -> None:
    if result.get("operating_income") is not None:
        return
    gross_profit = result.get("gross_profit")
    sga_expense = result.get("sga_expense")
    if gross_profit is not None and sga_expense is not None:
        result["operating_income"] = gross_profit - sga_expense
