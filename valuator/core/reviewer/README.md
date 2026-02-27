# Reviewer 역할 (Action-Only)

Reviewer는 plan–execute–aggregate 이후, LLM 판단 결과를 fail-fast 정책으로 반환한다.

## 입력

- **plan**: `query_units`, `contract`, `tasks(leaf/query_unit_ids)`
- **execution**: `leaf_completed_tasks`
- **aggregation**: `final_markdown`, (선택) `missing_contract_items`

## 내부 힌트 생성

Reviewer는 프롬프트 힌트용으로 아래를 계산한다.

1. **Contract 누락**
- `missing_contract_items`(또는 `evaluate_contract`) 기준으로 누락된 requirement를 찾고, 해당 `unit_id`를 action 후보로 만든다.

2. **Execution 누락**
- `plan`의 leaf task와 `execution.leaf_completed_tasks`를 비교해 누락 task를 찾고, 해당 task의 `query_unit_ids`를 action 후보로 만든다.

3. **최종본 비어 있음**
- `final_markdown`이 비어 있으면 모든 `query_unit_id`를 action 후보로 만든다.

4. **사유 병합**
- 같은 `node(query_unit_id)`에 여러 누락 원인이 있으면 reason을 하나로 병합한다.

## 출력 계약

Reviewer는 아래를 반환한다.

- `actions: list[ActionItem]`
- `ActionItem = { node: int, reason: str }`
  - `node`: `query_unit_id` (0-based)
  - `reason`: 도메인적으로 부족한 내용을 설명하는 자연어
- `coverage_feedback: dict`
  - `summary`: 3축 판단 요약 문자열
  - `self_assessment`: `decomposition/execution/propagation`별 `pass|revise|fail` + 이유
  - `signals`: 누락 신호 카운트(`missing_mapping`, `missing_leaf`, `missing_contract`, `final_empty`, `action_nodes_total`)

예시:

```json
{
  "actions": [
    {
      "node": 1,
      "reason": "핵심 사업부 OPM/기여도 정량 근거가 최종본에 반영되지 않음"
    }
  ]
}
```

Engine의 `status`는 Reviewer가 아니라 `actions` 존재 여부로 계산한다.
LLM 응답이 스키마/형식에 맞지 않으면 Reviewer는 `ValueError`로 fail-fast 한다.
