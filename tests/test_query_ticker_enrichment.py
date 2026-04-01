"""Tests for query intent ticker enrichment merge and dry-resolve."""

from __future__ import annotations

from domain.company import CompanySurfaceResolution, resolve_company_surfaces
from domain.query_analysis import (
    QueryIntentPayload,
    _company_surfaces_fully_resolved,
    _merge_ticker_enrichment_payload,
)


def test_merge_ticker_enrichment_appends_tickers_and_canonical_names() -> None:
    payload = {
        "as_of_utc": "2026-01-01T00:00:00Z",
        "query_intent": {
            "company_names": ["플래닝랩스"],
            "tickers": [],
        },
        "domain_ids": ["dcf"],
        "entities": [],
        "units": [],
        "requirements": [],
        "intent_tags": [],
        "rationale": "x",
    }
    enrich = {
        "tickers": ["PL"],
        "canonical_company_names": ["Planet Labs PBC"],
        "rationale": "Korean phonetic / typo → Planet Labs US listing",
    }
    out = _merge_ticker_enrichment_payload(payload, enrich)
    qi = out["query_intent"]
    assert "PL" in qi["tickers"]
    assert any("Planet" in n for n in qi["company_names"])


def test_company_surfaces_fully_resolved_empty_names() -> None:
    raw = QueryIntentPayload(company_names=[], tickers=[])
    assert _company_surfaces_fully_resolved(raw, None) is True


def test_company_surfaces_fully_resolved_unknown_without_on_miss() -> None:
    raw = QueryIntentPayload(company_names=["TotallyUnknownXyz999"], tickers=[])
    assert _company_surfaces_fully_resolved(raw, None) is False


def test_resolve_company_surfaces_returns_unresolved() -> None:
    r = resolve_company_surfaces(
        company_names=("TotallyUnknownXyz999",),
        on_miss=None,
    )
    assert isinstance(r, CompanySurfaceResolution)
    assert r.subjects == ()
    assert r.unresolved_surface_forms == ("TotallyUnknownXyz999",)
