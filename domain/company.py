from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Iterable

if TYPE_CHECKING:
    from .boundary.types import ListingSeed

_KRX_MARKETS = frozenset({"KRX", "KOSPI", "KOSDAQ", "KONEX"})
_US_MARKETS = frozenset({"USA", "US", "NASDAQ", "NYSE", "AMEX"})


@dataclass(frozen=True, slots=True)
class Company:
    company_id: str
    company_name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Listing:
    listing_id: str
    company_id: str
    security_code: str
    exchange: str
    vendor_symbols: dict[str, str]
    corp_code: str = ""
    aliases: tuple[str, ...] = ()
    is_primary: bool = False

    @property
    def yahoo_symbol(self) -> str:
        return self.vendor_symbols.get("yahoo", self.security_code)

    @property
    def legacy_market(self) -> str:
        return market_for(self.exchange)


@dataclass(frozen=True, slots=True)
class Subject:
    company: Company
    listing: Listing | None = None


@dataclass(frozen=True, slots=True)
class CompanySurfaceResolution:
    """Result of resolving user-provided company/ticker surface strings."""

    subjects: tuple[Subject, ...]
    unresolved_surface_forms: tuple[str, ...]


def resolve_surfaces(
    *,
    company_names: tuple[str, ...],
    on_miss: Callable[[str], Iterable[ListingSeed]] | None = None,
) -> CompanySurfaceResolution:
    """Resolve surface strings without failing the whole batch on one miss."""
    from .company_index import index, resolve_surface

    surfaces = tuple(
        dict.fromkeys(name.strip() for name in company_names if name.strip())
    )
    if not surfaces:
        return CompanySurfaceResolution(subjects=(), unresolved_surface_forms=())

    company_index = index()
    resolved: list[Subject] = []
    failures: list[str] = []
    for surface in surfaces:
        try:
            resolved.append(resolve_surface(company_index, surface, on_miss=on_miss))
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
) -> tuple[Subject, ...]:
    ticker_code = ticker.strip().upper()
    security_id = security_code.strip().upper()
    surfaces = tuple(
        dict.fromkeys(name.strip() for name in company_names if name.strip())
    )
    if (
        not ticker_code
        and not security_id
        and not surfaces
    ):
        return ()

    from .company_index import index, resolve_identifier

    company_index = index()
    identifier_subjects = resolve_identifier(
        company_index,
        ticker=ticker_code,
        security_code=security_id,
    )
    if not surfaces:
        return merge_subjects(identifier_subjects, ())

    surface_resolution = resolve_surfaces(
        company_names=surfaces,
        on_miss=on_miss,
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
    from .company_index import listings_for_company as _listings_for_company

    return _listings_for_company(company_id)


def representative_listing(subject: Subject) -> Listing | None:
    if subject.listing is not None:
        return subject.listing
    from .company_index import main_listing

    return main_listing(subject.company.company_id)


def clear_cache() -> None:
    from .company_index import clear_cache as clear_index_cache

    clear_index_cache()


def market_for(exchange: str) -> str:
    value = exchange.strip().upper()
    if value in _KRX_MARKETS:
        return "KRX"
    if value in _US_MARKETS:
        return "USA"
    return value


def name_key(text: str) -> str:
    """Stable key for company/title matching."""
    return "".join(char for char in text.strip().upper() if char.isalnum())
