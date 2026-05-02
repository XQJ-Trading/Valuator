from __future__ import annotations

from types import SimpleNamespace

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


def _row(sj_div: str, account_id: str, account_nm: str, amount: str) -> dict[str, str]:
    return {
        "sj_div": sj_div,
        "account_id": account_id,
        "account_nm": account_nm,
        "thstrm_amount": amount,
    }


def _fake_response(rows: list[dict[str, str]]) -> object:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"status": "000", "list": rows}

    return FakeResponse()


def _patch_dart(monkeypatch: pytest.MonkeyPatch, response: object) -> None:
    monkeypatch.setattr(
        "domain.boundary.opendart_financial.get_opendart_api_key",
        lambda: "test-key",
    )
    monkeypatch.setattr(
        "domain.boundary.opendart_financial.requests.get",
        lambda *_, **__: response,
    )


def test_fetch_opendart_financial_maps_response_and_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, str]] = []

    response = _fake_response(
        [
            _row("BS", "ifrs-full_Assets", "자산총계", "1,000"),
            _row("BS", "ifrs-full_Liabilities", "부채총계", "400"),
            _row("CIS", "dart_OperatingIncomeLoss", "영업이익(손실)", "120"),
        ]
    )

    def fake_get(url: str, *, params: dict[str, str], timeout: int):
        calls.append(params)
        assert url.endswith("fnlttSinglAcntAll.json")
        assert timeout == 5
        return response

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


def test_fetch_opendart_financial_uses_account_id_regardless_of_korean_label_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 회사가 한글 표기를 어떻게 쓰든 account_id가 같으면 매핑된다 — alias 추격 종결.
    _patch_dart(
        monkeypatch,
        _fake_response(
            [_row("CIS", "dart_OperatingIncomeLoss", "Ⅴ. 영업이익 (영업손실)", "120")]
        ),
    )

    data, err = fetch_opendart_financial("00126380", 2024)

    assert err is None
    assert data == {"operating_income": 120.0}


def test_fetch_opendart_financial_filters_by_statement_to_avoid_sce_overwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 같은 account_id가 CIS·SCE에 모두 등장하면 SCE의 0이 마지막에 와도
    # CIS 값이 보존돼야 한다.
    _patch_dart(
        monkeypatch,
        _fake_response(
            [
                _row("CIS", "ifrs-full_ProfitLoss", "당기순이익(손실)", "1,000"),
                _row("SCE", "ifrs-full_ProfitLoss", "당기순이익(손실)", "0"),
            ]
        ),
    )

    data, err = fetch_opendart_financial("00126380", 2024)

    assert err is None
    assert data == {"net_income": 1000.0}


def test_fetch_opendart_financial_falls_back_to_account_nm_when_id_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # account_id가 `-표준계정코드 미사용-` sentinel이거나 회사 커스텀이면 nm으로 fallback.
    _patch_dart(
        monkeypatch,
        _fake_response(
            [
                _row("CF", "-표준계정코드 미사용-", "유형자산의취득", "500"),
                _row("CF", "entity00126380_CustomCapex", "유형자산의취득", "999"),
            ]
        ),
    )

    data, err = fetch_opendart_financial("00126380", 2024)

    assert err is None
    # 첫 매칭 우선: 본문 표가 부속 표보다 먼저 오는 DART 응답 관례를 반영한다.
    assert data == {"capex": 500.0}


def test_fetch_opendart_financial_surfaces_dart_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"status": "013", "message": "조회된 데이타가 없습니다."}

    _patch_dart(monkeypatch, FakeResponse())

    data, err = fetch_opendart_financial("00126380", 2024)

    assert data is None
    assert err is not None
    assert "조회된" in err


def test_fetch_opendart_financial_backfills_operating_income_from_gross_profit_and_sga(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 일부 보고서가 영업이익 라인 자체를 빠뜨리는 경우 매출총이익-판관비로 보강.
    _patch_dart(
        monkeypatch,
        _fake_response(
            [
                _row("CIS", "ifrs-full_GrossProfit", "매출총이익", "346,792,172,979"),
                _row(
                    "CIS",
                    "dart_TotalSellingGeneralAdministrativeExpenses",
                    "판매비와관리비",
                    "160,413,734,039",
                ),
                _row("CIS", "ifrs-full_Revenue", "수익(매출액)", "2,308,571,092,877"),
            ]
        ),
    )

    data, err = fetch_opendart_financial("00126380", 2023)

    assert err is None
    assert data is not None
    assert data["operating_income"] == 186_378_438_940.0


def test_fetch_opendart_financial_keeps_explicit_operating_income(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dart(
        monkeypatch,
        _fake_response(
            [
                _row("CIS", "dart_OperatingIncomeLoss", "영업이익", "100"),
                _row("CIS", "ifrs-full_GrossProfit", "매출총이익", "300"),
                _row(
                    "CIS",
                    "dart_TotalSellingGeneralAdministrativeExpenses",
                    "판매비와관리비",
                    "150",
                ),
            ]
        ),
    )

    data, err = fetch_opendart_financial("00126380", 2023)

    assert err is None
    assert data is not None
    assert data["operating_income"] == 100.0


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
async def test_opendart_tool_computes_per(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "valuator.tools.opendart_financial_tool.resolve_krx_corp_record",
        lambda corp: {
            "corp_code": "00126380",
            "stock_code": "079550",
            "corp_name": "LIG넥스원",
        },
    )
    monkeypatch.setattr(
        "valuator.tools.opendart_financial_tool.fetch_krx_daily_price_bar",
        lambda listing_id: SimpleNamespace(close_krw=941000),
    )

    def fake_fetch(*, corp_code: str, year: int, fs_div: str = "CFS"):
        return {
            "total_revenue": 500.0,
            "net_income": 80.0,
            "eps": 11604.0,
        }, None

    monkeypatch.setattr(
        "valuator.tools.opendart_financial_tool.fetch_opendart_financial",
        fake_fetch,
    )

    tool = OpenDartFinancialTool()
    result = await tool.execute(corp="079550", start_year=2025, end_year=2025)

    row = result.result["results"][0]
    assert row["per"] == pytest.approx(941000 / 11604)
    assert "trailing_per" not in row
    assert row["corp_name"] == "LIG넥스원"


@pytest.mark.asyncio
async def test_opendart_tool_preserves_raw_values_against_derived_recompute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 정책: raw가 우선이다. 응답에 ebitda/operating_margin/free_cash_flow 등이 이미
    # 들어와 있으면 compute_metrics가 표준 공식으로 덮어씌우면 안 된다.
    monkeypatch.setattr(
        "valuator.tools.opendart_financial_tool.resolve_krx_corp_record",
        lambda corp: {"corp_code": "00126380"},
    )

    def fake_fetch(*, corp_code: str, year: int, fs_div: str = "CFS"):
        return {
            "operating_income": 100.0,
            "depreciation": 10.0,
            "amortization": 5.0,
            "total_revenue": 1000.0,
            "operating_cash_flow": 200.0,
            "capex": 50.0,
            # raw로 보고된 값들 — 표준 공식과 일부러 다르게 둠
            "ebitda": 999.0,
            "operating_margin": 0.5,
            "free_cash_flow": 777.0,
        }, None

    monkeypatch.setattr(
        "valuator.tools.opendart_financial_tool.fetch_opendart_financial",
        fake_fetch,
    )

    tool = OpenDartFinancialTool()
    result = await tool.execute(corp="005930", start_year=2024, end_year=2024)

    assert result.success is True
    row = result.result["results"][0]
    assert row["ebitda"] == 999.0
    assert row["operating_margin"] == 0.5
    assert row["free_cash_flow"] == 777.0


@pytest.mark.asyncio
async def test_opendart_tool_does_not_return_web_fallback_when_corp_code_missing(
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
    assert "fallback" not in result.metadata


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
