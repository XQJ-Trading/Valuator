from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from valuator.domain import company as company_module
from valuator.domain.company import Listing, ListingSeed, resolve_subjects


@contextmanager
def _patched_hyundai_mobis_record():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "krx_securities.json"
        path.write_text(
            (
                "[\n"
                "  {\n"
                '    "issuer_name": "현대모비스",\n'
                '    "security_code": "012330",\n'
                '    "exchange": "KOSPI",\n'
                '    "listing_id": "KRX:012330",\n'
                '    "vendor_symbols": {"yahoo": "012330.KS"},\n'
                '    "aliases": ["현대모비스", "Hyundai Mobis"],\n'
                '    "corp_code": "00164779"\n'
                "  }\n"
                "]\n"
            ),
            encoding="utf-8",
        )
        with patch.object(company_module, "KRX_SECURITIES_PATH", path):
            company_module._entity_index.cache_clear()
            try:
                yield
            finally:
                company_module._entity_index.cache_clear()


@contextmanager
def _patched_hyundai_movex_record():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "krx_securities.json"
        path.write_text(
            (
                "[\n"
                "  {\n"
                '    "issuer_name": "현대무벡스",\n'
                '    "security_code": "319400",\n'
                '    "exchange": "KOSDAQ",\n'
                '    "listing_id": "KRX:319400",\n'
                '    "vendor_symbols": {"yahoo": "319400.KQ"},\n'
                '    "aliases": ["현대무벡스", "Hyundai Movex"],\n'
                '    "corp_code": "01351164"\n'
                "  }\n"
                "]\n"
            ),
            encoding="utf-8",
        )
        with patch.object(company_module, "KRX_SECURITIES_PATH", path):
            company_module._entity_index.cache_clear()
            try:
                yield
            finally:
                company_module._entity_index.cache_clear()


class ResolveSubjectsTests(unittest.TestCase):
    def setUp(self) -> None:
        company_module._entity_index.cache_clear()

    def tearDown(self) -> None:
        company_module._entity_index.cache_clear()

    def test_resolve_subjects_returns_empty_without_subject(self) -> None:
        self.assertEqual(resolve_subjects(), ())

    def test_resolve_subjects_resolves_exact_company_name_at_company_level(
        self,
    ) -> None:
        subjects = resolve_subjects(company_names=("Amazon",))

        self.assertEqual(len(subjects), 1)
        subject = subjects[0]
        self.assertEqual(subject.company.company_name, "Amazon")
        self.assertIsNone(subject.listing)

    def test_resolve_subjects_resolves_krx_code_as_listing_identifier(self) -> None:
        with _patched_hyundai_movex_record():
            subjects = resolve_subjects(company_names=("319400",))

            self.assertEqual(len(subjects), 1)
            subject = subjects[0]
            assert subject.listing is not None
            self.assertEqual(subject.company.company_name, "현대무벡스")
            self.assertEqual(subject.listing.security_code, "319400")
            self.assertEqual(subject.listing.exchange, "KOSDAQ")
            self.assertEqual(subject.listing.vendor_symbols["yahoo"], "319400.KQ")

    def test_resolve_subjects_resolves_krx_company_by_korean_name(self) -> None:
        with _patched_hyundai_mobis_record():
            subjects = resolve_subjects(company_names=("현대모비스",))

            self.assertEqual(len(subjects), 1)
            subject = subjects[0]
            self.assertEqual(subject.company.company_name, "현대모비스")
            self.assertIsNone(subject.listing)

    def test_resolve_subjects_resolves_krx_company_by_english_alias(self) -> None:
        with _patched_hyundai_mobis_record():
            subjects = resolve_subjects(company_names=("Hyundai Mobis",))

            self.assertEqual(len(subjects), 1)
            subject = subjects[0]
            self.assertEqual(subject.company.company_name, "현대모비스")
            self.assertIsNone(subject.listing)

    def test_resolve_subjects_resolves_ticker_as_listing_identifier(self) -> None:
        subjects = resolve_subjects(company_names=("NVDA",))

        self.assertEqual(len(subjects), 1)
        subject = subjects[0]
        assert subject.listing is not None
        self.assertEqual(subject.company.company_name, "Nvidia")
        self.assertEqual(subject.listing.security_code, "NVDA")

    def test_resolve_subjects_collapses_same_company_multi_class_name(self) -> None:
        subjects = resolve_subjects(company_names=("Alphabet",))

        self.assertEqual(len(subjects), 1)
        subject = subjects[0]
        self.assertEqual(subject.company.company_name, "Alphabet Inc.")
        self.assertEqual(subject.company.company_id, "SEC:1652044")
        self.assertIsNone(subject.listing)

    def test_resolve_subjects_preserves_explicit_listing_with_same_company_name(
        self,
    ) -> None:
        subjects = resolve_subjects(ticker="GOOG", company_names=("Alphabet",))

        self.assertEqual(len(subjects), 1)
        subject = subjects[0]
        assert subject.listing is not None
        self.assertEqual(subject.company.company_name, "Alphabet Inc.")
        self.assertEqual(subject.listing.security_code, "GOOG")

    def test_resolve_subjects_resolves_fuzzy_typo_at_company_level(self) -> None:
        with _patched_hyundai_movex_record():
            subjects = resolve_subjects(company_names=("현대무백스",))

            self.assertEqual(len(subjects), 1)
            subject = subjects[0]
            self.assertEqual(subject.company.company_name, "현대무벡스")
            self.assertIsNone(subject.listing)

    def test_resolve_subjects_keeps_multi_listing_comparison(self) -> None:
        subjects = resolve_subjects(company_names=("GOOG", "GOOGL"))

        self.assertEqual(
            [
                subject.listing.security_code if subject.listing is not None else ""
                for subject in subjects
            ],
            ["GOOG", "GOOGL"],
        )

    def test_resolve_subjects_rejects_conflicting_identifier_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "identifier conflict"):
            resolve_subjects(
                ticker="GOOG",
                security_code="GOOGL",
            )

    def test_resolve_subjects_rejects_unknown_company(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown company"):
            resolve_subjects(company_names=("없는회사",))

    def test_resolve_subjects_rejects_cross_company_ambiguous_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "ambiguous company"):
            resolve_subjects(company_names=("Target",))

    def test_resolve_subjects_uses_on_miss_to_ingest_unknown_company(self) -> None:
        def on_miss(surface_form: str) -> list[ListingSeed]:
            self.assertEqual(surface_form, "드림텍")
            return [
                ListingSeed(
                    company_id="KRX:192650",
                    company_name="드림텍",
                    company_aliases=("드림텍", "Dreamtech"),
                    listing=Listing(
                        listing_id="KRX:192650",
                        company_id="KRX:192650",
                        security_code="192650",
                        exchange="KOSPI",
                        vendor_symbols={"yahoo": "192650.KS"},
                    ),
                )
            ]

        subjects = resolve_subjects(
            company_names=("드림텍",),
            on_miss=on_miss,
        )

        self.assertEqual(len(subjects), 1)
        self.assertEqual(subjects[0].company.company_name, "드림텍")
        self.assertIsNone(subjects[0].listing)

    def test_resolve_subjects_merges_aliases_for_existing_company_on_miss(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "krx_securities.json"
            path.write_text(
                (
                    "[\n"
                    "  {\n"
                    '    "issuer_name": "현대모비스",\n'
                    '    "security_code": "012330",\n'
                    '    "exchange": "KOSPI",\n'
                    '    "listing_id": "KRX:012330",\n'
                    '    "vendor_symbols": {"yahoo": "012330.KS"},\n'
                    '    "aliases": ["현대모비스"],\n'
                    '    "corp_code": "00164779"\n'
                    "  }\n"
                    "]\n"
                ),
                encoding="utf-8",
            )
            with patch.object(company_module, "KRX_SECURITIES_PATH", path):
                company_module._entity_index.cache_clear()
                try:
                    def on_miss(_surface_form: str) -> list[ListingSeed]:
                        return [
                            ListingSeed(
                                company_id="KRX:012330",
                                company_name="현대모비스",
                                company_aliases=("현대모비스", "Hyundai Mobis"),
                                listing=Listing(
                                    listing_id="KRX:012330",
                                    company_id="KRX:012330",
                                    security_code="012330",
                                    exchange="KOSPI",
                                    vendor_symbols={"yahoo": "012330.KS"},
                                ),
                            )
                        ]

                    subjects = resolve_subjects(
                        company_names=("Hyundai Mobis",),
                        on_miss=on_miss,
                    )
                    cached_subjects = resolve_subjects(company_names=("Hyundai Mobis",))
                finally:
                    company_module._entity_index.cache_clear()

        self.assertEqual(subjects[0].company.company_name, "현대모비스")
        self.assertEqual(cached_subjects[0].company.company_name, "현대모비스")
