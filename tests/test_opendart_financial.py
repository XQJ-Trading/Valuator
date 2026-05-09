from __future__ import annotations

import pytest

from datetime import date

from domain.boundary.krx_stock_price_collector import MarketView
from domain.boundary.opendart_financial import (
    FetchOutcome,
    YearFinancials,
    clear_opendart_financial_cache,
    fetch_opendart_report,
    fetch_opendart_year,
)
from valuator.tools.opendart_financial_tool import OpenDartFinancialTool


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_opendart_financial_cache()
    yield
    clear_opendart_financial_cache()


def _row(
    sj_div: str,
    account_id: str,
    account_nm: str,
    thstrm: str,
    *,
    frmtrm: str | None = None,
    bfefrmtrm: str | None = None,
    rcept_no: str = "20250317000990",
) -> dict[str, str]:
    return {
        "rcept_no": rcept_no,
        "sj_div": sj_div,
        "account_id": account_id,
        "account_nm": account_nm,
        "thstrm_amount": thstrm,
        "frmtrm_amount": thstrm if frmtrm is None else frmtrm,
        "bfefrmtrm_amount": "" if bfefrmtrm is None else bfefrmtrm,
    }


def _fake_response(
    rows: list[dict[str, str]],
    *,
    status: str = "000",
    message: str | None = None,
) -> object:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            body: dict[str, object] = {"status": status, "list": rows}
            if message is not None:
                body["message"] = message
            return body

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


def _patch_dart_by_year(
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[int, object],
    calls: list[dict[str, str]] | None = None,
) -> None:
    def fake_get(url: str, *, params: dict[str, str], timeout: int):
        if calls is not None:
            calls.append(params)
        assert url.endswith("fnlttSinglAcntAll.json")
        assert timeout == 5
        return responses[int(params["bsns_year"])]

    monkeypatch.setattr(
        "domain.boundary.opendart_financial.get_opendart_api_key",
        lambda: "test-key",
    )
    monkeypatch.setattr("domain.boundary.opendart_financial.requests.get", fake_get)


def test_fetch_opendart_report_maps_response_and_caches(
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
    _patch_dart_by_year(monkeypatch, {2024: response}, calls)

    first, first_outcome, first_err = fetch_opendart_report("00126380", 2024)
    second, second_outcome, second_err = fetch_opendart_report("00126380", 2024)

    assert first is not None
    assert first.thstrm == {
        "total_assets": 1000.0,
        "total_liabilities": 400.0,
        "operating_income": 120.0,
    }
    assert first.rcept_no == "20250317000990"
    assert first_outcome is FetchOutcome.OK
    assert first_err is None
    assert second == first
    assert second_outcome is FetchOutcome.OK
    assert second_err is None
    assert len(calls) == 1


def test_fetch_opendart_report_uses_account_id_regardless_of_korean_label_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 회사가 한글 표기를 어떻게 쓰든 account_id가 같으면 매핑된다 — alias 추격 종결.
    _patch_dart(
        monkeypatch,
        _fake_response(
            [_row("CIS", "dart_OperatingIncomeLoss", "Ⅴ. 영업이익 (영업손실)", "120")]
        ),
    )

    report, outcome, err = fetch_opendart_report("00126380", 2024)

    assert outcome is FetchOutcome.OK
    assert err is None
    assert report is not None
    assert report.thstrm == {"operating_income": 120.0}


def test_fetch_opendart_report_maps_income_statement_eps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dart(
        monkeypatch,
        _fake_response(
            [
                _row(
                    "IS",
                    "ifrs-full_BasicEarningsLossPerShare",
                    "기본주당이익",
                    "6,605",
                )
            ]
        ),
    )

    report, outcome, err = fetch_opendart_report("00126380", 2025)

    assert outcome is FetchOutcome.OK
    assert err is None
    assert report is not None
    assert report.thstrm == {"eps": 6605.0}


def test_fetch_opendart_report_filters_by_statement_to_avoid_sce_overwrite(
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

    report, outcome, err = fetch_opendart_report("00126380", 2024)

    assert outcome is FetchOutcome.OK
    assert err is None
    assert report is not None
    assert report.thstrm == {"net_income": 1000.0}


def test_fetch_opendart_report_falls_back_to_account_nm_when_id_missing(
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

    report, outcome, err = fetch_opendart_report("00126380", 2024)

    assert outcome is FetchOutcome.OK
    assert err is None
    assert report is not None
    # 첫 매칭 우선: 본문 표가 부속 표보다 먼저 오는 DART 응답 관례를 반영한다.
    assert report.thstrm == {"capex": 500.0}


def test_fetch_opendart_report_surfaces_not_filed_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dart(
        monkeypatch,
        _fake_response([], status="013", message="조회된 데이타가 없습니다."),
    )

    report, outcome, err = fetch_opendart_report("00126380", 2024)

    assert report is None
    assert outcome is FetchOutcome.NOT_FILED
    assert err is not None
    assert "조회된" in err


def test_fetch_opendart_report_backfills_operating_income_from_gross_profit_and_sga(
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

    report, outcome, err = fetch_opendart_report("00126380", 2023)

    assert outcome is FetchOutcome.OK
    assert err is None
    assert report is not None
    assert report.thstrm["operating_income"] == 186_378_438_940.0


def test_fetch_opendart_report_keeps_explicit_operating_income(
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

    report, outcome, err = fetch_opendart_report("00126380", 2023)

    assert outcome is FetchOutcome.OK
    assert err is None
    assert report is not None
    assert report.thstrm["operating_income"] == 100.0


def test_fetch_opendart_year_prefers_next_year_frmtrm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_2024 = _fake_response(
        [
            _row(
                "CIS",
                "ifrs-full_Revenue",
                "매출액",
                "9,359,000,000,000",
                frmtrm="7,889,686,804,711",
            ),
            _row(
                "CIS",
                "dart_OperatingIncomeLoss",
                "영업이익",
                "800,000,000,000",
                frmtrm="594,306,103,916",
            ),
        ]
    )
    _patch_dart_by_year(monkeypatch, {2024: response_2024})

    financials, err = fetch_opendart_year("00126380", 2023)

    assert err is None
    assert financials is not None
    assert financials.values["total_revenue"] == 7_889_686_804_711.0
    assert financials.values["operating_income"] == 594_306_103_916.0
    assert financials.restated is True
    assert financials.source_rcept_no == "20250317000990"
    assert financials.source_bsns_year == 2024


def test_fetch_opendart_year_falls_back_to_current_thstrm_when_next_not_filed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dart_by_year(
        monkeypatch,
        {
            2024: _fake_response([], status="013", message="조회된 데이타가 없습니다."),
            2023: _fake_response(
                [
                    _row(
                        "CIS",
                        "ifrs-full_Revenue",
                        "매출액",
                        "9,359,000,000,000",
                        rcept_no="20240318000990",
                    )
                ]
            ),
        },
    )

    financials, err = fetch_opendart_year("00126380", 2023)

    assert err is None
    assert financials is not None
    assert financials.values["total_revenue"] == 9_359_000_000_000.0
    assert financials.restated is False
    assert financials.source_rcept_no == "20240318000990"
    assert financials.source_bsns_year == 2023


def test_fetch_opendart_year_keeps_sparse_frmtrm_none_without_current_year_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dart_by_year(
        monkeypatch,
        {
            2024: _fake_response(
                [
                    _row(
                        "CIS",
                        "ifrs-full_Revenue",
                        "매출액",
                        "9,359,000,000,000",
                        frmtrm="-",
                    )
                ]
            ),
            2023: _fake_response(
                [
                    _row(
                        "CIS",
                        "ifrs-full_Revenue",
                        "매출액",
                        "9,359,000,000,000",
                        rcept_no="20240318000990",
                    )
                ]
            ),
        },
    )

    financials, err = fetch_opendart_year("00126380", 2023)

    assert err is None
    assert financials is not None
    assert financials.values["total_revenue"] is None
    assert financials.restated is True
    assert financials.source_rcept_no == "20250317000990"


def test_fetch_opendart_year_propagates_next_year_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            raise RuntimeError("HTTP 500")

    _patch_dart_by_year(
        monkeypatch,
        {
            2024: FakeResponse(),
            2023: _fake_response(
                [_row("CIS", "ifrs-full_Revenue", "매출액", "9,359,000,000,000")]
            ),
        },
    )

    with pytest.raises(RuntimeError, match="HTTP 500"):
        fetch_opendart_year("00126380", 2023)


def test_fetch_opendart_year_report_cache_dedups_shared_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, str]] = []
    _patch_dart_by_year(
        monkeypatch,
        {
            2024: _fake_response([], status="013", message="조회된 데이타가 없습니다."),
            2023: _fake_response(
                [
                    _row(
                        "CIS",
                        "ifrs-full_Revenue",
                        "매출액",
                        "9,359,000,000,000",
                        frmtrm="8,100,000,000,000",
                        rcept_no="20240318000990",
                    )
                ]
            ),
        },
        calls,
    )

    first, first_err = fetch_opendart_year("00126380", 2022)
    second, second_err = fetch_opendart_year("00126380", 2023)

    assert first_err is None
    assert second_err is None
    assert first is not None and second is not None
    assert first.values["total_revenue"] == 8_100_000_000_000.0
    assert second.values["total_revenue"] == 9_359_000_000_000.0
    assert [call["bsns_year"] for call in calls] == ["2023", "2024"]


def test_fetch_opendart_report_fails_fast_on_mixed_rcept_no(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dart(
        monkeypatch,
        _fake_response(
            [
                _row("CIS", "ifrs-full_Revenue", "매출액", "100", rcept_no="A"),
                _row("CIS", "dart_OperatingIncomeLoss", "영업이익", "10", rcept_no="B"),
            ]
        ),
    )

    with pytest.raises(ValueError, match="mixed rcept_no"):
        fetch_opendart_report("00126380", 2024)


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
        return (
            YearFinancials(
                values={
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
                },
                source_rcept_no="20250317000990",
                source_bsns_year=2025,
                fs_div="OFS",
                restated=True,
            ),
            None,
        )

    monkeypatch.setattr(
        "valuator.tools.opendart_financial_tool.fetch_opendart_year",
        fake_fetch_with_error,
    )

    tool = OpenDartFinancialTool()
    result = await tool.execute(corp="005930", start_year=2024, end_year=2024)

    assert result.success is True
    assert calls == [(2024, "CFS"), (2024, "OFS")]
    assert result.metadata["source"] == "opendart"
    assert result.metadata["corp_code"] == "00126380"
    assert result.metadata["fs_divs"] == ["OFS"]
    assert result.metadata["sources"] == [
        {
            "year": 2024,
            "rcept_no": "20250317000990",
            "restated": True,
            "fs_div": "OFS",
        }
    ]
    assert result.result["year_range"] == "2024"
    rows = result.result["results"]
    assert len(rows) == 1
    row = rows[0]
    assert row["year"] == 2024
    assert row["restated"] is True
    assert row["source_rcept_no"] == "20250317000990"
    assert row["source_bsns_year"] == 2025
    assert row["fs_div"] == "OFS"
    assert row["free_cash_flow"] == 90.0
    assert row["debt_to_equity"] == pytest.approx(400.0 / 600.0)
    assert row["current_ratio"] == 2.0
    assert row["interest_coverage"] == 4.0
    assert "source_rcept_no=20250317000990" in row["findings"]


@pytest.mark.asyncio
async def test_opendart_tool_aggregates_multi_year_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "valuator.tools.opendart_financial_tool.resolve_krx_corp_record",
        lambda corp: {"corp_code": "00126380"},
    )

    def fake_fetch(*, corp_code: str, year: int, fs_div: str = "CFS"):
        return (
            YearFinancials(
                values={
                    "total_assets": 1000.0 + year,
                    "total_equity": 600.0,
                    "operating_income": 100.0,
                    "total_revenue": 500.0,
                    "net_income": 80.0,
                },
                source_rcept_no=f"rcept-{year + 1}",
                source_bsns_year=year + 1,
                fs_div=fs_div,
                restated=True,
            ),
            None,
        )

    monkeypatch.setattr(
        "valuator.tools.opendart_financial_tool.fetch_opendart_year",
        fake_fetch,
    )

    tool = OpenDartFinancialTool()
    result = await tool.execute(corp="삼성전자", start_year=2022, end_year=2024)

    assert result.success is True
    assert result.result["year_range"] == "2022-2024"
    rows = result.result["results"]
    assert [row["year"] for row in rows] == [2022, 2023, 2024]
    assert rows[0]["total_assets"] == 3022.0
    assert rows[0]["restated"] is True
    assert result.result["missing_years"] == []
    assert result.metadata["sources"][0] == {
        "year": 2022,
        "rcept_no": "rcept-2023",
        "restated": True,
        "fs_div": "CFS",
    }


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
        "valuator.tools.opendart_financial_tool.fetch_krx_market_view",
        lambda listing_id: MarketView(
            listing_id="KRX:079550",
            as_of=date(2026, 5, 7),
            stock_price=950000,
            pbr=2.5,
        ),
    )
    monkeypatch.setattr(
        "valuator.tools.opendart_financial_tool.fetch_krx_year_end_market_view",
        lambda listing_id, year: MarketView(
            listing_id="KRX:079550",
            as_of=date(2025, 12, 30),
            stock_price=941000,
        ),
    )

    def fake_fetch(*, corp_code: str, year: int, fs_div: str = "CFS"):
        return (
            YearFinancials(
                values={
                    "total_revenue": 500.0,
                    "net_income": 116_040_000.0,
                    "total_equity": 3_200_000_000.0,
                    "eps": 11604.0,
                },
                source_rcept_no="20260317000990",
                source_bsns_year=2026,
                fs_div=fs_div,
                restated=True,
            ),
            None,
        )

    monkeypatch.setattr(
        "valuator.tools.opendart_financial_tool.fetch_opendart_year",
        fake_fetch,
    )

    tool = OpenDartFinancialTool()
    result = await tool.execute(corp="079550", start_year=2025, end_year=2025)

    row = result.result["results"][0]
    assert row["per"] == pytest.approx(941000 / 11604)
    assert row["pbr"] == pytest.approx(941000 / 320000)
    assert row["bps"] == pytest.approx(320000)
    assert row["shares_outstanding"] == pytest.approx(10000)
    assert row["stock_price"] == 941000
    assert row["stock_price_as_of"] == "2025-12-30"
    assert "trailing_per" not in row
    assert "current_price" not in row
    assert row["corp_name"] == "LIG넥스원"
    assert result.result["market_snapshot"]["current_price"] == 950000


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
        return (
            YearFinancials(
                values={
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
                },
                source_rcept_no="20250317000990",
                source_bsns_year=2025,
                fs_div=fs_div,
                restated=True,
            ),
            None,
        )

    monkeypatch.setattr(
        "valuator.tools.opendart_financial_tool.fetch_opendart_year",
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
