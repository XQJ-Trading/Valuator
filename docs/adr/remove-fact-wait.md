# ADR: Scheduler에서 Fact-based Wait 제거

## 상태: 제안됨

## 배경

Scheduler는 태스크 실행 순서를 관리한다. 현재 태스크가 대기하는 메커니즘이 두 가지 존재한다:

1. **Task dependency** (`depends_on_siblings` / `wait_for`): 구조적 의존. DECOMPOSE 시점에 선언. `_dependencies`/`_dependents`로 관리. `_would_cycle`로 순환 검출.
2. **Fact subscription** (`wait_for_facts`): 동적 의존. 런타임에 LLM이 fact key 문자열로 구독. `Scheduler._waiting_facts` + `SharedState._fact_waiters`로 이중 관리. 순환 검출 없음.

---

## 문제

### 1. Scheduler의 책임 침범: 순서 관리 → 내용 기반 스케줄링

Scheduler의 원래 역할은 "누가 먼저, 누가 나중에" — 순서만 관리하는 것이다.

`wait_for_facts`가 도입되면서 Scheduler가 **fact key의 의미**(= 태스크가 생산하는 데이터의 내용)를 알아야 스케줄링할 수 있게 됐다.

```
# scheduler.py:512-528 — Scheduler가 도메인 데이터의 temporal suffix를 조합
@staticmethod
def _fact_key_for_task(key: str, *, ctx: TaskContext | None) -> str:
    temporal = summarize_temporal_contract(...)
    canonical_suffix = f"@{temporal.target_start}:{temporal.target_end}"
    if temporal.time_scope == "historical" and ...:
        return f"{key}{canonical_suffix}"
    return key
```

Scheduler가 `temporal_contract`, `time_scope`, `target_start`/`target_end` 같은 도메인 개념을 해석하고 있다. 이는 순서 관리 책임을 넘어선다.

**원래 의도한 경계:**
- Scheduler: "누가 먼저, 누가 나중에" (순서)
- SharedState: "태스크가 생산한 데이터를 공유" (내용)

**현재 상태:**
- SharedState의 fact key가 Scheduler의 스케줄링 조건으로 침투
- `_waiting_facts`, `_fact_waiters`, `drain_waiters`, `subscribe` — 모두 "내용 기반 스케줄링"을 위한 배관

### 2. 이중 추적(Dual Tracking)으로 인한 동기화 부담

동일한 "task X가 fact Y를 기다린다"는 정보가 두 곳에 존재한다:

| 저장소 | 자료구조 | 방향 |
|--------|---------|------|
| `Scheduler._waiting_facts` | `dict[str, set[str]]` (task_id → fact_keys) | "이 태스크가 어떤 fact를 기다리는가" |
| `SharedState._fact_waiters` | `dict[str, set[str]]` (fact_key → task_ids) | "이 fact를 어떤 태스크가 기다리는가" |

역방향 인덱스다. 모든 상태 변경(`apply_decision`의 매 Action)에서 양쪽을 동기적으로 정리해야 한다:

```
# apply_decision 내 — 모든 Action 분기의 첫 두 줄
shared.remove_task_waits(task.id)      # SharedState 쪽 정리
self._waiting_facts.pop(task.id, None)  # Scheduler 쪽 정리
```

DECOMPOSE, EXECUTE, WAIT, AGGREGATE, FINALIZE, FAIL — 6개 분기 모두에 이 정리 코드가 반복된다.

### 3. Fact Wait 순환에 의한 Deadlock

Task dependency는 `_would_cycle`(scheduler.py:357-368)로 순환을 검출한다. Fact subscription에는 순환 검출이 **없다**.

```
Task A: wait_for_facts=["alpha"]  (B만 생산 가능)
Task B: wait_for_facts=["beta"]   (A만 생산 가능)
→ 교착: 둘 다 영원히 WAITING
```

이 deadlock은 LLM이 독립적으로 내린 두 결정이 문자열 매칭으로 얽히면서 발생한다. 시스템이 이를 사전에 감지할 방법이 없다.

### 4. 복구 메커니즘의 존재가 설계 결함을 증명한다

Fact wait deadlock을 처리하기 위해 3단계 복구 코드가 존재한다:

**1단계 — `_release_sibling_fact_waiters`** (scheduler.py:449-453):
태스크 완료 시 형제 중 CREATED/READY/RUNNING이 없으면 남은 fact waiter를 강제 해제.

**2단계 — `_flush_sibling_fact_waiters_under_parent`** (scheduler.py:455-468):
`break_deadlock`에서 모든 ComplexTask 부모에 대해 1단계를 반복 실행.

**3단계 — `break_deadlock` phase 3** (scheduler.py:106-116):
위 두 단계로도 해결 안 되면, dependency 없이 fact만 기다리는 **모든** 태스크를 일괄 강제 해제.

```
# break_deadlock phase 3 — 무차별 해제
for task_id in list(self._tasks.keys()):
    ...
    if not self._waiting_facts.get(task_id):
        continue
    shared.remove_task_waits(task_id)
    self._waiting_facts.pop(task_id, None)
    self._maybe_ready(task_id, newly_ready)
```

강제 해제된 태스크는 **기다리던 데이터 없이** 재개된다. 정확도 저하.

coordination 메커니즘에 전용 복구 코드가 3단계 필요하다면, 그 메커니즘은 근본적으로 취약하다.

### 5. LLM의 Fact Key 예측 의존 — 취약한 계약

`wait_for_facts`가 작동하려면 소비자 태스크의 LLM이 생산자 태스크가 publish할 **정확한 fact key 문자열**을 알아야 한다.

두 독립적 LLM 호출이 문자열 매칭으로 연결되는 구조다:
- 생산자: `facts={"revenue_2024": ...}` → publish
- 소비자: `wait_for_facts=["revenue_2024"]` → subscribe

key가 `revenue_2024`와 `revenue_FY2024`처럼 조금만 달라도 소비자는 영원히 블로킹된다. 시스템의 정확성이 LLM의 문자열 일관성에 의존한다.

---

## 결정: Fact-based Wait 제거

### 유지하는 것

| 대상 | 이유 |
|------|------|
| `depends_on_siblings` / `wait_for` | 구조적 task dependency. 순환 검출 있음. Scheduler의 본래 책임 |
| `SharedState.publish()` + fact 저장 | 태스크 간 데이터 공유. 스케줄링과 무관하게 유지 |
| `SharedStateView` | context에서 기존 fact 조회. 읽기 전용 |
| Conflict detection | 데이터 품질 검증 |
| `break_deadlock` phase 2 | stale dependency 해제 (fact wait과 무관한 실제 버그 방지) |

### 제거하는 것

| 대상 | 파일 |
|------|------|
| `_waiting_facts` dict + 모든 관련 로직 | `scheduler.py` |
| `_fact_waiters`, `subscribe()`, `drain_waiters()`, `remove_task_waits()` | `shared_state.py` |
| `_release_sibling_fact_waiters()`, `_flush_sibling_fact_waiters_under_parent()` | `scheduler.py` |
| `break_deadlock` phase 1, 3 | `scheduler.py` |
| `_maybe_ready`에서 `_waiting_facts` 체크 | `scheduler.py` |
| `wait_for_facts` 필드 | `types.py` TaskDecision |
| `_TaskDecisionPayload.wait_for_facts`, `_RawIntent.wait_for_facts` | `planning/parser.py` |
| StepPlanner 프롬프트의 `wait_for_facts` 옵션 | `planning/prompts.py` |
| `_fact_key_for_task()` | `scheduler.py` (fact key에 temporal suffix 붙이는 도메인 침범 제거) |

### 제거 후 Scheduler의 readiness 판단

```
# 변경 전 — _maybe_ready
if self._dependencies.get(task_id):    # task dependency 미해소
    return
if self._waiting_facts.get(task_id):   # fact wait 미해소
    return
self._mark_ready(task, newly_ready)

# 변경 후 — _maybe_ready
if self._dependencies.get(task_id):    # task dependency 미해소만 확인
    return
self._mark_ready(task, newly_ready)
```

### "동적으로 데이터가 필요한 경우"의 대안

Fact wait의 유일한 장점은 런타임에 동적으로 의존성을 선언할 수 있다는 점이다. 이 시나리오는 기존 메커니즘으로 대체 가능하다:

1. **DECOMPOSE 시 `depends_on_siblings`로 선언**: 대부분의 경우 어떤 자식이 어떤 자식의 결과를 필요로 하는지 분해 시점에 알 수 있다.
2. **부모의 AGGREGATE → 재분해**: 부모가 자식 결과를 집계한 후 추가 정보가 필요하면 다시 DECOMPOSE할 수 있다. 이미 지원되는 패턴이다.
3. **SharedState 읽기**: fact은 여전히 SharedState에 publish된다. 태스크가 다음 step에서 context를 통해 최신 fact를 읽을 수 있다. "기다림" 없이 "있으면 사용, 없으면 없는 대로 진행."

---

## Stale Context 문제에 대한 판단

별도로 제기된 stale context 문제 (LLM 호출 동안 다른 태스크가 상태를 변경)는 이번 변경 범위에 포함하지 않는다.

**이유**: `_propagate_completion`(scheduler.py:410-432)이 부모를 모든 자식이 terminal 상태가 된 후에만 READY로 만든다. 부모의 AGGREGATE 시점에 자식이 일부만 완료된 스냅샷으로 결정하는 시나리오는 발생하지 않는다. 형제 간 stale context는 최적화 기회 손실이지 정확성 오류가 아니다.

---

## 부수 변경: Session I/O 비동기화

`SessionStore`와 `SessionTraceWriter`의 동기 파일 I/O(`threading.RLock` + 동기 쓰기)가 asyncio 이벤트 루프를 블로킹한다. `_sync_session_tree()`는 매 step마다 호출되며 전체 태스크 트리를 재귀 순회한다.

`asyncio.to_thread()`로 래핑하여 이벤트 루프 블로킹을 해소한다. Fact wait 제거와 독립적이지만, 같은 맥락(Scheduler 동작 안정화)에서 함께 처리한다.
