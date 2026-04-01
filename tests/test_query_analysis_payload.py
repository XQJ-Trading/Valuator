"""Regression tests for query analysis LLM payload normalization."""

from domain.query_analysis import QueryUnitPayload


def test_query_unit_resolves_period_tokens_against_as_of() -> None:
    u = QueryUnitPayload.model_validate(
        {
            "id": "u1",
            "objective": "x",
            "retrieval_query": "q",
            "domain_ids": ["any"],
            "entity_ids": [],
            "time_scope": "current",
            "target_start": "P-1Y",
            "target_end": "CURRENT_DATE",
        },
        context={"as_of_utc": "2026-03-31T00:00:00Z"},
    )
    assert u.target_start == "2025-03-31"
    assert u.target_end == "2026-03-31"


def test_query_unit_iso_dates_unaffected_by_context() -> None:
    u = QueryUnitPayload.model_validate(
        {
            "id": "u1",
            "objective": "x",
            "retrieval_query": "q",
            "domain_ids": ["any"],
            "entity_ids": [],
            "time_scope": "historical",
            "target_start": "2024-01-01",
            "target_end": "2024-12-31",
        },
    )
    assert u.target_start == "2024-01-01"
    assert u.target_end == "2024-12-31"
