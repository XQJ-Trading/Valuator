# Plan: reason 제거 + LLM 출력 제한

## Context

`step_planner.py`가 매 step마다 LLM에게 "action 선택 + reason 자유서술 + payload"를 요청한다.
Gemini Flash가 `reason` 필드에서 반복 루프에 빠져 256KB+ 응답을 생성했다.

`reason`은 상태 전이에 쓰이지 않는 순수 정보성 필드인데, 모델이 메타 독백을 쏟아내는 side channel이 됐다.
제거하면 모델은 action + 구조화된 payload만 생성하게 되어 반복 루프 표면이 사라진다.

---

## 변경 사항

### 1. `valuator/core/types.py` — reason 제거

`TaskDecision`에서 `reason: str = ""` 필드 삭제.

### 2. `valuator/core/step_planner.py` — reason 제거 + repair 단순화

- `_TaskDecisionPayload`에서 `reason` 필드 제거
- `_system_prompt()`: "Keep reason concise" 문구 제거
- `_build_repair_prompt()`:
  - `[ORIGINAL_STEP_PROMPT]` 포함 제거 — repair 프롬프트가 원본 전체를 다시 넣으면서 메타 지시가 누적되는 문제 차단
  - task_id + validation_error + "Return corrected JSON only"만 남김
- `_parse_decision()`: reason 매핑 제거

### 3. `valuator/models/gemini_direct.py` — max_output_tokens 추가

- `generate()`, `generate_json()`, `_build_config()`에 `max_output_tokens: int | None = None` 파라미터 추가
- `_build_config()`에서 `GenerateContentConfig(max_output_tokens=...)` 전달
- 이것은 API 레벨 생성 제한 — 사후 검증(`len(raw) > max_response_chars`)과 별개로, 생성 시점에서 반복 루프를 물리적으로 차단
- `step_planner.py`의 `_generate_decision()`에서 적절한 값 전달 (action 선택은 짧으므로 8192 정도)

### 4. 참조 정리

| 파일 | 변경 |
|------|------|
| `scheduler.py:164` | `decision.reason or "task failed"` → `"task failed"` (또는 LLM이 FAIL 시 별도 error 필드 사용) |
| `agent.py:376` | event detail에서 `"reason": decision.reason` 제거 |
| `agent.py:402,408` | `decision.reason` → `task.error` (이미 `mark_failed`에서 설정됨) |
| `decomposition_critic.py` | `last_reason` 참조 제거 |
| `session_trace.py` | `reason` 파라미터 유지하되 None 전달 (기존 로그 호환) |

### 5. FAIL action의 error 메시지

`reason` 제거 후 FAIL의 에러 메시지 전달 방법:
- `scheduler.apply_decision()`의 FAIL case: `self.mark_failed(task, "task failed")`
- LLM이 FAIL을 선택할 때 사유를 전달해야 하면 — `_TaskDecisionPayload`에 `error: str = ""` 필드 추가 (FAIL 전용, reason과 달리 action-specific 구조화 필드)
- `TaskDecision`에도 동일하게 `error: str = ""` 추가

---

## 구현 순서

1. `gemini_direct.py` — `max_output_tokens` 파라미터 추가
2. `types.py` — `TaskDecision`에서 `reason` 제거, `error: str = ""` 추가
3. `step_planner.py` — `_TaskDecisionPayload` reason 제거, error 추가, repair 단순화, `max_output_tokens` 전달
4. `scheduler.py` — FAIL case에서 `decision.reason` → `decision.error`
5. `agent.py` — `decision.reason` 참조 제거
6. 나머지 참조 정리 (critic, session_trace)
7. 테스트 업데이트

---

## 검증

- `python -m pytest tests/test_step_planner.py`
- `python -m pytest tests/test_recursive_agent_scheduler.py`
- `python -m pytest tests/test_session_trace.py`
- `python -m pytest tests/`
- `ruff check . && ruff format .`
