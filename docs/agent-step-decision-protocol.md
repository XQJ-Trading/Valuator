# 에이전트 스텝 의사결정: 증상 분석·소규모 처방·대규모 리디자인

`step_invalid`와 `deadlock: no tasks ready, not all complete`의 원인·상태·대응 축을 정리한다. 현재 기준점은 `wait_for_facts` 제거 후 parser가 `StepIntentPayload` 하나를 경계 입력으로 받아 `TaskDecision`으로 매핑하는 구조다.

---

## 1. 두 가지 실패

### 1.1 `step_invalid` — 경계에서의 전이 거부

[`parser.py`](../valuator/core/planning/parser.py) `StepIntentPayload`와 `map_intent_to_task_decision`: `decompose`→`children`, `execute`→`tool_request`, `wait`→`wait_for`, `aggregate`→`output`|비어 있지 않은 `facts`, `finalize`→`output`.

흔한 로그: `aggregate`인데 `output/facts` 없이 reason만 있음; `decompose`인데 `children` 없이 `wait_for`만 있음; 이미 tool/child 결과가 있는데 `wait`로 빠짐. 전자는 parser가 child outputs 또는 마지막 성공 tool result로 암묵 집계를 시도하고, `decompose`도 같은 payload가 있으면 집계로 회복한다. [`loop.py`](../valuator/core/agent/loop.py)는 non-root task의 무의미한 `WAIT`(live dependency 없음, 순환 대기인데 이미 산출 가능)를 `AGGREGATE`로 회복하고, 그래도 payload가 없을 때만 `_handle_invalid_step`으로 재시도한다.

### 1.2 `deadlock: no tasks ready, not all complete`

[`scheduler.py`](../valuator/core/scheduler.py) `has_deadlock()` — `not is_complete()` 이면서 `READY`도 `RUNNING`도 없을 때 `True`(남은 일이 있는데 진행 스텝이 없음).

[`loop.py`](../valuator/core/agent/loop.py): `in_flight`가 비었을 때 `has_deadlock()`이면 먼저 [`break_deadlock()`](../valuator/core/scheduler.py)(이미 종료된 의존 태스크만 남은 stale dependency를 정리)를 호출하고, **여전히** `has_deadlock()`일 때만 `RuntimeError`를 던진다.

---

## 2. `concurrency`와 데드락

`Scheduler.concurrency`는 [`ready_tasks()`](../valuator/core/scheduler.py)가 한 번에 `RUNNING`으로 올리는 태스크 수 **상한**(counting semaphore에 가깝다). 병렬도만 제한한다. 데드락은 “슬롯 부족”이 아니라 **태스크 의존이 영원히 풀리지 않는 구성**에 가깝다(§3).

---

## 3. 상태 모델(OS 비유 포함)

| 층 / 비유 | 코드베이스 |
|-----------|------------|
| 스케줄러 상태 | `TaskState`, `_ready_queue`, `_dependencies`, `SharedState` facts/conflicts — 규칙으로 갱신 |
| LLM이 제안하는 전이 | 파싱되면 `TaskDecision` → `apply_decision` |
| 자원 잡고 다음 기다림 | `wait_for` → `_dependencies`, `validate_wait`, `_would_cycle` |
| 데이터 공유 | `aggregate`의 `facts` → `SharedState.publish()` |
| 깨우기 | 의존 태스크 완료/실패 시 `_release_dependents()` / `mark_failed()` |

`step_invalid`는 “LLM 전이”가 스케줄러 규칙에 들어가기 전에 경계에서 걸린 경우다. 같은 실수가 반복되면 `agent_max_invalid_decisions_per_task` 초과 시 해당 태스크는 **FAIL**.

디버깅: 세마포어 “개수”보다 **누가 `READY`가 될 수 있는지, 어떤 엣지가 영원히 만족되지 않는지**를 본다.

### 3.1 로그 인과 예

1. `aggregate`+산출 없음 → child output 또는 tool result로 보강 시도, 실패하면 거절 → 재시도.
2. 유효한 `wait` → `WAITING`, 의존 태스크가 끝날 때까지 `READY` 아님.
3. 전역이 막히면 §1.2의 `has_deadlock` / `break_deadlock` 경로 참고.

`validate_wait`는 `wait_for`가 **실패한 태스크만** 가리킬 때 별도 메시지로 잡을 수 있고, 순환 대기도 사전에 차단한다.

---

## 4. 소규모 처방: 경계 정규화

모델 의도는 연속적이고 프로토콜은 `decompose`/`execute`/`wait`/`aggregate`로 이산적이라 필드 혼합 시 `step_invalid`가 난다. 프롬프트만 늘리는 것은 증상 완화에 가깝다.

**CLAUDE.md:** `normalize`는 경계에서 1회. LLM JSON은 [`parse_decision`](../valuator/core/planning/parser.py)에서 **`normalize_decision_raw` 한 번** 후 Pydantic; `salvage_decision_candidates` 후보도 동일.

### 4.1 규칙 (`normalize_decision_raw`)

| 들어온 모순 | 정규화 |
|-------------|--------|
| `aggregate` + 산출 없음 + `wait_for` 비어 있지 않음 | `wait` |
| `decompose` + `children` 없음/빈 것 + 위와 같은 대기 대상 | `wait` |
| `aggregate` + `output` 또는 비어 있지 않은 `facts` | `aggregate` |

`facts`가 dict가 아니면 집계로 보지 않고 대기만 있으면 `aggregate`→`wait`. `aggregate`인데 산출이 비어 있으면 child outputs 또는 마지막 성공 tool result로 암묵 집계를 시도한다. `decompose`인데 `children`이 비어 있어도 같은 payload가 있으면 집계로 회복한다. 효과: invalid 재시도 루프가 줄어든다. 여전히 남으면 §1.2 `break_deadlock`·순환 WAIT 대응을 본다.

---

## 5. 대규모 리디자인: 런타임이 전이를 소유

### 5.1 구현 상태 (현재 코드)

- **의도 스키마:** [`StepIntentPayload`](../valuator/core/planning/parser.py) — `action` 선택; `tool_request` / `children` / `wait_for` / `output` / `facts` 등과 병행 가능.
- **매퍼:** [`map_intent_to_task_decision`](../valuator/core/planning/parser.py) — explicit `action`이 있으면 그 전이를 우선 해석하고, 없으면 구조 필드 기준으로 `WAIT` → `EXECUTE` → `DECOMPOSE` → `AGGREGATE` 순서로 확정한다.
- **후보:** [`_intent_parse_candidates`](../valuator/core/planning/parser.py) — salvage JSON 우선, 유효 후보 중 구조 필드 있는 쪽 우선.
- **플래너:** [`StepPlanner._decision_schema`](../valuator/core/planning/planner.py) — `StepIntentPayload` 기반 JSON Schema.
- **암묵 집계:** explicit `aggregate`인데 `output/facts`가 비어 있으면 child outputs 또는 마지막 성공 tool result로 보강한다. explicit `decompose`가 비어도 같은 payload가 있으면 집계로 회복한다.
- **WAIT 회복:** non-root task가 이미 tool result/child output을 갖고 있는데 `WAIT`가 live dependency 없이 끝나거나 순환 대기를 만들면 `loop.py`가 `AGGREGATE`로 바꿔 step_invalid 루프를 줄인다.
- **스케줄러:** [`break_deadlock`](../valuator/core/scheduler.py) + §1.2 루프 순서.

### 5.2 목표(미완 전체)

“모델이 `Action`을 맞춘다”가 아니라 **런타임만 합법 전이**; LLM은 의도·데이터만, `decompose`/`wait`/`aggregate` 조합은 코드가 확정한다.

### 5.3 향후 설계 축·범위·트레이드오프

**왜 근본인가:** [`Action`](../valuator/core/types.py) 6종·모드별 상호 배타 필드인데 JSON 한 덩어리로 들어와 연속적 의도와 충돌 — 책임 분리 문제다.

**축 (택일·병합):** **A** 의도 스키마 + `map_intent_to_transition` 한 곳에서 `Action` 확정. **B** 런타임이 `wait` 소유(LLM은 key만). **C** 2-phase(부족 분석 → 실행·산출).

| 영역 | 내용 |
|------|------|
| `types.py` | `TaskDecision`/`Action`·매퍼 출력 |
| `parser.py` | Intent 모델 병행·교체 |
| `planner.py`, `prompts.py` | 스키마·프롬프트 |
| `loop.py` | 매핑 후에만 `apply_decision` |
| `scheduler.py` | WAIT 불변식·데드락 정책 |
| `tests/` | 회귀 |

**트레이드오프:** 프로토콜이 코드에 가깝고 교착·invalid 원인 제거에 유리 / 마이그레이션·로그 포맷 비용 — 플래그 병행 검토.

**§4와:** 정규화는 단기 방패이거나 매퍼 내부 규칙으로 흡수; 최종적으로 LLM이 액션 문자열을 직접 고르지 않게 만드는 쪽이 목표다.

---

## 6. 구현 체크리스트

1. ~~**경계:** `StepIntent` + 매퍼로 `TaskDecision` 단일 소스(§5.1 수준 구현).~~
2. ~~**스케줄러:** `break_deadlock` + 루프에서 선호출(§1.2).~~
3. **명세:** 의도 스키마·런타임 전이를 TS/ADR 수준으로 고정 문서화(남은 작업).
4. **불변식:** 데드락 불가 조건·타임아웃·부모 승격 등을 스케줄러에 추가로 명시·강제할지 검토.
5. **마이그레이션:** gate·트레이스·플래너 나머지 정리 및 회귀.

---

## 7. 요약

| 증상 | 소규모 | 대규모(§5.3) |
|------|--------|--------------|
| `step_invalid` | §4 정규화 | 의도·매퍼·스케줄러 불변식으로 전이 소유 |
| `deadlock` | §4로 연쇄 완화 + §1.2 `break_deadlock` | `wait` 런타임 소유·그래프 불변식(5.3-B) |

`concurrency`는 동시 실행 상한일 뿐, 이 데드락의 직접 원인이 되기 어렵다(§2).
