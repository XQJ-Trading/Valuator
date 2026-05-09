from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from functools import lru_cache
from datetime import date
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable

from valuator.utils.hangul_fuzzy_key import jamo_fuzzy_key


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
KRX_SECURITIES_PATH = DATA_DIR / "krx_securities.json"
SEC_TICKERS_PATH = DATA_DIR / "sec_company_tickers.json"

_KRX_MARKETS = frozenset({"KRX", "KOSPI", "KOSDAQ", "KONEX"})
_US_MARKETS = frozenset({"USA", "US", "NASDAQ", "NYSE", "AMEX"})
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
_FUZZY_NAME_THRESHOLD = 0.7

if TYPE_CHECKING:
    from domain.price_bar import DailyPriceBar


@dataclass(frozen=True, slots=True)
class ReferenceStockPrice:
    """기준 주가 — 온톨로지 `stock_price`(KRW 종가)와 동일 시점·종목."""

    krw: int
    as_of: date
    listing_id: str


@dataclass(frozen=True, slots=True)
class Company:
    company_id: str
    company_name: str
    aliases: tuple[str, ...]
    reference_stock_price: ReferenceStockPrice | None = None

    @property
    def baseline_stock_price_krw(self) -> int | None:
        """기준 주가(KRW). 수집 전이면 None."""
        if self.reference_stock_price is None:
            return None
        return self.reference_stock_price.krw


@dataclass(frozen=True, slots=True)
class Listing:
    listing_id: str
    company_id: str
    security_code: str
    exchange: str
    vendor_symbols: dict[str, str]
    aliases: tuple[str, ...] = ()
    is_primary: bool = False

    @property
    def yahoo_symbol(self) -> str:
        return self.vendor_symbols.get("yahoo", self.security_code)

    @property
    def market(self) -> str:
        return market_for_exchange(self.exchange)


class SubjectRole(str, Enum):
    PRIMARY = "primary"
    PEER = "peer"


@dataclass(frozen=True, slots=True)
class Subject:
    company: Company
    listing: Listing | None = None
    role: SubjectRole = SubjectRole.PRIMARY


@dataclass(frozen=True, slots=True)
class ListingSeed:
    company_id: str
    company_name: str
    company_aliases: tuple[str, ...]
    listing: Listing


@dataclass(frozen=True, slots=True)
class CompanySurfaceResolution:
    """Result of resolving user-provided company/ticker surface strings."""

    subjects: tuple[Subject, ...]
    unresolved_surface_forms: tuple[str, ...]


@dataclass(slots=True)
class _EntityIndex:
    companies_by_id: dict[str, Company] = field(default_factory=dict)
    companies_by_name: dict[str, tuple[Company, ...]] = field(default_factory=dict)
    listings_by_id: dict[str, Listing] = field(default_factory=dict)
    listings_by_identifier: dict[str, Listing] = field(default_factory=dict)
    listings_by_company_id: dict[str, tuple[Listing, ...]] = field(default_factory=dict)


def resolve_company_surfaces(
    *,
    company_names: tuple[str, ...],
    on_miss: Callable[[str], Iterable[ListingSeed]] | None = None,
    role: SubjectRole = SubjectRole.PRIMARY,
) -> CompanySurfaceResolution:
    """Resolve surface strings without failing the whole batch on one miss."""
    normalized = tuple(
        dict.fromkeys(name.strip() for name in company_names if name.strip())
    )
    if not normalized:
        return CompanySurfaceResolution(subjects=(), unresolved_surface_forms=())

    index = _entity_index()
    resolved: list[Subject] = []
    failures: list[str] = []
    for surface in normalized:
        try:
            subject = _subject_from_surface_form(index, surface, on_miss=on_miss)
            resolved.append(replace(subject, role=role))
        except ValueError:
            failures.append(surface)

    return CompanySurfaceResolution(
        subjects=merge_subjects(tuple(resolved)),
        unresolved_surface_forms=tuple(failures),
    )


def resolve_subjects(
    *,
    ticker: str = "",
    security_code: str = "",
    company_names: tuple[str, ...] = (),
    on_miss: Callable[[str], Iterable[ListingSeed]] | None = None,
    role: SubjectRole = SubjectRole.PRIMARY,
) -> tuple[Subject, ...]:
    normalized_ticker = ticker.strip().upper()
    normalized_security_code = security_code.strip().upper()
    normalized_company_names = tuple(
        dict.fromkeys(name.strip() for name in company_names if name.strip())
    )
    if (
        not normalized_ticker
        and not normalized_security_code
        and not normalized_company_names
    ):
        return ()

    index = _entity_index()
    identifier_subjects = tuple(
        replace(subject, role=role)
        for subject in _resolve_identifier_subject(
            index,
            ticker=normalized_ticker,
            security_code=normalized_security_code,
        )
    )
    if not normalized_company_names:
        return merge_subjects(identifier_subjects, ())

    surface_resolution = resolve_company_surfaces(
        company_names=normalized_company_names,
        on_miss=on_miss,
        role=role,
    )
    if (
        not identifier_subjects
        and not surface_resolution.subjects
        and surface_resolution.unresolved_surface_forms
    ):
        raise ValueError(
            f"unknown company: {surface_resolution.unresolved_surface_forms[0]}"
        )

    return merge_subjects(identifier_subjects, surface_resolution.subjects)


def merge_subjects(*groups: Iterable[Subject]) -> tuple[Subject, ...]:
    merged: list[Subject] = []
    for group in groups:
        for subject in group:
            if subject.listing is not None:
                if any(
                    existing.listing is not None
                    and existing.listing.listing_id == subject.listing.listing_id
                    for existing in merged
                ):
                    continue
                merged = [
                    existing
                    for existing in merged
                    if existing.company.company_id != subject.company.company_id
                    or existing.listing is not None
                ]
                merged.append(subject)
                continue
            if any(
                existing.company.company_id == subject.company.company_id
                for existing in merged
            ):
                continue
            merged.append(subject)
    return tuple(merged)


def listings_for_company(company_id: str) -> tuple[Listing, ...]:
    return _entity_index().listings_by_company_id.get(company_id, ())


def representative_listing(subject: Subject) -> Listing | None:
    if subject.listing is not None:
        return subject.listing
    return _representative_listing_for_company(subject.company.company_id)


def market_for_exchange(exchange: str) -> str:
    value = exchange.strip().upper()
    if value in _KRX_MARKETS:
        return "KRX"
    if value in _US_MARKETS:
        return "USA"
    return value


def _resolve_identifier_subject(
    index: _EntityIndex,
    *,
    ticker: str,
    security_code: str,
) -> tuple[Subject, ...]:
    listing: Listing | None = None
    for identifier in (security_code, ticker):
        if not identifier:
            continue
        candidate = index.listings_by_identifier.get(identifier)
        if candidate is None:
            raise ValueError(f"unknown company: {identifier}")
        if listing is not None and candidate.listing_id != listing.listing_id:
            raise ValueError(f"identifier conflict: {security_code or ticker}")
        listing = candidate
    if listing is None:
        return ()
    return (_subject_for_listing(index, listing),)


def _subject_from_surface_form(
    index: _EntityIndex,
    surface_form: str,
    *,
    on_miss: Callable[[str], Iterable[ListingSeed]] | None = None,
) -> Subject:
    identifier = surface_form.strip().upper()
    listing = index.listings_by_identifier.get(identifier)
    if listing is not None:
        return _subject_for_listing(index, listing)

    company = _company_from_name(index, surface_form)
    if company is None and on_miss is not None:
        seeds = tuple(on_miss(surface_form))
        if seeds:
            _ingest_seeds(index, seeds)
            return _subject_from_surface_form(index, surface_form)
    if company is None:
        raise ValueError(f"unknown company: {surface_form}")
    return Subject(company=company)


def _subject_for_listing(index: _EntityIndex, listing: Listing) -> Subject:
    company = index.companies_by_id[listing.company_id]
    return Subject(company=company, listing=listing)


def _company_from_name(
    index: _EntityIndex,
    company_name: str,
) -> Company | None:
    key = _name_key(company_name)
    if not key:
        return None

    candidates = index.companies_by_name.get(key, ())
    if candidates:
        return _single_company(company_name, candidates)

    return _fuzzy_company_by_name(index, company_name)


def _fuzzy_company_by_name(
    index: _EntityIndex,
    company_name: str,
) -> Company | None:
    query_key = jamo_fuzzy_key(company_name)
    if not query_key:
        return None
    best_score = 0.0
    best_matches: dict[str, Company] = {}

    for candidate_key, candidates in index.companies_by_name.items():
        ck = jamo_fuzzy_key(candidate_key)
        if not ck:
            continue
        score = SequenceMatcher(None, query_key, ck).ratio()
        if score < _FUZZY_NAME_THRESHOLD:
            continue
        if score > best_score:
            best_score = score
            best_matches = {candidate.company_id: candidate for candidate in candidates}
            continue
        if score == best_score:
            for candidate in candidates:
                best_matches[candidate.company_id] = candidate

    if not best_matches:
        return None

    return _single_company(company_name, tuple(best_matches.values()))


def _single_company(
    company_name: str,
    candidates: tuple[Company, ...],
) -> Company:
    if len(candidates) == 1:
        return candidates[0]
    raise _ambiguous_company_error(company_name, candidates)


def _ambiguous_company_error(
    company_name: str,
    candidates: tuple[Company, ...],
) -> ValueError:
    company_ids = ", ".join(
        list(dict.fromkeys(candidate.company_id for candidate in candidates))[:5]
    )
    return ValueError(f"ambiguous company: {company_name} ({company_ids})")


def _representative_listing_for_company(company_id: str) -> Listing | None:
    listings = listings_for_company(company_id)
    if len(listings) == 1:
        return listings[0]
    primary_listings = [listing for listing in listings if listing.is_primary]
    if len(primary_listings) == 1:
        return primary_listings[0]
    return None


@lru_cache(maxsize=1)
def _entity_index() -> _EntityIndex:
    index = _EntityIndex()
    name_index: dict[str, list[Company]] = {}
    company_seeds: dict[str, list[ListingSeed]] = {}

    for seed in (*_load_krx_listing_seeds(), *_load_sec_listing_seeds()):
        _bind_listing(index, seed.listing)
        company_seeds.setdefault(seed.company_id, []).append(seed)

    for company_id, seeds in company_seeds.items():
        listings = tuple(seed.listing for seed in seeds)
        company = Company(
            company_id=company_id,
            company_name=seeds[0].company_name,
            aliases=_company_aliases_from_seeds(seeds),
        )
        index.companies_by_id[company_id] = company
        index.listings_by_company_id[company_id] = listings
        _bind_company(name_index, company)

    index.companies_by_name = {
        key: tuple(companies) for key, companies in name_index.items()
    }
    return index


def _bind_listing(index: _EntityIndex, listing: Listing) -> None:
    _bind_listing_unique(index.listings_by_id, listing.listing_id, listing)
    for identifier in (
        listing.security_code,
        listing.listing_id,
        *listing.vendor_symbols.values(),
    ):
        _bind_listing_unique(index.listings_by_identifier, identifier, listing)


def _bind_listing_unique(
    store: dict[str, Listing],
    identifier: str,
    listing: Listing,
) -> None:
    key = identifier.strip().upper()
    if not key:
        return
    existing = store.get(key)
    if existing is None:
        store[key] = listing
        return
    if existing.listing_id != listing.listing_id:
        raise ValueError(f"duplicate listing identifier: {key}")


def _bind_company(
    store: dict[str, list[Company]],
    company: Company,
) -> None:
    for alias in company.aliases:
        key = _name_key(alias)
        if not key:
            continue
        companies = store.setdefault(key, [])
        if any(existing.company_id == company.company_id for existing in companies):
            continue
        companies.append(company)


def _ingest_seeds(
    index: _EntityIndex,
    seeds: Iterable[ListingSeed],
) -> None:
    company_groups: dict[str, list[ListingSeed]] = {}
    for seed in seeds:
        _bind_listing(index, seed.listing)
        company_groups.setdefault(seed.company_id, []).append(seed)

    for company_id, group in company_groups.items():
        existing_company = index.companies_by_id.get(company_id)
        if existing_company is None:
            company_name = group[0].company_name
            aliases = _company_aliases_from_seeds(group)
        else:
            company_name = existing_company.company_name
            aliases = tuple(
                dict.fromkeys(
                    alias
                    for alias in (
                        existing_company.company_name,
                        *existing_company.aliases,
                        *_company_aliases_from_seeds(group),
                    )
                    if alias
                )
            )
        index.companies_by_id[company_id] = Company(
            company_id=company_id,
            company_name=company_name,
            aliases=aliases,
        )
        index.listings_by_company_id[company_id] = _merge_company_listings(
            index.listings_by_company_id.get(company_id, ()),
            [seed.listing for seed in group],
        )

    _rebuild_company_name_index(index)


def _rebuild_company_name_index(index: _EntityIndex) -> None:
    name_index: dict[str, list[Company]] = {}
    for company in index.companies_by_id.values():
        _bind_company(name_index, company)
    index.companies_by_name = {
        key: tuple(companies) for key, companies in name_index.items()
    }


def _merge_company_listings(
    existing: tuple[Listing, ...],
    incoming: list[Listing],
) -> tuple[Listing, ...]:
    listings_by_id = {listing.listing_id: listing for listing in existing}
    for listing in incoming:
        listings_by_id[listing.listing_id] = listing
    return tuple(listings_by_id.values())


def _company_aliases_from_seeds(seeds: list[ListingSeed]) -> tuple[str, ...]:
    aliases: list[str] = []
    for seed in seeds:
        aliases.append(seed.company_name)
        aliases.extend(seed.company_aliases)
    return tuple(dict.fromkeys(alias for alias in aliases if alias))


def _load_krx_listing_seeds() -> list[ListingSeed]:
    records = _load_json_records(KRX_SECURITIES_PATH)
    seeds: list[ListingSeed] = []
    for record in records:
        company_name = str(record["issuer_name"]).strip()
        security_code = str(record["security_code"]).strip().upper()
        exchange = str(record["exchange"]).strip().upper()
        listing_id = str(record["listing_id"]).strip().upper()
        vendor_symbols = {
            str(vendor): str(symbol).strip().upper()
            for vendor, symbol in dict(record["vendor_symbols"]).items()
            if str(symbol).strip()
        }
        company_aliases = tuple(
            dict.fromkeys(
                alias
                for alias in (
                    company_name,
                    *(str(item).strip() for item in record["aliases"]),
                )
                if alias
            )
        )
        listing = Listing(
            listing_id=listing_id,
            company_id=listing_id,
            security_code=security_code,
            exchange=exchange,
            vendor_symbols=vendor_symbols,
        )
        seeds.append(
            ListingSeed(
                company_id=listing.company_id,
                company_name=company_name,
                company_aliases=company_aliases,
                listing=listing,
            )
        )
    return seeds


def listing_seed_from_sec_record(record: dict[str, Any]) -> ListingSeed | None:
    """Boundary: build a US listing seed from a SEC company_tickers.json row."""
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


def _load_sec_listing_seeds() -> list[ListingSeed]:
    seeds: list[ListingSeed] = []
    for record in _load_json_records(SEC_TICKERS_PATH):
        seed = listing_seed_from_sec_record(dict(record))
        if seed is not None:
            seeds.append(seed)
    return seeds


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


def _name_key(text: str) -> str:
    return "".join(char for char in text.strip().upper() if char.isalnum())


def normalized_name_key(text: str) -> str:
    """Stable key for company/title matching (shared with SEC resolve boundary)."""
    return _name_key(text)


def company_with_reference_from_daily_bar(
    company: Company, bar: DailyPriceBar
) -> Company:
    """DailyPriceBar 종가·시점을 company.reference_stock_price(기준 주가)로 붙인다."""
    return replace(company, reference_stock_price=bar.as_reference_stock_price())
