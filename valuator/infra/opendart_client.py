from __future__ import annotations

import gzip
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from functools import lru_cache
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from threading import Lock
from types import ModuleType, SimpleNamespace
from typing import Any, Callable, TypeVar

import requests
from pydantic import BaseModel, ConfigDict, Field
from tqdm import tqdm

from valuator.domain.company import Listing, ListingSeed
from valuator.utils.dataclass_compat import dataclass


ROOT_DIR = Path(__file__).resolve().parents[2]
OUTPUT_PATH = ROOT_DIR / "data" / "krx_securities.json"
OPENDART_SNAPSHOT_PATH = (
    ROOT_DIR / "scripts" / "snapshots" / "opendart_companies.json.gz"
)
OPENDART_EXCHANGE_BY_CORP_CLS = {
    "Y": "KOSPI",
    "K": "KOSDAQ",
    "N": "KONEX",
}
_LOOKUP_FUZZY_THRESHOLD = 0.7
_BACKOFF_BASE_DELAY_SECONDS = 1.0
_BACKOFF_FACTOR = 2.0
_BACKOFF_MAX_DELAY_SECONDS = 30.0
_MAX_RETRIES = 2
_BULK_MAX_WORKERS = 4
_KST = timezone(timedelta(hours=9))
_SNAPSHOT_REFRESH_LOCK = Lock()
T = TypeVar("T")
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SecurityRecord:
    issuer_name: str
    security_code: str
    exchange: str
    listing_id: str
    vendor_symbols: dict[str, str]
    aliases: list[str]
    corp_code: str

    def to_payload(self) -> dict[str, object]:
        return {
            "issuer_name": self.issuer_name,
            "security_code": self.security_code,
            "exchange": self.exchange,
            "listing_id": self.listing_id,
            "vendor_symbols": dict(self.vendor_symbols),
            "aliases": list(self.aliases),
            "corp_code": self.corp_code,
        }


@dataclass(frozen=True, slots=True)
class _OpenDartListedCompany:
    stock_code: str
    corp_code: str
    corp_name: str
    stock_name: str
    corp_cls: str
    exchange: str


@dataclass(frozen=True, slots=True)
class _OpenDartSnapshotCompany:
    stock_code: str
    corp_code: str
    corp_name: str
    corp_name_eng: str
    stock_name: str
    corp_cls: str
    exchange: str

    def to_snapshot_payload(self) -> dict[str, str]:
        return {
            "corp_code": self.corp_code,
            "corp_name": self.corp_name,
            "corp_name_eng": self.corp_name_eng,
            "stock_name": self.stock_name,
            "stock_code": self.stock_code,
            "corp_cls": self.corp_cls,
        }

    def to_security_record(self) -> SecurityRecord:
        return SecurityRecord(
            issuer_name=self.stock_name,
            security_code=self.stock_code,
            exchange=self.exchange,
            listing_id=f"KRX:{self.stock_code}",
            vendor_symbols=_vendor_symbols(self.exchange, self.stock_code),
            aliases=_dedupe_strings(
                [
                    self.stock_name,
                    self.corp_name,
                    self.corp_name_eng,
                ]
            ),
            corp_code=self.corp_code,
        )


class _OpenDartSnapshotItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    corp_code: str
    corp_name: str
    corp_name_eng: str = ""
    stock_name: str
    stock_code: str
    corp_cls: str


class _OpenDartSnapshotEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    generated_at: str = ""
    entries: dict[str, _OpenDartSnapshotItem] = Field(default_factory=dict)


class _OpenDartCompanyInfoPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    corp_code: str = ""
    corp_name: str = ""
    corp_eng_name: str = ""
    stock_name: str = ""


class _OpenDartLookupError(Exception):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        kind: str,
        retry_after: float = 0.0,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.kind = kind
        self.retry_after = retry_after


def lookup_company(
    api_key: str,
    company_name: str,
    *,
    snapshot_path: Path = OPENDART_SNAPSHOT_PATH,
    output_path: Path = OUTPUT_PATH,
) -> list[ListingSeed]:
    surface_form = company_name.strip()
    if not surface_form:
        return []

    snapshot_companies = _cached_snapshot_companies(snapshot_path)
    matched_companies = _find_snapshot_companies(snapshot_companies, surface_form)
    if matched_companies:
        return [
            _listing_seed_from_snapshot_company(company)
            for company in matched_companies
        ]

    live_companies = _lookup_live_companies(
        api_key,
        surface_form,
        snapshot_companies=snapshot_companies,
    )
    if not live_companies:
        return []

    with _SNAPSHOT_REFRESH_LOCK:
        current_snapshot = _cached_snapshot_companies(snapshot_path)
        merged_snapshot = dict(current_snapshot)
        merged_snapshot.update(live_companies)
        _persist_snapshot_state(
            snapshot_path,
            output_path,
            merged_snapshot,
        )
    return [
        _listing_seed_from_snapshot_company(company)
        for _, company in sorted(live_companies.items())
    ]


def sync_all_companies(
    api_key: str,
    *,
    snapshot_path: Path = OPENDART_SNAPSHOT_PATH,
    output_path: Path = OUTPUT_PATH,
) -> list[ListingSeed]:
    with _SNAPSHOT_REFRESH_LOCK:
        companies = _sync_opendart_companies(
            api_key,
            snapshot_path=snapshot_path,
        )
        _persist_snapshot_state(snapshot_path, output_path, companies)
    return [
        _listing_seed_from_snapshot_company(company)
        for _, company in sorted(companies.items())
    ]


def _sync_opendart_companies(
    api_key: str,
    *,
    snapshot_path: Path = OPENDART_SNAPSHOT_PATH,
    max_workers: int = _BULK_MAX_WORKERS,
) -> dict[str, _OpenDartSnapshotCompany]:
    with tqdm(total=1, desc="OpenDART corp list", unit="step") as progress:
        live_companies = _fetch_opendart_listed_companies(api_key)
        progress.update(1)

    if not live_companies:
        raise _OpenDartLookupError(
            "OpenDART listed company sync returned 0 entries",
            retryable=False,
            kind="empty_listing",
        )

    snapshot_companies = _load_snapshot(snapshot_path)
    stale_codes = [
        stock_code
        for stock_code, live_company in sorted(live_companies.items())
        if _snapshot_needs_refresh(live_company, snapshot_companies.get(stock_code))
    ]
    refreshed_companies = _fetch_snapshot_companies(
        api_key,
        live_companies,
        snapshot_companies,
        stock_codes=stale_codes,
        max_workers=max_workers,
    )

    companies: dict[str, _OpenDartSnapshotCompany] = {}
    for stock_code, live_company in sorted(live_companies.items()):
        existing_company = snapshot_companies.get(stock_code)
        company = refreshed_companies.get(stock_code)
        if company is None and existing_company is not None:
            company = _merge_live_company(existing_company, live_company)
        if company is None:
            company = _snapshot_company_from_detail(live_company, {}, existing_company)
        companies[stock_code] = company

    if not companies:
        raise _OpenDartLookupError(
            "OpenDART snapshot sync produced 0 entries",
            retryable=False,
            kind="empty_snapshot",
        )

    print(
        "OpenDART sync complete: "
        f"listed={len(live_companies)} "
        f"snapshot={len(companies)} "
        f"refreshed={len(stale_codes)}"
    )
    return companies


def _lookup_live_companies(
    api_key: str,
    surface_form: str,
    *,
    snapshot_companies: dict[str, _OpenDartSnapshotCompany],
) -> dict[str, _OpenDartSnapshotCompany]:
    live_companies = _fetch_opendart_listed_companies(api_key)
    matched_companies = _find_listed_companies(live_companies, surface_form)
    if not matched_companies:
        return {}
    return _fetch_snapshot_companies(
        api_key,
        matched_companies,
        snapshot_companies,
        stock_codes=sorted(matched_companies),
        max_workers=1,
    )


def _fetch_opendart_listed_companies(
    api_key: str,
) -> dict[str, _OpenDartListedCompany]:
    corp_list = _with_retry(lambda: _request_opendart_corp_list(api_key))
    return _listed_companies_from_corp_list(corp_list)


def _request_opendart_corp_list(api_key: str) -> Any:
    try:
        auth, corp_code_api, _company_api, market_api = _load_dart_fss_modules()
        _configure_dart_fss(auth, _required_api_key(api_key))
        corp_codes = corp_code_api.get_corp_code()
        stock_market = _stock_market_by_code(market_api)
        return SimpleNamespace(
            corps=[
                corp
                for record in corp_codes
                for corp in [_corp_from_record(record, stock_market)]
                if corp is not None
            ]
        )
    except Exception as exc:
        raise _opendart_error_from_exception(exc) from exc


def _fetch_opendart_company_info(
    api_key: str,
    corp_code: str,
) -> dict[str, Any]:
    return _with_retry(lambda: _request_opendart_company_info(api_key, corp_code))


def _request_opendart_company_info(
    api_key: str,
    corp_code: str,
) -> dict[str, Any]:
    try:
        auth, _corp_code_api, company_api, _market_api = _load_dart_fss_modules()
        _configure_dart_fss(auth, _required_api_key(api_key))
        try:
            payload = company_api.get_corp_info(corp_code, api_key=api_key)
        except TypeError:
            payload = company_api.get_corp_info(corp_code)
    except Exception as exc:
        raise _opendart_error_from_exception(exc) from exc

    if not isinstance(payload, dict):
        raise _OpenDartLookupError(
            "OpenDART company info returned unexpected payload",
            retryable=False,
            kind="invalid_payload",
        )
    return dict(payload)


def _fetch_snapshot_companies(
    api_key: str,
    live_companies: dict[str, _OpenDartListedCompany],
    snapshot_companies: dict[str, _OpenDartSnapshotCompany],
    *,
    stock_codes: list[str],
    max_workers: int,
) -> dict[str, _OpenDartSnapshotCompany]:
    if not stock_codes:
        return {}

    if max_workers <= 1:
        companies: dict[str, _OpenDartSnapshotCompany] = {}
        with tqdm(total=len(stock_codes), desc="OpenDART company info", unit="company") as progress:
            for stock_code in stock_codes:
                live_company = live_companies[stock_code]
                companies[stock_code] = _snapshot_company_from_detail(
                    live_company,
                    _fetch_opendart_company_info(api_key, live_company.corp_code),
                    snapshot_companies.get(stock_code),
                )
                progress.update(1)
        return companies

    companies: dict[str, _OpenDartSnapshotCompany] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _fetch_snapshot_company_detail,
                api_key,
                live_companies[stock_code],
                snapshot_companies.get(stock_code),
            ): stock_code
            for stock_code in stock_codes
        }
        with tqdm(total=len(futures), desc="OpenDART company info", unit="company") as progress:
            for future in as_completed(futures):
                stock_code = futures[future]
                companies[stock_code] = future.result()
                progress.update(1)
    return companies


def _fetch_snapshot_company_detail(
    api_key: str,
    live_company: _OpenDartListedCompany,
    snapshot_company: _OpenDartSnapshotCompany | None,
) -> _OpenDartSnapshotCompany:
    payload = _fetch_opendart_company_info(api_key, live_company.corp_code)
    return _snapshot_company_from_detail(live_company, payload, snapshot_company)


def _snapshot_company_from_detail(
    live_company: _OpenDartListedCompany,
    payload: dict[str, Any],
    snapshot_company: _OpenDartSnapshotCompany | None,
) -> _OpenDartSnapshotCompany:
    info = _OpenDartCompanyInfoPayload.model_validate(payload)
    corp_name = info.corp_name or live_company.corp_name
    stock_name = info.stock_name or live_company.stock_name
    corp_name_eng = info.corp_eng_name
    if not corp_name_eng and snapshot_company is not None:
        corp_name_eng = snapshot_company.corp_name_eng
    return _OpenDartSnapshotCompany(
        stock_code=live_company.stock_code,
        corp_code=live_company.corp_code,
        corp_name=corp_name,
        corp_name_eng=corp_name_eng,
        stock_name=stock_name,
        corp_cls=live_company.corp_cls,
        exchange=live_company.exchange,
    )


def _listed_companies_from_corp_list(
    corp_list: Any,
) -> dict[str, _OpenDartListedCompany]:
    companies: dict[str, _OpenDartListedCompany] = {}
    for corp in getattr(corp_list, "corps", ()):
        company = _listed_company_from_corp(corp)
        if company is None:
            continue
        companies[company.stock_code] = company
    return companies


def _listed_company_from_corp(corp: Any) -> _OpenDartListedCompany | None:
    stock_code = str(getattr(corp, "stock_code", "") or "").strip()
    corp_code = str(getattr(corp, "corp_code", "") or "").strip()
    corp_name = str(getattr(corp, "corp_name", "") or "").strip()
    corp_cls = str(getattr(corp, "corp_cls", "") or "").strip().upper()
    exchange = OPENDART_EXCHANGE_BY_CORP_CLS.get(corp_cls, "")
    if not stock_code or not corp_code or not corp_name or not exchange:
        return None
    return _OpenDartListedCompany(
        stock_code=stock_code,
        corp_code=corp_code,
        corp_name=corp_name,
        stock_name=corp_name,
        corp_cls=corp_cls,
        exchange=exchange,
    )


def _merge_live_company(
    snapshot_company: _OpenDartSnapshotCompany,
    live_company: _OpenDartListedCompany,
) -> _OpenDartSnapshotCompany:
    return _OpenDartSnapshotCompany(
        stock_code=live_company.stock_code,
        corp_code=live_company.corp_code,
        corp_name=live_company.corp_name,
        corp_name_eng=snapshot_company.corp_name_eng,
        stock_name=live_company.stock_name,
        corp_cls=live_company.corp_cls,
        exchange=live_company.exchange,
    )


def _corp_from_record(
    record: Any,
    stock_market: dict[str, dict[str, Any]],
) -> SimpleNamespace | None:
    data = dict(record)
    stock_code = str(data.get("stock_code") or "").strip()
    corp_code = str(data.get("corp_code") or "").strip()
    corp_name = str(data.get("corp_name") or "").strip()
    market_info = stock_market.get(stock_code)
    if not stock_code or not corp_code or not corp_name or market_info is None:
        return None
    corp_cls = str(market_info.get("corp_cls") or "").strip().upper()
    if corp_cls not in OPENDART_EXCHANGE_BY_CORP_CLS:
        return None
    stock_name = str(market_info.get("corp_name") or corp_name).strip() or corp_name
    return SimpleNamespace(
        stock_code=stock_code,
        corp_code=corp_code,
        corp_name=corp_name,
        stock_name=stock_name,
        corp_cls=corp_cls,
    )


def _stock_market_by_code(market_api: Any) -> dict[str, dict[str, Any]]:
    stock_market: dict[str, dict[str, Any]] = {}
    for corp_cls in ("Y", "K", "N"):
        entries = market_api.get_stock_market_list(corp_cls, True)
        stock_market.update(
            {
                str(stock_code).strip(): dict(entry)
                for stock_code, entry in dict(entries).items()
                if str(stock_code).strip()
            }
        )
    return stock_market


def _snapshot_needs_refresh(
    live_company: _OpenDartListedCompany,
    snapshot_company: _OpenDartSnapshotCompany | None,
) -> bool:
    if snapshot_company is None:
        return True
    if snapshot_company.corp_code != live_company.corp_code:
        return True
    if snapshot_company.corp_name != live_company.corp_name:
        return True
    if snapshot_company.stock_name != live_company.stock_name:
        return True
    if snapshot_company.corp_cls != live_company.corp_cls:
        return True
    if snapshot_company.exchange != live_company.exchange:
        return True
    return not snapshot_company.corp_name_eng


@lru_cache(maxsize=4)
def _cached_snapshot_envelope(
    snapshot_key: str,
) -> _OpenDartSnapshotEnvelope | None:
    path = Path(snapshot_key)
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    return _OpenDartSnapshotEnvelope.model_validate(payload)


def _cached_snapshot_companies(
    snapshot_path: Path,
) -> dict[str, _OpenDartSnapshotCompany]:
    envelope = _cached_snapshot_envelope(str(snapshot_path.resolve()))
    return _snapshot_companies_from_envelope(envelope)


def _snapshot_generated_at(
    snapshot_path: Path,
) -> datetime | None:
    envelope = _cached_snapshot_envelope(str(snapshot_path.resolve()))
    if envelope is None or not envelope.generated_at:
        return None
    return _parse_timestamp(envelope.generated_at)


def _snapshot_is_fresh_today_kst(snapshot_path: Path) -> bool:
    envelope = _cached_snapshot_envelope(str(snapshot_path.resolve()))
    if envelope is None or not envelope.entries:
        return False
    generated_at = _snapshot_generated_at(snapshot_path)
    if generated_at is None:
        return False
    return generated_at.astimezone(_KST).date() == datetime.now(_KST).date()


def _find_snapshot_companies(
    companies: dict[str, _OpenDartSnapshotCompany],
    company_name: str,
) -> list[_OpenDartSnapshotCompany]:
    surface_key = _name_key(company_name)
    if not surface_key:
        return []

    exact_matches = {
        company.stock_code: company
        for company in companies.values()
        if surface_key in _snapshot_company_keys(company)
    }
    if exact_matches:
        return [exact_matches[stock_code] for stock_code in sorted(exact_matches)]

    best_score = 0.0
    fuzzy_matches: dict[str, _OpenDartSnapshotCompany] = {}
    for company in companies.values():
        score = max(
            (
                SequenceMatcher(None, surface_key, candidate_key).ratio()
                for candidate_key in _snapshot_company_keys(company)
            ),
            default=0.0,
        )
        if score < _LOOKUP_FUZZY_THRESHOLD:
            continue
        if score > best_score:
            best_score = score
            fuzzy_matches = {company.stock_code: company}
            continue
        if score == best_score:
            fuzzy_matches[company.stock_code] = company

    return [fuzzy_matches[stock_code] for stock_code in sorted(fuzzy_matches)]


def _find_listed_companies(
    companies: dict[str, _OpenDartListedCompany],
    company_name: str,
) -> dict[str, _OpenDartListedCompany]:
    surface_key = _name_key(company_name)
    if not surface_key:
        return {}

    exact_matches = {
        company.stock_code: company
        for company in companies.values()
        if surface_key in _listed_company_keys(company)
    }
    if exact_matches:
        return {stock_code: exact_matches[stock_code] for stock_code in sorted(exact_matches)}

    best_score = 0.0
    fuzzy_matches: dict[str, _OpenDartListedCompany] = {}
    for company in companies.values():
        score = max(
            (
                SequenceMatcher(None, surface_key, candidate_key).ratio()
                for candidate_key in _listed_company_keys(company)
            ),
            default=0.0,
        )
        if score < _LOOKUP_FUZZY_THRESHOLD:
            continue
        if score > best_score:
            best_score = score
            fuzzy_matches = {company.stock_code: company}
            continue
        if score == best_score:
            fuzzy_matches[company.stock_code] = company
    return {stock_code: fuzzy_matches[stock_code] for stock_code in sorted(fuzzy_matches)}


def _snapshot_company_keys(company: _OpenDartSnapshotCompany) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            key
            for key in (
                _name_key(company.stock_name),
                _name_key(company.corp_name),
                _name_key(company.corp_name_eng),
                _name_key(company.stock_code),
                _name_key(f"KRX:{company.stock_code}"),
            )
            if key
        )
    )


def _listed_company_keys(company: _OpenDartListedCompany) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            key
            for key in (
                _name_key(company.stock_name),
                _name_key(company.corp_name),
                _name_key(company.stock_code),
                _name_key(f"KRX:{company.stock_code}"),
            )
            if key
        )
    )


def _listing_seed_from_snapshot_company(
    company: _OpenDartSnapshotCompany,
) -> ListingSeed:
    listing_id = f"KRX:{company.stock_code}"
    listing = Listing(
        listing_id=listing_id,
        company_id=listing_id,
        security_code=company.stock_code,
        exchange=company.exchange,
        vendor_symbols=_vendor_symbols(company.exchange, company.stock_code),
    )
    return ListingSeed(
        company_id=listing_id,
        company_name=company.stock_name,
        company_aliases=tuple(
            _dedupe_strings(
                [
                    company.stock_name,
                    company.corp_name,
                    company.corp_name_eng,
                ]
            )
        ),
        listing=listing,
    )


def _load_snapshot(path: Path) -> dict[str, _OpenDartSnapshotCompany]:
    envelope = _cached_snapshot_envelope(str(path.resolve()))
    return _snapshot_companies_from_envelope(envelope)


def _snapshot_companies_from_envelope(
    envelope: _OpenDartSnapshotEnvelope | None,
) -> dict[str, _OpenDartSnapshotCompany]:
    if envelope is None:
        return {}

    companies: dict[str, _OpenDartSnapshotCompany] = {}
    for stock_code, item in envelope.entries.items():
        if stock_code != item.stock_code:
            raise RuntimeError(f"snapshot key mismatch: {stock_code}")

        exchange = OPENDART_EXCHANGE_BY_CORP_CLS.get(item.corp_cls, "")
        if not exchange:
            raise RuntimeError(
                f"snapshot contains unsupported corp_cls: {item.corp_cls}"
            )

        companies[stock_code] = _OpenDartSnapshotCompany(
            stock_code=item.stock_code,
            corp_code=item.corp_code,
            corp_name=item.corp_name,
            corp_name_eng=item.corp_name_eng,
            stock_name=item.stock_name,
            corp_cls=item.corp_cls,
            exchange=exchange,
        )
    return companies


def _persist_snapshot_state(
    snapshot_path: Path,
    output_path: Path,
    companies: dict[str, _OpenDartSnapshotCompany],
) -> None:
    _write_snapshot(snapshot_path, companies)
    records = _security_records_from_snapshot(companies)
    _write_security_records(output_path, records)


def _write_snapshot(
    path: Path,
    companies: dict[str, _OpenDartSnapshotCompany],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": _timestamp_utc(),
        "entries": {
            stock_code: company.to_snapshot_payload()
            for stock_code, company in sorted(companies.items())
        },
    }
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    _cached_snapshot_envelope.cache_clear()


def _write_security_records(path: Path, records: list[SecurityRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [record.to_payload() for record in records],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _security_records_from_snapshot(
    companies: dict[str, _OpenDartSnapshotCompany],
) -> list[SecurityRecord]:
    records: list[SecurityRecord] = []
    ordered_companies = [company for _, company in sorted(companies.items())]
    with tqdm(
        total=len(ordered_companies),
        desc="Build securities",
        unit="security",
    ) as progress:
        for company in ordered_companies:
            records.append(company.to_security_record())
            progress.update(1)
    return records


def _with_retry(request: Callable[[], T]) -> T:
    max_attempts = _MAX_RETRIES + 1
    for attempt in range(max_attempts):
        try:
            return request()
        except _OpenDartLookupError as exc:
            if not exc.retryable:
                raise
            if attempt == _MAX_RETRIES:
                logger.warning(
                    "OpenDART request failed after %s attempts: kind=%s error=%s",
                    max_attempts,
                    exc.kind,
                    exc,
                )
                raise
            delay = _retry_delay_seconds(attempt + 1, exc.retry_after)
            logger.warning(
                "OpenDART request failed; retrying in %.2fs "
                "(attempt=%s/%s kind=%s error=%s)",
                delay,
                attempt + 1,
                max_attempts,
                exc.kind,
                exc,
            )
            time.sleep(delay)
    raise RuntimeError("OpenDART retry loop exhausted")


def _retry_delay_seconds(
    attempt: int,
    retry_after: float,
) -> float:
    delay = min(
        _BACKOFF_BASE_DELAY_SECONDS * (_BACKOFF_FACTOR ** max(attempt - 1, 0)),
        _BACKOFF_MAX_DELAY_SECONDS,
    )
    return max(delay, retry_after)


def _next_quota_reset_at_kst(now: datetime | None = None) -> datetime:
    current = now or datetime.now(_KST)
    current_kst = current.astimezone(_KST)
    next_day = current_kst.date() + timedelta(days=1)
    return datetime(
        year=next_day.year,
        month=next_day.month,
        day=next_day.day,
        tzinfo=_KST,
    )


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _name_key(text: str) -> str:
    return "".join(char for char in text.strip().upper() if char.isalnum())


def _timestamp_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _vendor_symbols(exchange: str, security_code: str) -> dict[str, str]:
    if exchange == "KOSDAQ":
        return {"yahoo": f"{security_code}.KQ"}
    if exchange == "KOSPI":
        return {"yahoo": f"{security_code}.KS"}
    return {"yahoo": security_code}


def _required_api_key(api_key: str) -> str:
    value = api_key.strip()
    if value:
        return value
    raise RuntimeError("OPENDART_API_KEY not set")


def _load_dart_fss_modules() -> tuple[Any, Any, Any, Any]:
    _bootstrap_dart_fss_namespace()
    try:
        auth = import_module("dart_fss.auth")
        corp_code_api = import_module("dart_fss.api.filings.corp_code")
        company_api = import_module("dart_fss.api.filings.company")
        market_api = import_module("dart_fss.api.market.stock_market")
    except ModuleNotFoundError as exc:
        raise _OpenDartLookupError(
            "dart-fss is not installed",
            retryable=False,
            kind="dependency_missing",
        ) from exc
    return auth, corp_code_api, company_api, market_api


def _bootstrap_dart_fss_namespace() -> None:
    package = sys.modules.get("dart_fss")
    if package is not None and getattr(package, "__path__", None):
        return

    spec = find_spec("dart_fss")
    if spec is None or spec.submodule_search_locations is None:
        raise _OpenDartLookupError(
            "dart-fss is not installed",
            retryable=False,
            kind="dependency_missing",
        )

    root = Path(list(spec.submodule_search_locations)[0])
    namespace = ModuleType("dart_fss")
    namespace.__file__ = str(root / "__init__.py")
    namespace.__path__ = [str(root)]
    sys.modules["dart_fss"] = namespace


def _configure_dart_fss(auth: Any, api_key: str) -> None:
    try:
        auth.set_api_key(api_key=api_key)
    except TypeError:
        auth.set_api_key(api_key)


def _opendart_error_from_exception(exc: Exception) -> _OpenDartLookupError:
    if isinstance(exc, _OpenDartLookupError):
        return exc
    if isinstance(exc, requests.Timeout):
        return _OpenDartLookupError(str(exc), retryable=True, kind="timeout")
    if isinstance(exc, requests.ConnectionError):
        return _OpenDartLookupError(
            str(exc),
            retryable=True,
            kind="connection_reset",
        )
    if isinstance(exc, requests.RequestException):
        return _OpenDartLookupError(
            str(exc),
            retryable=False,
            kind="http_error",
        )

    error_type = type(exc).__name__
    if error_type == "OverQueryLimit":
        reset_at = _next_quota_reset_at_kst().strftime("%Y-%m-%d %H:%M:%S %Z")
        return _OpenDartLookupError(
            f"{exc}. Quota resets at {reset_at}.",
            retryable=False,
            kind="daily_quota",
        )
    if error_type in {"TemporaryLocked", "ServiceClose"}:
        return _OpenDartLookupError(
            str(exc),
            retryable=True,
            kind="service_unavailable",
        )
    if error_type == "APIKeyError":
        return _OpenDartLookupError(
            str(exc),
            retryable=False,
            kind="invalid_api_key",
        )
    if error_type == "NoDataReceived":
        return _OpenDartLookupError(
            str(exc),
            retryable=False,
            kind="no_data",
        )
    if error_type == "ModuleNotFoundError":
        return _OpenDartLookupError(
            str(exc),
            retryable=False,
            kind="dependency_missing",
        )
    return _OpenDartLookupError(
        str(exc),
        retryable=False,
        kind="sdk_error",
    )
