from __future__ import annotations

import pytest

from domain.boundary.opendart_financial import (
    clear_opendart_financial_cache,
    fetch_opendart_financial,
)
from valuator.tools.opendart_financial_tool import OpenDartFinancialTool


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_opendart_financial_cache()
    yield
    clear_opendart_financial_cache()


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
        assert timeout == 5
        return FakeResponse()

    monkeypatch.setattr(
        "domain.boundary.opendart_financial.get_opendart_api_key",
        lambda: "test-key",
    )
    monkeypatch.setattr("domain.boundary.opendart_financial.requests.get", fake_get)

    first, first_err = fetch_opendart_financial("00126380", 2024)
    second, second_err = fetch_opendart_financial("00126380", 2024)

    assert first == {
        "total_assets": 1000.0,
        "total_liabilities": 400.0,
        "operating_income": 120.0,
    }
    assert first_err is None
    assert second == first
    assert second_err is None
    assert len(calls) == 1


def test_fetch_opendart_financial_surfaces_dart_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"status": "013", "message": "조회된 데이타가 없습니다."}

    monkeypatch.setattr(
        "domain.boundary.opendart_financial.get_opendart_api_key",
        lambda: "test-key",
    )
    monkeypatch.setattr(
        "domain.boundary.opendart_financial.requests.get",
        lambda *_, **__: FakeResponse(),
    )

    data, err = fetch_opendart_financial("00126380", 2024)

    assert data is None
    assert err is not None
    assert "조회된" in err


@pytest.mark.asyncio
async def test_opendart_tool_falls_back_from_cfs_to_ofs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, str]] = []

    monkeypatch.setattr(
        "valuator.tools.opendart_financial_tool.resolve_krx_corp_record",
        lambda corp: {"corp_code": "00126380"},
    )

    def fake_fetch_with_error(*, corp_code: str, year: int, fs_div: str = "CFS"):
        calls.append((year, fs_div))
        if fs_div == "CFS":
            return None, "no CFS rows"
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
        }, None

    monkeypatch.setattr(
        "valuator.tools.opendart_financial_tool.fetch_opendart_financial",
        fake_fetch_with_error,
    )

    tool = OpenDartFinancialTool()
    result = await tool.execute(corp="005930", start_year=2024, end_year=2024)

    assert result.success is True
    assert calls == [(2024, "CFS"), (2024, "OFS")]
    assert result.metadata["source"] == "opendart"
    assert result.metadata["corp_code"] == "00126380"
    assert result.metadata["fs_divs"] == ["OFS"]
    assert result.result["year_range"] == "2024"
    rows = result.result["results"]
    assert len(rows) == 1
    row = rows[0]
    assert row["year"] == 2024
    assert row["free_cash_flow"] == 90.0
    assert row["debt_to_equity"] == pytest.approx(400.0 / 600.0)
    assert row["current_ratio"] == 2.0
    assert row["interest_coverage"] == 4.0


@pytest.mark.asyncio
async def test_opendart_tool_aggregates_multi_year_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "valuator.tools.opendart_financial_tool.resolve_krx_corp_record",
        lambda corp: {"corp_code": "00126380"},
    )

    def fake_fetch(*, corp_code: str, year: int, fs_div: str = "CFS"):
        return {
            "total_assets": 1000.0 + year,
            "total_equity": 600.0,
            "operating_income": 100.0,
            "total_revenue": 500.0,
            "net_income": 80.0,
        }, None

    monkeypatch.setattr(
        "valuator.tools.opendart_financial_tool.fetch_opendart_financial",
        fake_fetch,
    )

    tool = OpenDartFinancialTool()
    result = await tool.execute(corp="삼성전자", start_year=2022, end_year=2024)

    assert result.success is True
    assert result.result["year_range"] == "2022-2024"
    rows = result.result["results"]
    assert [row["year"] for row in rows] == [2022, 2023, 2024]
    assert rows[0]["total_assets"] == 3022.0
    assert result.result["missing_years"] == []


@pytest.mark.asyncio
async def test_opendart_tool_returns_web_fallback_when_corp_code_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "valuator.tools.opendart_financial_tool.resolve_krx_corp_record",
        lambda corp: None,
    )

    tool = OpenDartFinancialTool()
    result = await tool.execute(corp="없는회사", start_year=2024, end_year=2024)

    assert result.success is False
    assert result.error == "Corp code not found: 없는회사"
    assert result.metadata["fallback"]["tool_name"] == "web_search_tool"


@pytest.mark.asyncio
async def test_opendart_tool_requires_corp() -> None:
    tool = OpenDartFinancialTool()

    result = await tool.execute(ticker="005930", start_year=2024, end_year=2024)

    assert result.success is False
    assert result.error == "'corp' is required"


@pytest.mark.asyncio
async def test_opendart_tool_requires_year_range() -> None:
    tool = OpenDartFinancialTool()

    result = await tool.execute(corp="005930")

    assert result.success is False
    assert "start_year" in result.error and "end_year" in result.error
