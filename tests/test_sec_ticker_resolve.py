"""Tests for SEC ticker boundary resolution (on_miss)."""

from __future__ import annotations

import pytest

from domain.boundary.sec_ticker_resolve import (
    clear_cache,
    resolve_seeds,
    seed_from_record,
    sec_on_miss,
)
from domain.company import resolve_subjects


@pytest.fixture(autouse=True)
def _clear_sec_cache() -> None:
    clear_cache()
    yield
    clear_cache()


def test_seed_from_record_builds_usa_listing() -> None:
    seed = seed_from_record(
        {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
    )
    assert seed is not None
    assert seed.listing.security_code == "AAPL"
    assert seed.listing.exchange == "USA"
    assert seed.listing.listing_id == "USA:AAPL"


def test_resolve_by_ticker(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"cik_str": "1", "ticker": "ABCD", "title": "Abcd Corp"},
    ]
    monkeypatch.setattr(
        "domain.boundary.sec_ticker_resolve.fetch_records",
        lambda **_: rows,
    )
    seeds = resolve_seeds("ABCD")
    assert len(seeds) == 1
    assert seeds[0].listing.security_code == "ABCD"


def test_resolve_by_ticker_class_share_dot(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"cik_str": "1", "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"},
    ]
    monkeypatch.setattr(
        "domain.boundary.sec_ticker_resolve.fetch_records",
        lambda **_: rows,
    )
    seeds = resolve_seeds("BRK.B")
    assert len(seeds) == 1
    assert seeds[0].listing.security_code == "BRK-B"


def test_exact_title_duplicate_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"cik_str": "1", "ticker": "A", "title": "Same Name Inc"},
        {"cik_str": "2", "ticker": "B", "title": "Same Name Inc"},
    ]
    monkeypatch.setattr(
        "domain.boundary.sec_ticker_resolve.fetch_records",
        lambda **_: rows,
    )
    assert resolve_seeds("Same Name Inc") == ()


def test_sec_on_miss_is_resolve_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"cik_str": "1", "ticker": "ZZ", "title": "Zz Corp"}]
    monkeypatch.setattr(
        "domain.boundary.sec_ticker_resolve.fetch_records",
        lambda **_: rows,
    )
    assert sec_on_miss("ZZ") == resolve_seeds("ZZ")


def test_resolve_subjects_uses_on_miss_for_unknown_ticker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {
            "cik_str": "999999",
            "ticker": "Q91UNIQ",
            "title": "Q91 Uniq Test Corp",
        },
    ]
    monkeypatch.setattr(
        "domain.boundary.sec_ticker_resolve.fetch_records",
        lambda **_: rows,
    )
    subjects = resolve_subjects(
        company_names=("Q91UNIQ",),
        on_miss=sec_on_miss,
    )
    assert len(subjects) == 1
    assert subjects[0].listing is not None
    assert subjects[0].listing.security_code == "Q91UNIQ"
