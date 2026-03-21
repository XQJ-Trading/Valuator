# Reviewer 역할 (ID-Action)

Reviewer는 plan–execute–aggregate 이후, LLM 판단 결과를 fail-fast 정책으로 반환한다.

## 입력

- **plan**: `query_units`, `contract`, `tasks(leaf/query_unit_ids)`
- **execution**: `leaf_completed_tasks`
- **aggregation**: `final_markdown`, (선택) `missing_requirement_ids`

## 내부 힌트 생성

Reviewer는 프롬프트 힌트용으로 아래를 계산한다.

1. **Requirement 누락**
- `missing_requirement_ids`(또는 `evaluate_contract`) 기준으로 누락 requirement를 action 후보(`id_type=requirement`)로 만든다.

2. **Execution 누락**
- `plan`의 leaf task와 `execution.leaf_completed_tasks`를 비교해 누락 task를 action 후보(`id_type=task`)로 만든다.

3. **최종본 비어 있음**
- `final_markdown`이 비어 있으면 모든 requirement를 action 후보로 만든다.

## 출력 계약

Reviewer는 아래를 반환한다.

- `actions: list[ActionItem]`
- `ActionItem = { id_type: "task"|"requirement", id: str, action: str, feedback: str }`
  - `id_type=task`: 재실행/재탐색 대상 task id
  - `id_type=requirement`: 보강 대상 requirement id
  - `action`: rerun/refine/expand/drop 중 하나
  - `feedback`: 도메인적으로 부족한 내용을 설명하는 자연어
- `coverage_feedback: dict`
  - `summary`: 4축 판단 요약 문자열
  - `self_assessment`: `query_reflection/plan_reflection/execution_reflection/domain_reflection`별 `pass|revise|fail` + 이유
  - `signals`: 누락 신호 카운트
    - `missing_mapping`, `missing_leaf`, `missing_requirements`, `missing_requirement_task_mapping`, `final_empty`, `action_targets_total`
    - 도메인 커버리지 관련:
      - `domain.total`
      - `domain.used_in_plan`
      - `domain.mentioned_in_final`
      - `domain.missing_in_plan`
      - `domain.missing_in_final`
      - `domain.missing_ids_in_plan`
      - `domain.missing_ids_in_final`
      - `domain.missing_in_evidence`
      - `domain.missing_ids_in_evidence`

예시:

```json
{
  "actions": [
    {
      "id_type": "requirement",
      "id": "DM-CEO-02",
      "action": "refine",
      "feedback": "핵심 사업부 OPM/기여도 정량 근거가 최종본에 반영되지 않음"
    },
    {
      "id_type": "task",
      "id": "T-LEAF-6",
      "action": "rerun",
      "feedback": "최신 공시 기준으로 재탐색 필요"
    }
  ]
}
```

Engine의 `review_status`는 Reviewer가 아니라 `actions` 존재 여부로 계산한다.
LLM 응답이 스키마/형식에 맞지 않으면 Reviewer는 `ValueError`로 fail-fast 한다.

또한 도메인 아키텍처가 활성화된 세션에서:

- 하나 이상의 도메인 모듈이 선택되었지만,
- Plan의 leaf task들에서 해당 모듈의 도구가 사용되지 않았거나,
- 최종 보고서(final markdown)에 도메인 모듈 id/이름이 언급되지 않은 경우,

Reviewer는 LLM 응답에 `actions`가 비어 있더라도 **최소 하나의 action을 강제로 추가**하여
엔진이 재계획(replan)을 수행하도록 강제한다.
