"""OpenRouter model price cache (data/openrouter_model_prices.json)."""

import json

from valuator.models import openrouter as openrouter_module
from valuator.utils.llm_usage import MODEL_PRICES, get_model_price


def test_load_openrouter_price_cache_from_file(tmp_path, monkeypatch) -> None:
    key = "test/openrouter-cache-model"
    path = tmp_path / "openrouter_model_prices.json"
    path.write_text(
        json.dumps(
            {key: {"prompt_usd_per_1m": 1.0, "completion_usd_per_1m": 2.0}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(openrouter_module, "_openrouter_price_cache_path", lambda: path)
    count = openrouter_module._load_openrouter_price_cache()
    assert count == 1
    price = get_model_price(key)
    assert price is not None
    assert price.prompt_usd_per_1m == 1.0
    assert price.completion_usd_per_1m == 2.0
    MODEL_PRICES.pop(key, None)


def test_write_openrouter_price_cache_roundtrip(tmp_path, monkeypatch) -> None:
    key = "vendor/model-x"
    path = tmp_path / "openrouter_model_prices.json"
    monkeypatch.setattr(openrouter_module, "_openrouter_price_cache_path", lambda: path)
    body = {
        "data": [
            {
                "id": key,
                "pricing": {"prompt": "0.000001", "completion": "0.000002"},
            }
        ]
    }
    openrouter_module._write_openrouter_price_cache(body)
    assert path.is_file()
    monkeypatch.setattr(openrouter_module, "_openrouter_price_cache_path", lambda: path)
    assert openrouter_module._load_openrouter_price_cache() == 1
    p = get_model_price(key)
    assert p is not None
    assert abs(p.prompt_usd_per_1m - 1.0) < 1e-9
    MODEL_PRICES.pop(key, None)
