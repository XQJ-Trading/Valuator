# 스케줄링 교착(Deadlock)과 전역 정지 — 통합 가이드

에이전트 실행이 **진행 중인 태스크는 없는데(READY/RUNNING 없음)** 아직 **완료도 아닌** 상태로 멈춘 현상, **순환 대기**, **과거 fact-wait 교착**, **검색 실패·재시도**까지 **한 문서**에서 정리한다.  
(`step_invalid`·parser 정규화·의도 스키마는 [agent-step-decision-protocol.md](agent-step-decision-protocol.md)가 본문이다.)

---

## 1. 용어: 두 가지 “막힘”

| 구분 | 의미 | 문서 |
|------|------|------|
| **`step_invalid`** | LLM JSON이 경계에서 거절되어 **한 태스크**의 전이가 적용되지 않음 | [agent-step-decision-protocol §1.1](agent-step-decision-protocol.md) |
| **스케줄링 교착** (`deadlock: no tasks ready, not all complete`) | **전역**적으로 READY/RUNNING이 없고, 전체 완료도 아님 | 이 문서 §2 |

둘 다 로그에서 동시에 논의되지만, 원인과 대응 축이 다르다.

---

<a id="global-deadlock"></a>

## 2. 전역 교착: `has_deadlock()`과 루프 복구

### 2.1 정의

[`scheduler.py`](../valuator/core/scheduler.py)의 `has_deadlock()` — `not is_complete()`인데 **READY도 RUNNING도 없을 때** `True`.  
즉 “남은 일이 있는데 다음에 돌릴 태스크가 없다.”

### 2.2 에이전트 루프에서의 처리

[`loop.py`](../valuator/core/agent/loop.py): 비행 중(`in_flight`) 작업이 비었을 때 `has_deadlock()`이면 **먼저** [`break_deadlock()`](../valuator/core/scheduler.py)을 호출한다.  
이미 종료된 의존 태스크만 남은 **stale dependency** 등을 정리한 뒤, **그래도** `has_deadlock()`이면 `RuntimeError`로 fail-fast한다.

순서: **`break_deadlock` 선호출 → 재판단 → 여전히 교착이면 예외.**

---

<a id="concurrency-vs-deadlock"></a>

## 3. `concurrency`는 교착의 원인이 아니다

`Scheduler.concurrency`는 [`ready_tasks()`](../valuator/core/scheduler.py)가 한 번에 `RUNNING`으로 올리는 태스크 수 **상한**(세마포에 가깝다). **병렬도만** 제한한다.

교착은 “슬롯 부족”이 아니라 **태스크 의존 관계가 영원히 풀리지 않는 구성**에 가깝다. 디버깅할 때는 세마포 “개수”보다 **누가 READY가 될 수 있는지, 어떤 엣지가 만족되지 않는지**를 본다.

---

## 4. 과거: Fact 기반 대기(`wait_for_facts`)와 교착

`wait_for_facts`로 SharedState fact key를 구독해 readiness를 섞던 시절에는, **task dependency**와는 별도로 **문자열 매칭**이 얽히며 교착이 생길 수 있었고, 순환 검출도 어렵다 — [remove-fact-wait ADR](adr/remove-fact-wait.md) §3.

**현재 방향**: fact 구독 기반 스케줄링은 제거하고, 대기는 **`wait_for`(task id)** 등 **구조적 의존**으로만 표현한다. 상세·근거는 ADR 본문.

---

## 5. 순환 WAIT · 검색 실패 연쇄 (설계·완화)

LLM이 `WAIT`를 제안할 때 형제 태스크 간 **순환 의존**이 생기면 전역적으로 READY가 비어버릴 수 있다. 예: 검색 도구가 대량 실패한 뒤, 서로의 결과를 기다리며 순환 대기.

### 5.1 스케줄러 측: 순환 검증

의도(과거·현재 구현 논의 요지):

- `_dependencies` 그래프에 대해, `wait_for` 후보를 추가했을 때 **cycle**이 생기는지 검사(`_would_cycle` 등).
- `validate_wait(task_id, wait_for)`가 순환·무결성 오류 문자열을 반환하면, 에이전트는 해당 step을 invalid 처리하고 재질의할 수 있다.

구체 시그니처·라인 번호는 코드 [`scheduler.py`](../valuator/core/scheduler.py)를 본다.

### 5.2 경계 측: 도구 실패 완화

`web_search` 등 외부 API rate limit·일시 실패는 **재시도·백오프**로 완화하고, 불필요한 `WAIT` 연쇄를 줄인다 — 설정·도구 구현은 `valuator/utils/config.py`, `valuator/tools/web_search_tool.py` 등.

(과거 계획 문서에 있던 단계별 체크리스트는 이 절로 흡수했다.)

---

## 6. `step_invalid`·경계 정규화와의 관계

모델 출력이 필드 혼합으로 자주 거절되면 재시도·상태 꼬임이 늘고, 간접적으로 **전역 정지**로 이어질 수 있다.  
**소규모 처방**은 parser에서 `normalize_decision_raw` **1회** 등 — [agent-step-decision-protocol §4](agent-step-decision-protocol.md).

여전히 막히면 §2의 `break_deadlock`·순환 `WAIT`·`loop`의 회복 로직을 함께 본다.

---

## 7. 상태 모델 요약 (스케줄러 관점)

| 비유 / 층 | 코드베이스 |
|-----------|-------------|
| 스케줄러 상태 | `TaskState`, `_ready_queue`, `_dependencies`, SharedState facts/conflicts |
| LLM이 제안하는 전이 | 파싱 후 `TaskDecision` → `apply_decision` |
| 대기 | `wait_for` → `_dependencies`, `validate_wait`, 순환 검사 |
| 데이터 공유 | `aggregate`의 `facts` → `SharedState.publish()` |
| 깨우기 | 의존 태스크 완료/실패 시 의존 해소 |

`validate_wait`는 `wait_for`가 **실패한 태스크만** 가리키는 경우 등을 별도 메시지로 잡을 수 있다 — [agent-step-decision-protocol](agent-step-decision-protocol.md) §3.

---

## 8. 요약 표

| 증상 | 먼저 볼 것 |
|------|------------|
| 전역 `deadlock` 메시지 | §2 `break_deadlock`·루프 순서, §5 순환 `WAIT` |
| `step_invalid` 반복 | [agent-step-decision-protocol §4](agent-step-decision-protocol.md) 정규화 |
| 과거 fact 문자열 대기 | [remove-fact-wait](adr/remove-fact-wait.md) |
| 병렬도 부족처럼 보임 | §3 — `concurrency`는 교착 직접 원인이 아님 |

---

## 9. 관련 문서·코드

| 항목 | 위치 |
|------|------|
| Parser·정규화·대규모 리디자인 | [agent-step-decision-protocol.md](agent-step-decision-protocol.md) |
| Fact-wait 제거 ADR | [adr/remove-fact-wait.md](adr/remove-fact-wait.md) |
| 스케줄러 | [`valuator/core/scheduler.py`](../valuator/core/scheduler.py) |
| 루프 | [`valuator/core/agent/loop.py`](../valuator/core/agent/loop.py) |
