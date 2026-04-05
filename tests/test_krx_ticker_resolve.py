from __future__ import annotations

import pytest

from domain.boundary.krx_ticker_resolve import (
    clear_cache,
    load_seeds,
    resolve_corp_code,
    resolve_seeds,
)


@pytest.fixture(autouse=True)
def _clear_krx_cache() -> None:
    clear_cache()
    yield
    clear_cache()


def test_load_seeds_preserves_corp_code() -> None:
    seeds = load_seeds()

    assert len(seeds) == 1
    assert seeds[0].listing.security_code == "319400"
    assert seeds[0].listing.corp_code == "01358463"


def test_resolve_corp_code_from_static_seed() -> None:
    assert resolve_corp_code("319400") == "01358463"
    assert resolve_corp_code("현대무벡스") == "01358463"


def test_resolve_corp_code_falls_back_to_remote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {
            "corp_code": "09999999",
            "corp_name": "테스트전자",
            "stock_code": "123456",
        }
    ]
    monkeypatch.setattr(
        "domain.boundary.krx_ticker_resolve.fetch_records",
        lambda **_: rows,
    )
    monkeypatch.setattr(
        "domain.boundary.krx_ticker_resolve._fetch_corp_cls",
        lambda corp_code, api_key: "Y",
    )
    monkeypatch.setattr(
        "domain.boundary.krx_ticker_resolve.get_opendart_api_key",
        lambda required=False: "test-key",
    )

    seeds = resolve_seeds("123456")

    assert len(seeds) == 1
    assert seeds[0].listing.exchange == "KOSPI"
    assert seeds[0].listing.corp_code == "09999999"
    assert resolve_corp_code("테스트전자") == "09999999"
