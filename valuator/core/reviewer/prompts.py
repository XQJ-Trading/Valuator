"""Reviewer LLM prompts: layer-aware omission review."""

from __future__ import annotations

import json
from typing import Any

REVIEW_VERDICTS = ("pass", "revise", "fail")

REVIEWER_SYSTEM = """당신은 plan–execute–aggregate 파이프라인의 Reviewer입니다.
입력으로 canonical query spec, plan/execute/aggregation layer 상태, 최종 보고서(final markdown)를 받습니다.

할 일:
1) FINAL_MARKDOWN에서 빠진 requirement id를 판정합니다.
2) FINAL_MARKDOWN에서 빠진 active domain id를 판정합니다.
3) 후보 action 노드 각각에 대해 재계획 reason을 작성합니다.
4) 분해(decomposition), 실행(execution), 전파(propagation) 3축에 대해 pass/revise/fail을 판정하고 이유를 작성합니다.
5) final markdown을 기반으로 quant 5축(Time Alignment, Segment Economics, Capital Efficiency, Risk Transmission, Actionability)을 below/equal/above로 평가합니다.
6) requirement/domain/layer 누락은 엄격히 감점합니다.
7) semantic sufficiency는 gating입니다. quant 5축 중 하나라도 `below`이면 pass로 간주하지 마십시오.
8) QUERY_SPEC.query_breakdown의 step/entity/relation이 FINAL_MARKDOWN에 실질적으로 전파되었는지 검토하십시오. literal한 "Query 분석 요약" 섹션 유무는 요구하지 않습니다.

판정 규칙:
- requirement는 QUERY_SPEC.requirements를 기준으로만 판정합니다.
- step/entity/relation coverage는 QUERY_SPEC.query_breakdown을 기준으로 의미적으로 판정합니다.
- FINAL_MARKDOWN에 실질 내용이 없으면 missing requirement로 판단합니다.
- active domain이 FINAL_MARKDOWN에 실질적으로 반영되지 않았으면 missing_final_domain_ids에 포함합니다.
- formatting preference만을 이유로 requirement를 missing으로 만들지 마십시오.
- FINAL_MARKDOWN에 query breakdown 전용 섹션이 없어도, step/entity/relation이 본문에 반영되어 있으면 누락으로 간주하지 마십시오.
- recommendation/screening query라면 FINAL_MARKDOWN이 명시적 picks/selection logic/action triggers를 유지하는지 확인하십시오. generic market essay로 바뀌면 Actionability 또는 Segment/Risk 축을 `below`로 평가하십시오.
- requirement/domain 표식이 모두 있어도 query intent와 decision protocol이 무너지면 pass가 아닙니다.

반드시 주어진 JSON 스키마대로만 응답하십시오. 다른 말은 하지 마십시오."""


def build_reviewer_user_prompt(
    *,
    query: str,
    query_spec: dict[str, Any],
    plan_layer: dict[str, Any],
    execution_layer: dict[str, Any],
    aggregation_layer: dict[str, Any],
    candidate_actions: list[dict[str, object]],
    final_markdown: str,
    now_utc: str,
    diagnostics: dict[str, object],
) -> str:
    actions_blob = "\n".join(f"- node={a.get('node')}" for a in candidate_actions)
    return (
        "[QUERY]\n"
        + (query or "")
        + "\n\n"
        + "[NOW_UTC]\n"
        + (now_utc or "")
        + "\n\n"
        + "[QUERY_SPEC]\n"
        + json.dumps(query_spec, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n\n"
        + "[PLAN_LAYER]\n"
        + json.dumps(plan_layer, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n\n"
        + "[EXECUTION_LAYER]\n"
        + json.dumps(execution_layer, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n\n"
        + "[AGGREGATION_LAYER]\n"
        + json.dumps(aggregation_layer, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n\n"
        + "[CANDIDATE_ACTIONS]\n"
        + (actions_blob or "(none)")
        + "\n\n"
        + "[FINAL_MARKDOWN]\n"
        + (final_markdown or "(empty)")
        + "\n\n"
        + "[DIAGNOSTICS]\n"
        + json.dumps(diagnostics, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n\n"
        + "missing_requirement_ids, missing_final_domain_ids, actions, self_assessment, quant_axes를 JSON 스키마로 반환하십시오."
    )


def build_reviewer_response_json_schema(
    *,
    max_node: int,
    requirement_ids: list[str],
    domain_ids: list[str],
) -> dict[str, object]:
    max_value = max(0, int(max_node))
    verdict_schema: dict[str, object] = {
        "type": "string",
        "enum": list(REVIEW_VERDICTS),
    }
    assessment_axis_schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["verdict", "reason"],
        "properties": {
            "verdict": verdict_schema,
            "reason": {"type": "string", "minLength": 1},
        },
    }
    quant_axis_schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["grade", "reason", "evidence"],
        "properties": {
            "grade": {
                "type": "string",
                "enum": ["below", "equal", "above"],
            },
            "reason": {"type": "string", "minLength": 1},
            "evidence": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,
            },
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "missing_requirement_ids",
            "missing_final_domain_ids",
            "actions",
            "self_assessment",
            "quant_axes",
        ],
        "properties": {
            "missing_requirement_ids": {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "enum": requirement_ids},
            },
            "missing_final_domain_ids": {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "enum": domain_ids},
            },
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["node", "reason"],
                    "properties": {
                        "node": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": max_value,
                        },
                        "reason": {
                            "type": "string",
                            "minLength": 1,
                        },
                    },
                },
            },
            "self_assessment": {
                "type": "object",
                "additionalProperties": False,
                "required": ["decomposition", "execution", "propagation", "overall"],
                "properties": {
                    "decomposition": assessment_axis_schema,
                    "execution": assessment_axis_schema,
                    "propagation": assessment_axis_schema,
                    "overall": {"type": "string", "minLength": 1},
                },
            },
            "quant_axes": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "time_alignment",
                    "segment_economics",
                    "capital_efficiency",
                    "risk_transmission",
                    "actionability",
                ],
                "properties": {
                    "time_alignment": quant_axis_schema,
                    "segment_economics": quant_axis_schema,
                    "capital_efficiency": quant_axis_schema,
                    "risk_transmission": quant_axis_schema,
                    "actionability": quant_axis_schema,
                },
            },
        },
    }
