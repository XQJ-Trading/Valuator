from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from valuator.session.trace import task_rel_path

from .store import EvidenceRow

FinancialToolName = Literal["opendart_financial_tool", "yfinance_balance_sheet"]
FINANCIAL_RANGE_TOOLS = frozenset(
    {
        "opendart_financial_tool",
        "yfinance_balance_sheet",
    }
)


class FinancialRangeRequest(BaseModel):
    tool_name: FinancialToolName
    subject: str
    start_year: int
    end_year: int
    fs_div: str = "CFS"

    @classmethod
    def from_tool_args(
        cls,
        *,
        tool_name: str,
        args: dict[str, Any],
    ) -> "FinancialRangeRequest | None":
        if tool_name not in FINANCIAL_RANGE_TOOLS:
            return None
        try:
            return cls.model_validate(
                _request_payload(tool_name=tool_name, args=args)
            )
        except (KeyError, ValidationError):
            return None

    @model_validator(mode="after")
    def year_order(self) -> "FinancialRangeRequest":
        if self.start_year > self.end_year:
            raise ValueError("start_year must not exceed end_year")
        return self

    @property
    def years(self) -> set[int]:
        return set(range(self.start_year, self.end_year + 1))

    @property
    def span(self) -> int:
        return self.end_year - self.start_year

    @property
    def range_text(self) -> str:
        if self.start_year == self.end_year:
            return str(self.start_year)
        return f"{self.start_year}-{self.end_year}"

    def covers(self, other: "FinancialRangeRequest") -> bool:
        return (
            self.tool_name == other.tool_name
            and self.subject == other.subject
            and self.fs_div == other.fs_div
            and self.start_year <= other.start_year
            and other.end_year <= self.end_year
        )


class FinancialResultRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    year: int
    findings: str | None = None


class FinancialResultPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    results: list[FinancialResultRow] = Field(default_factory=list)
    missing_years: list[Any] = Field(default_factory=list)
    findings: str | None = None
    year_range: str | None = None

    @property
    def covered_years(self) -> set[int]:
        return {row.year for row in self.results}

    def for_request(
        self,
        *,
        request: FinancialRangeRequest,
        evidence: EvidenceRow,
    ) -> dict[str, Any]:
        rows = [row for row in self.results if row.year in request.years]
        payload = self.model_dump(mode="json")
        payload["results"] = [row.model_dump(mode="json") for row in rows]
        payload["year_range"] = request.range_text
        payload["missing_years"] = []

        findings = [row.findings.strip() for row in rows if row.findings]
        if findings:
            payload["findings"] = "\n".join(findings)

        payload["evidence_reused"] = {
            "source_task_id": evidence.task_id,
            "source_args": dict(evidence.stable_args),
            "source_value_ref": evidence.value_ref,
        }
        return payload


@dataclass(frozen=True)
class FinancialEvidence:
    row: EvidenceRow
    request: FinancialRangeRequest
    payload: FinancialResultPayload

    def reusable_for(self, request: FinancialRangeRequest) -> bool:
        return (
            self.request.covers(request)
            and request.years <= self.payload.covered_years
        )

    def result_payload_for(self, request: FinancialRangeRequest) -> dict[str, Any]:
        return self.payload.for_request(request=request, evidence=self.row)

    @property
    def span(self) -> int:
        return self.request.span


@dataclass(frozen=True)
class FinancialEvidenceReuse:
    payload: dict[str, Any]
    metadata: dict[str, Any]
    span: int


def financial_reuse_from_session(
    *,
    tasks_dir: Path,
    row: EvidenceRow,
    requested: FinancialRangeRequest,
) -> FinancialEvidenceReuse | None:
    evidence = _financial_evidence_from_session(tasks_dir=tasks_dir, row=row)
    if evidence is None or not evidence.reusable_for(requested):
        return None
    return FinancialEvidenceReuse(
        payload=evidence.result_payload_for(requested),
        span=evidence.span,
        metadata={
            "evidence_reused": True,
            "source_task_id": row.task_id,
            "source_value_ref": row.value_ref,
            "source_args": dict(row.stable_args),
        },
    )


def _financial_evidence_from_session(
    *,
    tasks_dir: Path,
    row: EvidenceRow,
) -> FinancialEvidence | None:
    request = FinancialRangeRequest.from_tool_args(
        tool_name=row.tool_name,
        args=row.stable_args,
    )
    if request is None:
        return None
    try:
        rel = Path(row.value_ref or "execution/result.md")
        if rel.suffix == ".md":
            rel = rel.with_suffix(".json")
        result_path = tasks_dir / task_rel_path(row.task_id) / rel
        with result_path.open(encoding="utf-8") as handle:
            raw_result = json.load(handle)["raw_result"]
        payload = FinancialResultPayload.model_validate(
            raw_result
        )
    except (
        FileNotFoundError,
        KeyError,
        OSError,
        json.JSONDecodeError,
        ValidationError,
    ):
        return None
    if not payload.results:
        return None
    return FinancialEvidence(row=row, request=request, payload=payload)


def _request_payload(*, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    # Boundary: each tool's external arg shape enters one typed financial request.
    if tool_name == "opendart_financial_tool":
        return {
            "tool_name": tool_name,
            "subject": args["corp"],
            "start_year": args["start_year"],
            "end_year": args["end_year"],
            "fs_div": str(args.get("fs_div") or "CFS").upper(),
        }
    return {
        "tool_name": tool_name,
        "subject": args.get("ticker") or args["corp"],
        "start_year": args["start_year"],
        "end_year": args["end_year"],
    }
