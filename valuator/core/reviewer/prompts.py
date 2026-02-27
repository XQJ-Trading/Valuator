"""Reviewer LLM prompts: action + self-assessment output contract."""

from __future__ import annotations

import json

REVIEW_VERDICTS = ("pass", "revise", "fail")

REVIEWER_SYSTEM = """당신은 plan–execute–aggregate 파이프라인의 Reviewer입니다.
입력으로 사용자 쿼리, query unit 목록, 후보 action 노드, 최종 보고서(final markdown), 그리고 진단 요약을 받습니다.

할 일:
1) 후보 action 노드 각각에 대해, 왜 해당 노드를 재계획해야 하는지 reason을 작성합니다.
2) reason은 반드시 다음을 포함합니다:
   - entity(어떤 기업/사업/지표가 부족한지)
   - domain(예: segment, demand, supply, financial, governance, valuation, action)
   - depth/insight gap(사실 나열인지, 전이 설명 부족인지, 트리거 부족인지)
   - next retrieval hint(다음 단계에서 무엇을 더 검색할지)
3) 분해(decomposition), 실행(execution), 전파(propagation) 3축에 대해 pass/revise/fail을 판정하고 이유를 작성합니다.
4) final markdown을 기반으로 quant 5축(Time Alignment, Segment Economics, Capital Efficiency, Risk Transmission, Actionability)을 below/equal/above로 평가합니다.
5) Risk Transmission 축의 reason/evidence에는 반드시 손익 또는 현금흐름 line-item과 impact range(범위 표현)가 포함되어야 합니다.
6) baseline 보존 관점에서 다음 누락을 엄격히 감점합니다:
   - 핵심 시점(anchor) 좌표 누락 (예: 2025Q3 같은 분기/연도 기준)
   - valuation/pricing 좌표 누락 (시총, PER, PBR, 가격대/목표가)
   - 액션 트리거의 수치 임계치 부재
   - QUERY/QUERY_UNITS에 명시된 핵심 엔티티·티커가 다른 종목/테마로 치환된 경우
   - 필요한 정보가 누락된 경우

반드시 주어진 JSON 스키마대로만 응답하십시오. 다른 말은 하지 마십시오."""


def build_reviewer_user_prompt(
    query: str,
    query_units: list[str],
    candidate_actions: list[dict[str, object]],
    diagnostics: dict[str, object],
    final_markdown: str,
    now_utc: str,
) -> str:
    """Build the user prompt for the reviewer LLM."""
    units_blob = "\n".join(f"- unit_id={i}: {u}" for i, u in enumerate(query_units))
    actions_blob = "\n".join(f"- node={a.get('node')}" for a in candidate_actions)
    diagnostics_blob = json.dumps(
        diagnostics,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return (
        "[QUERY]\n" + (query or "") + "\n\n"
        "[NOW_UTC]\n" + (now_utc or "") + "\n\n"
        "[QUERY_UNITS]\n" + (units_blob or "(none)") + "\n\n"
        "[CANDIDATE_ACTIONS]\n" + (actions_blob or "(none)") + "\n\n"
        "[FINAL_MARKDOWN]\n" + (final_markdown or "(empty)") + "\n\n"
        "[DIAGNOSTICS]\n" + diagnostics_blob + "\n\n"
        "후보 노드 reason, 3축 self-assessment, quant_axes를 JSON 스키마로 반환하십시오."
    )


def build_reviewer_response_json_schema(max_node: int) -> dict[str, object]:
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
        "required": ["actions", "self_assessment", "quant_axes"],
        "properties": {
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
