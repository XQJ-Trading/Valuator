from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from typing import TYPE_CHECKING, Callable, Iterable

from .company import Company, Listing, Subject, name_key

if TYPE_CHECKING:
    from .boundary.types import ListingSeed

_FUZZY_NAME_THRESHOLD = 0.7


@dataclass(slots=True)
class _EntityIndex:
    companies_by_id: dict[str, Company] = field(default_factory=dict)
    companies_by_name: dict[str, tuple[Company, ...]] = field(default_factory=dict)
    listings_by_id: dict[str, Listing] = field(default_factory=dict)
    listings_by_identifier: dict[str, Listing] = field(default_factory=dict)
    listings_by_company_id: dict[str, tuple[Listing, ...]] = field(default_factory=dict)


def clear_cache() -> None:
    index.cache_clear()


def listings_for_company(company_id: str) -> tuple[Listing, ...]:
    return index().listings_by_company_id.get(company_id, ())


def main_listing(company_id: str) -> Listing | None:
    listings = listings_for_company(company_id)
    if len(listings) == 1:
        return listings[0]
    primary_listings = [listing for listing in listings if listing.is_primary]
    if len(primary_listings) == 1:
        return primary_listings[0]
    return None


def resolve_identifier(
    company_index: _EntityIndex,
    *,
    ticker: str,
    security_code: str,
) -> tuple[Subject, ...]:
    listing: Listing | None = None
    for identifier in (security_code, ticker):
        if not identifier:
            continue
        candidate = company_index.listings_by_identifier.get(identifier)
        if candidate is None:
            raise ValueError(f"unknown company: {identifier}")
        if listing is not None and candidate.listing_id != listing.listing_id:
            raise ValueError(f"identifier conflict: {security_code or ticker}")
        listing = candidate
    if listing is None:
        return ()
    return (_subject_for_listing(company_index, listing),)


def resolve_surface(
    company_index: _EntityIndex,
    surface_form: str,
    *,
    on_miss: Callable[[str], Iterable["ListingSeed"]] | None = None,
) -> Subject:
    identifier = surface_form.strip().upper()
    listing = company_index.listings_by_identifier.get(identifier)
    if listing is not None:
        return _subject_for_listing(company_index, listing)

    company = _company_from_name(company_index, surface_form)
    if company is None and on_miss is not None:
        seeds = tuple(on_miss(surface_form))
        if seeds:
            ingest_seeds(company_index, seeds)
            return resolve_surface(company_index, surface_form)
    if company is None:
        raise ValueError(f"unknown company: {surface_form}")
    return Subject(company=company)


@lru_cache(maxsize=1)
def index() -> _EntityIndex:
    from .boundary.krx_ticker_resolve import load_seeds as load_krx_seeds
    from .boundary.sec_ticker_resolve import load_seeds as load_sec_seeds

    company_index = _EntityIndex()
    name_index: dict[str, list[Company]] = {}
    company_seeds: dict[str, list[ListingSeed]] = {}

    for seed in (*load_krx_seeds(), *load_sec_seeds()):
        _bind_listing(company_index, seed.listing)
        company_seeds.setdefault(seed.company_id, []).append(seed)

    for company_id, seeds in company_seeds.items():
        listings = tuple(seed.listing for seed in seeds)
        company = Company(
            company_id=company_id,
            company_name=seeds[0].company_name,
            aliases=_company_aliases_from_seeds(seeds),
        )
        company_index.companies_by_id[company_id] = company
        company_index.listings_by_company_id[company_id] = listings
        _bind_company(name_index, company)

    company_index.companies_by_name = {
        key: tuple(companies) for key, companies in name_index.items()
    }
    return company_index


def ingest_seeds(
    company_index: _EntityIndex,
    seeds: Iterable["ListingSeed"],
) -> None:
    company_groups: dict[str, list[ListingSeed]] = {}
    for seed in seeds:
        _bind_listing(company_index, seed.listing)
        company_groups.setdefault(seed.company_id, []).append(seed)

    for company_id, group in company_groups.items():
        existing_company = company_index.companies_by_id.get(company_id)
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
        company_index.companies_by_id[company_id] = Company(
            company_id=company_id,
            company_name=company_name,
            aliases=aliases,
        )
        company_index.listings_by_company_id[company_id] = _merge_company_listings(
            company_index.listings_by_company_id.get(company_id, ()),
            [seed.listing for seed in group],
        )

    _rebuild_company_name_index(company_index)


def _subject_for_listing(index: _EntityIndex, listing: Listing) -> Subject:
    company = index.companies_by_id[listing.company_id]
    return Subject(company=company, listing=listing)


def _company_from_name(index: _EntityIndex, company_name: str) -> Company | None:
    key = name_key(company_name)
    if not key:
        return None

    candidates = index.companies_by_name.get(key, ())
    if candidates:
        return _single_company(company_name, candidates)

    return _fuzzy_company_by_name(index, key, company_name)


def _fuzzy_company_by_name(
    index: _EntityIndex,
    name_key: str,
    company_name: str,
) -> Company | None:
    best_score = 0.0
    best_matches: dict[str, Company] = {}

    for candidate_key, candidates in index.companies_by_name.items():
        score = SequenceMatcher(None, name_key, candidate_key).ratio()
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
        key = name_key(alias)
        if not key:
            continue
        companies = store.setdefault(key, [])
        if any(existing.company_id == company.company_id for existing in companies):
            continue
        companies.append(company)


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


def _company_aliases_from_seeds(seeds: list["ListingSeed"]) -> tuple[str, ...]:
    aliases: list[str] = []
    for seed in seeds:
        aliases.append(seed.company_name)
        aliases.extend(seed.company_aliases)
    return tuple(dict.fromkeys(alias for alias in aliases if alias))
