from __future__ import annotations

import pytest

from domain.boundary.opendart_financial import (
    clear_opendart_financial_cache,
    fetch_opendart_financial,
    resolve_corp_code,
)
from valuator.tools.opendart_financial_tool import OpenDartFinancialTool


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_opendart_financial_cache()
    yield
    clear_opendart_financial_cache()


def test_resolve_corp_code_by_stock_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "domain.boundary.opendart_financial.resolve_krx_corp_record",
        lambda _: {"stock_code": "005930", "corp_code": "00126380"},
    )

    assert resolve_corp_code("005930") == "00126380"


def test_resolve_corp_code_by_normalized_corp_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "domain.boundary.opendart_financial.resolve_krx_corp_record",
        lambda _: {"corp_name": "LS  ELECTRIC", "corp_code": "00811111"},
    )

    assert resolve_corp_code("ls electric") == "00811111"


def test_fetch_opendart_financial_maps_response_and_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, str]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "status": "000",
                "list": [
                    {"account_nm": "자산총계", "thstrm_amount": "1,000"},
                    {"account_nm": "부채총계", "thstrm_amount": "400"},
                    {"account_nm": "영업이익", "thstrm_amount": "120"},
                ],
            }

    def fake_get(url: str, *, params: dict[str, str], timeout: int) -> FakeResponse:
        calls.append(params)
        assert url.endswith("fnlttSinglAcntAll.json")
        assert timeout == 30
        return FakeResponse()

    monkeypatch.setattr(
        "domain.boundary.opendart_financial.get_opendart_api_key",
        lambda: "test-key",
    )
    monkeypatch.setattr("domain.boundary.opendart_financial.requests.get", fake_get)

    first = fetch_opendart_financial("00126380", 2024)
    second = fetch_opendart_financial("00126380", 2024)

    assert first == {
        "total_assets": 1000.0,
        "total_liabilities": 400.0,
        "operating_income": 120.0,
    }
    assert second == first
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_opendart_tool_falls_back_from_cfs_to_ofs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "valuator.tools.opendart_financial_tool.resolve_corp_code",
        lambda corp: "00126380",
    )

    def fake_fetch(corp_code: str, year: int, reprt_code: str = "11011", fs_div: str = "CFS"):
        calls.append(fs_div)
        if fs_div == "CFS":
            return None
        return {
            "total_assets": 1000.0,
            "total_liabilities": 400.0,
            "total_equity": 600.0,
            "current_assets": 300.0,
            "current_liabilities": 150.0,
            "operating_income": 120.0,
            "interest_expense": 30.0,
            "total_revenue": 500.0,
            "gross_profit": 200.0,
            "net_income": 90.0,
            "operating_cash_flow": 140.0,
            "capex": 50.0,
        }

    monkeypatch.setattr(
        "valuator.tools.opendart_financial_tool.fetch_opendart_financial",
        fake_fetch,
    )

    tool = OpenDartFinancialTool()
    result = await tool.execute(corp="005930", year=2024)

    assert result.success is True
    assert calls == ["CFS", "OFS"]
    assert result.metadata["source"] == "opendart"
    assert result.metadata["corp_code"] == "00126380"
    assert result.metadata["fs_div"] == "OFS"
    assert result.result["free_cash_flow"] == 90.0
    assert result.result["debt_to_equity"] == pytest.approx(400.0 / 600.0)
    assert result.result["current_ratio"] == 2.0
    assert result.result["interest_coverage"] == 4.0


@pytest.mark.asyncio
async def test_opendart_tool_returns_web_fallback_when_corp_code_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "valuator.tools.opendart_financial_tool.resolve_corp_code",
        lambda corp: None,
    )

    tool = OpenDartFinancialTool()
    result = await tool.execute(corp="없는회사", year=2024)

    assert result.success is False
    assert result.error == "Corp code not found: 없는회사"
    assert result.metadata["fallback"]["tool_name"] == "web_search_tool"


@pytest.mark.asyncio
async def test_opendart_tool_rejects_ticker_arg_without_corp() -> None:
    tool = OpenDartFinancialTool()

    result = await tool.execute(ticker="005930", year=2024)

    assert result.success is False
    assert result.error == "'corp' is required"
