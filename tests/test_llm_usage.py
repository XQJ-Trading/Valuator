from __future__ import annotations

from types import SimpleNamespace

import pytest

from valuator.utils import llm_usage as llm_usage_module
from valuator.utils.llm_usage import LLMUsage, TokenUsage, get_model_price


def test_token_usage_from_raw_splits_cached_prompt_and_thoughts() -> None:
    usage = TokenUsage.from_raw(
        {
            "prompt_token_count": 100,
            "cached_content_token_count": 80,
            "candidates_token_count": 7,
            "thoughts_token_count": 3,
            "total_token_count": 110,
        }
    )

    assert usage.prompt_tokens == 100
    assert usage.cached_prompt_tokens == 80
    assert usage.uncached_prompt_tokens == 20
    assert usage.completion_tokens == 7
    assert usage.thought_tokens == 3
    assert usage.output_tokens == 10
    assert usage.total_tokens == 110


def test_explicit_cache_request_cost_uses_only_uncached_prompt_tokens() -> None:
    row = LLMUsage.from_call(
        method="gemini.generate",
        model="gemini-3-flash-preview",
        usage=TokenUsage(
            prompt_tokens=100,
            cached_prompt_tokens=80,
            completion_tokens=7,
            thought_tokens=3,
            total_tokens=110,
        ),
        latency_ms=12.5,
        started_at="2026-04-17T00:00:00Z",
        cache_source="explicit",
    )

    details = row.cost_breakdown()

    assert details["billable_prompt_tokens"] == 20.0
    assert details["billable_output_tokens"] == 10.0
    assert details["prompt_cost_usd"] == pytest.approx(0.00001)
    assert details["output_cost_usd"] == pytest.approx(0.00003)
    assert row.cost_usd() == pytest.approx(0.00004)


def test_gemini_31_flash_uses_text_pricing_without_changing_gemini_3() -> None:
    gemini_3 = get_model_price("gemini-3-flash-preview")
    gemini_31 = get_model_price("gemini-3.1-flash")

    assert gemini_3 is not None
    assert gemini_3.prompt_usd_per_1m == pytest.approx(0.50)
    assert gemini_3.completion_usd_per_1m == pytest.approx(3.00)

    assert gemini_31 is not None
    assert gemini_31.prompt_usd_per_1m == pytest.approx(0.25)
    assert gemini_31.completion_usd_per_1m == pytest.approx(1.50)
    assert gemini_31.cache_write_usd_per_1m == pytest.approx(0.025)
    assert gemini_31.cache_storage_usd_per_1m_hour == pytest.approx(1.00)


def test_explicit_cache_create_cost_includes_write_and_storage() -> None:
    row = LLMUsage.from_call(
        method="gemini.cache.create",
        model="gemini-3-flash-preview",
        usage=TokenUsage(cache_write_tokens=500_000),
        latency_ms=40.0,
        started_at="2026-04-17T00:00:00Z",
        cache_source="explicit",
        cache_storage_hours=2.0,
    )

    details = row.cost_breakdown()

    assert details["cache_write_cost_usd"] == pytest.approx(0.025)
    assert details["cache_storage_cost_usd"] == pytest.approx(1.0)
    assert row.cost_usd() == pytest.approx(1.025)


def test_implicit_cache_cost_mode_observe_only_keeps_full_prompt_bill() -> None:
    original = llm_usage_module.config
    try:
        llm_usage_module.config = SimpleNamespace(
            gemini_implicit_cache_cost_mode="observe_only"
        )
        row = LLMUsage.from_call(
            method="gemini.generate",
            model="gemini-3-flash-preview",
            usage=TokenUsage(prompt_tokens=100, cached_prompt_tokens=80),
            latency_ms=12.5,
            started_at="2026-04-17T00:00:00Z",
            cache_source="implicit",
        )

        assert row.cost_breakdown()["billable_prompt_tokens"] == 100.0
    finally:
        llm_usage_module.config = original


def test_implicit_cache_cost_mode_bill_uncached_only_discounts_cached_prefix() -> None:
    original = llm_usage_module.config
    try:
        llm_usage_module.config = SimpleNamespace(
            gemini_implicit_cache_cost_mode="bill_uncached_only"
        )
        row = LLMUsage.from_call(
            method="gemini.generate",
            model="gemini-3-flash-preview",
            usage=TokenUsage(prompt_tokens=100, cached_prompt_tokens=80),
            latency_ms=12.5,
            started_at="2026-04-17T00:00:00Z",
            cache_source="implicit",
        )

        assert row.cost_breakdown()["billable_prompt_tokens"] == 20.0
    finally:
        llm_usage_module.config = original
