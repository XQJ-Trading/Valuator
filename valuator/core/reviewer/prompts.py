"""Reviewer LLM prompts: action + self-assessment output contract."""

from __future__ import annotations

import json

REVIEWER_SYSTEM = """당신은 plan–execute–aggregate 파이프라인의 Reviewer입니다.
입력으로 사용자 쿼리, query unit 목록, 후보 action 노드, 그리고 진단 요약을 받습니다.

할 일:
1) 후보 action 노드 각각에 대해, 왜 해당 노드를 재계획해야 하는지 reason을 작성합니다.
2) reason은 반드시 다음을 포함합니다:
   - entity(어떤 기업/사업/지표가 부족한지)
   - domain(예: segment, demand, supply, financial, governance, valuation, action)
   - depth/insight gap(사실 나열인지, 전이 설명 부족인지, 트리거 부족인지)
   - next retrieval hint(다음 단계에서 무엇을 더 검색할지)
3) 분해(decomposition), 실행(execution), 전파(propagation) 3축에 대해 pass/revise/fail을 판정하고 이유를 작성합니다.
4) node는 반드시 입력 후보 node 값만 사용합니다.

반드시 주어진 JSON 스키마대로만 응답하십시오. 다른 말은 하지 마십시오."""


def build_reviewer_user_prompt(
    query: str,
    query_units: list[str],
    candidate_actions: list[dict[str, object]],
    diagnostics: dict[str, object],
) -> str:
    """Build the user prompt for the reviewer LLM."""
    units_blob = "\n".join(f"- unit_id={i}: {u}" for i, u in enumerate(query_units))
    actions_blob = "\n".join(
        f"- node={a.get('node')} gaps={a.get('gaps')}"
        for a in candidate_actions
    )
    diagnostics_blob = json.dumps(
        diagnostics,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return (
        "[QUERY]\n" + (query or "") + "\n\n"
        "[QUERY_UNITS]\n" + (units_blob or "(none)") + "\n\n"
        "[CANDIDATE_ACTIONS]\n" + (actions_blob or "(none)") + "\n\n"
        "[DIAGNOSTICS]\n" + diagnostics_blob + "\n\n"
        "후보 노드 reason과 3축 self-assessment를 JSON 스키마로 반환하십시오."
    )


def build_reviewer_response_json_schema(max_node: int) -> dict[str, object]:
    max_value = max(0, int(max_node))
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["actions", "self_assessment"],
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
                    "decomposition": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["verdict", "reason"],
                        "properties": {
                            "verdict": {
                                "type": "string",
                                "enum": ["pass", "revise", "fail"],
                            },
                            "reason": {"type": "string", "minLength": 1},
                        },
                    },
                    "execution": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["verdict", "reason"],
                        "properties": {
                            "verdict": {
                                "type": "string",
                                "enum": ["pass", "revise", "fail"],
                            },
                            "reason": {"type": "string", "minLength": 1},
                        },
                    },
                    "propagation": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["verdict", "reason"],
                        "properties": {
                            "verdict": {
                                "type": "string",
                                "enum": ["pass", "revise", "fail"],
                            },
                            "reason": {"type": "string", "minLength": 1},
                        },
                    },
                    "overall": {"type": "string", "minLength": 1},
                },
            },
        },
    }
