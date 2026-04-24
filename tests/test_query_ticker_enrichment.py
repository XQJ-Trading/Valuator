"""Tests for query intent ticker enrichment merge and dry-resolve."""

from __future__ import annotations

from domain.company import CompanySurfaceResolution, resolve_company_surfaces
from domain.boundary.query_analysis_payload import (
    QueryIntentPayload,
    _build_query_analysis,
    _company_surfaces_fully_resolved,
    _merge_ticker_enrichment_payload,
)


def test_merge_ticker_enrichment_appends_tickers_and_canonical_names() -> None:
    payload = {
        "as_of_kst": "2026-01-01 09:00:00",
        "query_intent": {
            "company_names": ["플래닝랩스"],
            "tickers": [],
        },
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


def test_build_query_analysis_preserves_entity_kinds() -> None:
    analysis = _build_query_analysis(
        {
            "query_intent": {
                "company_names": [],
                "tickers": [],
            },
            "entities": [
                {
                    "id": "industry_shipbuilding",
                    "label": "조선업",
                    "kind": "theme",
                },
                {
                    "id": "company_peer",
                    "label": "HD현대중공업",
                    "kind": "company",
                },
            ],
            "units": [
                {
                    "id": "u0",
                    "objective": "industry position",
                    "retrieval_query": "한화오션 조선업 점유율",
                    "entity_ids": ["industry_shipbuilding", "company_peer"],
                    "time_scope": "현재",
                }
            ],
            "requirements": [
                {
                    "acceptance": "경쟁 구도와 수주 경쟁력이 포함되어야 함",
                    "unit_ids": ["u0"],
                    "entity_ids": ["industry_shipbuilding", "company_peer"],
                    "provenance": "market_research",
                }
            ],
            "intent_tags": [],
            "rationale": "x",
        },
        query="한화오션 분석해줘",
        on_miss=None,
    )
    assert analysis.entity_kinds == {
        "industry_shipbuilding": "theme",
        "company_peer": "company",
    }
