from __future__ import annotations

import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


def _field(default=..., *, default_factory=None, **_kwargs):
    if default_factory is not None:
        return default_factory()
    if default is ...:
        return None
    return default


class _BaseModel:
    def __init__(self, **data: object) -> None:
        for name, value in self.__class__.__dict__.items():
            if name.startswith("_") or callable(value):
                continue
            if name in data:
                continue
            if isinstance(value, dict):
                setattr(self, name, dict(value))
                continue
            if isinstance(value, list):
                setattr(self, name, list(value))
                continue
            setattr(self, name, value)
        for key, value in data.items():
            setattr(self, key, value)

    @classmethod
    def model_validate(cls, payload: dict[str, object]) -> "_BaseModel":
        return cls(**payload)

    def model_dump(self) -> dict[str, object]:
        return dict(self.__dict__)


sys.modules.setdefault(
    "dotenv",
    SimpleNamespace(load_dotenv=lambda *_args, **_kwargs: None),
)
sys.modules.setdefault(
    "pydantic",
    SimpleNamespace(BaseModel=_BaseModel, ConfigDict=dict, Field=_field),
)

from valuator.tools.yfinance_tool import YFinanceBalanceSheetTool


class _FakeLoc:
    def __init__(self, frame: "_FakeFrame") -> None:
        self._frame = frame

    def __getitem__(self, key: tuple[str, str]) -> float:
        row, column = key
        if column != self._frame.column:
            raise KeyError(column)
        return self._frame.rows[row]


class _FakeFrame:
    def __init__(
        self,
        rows: dict[str, float] | None = None,
        *,
        column: str = "2025-12-31",
    ) -> None:
        self.rows = dict(rows or {})
        self.column = column

    @property
    def empty(self) -> bool:
        return not self.rows

    @property
    def columns(self) -> list[str]:
        return [self.column] if self.column else []

    @columns.setter
    def columns(self, values: list[str]) -> None:
        self.column = values[0] if values else ""

    @property
    def index(self) -> list[str]:
        return list(self.rows)

    @property
    def loc(self) -> _FakeLoc:
        return _FakeLoc(self)


def _frame(rows: dict[str, float]) -> _FakeFrame:
    return _FakeFrame(rows)


class _FakeTicker:
    def __init__(self, _symbol: str) -> None:
        self.balance_sheet = _frame(
            {
                "Total Assets": 1000.0,
                "Total Liabilities": 400.0,
                "Stockholders Equity": 600.0,
                "Total Current Assets": 300.0,
                "Total Current Liabilities": 150.0,
            }
        )
        self.quarterly_balance_sheet = _FakeFrame()
        self.cashflow = _frame(
            {
                "Total Cash From Operating Activities": 30.0,
                "Capital Expenditures": 10.0,
            }
        )
        self.quarterly_cashflow = _FakeFrame()
        self.financials = _frame(
            {
                "Operating Income": 20.0,
                "Interest Expense": -5.0,
                "Total Revenue": 200.0,
                "Gross Profit": 80.0,
                "Net Income Common Stockholders": 15.0,
                "EBITDA": 25.0,
            }
        )
        self.quarterly_financials = _FakeFrame()
        self.info = {
            "marketCap": 1000000.0,
            "currentPrice": 123.45,
            "trailingPE": 20.0,
            "priceToBook": 3.0,
        }


class YFinanceIncomeFieldTests(unittest.TestCase):
    def test_execute_includes_income_statement_fields_and_gross_margin(self) -> None:
        tool = YFinanceBalanceSheetTool()
        fake_module = SimpleNamespace(Ticker=_FakeTicker)

        with patch.dict("sys.modules", {"yfinance": fake_module}):
            result = asyncio.run(tool.execute(ticker="AMZN", year="latest"))

        self.assertTrue(result.success)
        self.assertEqual(result.result["total_revenue"], 200.0)
        self.assertEqual(result.result["gross_profit"], 80.0)
        self.assertEqual(result.result["net_income"], 15.0)
        self.assertEqual(result.result["ebitda"], 25.0)
        self.assertAlmostEqual(result.result["gross_margin"], 0.4)
        self.assertIn("total_revenue=200.0", result.result["findings"])
        self.assertIn("gross_margin=0.4", result.result["findings"])


if __name__ == "__main__":
    unittest.main()
