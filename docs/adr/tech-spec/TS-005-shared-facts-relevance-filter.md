# TS-005: SHARED_FACTS 태스크 관련성 필터링

## Context

현재 `[SHARED_FACTS]`는 전체 fact를 필터 없이 모든 태스크에 주입한다. step_0130 사례에서 24,747 prompt tokens 중 ~54%가 현재 태스크와 무관한 peer 기업 밸류에이션 데이터였다. fact의 데이터 축(subject, metric, time, qualifier)은 다양하므로, 도메인 특화 필터 대신 이미 존재하는 메타데이터(task_id 계보 + query_unit_ids)를 활용해 일반적으로 필터링한다.

## Approach: 2단 필터 (서브트리 + query_unit_ids)

### Filter 1: 서브트리 소속 (task_id prefix)

- `source_task_id`가 현재 태스크와 같은 서브트리에 속하면 관련 fact
- 예: `root.0.1` 태스크 → `root.0.*`에서 발행된 fact는 포함, `root.2.*`는 제외
- 직계 조상 체인(`root.0`, `root`)에서 발행된 fact도 포함

### Filter 2: query_unit_ids 교집합

- Fact에 `query_unit_ids` 필드 추가 (발행 태스크의 query_unit_ids 전파)
- 현재 태스크의 query_unit_ids와 교집합이 있으면 관련 fact
- query_unit_ids가 빈 fact는 전역 fact로 간주하여 항상 포함

### 합산 규칙

두 필터는 **OR** 결합: 서브트리 소속이거나 query_unit 교집합이 있으면 포함. 이유: aggregate 태스크는 다른 서브트리의 fact가 필요할 수 있는데, 같은 query_unit을 공유하면 접근 가능해야 한다.

## Changes

### 1. `Fact`에 `query_unit_ids` 추가

**File:** `valuator/core/shared_state.py`

```python
@dataclass(frozen=True)
class Fact:
    key: str
    value: Any
    source_task_id: str
    query_unit_ids: tuple[int, ...] = ()   # NEW
    grounded: bool = False
    # ... rest unchanged
```

`SharedState.publish()`에 `query_unit_ids` 파라미터 추가.

`SharedState`에 `view_for()` 메서드 추가:

```python
def view_for(self, *, task_id: str, query_unit_ids: list[int]) -> SharedStateView:
    unit_set = set(query_unit_ids)
    subtree_prefix = _subtree_prefix(task_id)  # "root.0" for "root.0.1"
    ancestry_prefixes = _ancestry_prefixes(task_id)  # ["root.0", "root"]

    relevant = {
        k: f for k, f in self._facts.items()
        if _is_relevant(f, subtree_prefix, ancestry_prefixes, unit_set)
    }
    return SharedStateView(facts=relevant, conflicts=self._conflicts)
```

`_is_relevant` 판정:
- `source_task_id`가 `subtree_prefix`로 시작 → True
- `source_task_id`가 ancestry_prefixes 중 하나와 정확히 일치 → True
- fact의 `query_unit_ids`와 `unit_set`에 교집합 → True
- fact의 `query_unit_ids`가 비어있음 → True (전역)
- 그 외 → False

### 2. publish 호출부에 query_unit_ids 전파

**File:** `valuator/core/scheduler.py` (lines 161-175)

`shared.publish()` 호출 시 `task.query_unit_ids`를 전달:

```python
shared.publish(
    key, fact_value, task.id,
    query_unit_ids=tuple(task.query_unit_ids),  # NEW
    grounded=grounded,
    ...
)
```

**File:** `valuator/core/agent/loop.py` (lines 830-832)

`_force_finalize`에서도 동일하게 전파:

```python
self._shared.publish(
    key, value, source_task_id=task.id,
    query_unit_ids=tuple(task.query_unit_ids),  # NEW
)
```

### 3. context_builder에서 `view()` → `view_for()` 전환

**File:** `valuator/core/agent/context_builder.py` (line 50)

```python
shared=shared.view_for(
    task_id=task.id,
    query_unit_ids=task.query_unit_ids,
),
```

### 4. CURRENT_CHILDREN output 중복 제거

**File:** `valuator/core/agent/context_builder.py` (lines 35-47)

`TaskSummary.output`에 full payload를 넣는 대신, `child_outputs`에 이미 있으면 output을 None으로:

```python
current_children=[
    TaskSummary(
        id=child.id,
        description=child.description,
        state=child.state,
        output=(
            child.completion_payload()
            if child.state is TaskState.DONE and child.id not in task.child_outputs
            else None
        ),
    )
    for child in task.children()
],
```

### 5. fact line 렌더링 간소화 — 메타데이터 제거

**File:** `valuator/core/planning/prompts.py`

현재 `shared_fact_line()`이 매 fact마다 `(from root.2.0.1, grounded=False, time_scope=최근 5년 밴드)` 같은 메타데이터를 붙인다. 이 정보는:
- `source_task_id` — 내부 라우팅 경로, LLM에게 무의미
- `grounded` — 시스템 프롬프트에서 이미 일괄 지시, 매 line 반복 불필요
- `time_scope` — `[TEMPORAL_CONTRACT]`와 query unit에 이미 존재하는 중복
- `sources=N` — 소스 개수만으로는 의미 없음

필터링이 context_builder에서 완결되므로, 프롬프트에는 key:value만 렌더링한다:

```python
def shared_fact_line(*, key: str, fact: Any) -> str:
    return f"{key}: {render_prompt_value(fact.value)}"
```

메타데이터는 디버그 로그(step JSON)에 이미 Fact 객체로 남아있으므로 추적성 손실 없음.

## Files to Modify

1. `valuator/core/shared_state.py` — Fact.query_unit_ids, SharedState.view_for(), helper functions
2. `valuator/core/scheduler.py` — publish 호출에 query_unit_ids 전달
3. `valuator/core/agent/loop.py` — _force_finalize publish에 query_unit_ids 전달
4. `valuator/core/agent/context_builder.py` — view() → view_for(), CURRENT_CHILDREN 중복 제거
5. `valuator/core/planning/prompts.py` — shared_fact_line() 간소화

## Files NOT Modified

- `valuator/core/context.py` — TaskContext.shared 타입 변경 없음.

## Verification

1. `python -m pytest tests/` — 기존 테스트 통과
2. `tests/test_step_planner.py` — shared facts 관련 기존 테스트 확인
3. 수동 검증: step_0130 시나리오 재현 — root.0.1 태스크에 root.2.* facts가 제외되는지 확인
4. 엣지 케이스: root 태스크(query_unit_ids=[], task_id="root")는 모든 fact를 봐야 함 → view_for에서 빈 unit_ids + root prefix면 전체 반환
