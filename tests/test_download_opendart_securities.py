from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import scripts.download_opendart_securities as opendart_script
import scripts.refresh_opendart_snapshot as snapshot_refresh
import valuator.infra.opendart_client as opendart_client


def _corp(
    *,
    stock_code: str = "012330",
    corp_code: str = "00164779",
    corp_name: str = "현대모비스",
    corp_cls: str = "Y",
) -> SimpleNamespace:
    return SimpleNamespace(
        stock_code=stock_code,
        corp_code=corp_code,
        corp_name=corp_name,
        corp_cls=corp_cls,
    )


def _corp_list(*corps: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(corps=list(corps))


def _listed_company(
    *,
    stock_code: str = "012330",
    corp_code: str = "00164779",
    corp_name: str = "현대모비스",
    stock_name: str = "현대모비스",
    corp_cls: str = "Y",
) -> opendart_client._OpenDartListedCompany:
    return opendart_client._OpenDartListedCompany(
        stock_code=stock_code,
        corp_code=corp_code,
        corp_name=corp_name,
        stock_name=stock_name,
        corp_cls=corp_cls,
        exchange=opendart_client.OPENDART_EXCHANGE_BY_CORP_CLS[corp_cls],
    )


def _snapshot_company(
    *,
    stock_code: str = "012330",
    corp_code: str = "00164779",
    corp_name: str = "현대모비스",
    corp_name_eng: str = "Hyundai Mobis",
    stock_name: str = "현대모비스",
    corp_cls: str = "Y",
) -> opendart_client._OpenDartSnapshotCompany:
    return opendart_client._OpenDartSnapshotCompany(
        stock_code=stock_code,
        corp_code=corp_code,
        corp_name=corp_name,
        corp_name_eng=corp_name_eng,
        stock_name=stock_name,
        corp_cls=corp_cls,
        exchange=opendart_client.OPENDART_EXCHANGE_BY_CORP_CLS[corp_cls],
    )


def _company_info(
    *,
    corp_code: str = "00164779",
    corp_name: str = "현대모비스주식회사",
    corp_eng_name: str = "Hyundai Mobis",
    stock_name: str = "현대모비스",
) -> dict[str, str]:
    return {
        "corp_code": corp_code,
        "corp_name": corp_name,
        "corp_eng_name": corp_eng_name,
        "stock_name": stock_name,
    }


class OverQueryLimit(RuntimeError):
    pass


class OpenDartBoundaryTests(unittest.TestCase):
    def test_listed_companies_from_corp_list_maps_exchange_and_filters_e(self) -> None:
        companies = opendart_client._listed_companies_from_corp_list(
            _corp_list(
                _corp(),
                _corp(
                    stock_code="005930",
                    corp_code="00126380",
                    corp_name="삼성전자",
                    corp_cls="K",
                ),
                _corp(
                    stock_code="152550",
                    corp_code="00849940",
                    corp_name="한국ANKOR유전",
                    corp_cls="N",
                ),
                _corp(
                    stock_code="999999",
                    corp_code="00000001",
                    corp_name="제외대상",
                    corp_cls="E",
                ),
            )
        )

        self.assertEqual(set(companies), {"012330", "005930", "152550"})
        self.assertEqual(companies["012330"].exchange, "KOSPI")
        self.assertEqual(companies["005930"].exchange, "KOSDAQ")
        self.assertEqual(companies["152550"].exchange, "KONEX")

    def test_opendart_error_from_exception_surfaces_daily_quota_reset(self) -> None:
        error = opendart_client._opendart_error_from_exception(
            OverQueryLimit("요청 제한을 초과하였습니다.")
        )

        self.assertEqual(error.kind, "daily_quota")
        self.assertIn("Quota resets at", str(error))

    def test_write_and_load_snapshot_round_trip(self) -> None:
        companies = {
            "012330": _snapshot_company(),
            "005930": _snapshot_company(
                stock_code="005930",
                corp_code="00126380",
                corp_name="삼성전자주식회사",
                corp_name_eng="Samsung Electronics",
                stock_name="삼성전자",
            ),
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_path = Path(tmpdir) / "opendart_companies.json.gz"
            opendart_client._write_snapshot(snapshot_path, companies)
            loaded = opendart_client._load_snapshot(snapshot_path)

        self.assertEqual(loaded["005930"], companies["005930"])

    def test_sync_opendart_companies_keeps_unchanged_snapshot_without_detail_fetch(
        self,
    ) -> None:
        live_companies = {"012330": _listed_company()}

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            opendart_client,
            "_fetch_opendart_listed_companies",
            return_value=live_companies,
        ), patch.object(
            opendart_client,
            "_fetch_opendart_company_info",
        ) as fetch_company_info:
            snapshot_path = Path(tmpdir) / "opendart_companies.json.gz"
            opendart_client._write_snapshot(
                snapshot_path,
                {"012330": _snapshot_company()},
            )

            companies = opendart_client._sync_opendart_companies(
                "key",
                snapshot_path=snapshot_path,
            )

        self.assertEqual(companies["012330"].corp_name_eng, "Hyundai Mobis")
        fetch_company_info.assert_not_called()

    def test_sync_opendart_companies_fetches_details_only_for_changed_company(
        self,
    ) -> None:
        live_companies = {
            "012330": _listed_company(),
            "005930": _listed_company(
                stock_code="005930",
                corp_code="00126380",
                corp_name="삼성전자주식회사",
                stock_name="삼성전자주식회사",
                corp_cls="K",
            ),
        }

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            opendart_client,
            "_fetch_opendart_listed_companies",
            return_value=live_companies,
        ), patch.object(
            opendart_client,
            "_fetch_opendart_company_info",
            return_value=_company_info(
                corp_code="00126380",
                corp_name="삼성전자주식회사",
                corp_eng_name="Samsung Electronics",
                stock_name="삼성전자",
            ),
        ) as fetch_company_info:
            snapshot_path = Path(tmpdir) / "opendart_companies.json.gz"
            opendart_client._write_snapshot(
                snapshot_path,
                {
                    "012330": _snapshot_company(),
                    "005930": _snapshot_company(
                        stock_code="005930",
                        corp_code="00126380",
                        corp_name="삼성전자",
                        corp_name_eng="Samsung Electronics",
                        stock_name="삼성전자",
                        corp_cls="K",
                    ),
                },
            )

            companies = opendart_client._sync_opendart_companies(
                "key",
                snapshot_path=snapshot_path,
            )

        self.assertEqual(companies["005930"].corp_name, "삼성전자주식회사")
        self.assertEqual(companies["005930"].stock_name, "삼성전자")
        fetch_company_info.assert_called_once_with("key", "00126380")

    def test_sync_all_companies_writes_compatible_krx_securities_json(self) -> None:
        companies = {
            "012330": _snapshot_company(corp_name="현대모비스주식회사"),
        }

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            opendart_client,
            "_sync_opendart_companies",
            return_value=companies,
        ):
            snapshot_path = Path(tmpdir) / "opendart_companies.json.gz"
            output_path = Path(tmpdir) / "krx_securities.json"

            seeds = opendart_client.sync_all_companies(
                "key",
                snapshot_path=snapshot_path,
                output_path=output_path,
            )

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            loaded_snapshot = opendart_client._load_snapshot(snapshot_path)

        self.assertEqual(len(seeds), 1)
        self.assertEqual(payload[0]["issuer_name"], "현대모비스")
        self.assertEqual(
            payload[0]["aliases"],
            ["현대모비스", "현대모비스주식회사", "Hyundai Mobis"],
        )
        self.assertEqual(payload[0]["corp_code"], "00164779")
        self.assertEqual(loaded_snapshot, companies)

    def test_lookup_company_returns_snapshot_match_without_network(self) -> None:
        companies = {"012330": _snapshot_company()}

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            opendart_client,
            "_fetch_opendart_listed_companies",
        ) as fetch_listed_companies:
            snapshot_path = Path(tmpdir) / "opendart_companies.json.gz"
            opendart_client._write_snapshot(snapshot_path, companies)

            seeds = opendart_client.lookup_company(
                "key",
                "현대모비스",
                snapshot_path=snapshot_path,
            )

        self.assertEqual(len(seeds), 1)
        self.assertEqual(seeds[0].company_name, "현대모비스")
        self.assertEqual(seeds[0].listing.security_code, "012330")
        fetch_listed_companies.assert_not_called()

    def test_lookup_company_fetches_live_match_for_same_day_empty_snapshot(self) -> None:
        live_companies = {
            "319400": _listed_company(
                stock_code="319400",
                corp_code="01415110",
                corp_name="현대무벡스",
                stock_name="현대무벡스",
            )
        }

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            opendart_client,
            "_fetch_opendart_listed_companies",
            return_value=live_companies,
        ) as fetch_listed_companies, patch.object(
            opendart_client,
            "_fetch_opendart_company_info",
            return_value=_company_info(
                corp_code="01415110",
                corp_name="현대무벡스",
                corp_eng_name="Hyundai Movex",
                stock_name="현대무벡스",
            ),
        ):
            snapshot_path = Path(tmpdir) / "opendart_companies.json.gz"
            output_path = Path(tmpdir) / "krx_securities.json"
            opendart_client._write_snapshot(snapshot_path, {})

            seeds = opendart_client.lookup_company(
                "key",
                "현대무벡스",
                snapshot_path=snapshot_path,
                output_path=output_path,
            )

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            loaded_snapshot = opendart_client._load_snapshot(snapshot_path)

        self.assertEqual(len(seeds), 1)
        self.assertEqual(seeds[0].listing.security_code, "319400")
        self.assertEqual(payload[0]["security_code"], "319400")
        self.assertIn("319400", loaded_snapshot)
        fetch_listed_companies.assert_called_once_with("key")

    def test_lookup_company_fetches_live_match_for_same_day_miss(self) -> None:
        live_companies = {
            "192650": _listed_company(
                stock_code="192650",
                corp_code="01063041",
                corp_name="드림텍주식회사",
                stock_name="드림텍",
            )
        }

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            opendart_client,
            "_fetch_opendart_listed_companies",
            return_value=live_companies,
        ), patch.object(
            opendart_client,
            "_fetch_opendart_company_info",
            return_value=_company_info(
                corp_code="01063041",
                corp_name="드림텍주식회사",
                corp_eng_name="Dreamtech",
                stock_name="드림텍",
            ),
        ):
            snapshot_path = Path(tmpdir) / "opendart_companies.json.gz"
            output_path = Path(tmpdir) / "krx_securities.json"
            opendart_client._write_snapshot(
                snapshot_path,
                {"012330": _snapshot_company()},
            )

            seeds = opendart_client.lookup_company(
                "key",
                "드림텍",
                snapshot_path=snapshot_path,
                output_path=output_path,
            )

            loaded_snapshot = opendart_client._load_snapshot(snapshot_path)

        self.assertEqual(len(seeds), 1)
        self.assertEqual(seeds[0].listing.security_code, "192650")
        self.assertIn("012330", loaded_snapshot)
        self.assertIn("192650", loaded_snapshot)

    def test_lookup_company_propagates_live_fetch_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            opendart_client,
            "_fetch_opendart_listed_companies",
            side_effect=opendart_client._OpenDartLookupError(
                "connection reset",
                retryable=True,
                kind="connection_reset",
            ),
        ):
            snapshot_path = Path(tmpdir) / "opendart_companies.json.gz"

            with self.assertRaises(opendart_client._OpenDartLookupError) as context:
                opendart_client.lookup_company(
                    "key",
                    "현대무벡스",
                    snapshot_path=snapshot_path,
                )

        self.assertEqual(context.exception.kind, "connection_reset")

    def test_fetch_opendart_listed_companies_retries_only_retryable_errors(self) -> None:
        with patch.object(
            opendart_client,
            "_request_opendart_corp_list",
            side_effect=[
                opendart_client._OpenDartLookupError(
                    "OpenDART temporary lock",
                    retryable=True,
                    kind="service_unavailable",
                ),
                _corp_list(_corp()),
            ],
        ) as request_corp_list, patch.object(
            opendart_client,
            "_retry_delay_seconds",
            return_value=1.5,
        ), patch.object(
            opendart_client.time,
            "sleep",
        ) as sleep:
            result = opendart_client._fetch_opendart_listed_companies("key")

        self.assertEqual(set(result), {"012330"})
        self.assertEqual(request_corp_list.call_count, 2)
        sleep.assert_called_once_with(1.5)


class OpenDartScriptTests(unittest.TestCase):
    def test_download_script_delegates_to_sync_all_companies(self) -> None:
        with patch.object(
            opendart_script,
            "get_opendart_api_key",
            return_value="key",
        ), patch.object(
            opendart_script,
            "sync_all_companies",
            return_value=[object()],
        ) as sync_all_companies:
            opendart_script.main()

        sync_all_companies.assert_called_once_with(
            "key",
            snapshot_path=opendart_script.OPENDART_SNAPSHOT_PATH,
            output_path=opendart_script.OUTPUT_PATH,
        )

    def test_refresh_snapshot_script_runs_sync(self) -> None:
        with patch.object(
            snapshot_refresh,
            "get_opendart_api_key",
            return_value="key",
        ), patch.object(
            snapshot_refresh,
            "sync_all_companies",
            return_value=[object()],
        ) as sync_all_companies:
            snapshot_refresh.main()

        sync_all_companies.assert_called_once_with(
            "key",
            snapshot_path=snapshot_refresh.OPENDART_SNAPSHOT_PATH,
            output_path=snapshot_refresh.OUTPUT_PATH,
        )


if __name__ == "__main__":
    unittest.main()
