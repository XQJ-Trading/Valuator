from __future__ import annotations

from ast import literal_eval
from typing import Any

from .types import (
    BalanceSheetComponent,
    BalanceSheetSection,
    BalanceSheetSummary,
    CeoSummary,
    DcfSummary,
)


def build_domain_artifact_fields(
    *,
    tool_name: str,
    raw_result: Any,
    metadata: dict[str, Any] | None = None,
    fallback_domain_id: str = "",
) -> dict[str, Any]:
    """Project a tool result into execution-artifact domain fields."""

    if not isinstance(raw_result, dict):
        return {}

    meta = metadata or {}
    tool_type = str(meta.get("tool_type") or "").strip()
    domain_id = str(meta.get("domain") or "").strip()
    if tool_type != "domain" or not domain_id:
        if not fallback_domain_id:
            return {}
        summary = str(raw_result.get("findings") or raw_result.get("summary") or "").strip()
        return {
            "domain_id": fallback_domain_id,
            "domain_summary": summary,
            "domain_key_values": {},
            "domain_payload": {"tool_name": tool_name, "raw_result": raw_result},
        }

    if domain_id == "dcf":
        return _dcf_artifact_fields(raw_result)
    if domain_id == "ceo":
        return _ceo_artifact_fields(raw_result)
    if domain_id == "balance_sheet":
        return _balance_sheet_artifact_fields(raw_result)

    return {
        "domain_id": domain_id,
        "domain_summary": str(raw_result.get("findings") or "").strip(),
        "domain_key_values": {},
        "domain_payload": {"raw_result": raw_result},
    }


def _dcf_artifact_fields(raw_result: dict[str, Any]) -> dict[str, Any]:
    company_name = str(raw_result.get("company_name") or "").strip()
    summary = str(raw_result.get("findings") or "").strip()
    assumptions = raw_result.get("assumptions") or {}
    calculation = raw_result.get("calculation") or {}
    if not isinstance(calculation, dict):
        calculation = {}

    output_text = str(calculation.get("output") or "").strip()
    payload = _parse_dcf_output(output_text)
    if payload is None:
        return {
            "domain_id": "dcf",
            "domain_summary": summary or output_text,
            "domain_key_values": {},
            "domain_payload": {
                "company_name": company_name,
                "assumptions": assumptions,
                "calculation": calculation,
            },
        }

    dcf_summary = DcfSummary(
        enterprise_value=float(payload.get("enterprise_value") or 0.0),
        pv_explicit=float(payload.get("pv_explicit") or 0.0),
        terminal_value=float(payload.get("terminal_value") or 0.0),
        terminal_pv=float(payload.get("terminal_pv") or 0.0),
        scenarios=payload.get("scenarios") or {},
        sensitivity=payload.get("sensitivity") or {},
        most_impactful_variable=str(
            (payload.get("sensitivity") or {})
            .get("impact", {})
            .get("most_impactful_variable", "")
        ),
    )
    return {
        "domain_id": "dcf",
        "domain_summary": summary,
        "domain_key_values": {
            "enterprise_value": f"{dcf_summary.enterprise_value:.2f}",
            "pv_explicit": f"{dcf_summary.pv_explicit:.2f}",
            "terminal_value": f"{dcf_summary.terminal_value:.2f}",
            "terminal_pv": f"{dcf_summary.terminal_pv:.2f}",
        },
        "domain_payload": {
            "company_name": company_name,
            "assumptions": assumptions,
            "dcf": payload,
        },
    }


def _parse_dcf_output(output: str) -> dict[str, Any] | None:
    if not output:
        return None
    try:
        data = literal_eval(output)
    except (ValueError, SyntaxError):
        return None
    if isinstance(data, dict):
        return data
    return None


def _ceo_artifact_fields(raw_result: dict[str, Any]) -> dict[str, Any]:
    corp = str(raw_result.get("corp") or "").strip()
    summary = str(raw_result.get("findings") or "").strip()
    ceo_summary = CeoSummary(
        rating="",
        strengths=[],
        risks=[],
        capital_allocation_style="",
        culture_themes=[],
    )
    title = corp or "CEO / Leadership"
    return {
        "domain_id": "ceo",
        "domain_summary": summary,
        "domain_key_values": {"subject": title},
        "domain_payload": {
            "corp": corp,
            "findings": summary,
            "ceo": ceo_summary.model_dump(),
        },
    }


def _balance_sheet_artifact_fields(raw_result: dict[str, Any]) -> dict[str, Any]:
    balance_sheet = raw_result.get("balance_sheet") or {}
    if not isinstance(balance_sheet, dict):
        return {}
    units = str(raw_result.get("units") or "").strip()
    as_of = raw_result.get("as_of")
    summary = str(raw_result.get("findings") or "").strip()

    balance_sheet_summary = BalanceSheetSummary(
        assets=_build_section(balance_sheet.get("assets") or {}),
        liabilities=_build_section(balance_sheet.get("liabilities") or {}),
        equity=_build_section(balance_sheet.get("equity") or {}),
        units=units,
        as_of=as_of,
    )
    return {
        "domain_id": "balance_sheet",
        "domain_summary": summary,
        "domain_key_values": {
            "assets_total": balance_sheet_summary.assets.total,
            "liabilities_total": balance_sheet_summary.liabilities.total,
            "equity_total": balance_sheet_summary.equity.total,
            "units": balance_sheet_summary.units,
        },
        "domain_payload": {"balance_sheet": balance_sheet_summary.model_dump()},
    }


def _build_section(raw: Any) -> BalanceSheetSection:
    if not isinstance(raw, dict):
        return BalanceSheetSection(total="N/A", components=[])

    components: list[BalanceSheetComponent] = []
    for item in raw.get("components") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("item") or "").strip()
        value = str(item.get("value") or "").strip()
        if not name or not value:
            continue
        components.append(BalanceSheetComponent(item=name, value=value))

    return BalanceSheetSection(
        total=str(raw.get("total") or "N/A"),
        components=components,
    )
