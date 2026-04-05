from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from valuator.tools.opendart_tool import OpenDartTool


class FakeFrame:
    def __init__(self, records):
        self.records = records

    def to_dict(self, orient="records"):
        assert orient == "records"
        return list(self.records)


class FakeReader:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.finstate_all_calls: list[tuple[str, int | None, str, str]] = []
        self.list_calls: list[tuple[str, dict[str, str]]] = []

    def finstate_all(self, corp_code, year, reprt_code="11011", fs_div="CFS"):
        self.finstate_all_calls.append((corp_code, year, reprt_code, fs_div))
        if fs_div == "CFS":
            return FakeFrame([])
        return FakeFrame(
            [
                {
                    "account_id": "ifrs-full_Revenue",
                    "account_nm": "매출액",
                    "thstrm_amount": "1,000",
                },
                {
                    "account_id": "dart_OperatingIncomeLoss",
                    "account_nm": "영업이익",
                    "thstrm_amount": "100",
                },
                {
                    "account_id": "ifrs-full_ProfitLoss",
                    "account_nm": "당기순이익",
                    "thstrm_amount": "80",
                },
                {
                    "account_id": "ifrs-full_Assets",
                    "account_nm": "자산총계",
                    "thstrm_amount": "5,000",
                },
                {
                    "account_id": "ifrs-full_Liabilities",
                    "account_nm": "부채총계",
                    "thstrm_amount": "2,000",
                },
                {
                    "account_id": "ifrs-full_Equity",
                    "account_nm": "자본총계",
                    "thstrm_amount": "3,000",
                },
            ]
        )

    def list(self, corp_code, **kwargs):
        self.list_calls.append((corp_code, kwargs))
        return FakeFrame(
            [
                {"rcept_dt": "20240131", "report_nm": "사업보고서"},
                {"rcept_dt": "20240515", "report_nm": "분기보고서"},
            ]
        )


def _patch_reader(monkeypatch: pytest.MonkeyPatch) -> list[FakeReader]:
    created: list[FakeReader] = []

    def factory(api_key: str) -> FakeReader:
        reader = FakeReader(api_key)
        created.append(reader)
        return reader

    monkeypatch.setattr(
        "valuator.tools.opendart_tool.importlib.import_module",
        lambda name: SimpleNamespace(OpenDartReader=factory),
    )
    monkeypatch.setattr(
        "valuator.tools.opendart_tool.get_opendart_api_key",
        lambda required=False: "api-key",
    )
    monkeypatch.setattr(
        "valuator.tools.opendart_tool.resolve_corp_code",
        lambda corp: "01358463",
    )
    return created


@pytest.mark.asyncio
async def test_opendart_tool_financial_statement_uses_ofs_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _patch_reader(monkeypatch)
    tool = OpenDartTool()

    result = await tool.execute(corp="현대무벡스", year=2024)

    assert result.success is True
    assert result.result["corp_code"] == "01358463"
    assert result.result["fs_div"] == "OFS"
    assert result.result["summary"]["revenue"] == 1000
    assert result.result["summary"]["total_equity"] == 3000
    assert result.metadata["row_count"] == 6
    assert created[0].finstate_all_calls == [
        ("01358463", 2024, "11011", "CFS"),
        ("01358463", 2024, "11011", "OFS"),
    ]


@pytest.mark.asyncio
async def test_opendart_tool_disclosure_list_accepts_optional_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _patch_reader(monkeypatch)
    tool = OpenDartTool()

    result = await tool.execute(
        corp="현대무벡스",
        data_type="disclosure_list",
        year=2024,
    )

    assert result.success is True
    assert result.result["count"] == 2
    assert created[0].list_calls == [
        ("01358463", {"start": "2024-01-01", "end": "2024-12-31"})
    ]


@pytest.mark.asyncio
async def test_opendart_tool_requires_year_for_financial_statement() -> None:
    tool = OpenDartTool()

    result = await tool.execute(corp="현대무벡스")

    assert result.success is False
    assert "year" in (result.error or "")


@pytest.mark.asyncio
async def test_opendart_tool_rejects_company_info_data_type() -> None:
    tool = OpenDartTool()

    result = await tool.execute(corp="현대무벡스", data_type="company_info")

    assert result.success is False
    assert "financial_statement" in (result.error or "")
    assert "disclosure_list" in (result.error or "")


@pytest.mark.asyncio
async def test_opendart_tool_dependency_error_includes_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "valuator.tools.opendart_tool.importlib.import_module",
        lambda name: (_ for _ in ()).throw(ImportError("No module named 'OpenDartReader'")),
    )
    monkeypatch.setattr(
        "valuator.tools.opendart_tool.get_opendart_api_key",
        lambda required=False: "api-key",
    )
    monkeypatch.setattr(
        "valuator.tools.opendart_tool.resolve_corp_code",
        lambda corp: "01358463",
    )

    tool = OpenDartTool()
    result = await tool.execute(corp="현대무벡스", year=2024)

    assert result.success is False
    assert "OpenDartReader dependency is unavailable" in (result.error or "")
    assert "Install `opendartreader`" in (result.error or "")
    assert sys.executable in (result.error or "")
