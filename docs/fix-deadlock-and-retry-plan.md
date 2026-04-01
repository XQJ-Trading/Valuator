# Fix: Deadlock from Circular Waits + Web Search Retry

## Context

재귀 에이전트 실행 시 두 가지 연쇄 장애가 발생한다:
1. Perplexity API rate limit으로 web_search 대량 실패 (48건+, 200ms latency)
2. 검색 실패 후 LLM이 형제 태스크 결과를 WAIT → 형제도 동일 → 순환 대기 → deadlock

검색 실패가 근본 트리거이고, 순환 WAIT 허용이 deadlock의 직접 원인이다. 두 문제 모두 경계(boundary) 계층에서 해결한다.

---

## Change 1: Scheduler에 순환 대기 검증 추가

**파일:** `valuator/core/scheduler.py`

### 1-A. `_would_cycle` 메서드 추가

기존 `_dependencies` 그래프에서, `task_id`에 `proposed_deps`를 추가했을 때 cycle이 생기는지 BFS로 검사한다. `proposed_deps` 각각에서 출발해 `_dependencies`를 따라가다 `task_id`에 도달하면 cycle.

```python
def _would_cycle(self, task_id: str, proposed_deps: list[str]) -> bool:
    visited: set[str] = set()
    queue = list(proposed_deps)
    while queue:
        current = queue.pop()
        if current == task_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        queue.extend(self._dependencies.get(current, ()))
    return False
```

### 1-B. `validate_wait` 메서드 추가

`validate_decomposition`과 동일한 패턴. agent가 호출하여 에러 문자열 또는 None을 반환.

```python
def validate_wait(self, task_id: str, wait_for: list[str]) -> str | None:
    unresolved = [
        dep_id for dep_id in wait_for
        if dep_id in self._tasks and self._tasks[dep_id].state != TaskState.DONE
    ]
    if not unresolved:
        return None
    if self._would_cycle(task_id, unresolved):
        cycle_ids = ", ".join(unresolved)
        return f"wait would create circular dependency: {task_id} -> [{cycle_ids}]"
    return None
```

**파일:** `valuator/core/agent.py`

### 1-C. `_step_one`에 WAIT 검증 블록 추가

기존 DECOMPOSE 검증 블록(279-293행) 바로 뒤에 동일 패턴으로 삽입:

```python
if decision.action is Action.WAIT:
    error = self._scheduler.validate_wait(task.id, decision.wait_for)
    if error is not None:
        self._log_step_decision(
            task=task, task_seq=task_seq, ctx=ctx, decision=decision,
            status="failed", started_at=decision_measurement.started_at,
            duration_ms=decision_duration_ms, error=error,
        )
        await self._handle_invalid_step(task, error)
        return
```

`_handle_invalid_step`이 `invalid_decision_count`를 증가시키고 `last_invalid_error`에 에러를 기록한 뒤 READY로 재큐한다. LLM이 다음 step에서 에러를 보고 다른 action(AGGREGATE/FAIL)을 선택하게 된다.

---

## Change 2: Web Search Tool에 재시도 추가

**파일:** `valuator/utils/config.py`

### 2-A. Config 필드 추가

dataclass에 필드 2개 추가 (86-87행 뒤):
```python
web_search_retry_count: int
web_search_retry_base_delay: float
```

`load_config()` 반환값에 추가 (260행 직전):
```python
web_search_retry_count=_as_int(
    read_env("WEB_SEARCH_RETRY_COUNT"), default=2
),
web_search_retry_base_delay=_as_float(
    read_env("WEB_SEARCH_RETRY_BASE_DELAY"), default=2.0
),
```

### 2-B. `_execute_single_search`에 재시도 루프 적용

**파일:** `valuator/tools/web_search_tool.py`

기존 `_execute_single_search` (88-185행)의 try/except 블록을 `gemini_direct.py`의 retry 패턴으로 감싼다:

- `for attempt in range(retry_count + 1):` 루프
- 성공 시 즉시 return
- 실패 시: 마지막 attempt가 아니면 `asyncio.sleep(base_delay * 2**attempt)` 후 재시도
- usage writer 기록 시 재시도면 method에 `.retry{attempt}` suffix 추가
- 마지막 attempt 실패 시 기존과 동일하게 `ToolResult(success=False)` 반환

---

## Change 3: 테스트

**파일:** `tests/test_recursive_agent_scheduler.py`

- `test_validate_wait_detects_direct_cycle` — A→waits B, B→waits A: 에러 반환
- `test_validate_wait_detects_transitive_cycle` — A→B, B→C, C→A: 에러 반환
- `test_validate_wait_allows_non_cyclic` — A→waits B (무순환): None 반환
- `test_validate_wait_skips_done_tasks` — B가 DONE이면 검사 불필요: None 반환

**파일:** `tests/test_web_search_tool.py`

- `test_web_search_retries_on_failure` — ainvoke 2회 실패 후 3회째 성공: success=True, sleep 호출 검증
- `test_web_search_exhausts_retries` — 항상 실패: success=False, retry_count+1회 호출 검증

**파일:** `tests/test_config.py`

- 새 config 필드 기본값 검증 (web_search_retry_count=2, web_search_retry_base_delay=2.0)

---

## 구현 순서

1. `config.py` — config 필드 추가
2. `scheduler.py` — `_would_cycle`, `validate_wait` 추가
3. `web_search_tool.py` — retry 루프 적용
4. `agent.py` — WAIT 검증 블록 추가
5. 테스트 작성 및 실행

## 검증

```bash
python -m pytest tests/test_recursive_agent_scheduler.py tests/test_web_search_tool.py tests/test_config.py -v
python -m pytest tests/ -v  # 전체 테스트 회귀 확인
ruff check .
```
