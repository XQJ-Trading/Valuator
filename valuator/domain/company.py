from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
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


@dataclass(frozen=True, slots=True)
class Company:
    issuer_name: str
    security_code: str
    exchange: str
    listing_id: str
    vendor_symbols: dict[str, str]
    aliases: tuple[str, ...]

    @property
    def yahoo_symbol(self) -> str:
        return self.vendor_symbols.get("yahoo", self.security_code)

    @property
    def legacy_market(self) -> str:
        return legacy_market_for_exchange(self.exchange)


@dataclass(slots=True)
class _CompanyIndex:
    by_id: dict[str, Company] = field(default_factory=dict)
    by_name: dict[str, tuple[Company, ...]] = field(default_factory=dict)


def find_company(
    *,
    ticker: str = "",
    security_code: str = "",
    company_name: str = "",
) -> Company | None:
    normalized_ticker = ticker.strip().upper()
    normalized_security_code = security_code.strip().upper()
    normalized_company_name = company_name.strip()

    if not any((normalized_ticker, normalized_security_code, normalized_company_name)):
        return None

    index = _company_index()
    company = _company_from_identifiers(
        index,
        ticker=normalized_ticker,
        security_code=normalized_security_code,
    )

    if not normalized_company_name:
        if company is None:
            raise ValueError(
                f"unknown company: {normalized_security_code or normalized_ticker}"
            )
        return company

    candidates = index.by_name.get(_name_key(normalized_company_name), ())
    if not candidates:
        if company is not None:
            raise ValueError(
                f"identifier conflict: {normalized_security_code or normalized_ticker} != {normalized_company_name}"
            )
        raise ValueError(f"unknown company: {normalized_company_name}")

    if company is not None:
        if any(candidate.listing_id == company.listing_id for candidate in candidates):
            return company
        raise ValueError(
            f"identifier conflict: {normalized_security_code or normalized_ticker} != {normalized_company_name}"
        )

    if len(candidates) > 1:
        listing_ids = ", ".join(candidate.listing_id for candidate in candidates[:5])
        raise ValueError(f"ambiguous company: {normalized_company_name} ({listing_ids})")
    return candidates[0]


def legacy_market_for_exchange(exchange: str) -> str:
    value = exchange.strip().upper()
    if value in _KRX_MARKETS:
        return "KRX"
    if value in _US_MARKETS:
        return "USA"
    return value


def _company_from_identifiers(
    index: _CompanyIndex,
    *,
    ticker: str,
    security_code: str,
) -> Company | None:
    company: Company | None = None
    for identifier in (security_code, ticker):
        if not identifier:
            continue
        candidate = index.by_id.get(identifier)
        if candidate is None:
            raise ValueError(f"unknown company: {identifier}")
        if company is not None and candidate.listing_id != company.listing_id:
            raise ValueError(f"identifier conflict: {security_code or ticker}")
        company = candidate
    return company


@lru_cache(maxsize=1)
def _company_index() -> _CompanyIndex:
    index = _CompanyIndex()
    names: dict[str, list[Company]] = {}

    for company in _load_krx_companies():
        _add_company(index, names, company)
    for company in _load_sec_companies():
        _add_company(index, names, company)

    index.by_name = {
        key: tuple(companies)
        for key, companies in names.items()
    }
    return index


def _add_company(
    index: _CompanyIndex,
    names: dict[str, list[Company]],
    company: Company,
) -> None:
    _bind_identifier(index.by_id, company.security_code, company)
    _bind_identifier(index.by_id, company.listing_id, company)
    for symbol in company.vendor_symbols.values():
        _bind_identifier(index.by_id, symbol.strip().upper(), company)
    for alias in company.aliases:
        key = _name_key(alias)
        if not key:
            continue
        companies = names.setdefault(key, [])
        if any(existing.listing_id == company.listing_id for existing in companies):
            continue
        companies.append(company)


def _bind_identifier(store: dict[str, Company], identifier: str, company: Company) -> None:
    key = identifier.strip().upper()
    if not key:
        return
    existing = store.get(key)
    if existing is None:
        store[key] = company
        return
    if existing.listing_id != company.listing_id:
        raise ValueError(f"duplicate company identifier: {key}")


def _load_krx_companies() -> list[Company]:
    records = _load_json_records(KRX_SECURITIES_PATH)
    return [
        Company(
            issuer_name=str(record["issuer_name"]),
            security_code=str(record["security_code"]).strip().upper(),
            exchange=str(record["exchange"]).strip().upper(),
            listing_id=str(record["listing_id"]).strip().upper(),
            vendor_symbols={
                str(vendor): str(symbol).strip().upper()
                for vendor, symbol in dict(record["vendor_symbols"]).items()
                if str(symbol).strip()
            },
            aliases=tuple(
                dict.fromkeys(
                    str(alias).strip()
                    for alias in record["aliases"]
                    if str(alias).strip()
                )
            ),
        )
        for record in records
    ]


def _load_sec_companies() -> list[Company]:
    companies: list[Company] = []
    for record in _load_json_records(SEC_TICKERS_PATH):
        ticker = str(record.get("ticker") or "").strip().upper()
        title = str(record.get("title") or "").strip()
        if not ticker:
            continue
        aliases = _sec_aliases(title, ticker)
        issuer_name = _sec_issuer_name(title, aliases, ticker)
        companies.append(
            Company(
                issuer_name=issuer_name,
                security_code=ticker,
                exchange="USA",
                listing_id=f"USA:{ticker}",
                vendor_symbols={"yahoo": ticker},
                aliases=aliases,
            )
        )
    return companies


def _load_json_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [dict(record) for record in payload]


def _sec_aliases(title: str, ticker: str) -> tuple[str, ...]:
    aliases: list[str] = []
    for value in (title, ticker):
        if value:
            aliases.append(value.strip())

    words = _title_words(title)
    words = _trim_trailing_words(words, _SEC_PRIMARY_SUFFIXES)
    while words:
        aliases.append(" ".join(words))
        if words[-1] not in _SEC_SECONDARY_SUFFIXES:
            break
        words = words[:-1]

    return tuple(
        dict.fromkeys(alias for alias in aliases if alias)
    )


def _sec_issuer_name(title: str, aliases: tuple[str, ...], ticker: str) -> str:
    if title and not title.isupper():
        return title
    for alias in reversed(aliases):
        if alias == ticker:
            continue
        return _display_sec_name(alias)
    return title or ticker


def _display_sec_name(alias: str) -> str:
    if not alias.isupper():
        return alias
    words = alias.split()
    return " ".join(
        word if len(word) <= 4 else word.capitalize()
        for word in words
    )


def _title_words(text: str) -> list[str]:
    cleaned = "".join(
        char if char.isalnum() else " "
        for char in text.strip().upper()
    )
    return [word for word in cleaned.split() if word]


def _trim_trailing_words(words: list[str], suffixes: frozenset[str]) -> list[str]:
    trimmed = list(words)
    while trimmed and trimmed[-1] in suffixes:
        trimmed.pop()
    return trimmed


def _name_key(text: str) -> str:
    return "".join(char for char in text.strip().upper() if char.isalnum())
