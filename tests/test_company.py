from __future__ import annotations

import unittest

from valuator.domain.company import find_company


class FindCompanyTests(unittest.TestCase):
    def test_find_company_returns_none_without_subject(self) -> None:
        self.assertIsNone(find_company())

    def test_find_company_resolves_us_ticker(self) -> None:
        company = find_company(
            ticker="AMZN",
            company_name="Amazon",
        )

        self.assertIsNotNone(company)
        assert company is not None
        self.assertEqual(company.security_code, "AMZN")
        self.assertEqual(company.vendor_symbols["yahoo"], "AMZN")
        self.assertEqual(company.issuer_name, "Amazon")

    def test_find_company_resolves_krx_code(self) -> None:
        company = find_company(
            security_code="319400",
            company_name="현대무벡스",
        )

        self.assertIsNotNone(company)
        assert company is not None
        self.assertEqual(company.exchange, "KOSDAQ")
        self.assertEqual(company.vendor_symbols["yahoo"], "319400.KQ")

    def test_find_company_rejects_identifier_conflict(self) -> None:
        with self.assertRaisesRegex(ValueError, "identifier conflict"):
            find_company(
                security_code="319400",
                company_name="삼성전자",
            )

    def test_find_company_rejects_unknown_company(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown company"):
            find_company(
                security_code="999999",
                company_name="없는회사",
            )

    def test_find_company_rejects_ambiguous_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "ambiguous company"):
            find_company(company_name="Alphabet")
