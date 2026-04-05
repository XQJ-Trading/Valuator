from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from domain.boundary.krx_ticker_resolve import resolve_corp_code
from valuator.utils.config import get_opendart_api_key

from .base import BaseTool, ToolResult

REPORT_CODES = {
    "annual": "11011",
    "q1": "11013",
    "q2": "11012",
    "q3": "11014",
}
CURRENT_AMOUNT_KEYS = (
    "thstrm_amount",
    "thstrm_add_amount",
    "current_amount",
    "amount",
)
STATEMENT_ACCOUNTS = {
    "revenue": {
        "label": "매출액",
        "ids": frozenset({"ifrsfullRevenue"}),
        "names": frozenset({"매출액", "영업수익", "수익"}),
    },
    "operating_income": {
        "label": "영업이익",
        "ids": frozenset(
            {
                "dartOperatingIncomeLoss",
                "ifrsfullProfitLossFromOperatingActivities",
            }
        ),
        "names": frozenset({"영업이익", "영업이익손실"}),
    },
    "net_income": {
        "label": "당기순이익",
        "ids": frozenset({"ifrsfullProfitLoss"}),
        "names": frozenset(
            {
                "당기순이익",
                "당기순이익손실",
                "분기순이익",
                "분기순이익손실",
                "반기순이익",
                "반기순이익손실",
            }
        ),
    },
    "total_assets": {
        "label": "자산총계",
        "ids": frozenset({"ifrsfullAssets"}),
        "names": frozenset({"자산총계"}),
    },
    "total_liabilities": {
        "label": "부채총계",
        "ids": frozenset({"ifrsfullLiabilities"}),
        "names": frozenset({"부채총계"}),
    },
    "total_equity": {
        "label": "자본총계",
        "ids": frozenset({"ifrsfullEquity"}),
        "names": frozenset({"자본총계"}),
    },
}


class OpenDartToolError(Exception):
    def __init__(self, message: str, *, error_code: str = "other") -> None:
        super().__init__(message)
        self.error_code = error_code


class OpenDartRequest(BaseModel):
    corp: str = Field(min_length=1)
    data_type: Literal["financial_statement", "disclosure_list"] = (
        "financial_statement"
    )
    year: int | None = None
    report_type: Literal["annual", "q1", "q2", "q3"] = "annual"

    @classmethod
    def from_kwargs(cls, kwargs: dict[str, Any]) -> "OpenDartRequest":
        return cls.model_validate(
            {
                "corp": str(kwargs.get("corp") or "").strip(),
                "data_type": kwargs.get("data_type") or "financial_statement",
                "year": kwargs.get("year"),
                "report_type": kwargs.get("report_type") or "annual",
            }
        )

    @model_validator(mode="after")
    def validate_request(self) -> "OpenDartRequest":
        if self.data_type == "financial_statement" and self.year is None:
            raise ValueError("'year' is required for financial_statement")
        return self

    def fallback_query(self) -> str:
        if self.data_type == "financial_statement" and self.year is not None:
            return f"{self.corp} {self.year} 재무제표 사업보고서 반기보고서 분기보고서"
        return f"{self.corp} 최근 공시"


class OpenDartTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            "opendart_tool",
            "Retrieve Korean company financial statements and disclosures via Open DART.",
        )
        self._reader: Any | None = None

    async def execute(self, **kwargs) -> ToolResult:
        try:
            request = OpenDartRequest.from_kwargs(kwargs)
        except (ValidationError, ValueError) as exc:
            return ToolResult(success=False, result=None, error=str(exc))

        try:
            corp_code = resolve_corp_code(request.corp)
            client = self._reader_client()
            if request.data_type == "financial_statement":
                result, metadata = self._financial_statement(
                    client,
                    request,
                    corp_code,
                )
            else:
                result, metadata = self._disclosure_list(client, request, corp_code)
            return ToolResult(success=True, result=result, metadata=metadata)
        except OpenDartToolError as exc:
            return ToolResult(
                success=False,
                result=None,
                error=str(exc),
                metadata={
                    "error_code": exc.error_code,
                    "fallback": {
                        "tool_name": "web_search_tool",
                        "tool_args": {"query": request.fallback_query()},
                    },
                },
            )
        except ValueError as exc:
            return ToolResult(
                success=False,
                result=None,
                error=str(exc),
                metadata={"error_code": "corp_code_not_found"},
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                result=None,
                error=str(exc),
                metadata={"error_code": "other"},
            )

    def _reader_client(self) -> Any:
        if self._reader is not None:
            return self._reader

        api_key = get_opendart_api_key()
        if not api_key:
            raise OpenDartToolError(
                "OPENDART_API_KEY not set",
                error_code="missing_api_key",
            )

        try:
            module = importlib.import_module("OpenDartReader")
        except ImportError as exc:
            raise OpenDartToolError(
                "OpenDartReader dependency is unavailable: "
                f"{exc}. Install `opendartreader` in the active environment "
                f"({sys.executable}).",
                error_code="dependency_missing",
            ) from exc

        reader_factory = getattr(module, "OpenDartReader", module)
        if not callable(reader_factory):
            raise OpenDartToolError(
                "OpenDartReader dependency does not expose a callable client",
                error_code="dependency_missing",
            )

        cache_root = Path(__file__).resolve().parents[2] / ".cache"
        cache_root.mkdir(exist_ok=True)
        current_dir = Path.cwd()
        os.chdir(cache_root)
        try:
            self._reader = reader_factory(api_key)
        finally:
            os.chdir(current_dir)
        return self._reader

    def _financial_statement(
        self,
        reader: Any,
        request: OpenDartRequest,
        corp_code: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        reprt_code = REPORT_CODES[request.report_type]
        rows, fs_div = _load_rows(
            reader,
            corp_code=corp_code,
            year=request.year,
            reprt_code=reprt_code,
        )
        if rows:
            summary = _statement_summary(rows)
            result = {
                "corp": request.corp,
                "corp_code": corp_code,
                "year": request.year,
                "report_type": request.report_type,
                "reprt_code": reprt_code,
                "fs_div": fs_div,
                "summary": summary,
                "statements": rows,
                "findings": _financial_findings(
                    corp_code=corp_code,
                    year=request.year,
                    report_type=request.report_type,
                    fs_div=fs_div,
                    summary=summary,
                ),
            }
            metadata = {
                "source": "opendart",
                "data_type": "financial_statement",
                "row_count": len(rows),
                "fs_div": fs_div,
                "corp_code": corp_code,
            }
            return result, metadata
        raise OpenDartToolError(
            f"No financial statements found for {request.corp} in {request.year}",
            error_code="not_found",
        )

    def _disclosure_list(
        self,
        reader: Any,
        request: OpenDartRequest,
        corp_code: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if request.year is None:
            rows = _records_payload(reader.list(corp_code))
        else:
            rows = _records_payload(
                reader.list(
                    corp_code,
                    start=f"{request.year}-01-01",
                    end=f"{request.year}-12-31",
                )
            )
        result = {
            "corp": request.corp,
            "corp_code": corp_code,
            "year": request.year,
            "disclosures": rows,
            "count": len(rows),
            "findings": _disclosure_findings(rows),
        }
        metadata = {
            "source": "opendart",
            "data_type": "disclosure_list",
            "corp_code": corp_code,
            "count": len(rows),
        }
        return result, metadata


def _records_payload(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if hasattr(value, "to_dict"):
        try:
            records = value.to_dict(orient="records")
        except TypeError:
            records = value.to_dict()
        if isinstance(records, list):
            return [dict(item) for item in records if isinstance(item, dict)]
        if isinstance(records, dict):
            return [dict(records)]
    if isinstance(value, dict):
        return [dict(value)]
    return []


def _load_rows(
    reader: Any,
    *,
    corp_code: str,
    year: int | None,
    reprt_code: str,
) -> tuple[list[dict[str, Any]], str]:
    for fs_div in ("CFS", "OFS"):
        rows = _records_payload(
            reader.finstate_all(
                corp_code,
                year,
                reprt_code=reprt_code,
                fs_div=fs_div,
            )
        )
        if rows:
            return rows, fs_div
    return [], ""


def _statement_summary(rows: list[dict[str, Any]]) -> dict[str, int | None]:
    summary: dict[str, int | None] = {}
    for key, config in STATEMENT_ACCOUNTS.items():
        summary[key] = _statement_amount(
            rows,
            account_ids=config["ids"],
            account_names=config["names"],
        )
    return summary


def _statement_amount(
    rows: list[dict[str, Any]],
    *,
    account_ids: frozenset[str],
    account_names: frozenset[str],
) -> int | None:
    for row in rows:
        account_id = _token_key(
            row.get("account_id") or row.get("accountId") or ""
        )
        account_name = _token_key(
            row.get("account_nm") or row.get("account_name") or row.get("label") or ""
        )
        if account_id in account_ids or account_name in account_names:
            amount = _row_amount(row)
            if amount is not None:
                return amount
    return None


def _row_amount(row: dict[str, Any]) -> int | None:
    for key in CURRENT_AMOUNT_KEYS:
        amount = _parse_amount(row.get(key))
        if amount is not None:
            return amount
    for key, value in row.items():
        if "amount" not in str(key).lower():
            continue
        amount = _parse_amount(value)
        if amount is not None:
            return amount
    return None


def _parse_amount(value: Any) -> int | None:
    if value in (None, "", "-"):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    if not text or text == "-":
        return None
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    try:
        return int(float(text))
    except ValueError:
        return None


def _token_key(text: Any) -> str:
    return "".join(char for char in str(text).strip() if char.isalnum())


def _financial_findings(
    *,
    corp_code: str,
    year: int | None,
    report_type: str,
    fs_div: str,
    summary: dict[str, int | None],
) -> str:
    parts = [
        f"corp_code={corp_code}",
        f"year={year}",
        f"report_type={report_type}",
        f"fs_div={fs_div}",
    ]
    for key, config in STATEMENT_ACCOUNTS.items():
        value = summary.get(key)
        parts.append(f"{config['label']}={value}")
    return ", ".join(parts)


def _disclosure_findings(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "count=0"
    preview = rows[:3]
    parts = [f"count={len(rows)}"]
    for row in preview:
        receipt = row.get("rcept_dt") or row.get("receipt_date") or ""
        name = row.get("report_nm") or row.get("report_name") or ""
        if receipt or name:
            parts.append(f"{receipt}:{name}".strip(":"))
    return ", ".join(parts)
