# 작업 시스템 (Task & AtomicTask)

## Task 기본

모든 작업의 기본 클래스. **상태 머신**으로 작동.

```python
class Task(ABC):
    id: str                          # 작업 고유 ID
    description: str                 # 사람이 읽을 수 있는 설명
    task_name: str                   # 간단한 이름 (30자 제한)
    
    # 상태
    state: TaskState                 # CREATED, READY, RUNNING, WAITING, DONE, FAILED
    
    # 실행 결과
    tool_results: list[ToolResult]   # 지금까지의 도구 실행 결과
    tool_failure_counts: dict        # 도구별 실패 횟수
    output: Any                      # 최종 출력
    error: str | None               # 실패 이유
    
    # 의존성 & 계층
    parent_id: str | None           # 부모 작업 ID
    child_outputs: dict             # 자식 출력들 {child_id: output}
    
    # 공개된 사실들
    published_facts: dict[str, Any] # AGGREGATE 시 발행한 팩트
    
    # 쿼리 추적
    query_unit_ids: list[int]       # 이 작업이 담당하는 질의 단위들
```

### 상태 전이 다이어그램

```
CREATED
  ↓ (register with no deps)
READY
  ├→ [Plan] → DECOMPOSE ─→ ComplexTask로 승격 → WAITING (자식 생성)
  ├→ [Plan] → EXECUTE ─────────────→ RUNNING (도구 실행)
  │                              ↓ (tool result)
  │                           READY (다시)
  ├→ [Plan] → AGGREGATE ───────────→ DONE (팩트 발행)
  ├→ [Plan] → FINALIZE ────────────→ DONE
  └→ [Plan] → FAIL ─────────────────→ FAILED

WAITING
  ├→ (dependencies done) → READY
  └→ (ancestor fails) → FAILED

RUNNING
  ├→ (tool result) → READY
  └→ (tool error) → READY (다시 계획)

DONE / FAILED (terminal)
```

## AtomicTask

도구 실행이 필요한 작업. **분해 불가능**.

```python
class AtomicTask(Task):
    def children(self) -> list[Task]:
        return []  # 항상 빈 리스트
    
    def add_child(self, child: Task) -> None:
        raise TypeError("AtomicTask cannot have children")
```

**사용 사례**:
- 웹 검색 수행
- 코드 실행
- SEC 문서 조회
- 재무 데이터 조회

**특징**:
- Tool hint를 가짐 (어떤 도구를 사용할지 힌트)
- tool_results 리스트 업데이트
- LLM이 도구 다시 호출할지 결정

## ComplexTask

자식 작업으로 분해 가능. **순수 조정자**.

```python
class ComplexTask(Task):
    _children: list[Task]
    
    def children(self) -> list[Task]:
        return list(self._children)
    
    def add_child(self, child: Task) -> None:
        child.parent_id = self.id
        self._children.append(child)
```

**사용 사례**:
- 루트 작업
- 질의 분해 필요한 중간 작업
- 여러 하위 분석 조정

**특징**:
- 도구 실행 없음 (tool_hint 없음)
- child_outputs에 자식 결과 수집
- 모든 자식 완료 시 READY로 전환

## 작업 생성

### Scheduler에서 동적 생성

```python
# TaskSpec으로 자식 명세
spec = TaskSpec(
    description="Apple의 2024 수익 조회",
    task_name="search_revenue",
    tool_hint="web_search",  # 도구 실행 필요 → AtomicTask
    depends_on_siblings=[0],  # 첫번째 형제 완료 후 시작
    query_unit_ids=[0, 1],    # 어떤 질의 단위 담당
)

# Scheduler가 생성
child_task = scheduler._create_children(parent, [spec])
# → AtomicTask (tool_hint 있음) 또는 ComplexTask (tool_hint 없음)
```

### 초기 루트 작업

```python
root = ComplexTask(
    id="root",
    description="분석 쿼리 실행",
    decide=planner.decide,  # 단계 결정 콜백
)
```

## 실행 흐름

### AtomicTask → 도구 실행

```
State: READY
  ↓
[Plan] → TaskDecision(EXECUTE, tool_request)
  ↓
[Agent] tool_registry.execute(tool_request)
  ↓
State: RUNNING → READY (tool_results 추가)
  ↓
[Plan] 다시 → AGGREGATE 또는 EXECUTE
```

### ComplexTask → 자식 분해

```
State: READY
  ↓
[Plan] → TaskDecision(DECOMPOSE, children=[spec1, spec2])
  ↓
[Scheduler] 자식 생성 + 등록
  ↓
State: WAITING (모든 자식 완료까지)
  ↓
[Scheduler] (자식 DONE) → READY
  ↓
[Plan] → AGGREGATE (child_outputs 병합)
```

## 중요 메서드

### `completion_payload()`
이 작업이 부모에게 전달할 결과:

```python
def completion_payload(self) -> Any:
    if self.output is not None:
        return self.output
    if self.published_facts:
        return {
            "status": "facts_only",
            "facts": dict(self.published_facts),
        }
    return None
```

### `implicit_aggregate_payload()`
자동 집계 시 계산되는 output과 facts:

```python
def implicit_aggregate_payload(self) -> tuple[Any, dict[str, Any]]:
    # 모든 자식이 facts_only면 병합
    if all_children_facts_only:
        return None, merged_facts
    
    # 마지막 도구 결과 사용
    if self.last_tool_success:
        return self.tool_results[-1].result, {}
    
    return None, {}
```

## 의존성

작업 간 의존성은 Scheduler가 관리:

```python
# 시블링 의존성 (같은 부모의 자식들 간)
TaskSpec(
    description="B",
    depends_on_siblings=[0],  # 인덱스 0 (첫번째)의 자식이 완료 후 시작
)

# 크로스 태스크 의존성 (WAIT 행동)
TaskDecision(
    action=Action.WAIT,
    wait_for=("task.1.0", "task.2.0"),  # 이 두 작업 완료까지 대기
)
```

## 쿼리 단위 추적

작업이 원래 질의의 어느 부분을 담당하는지 추적:

```python
# 루트 작업이 질의 0, 1, 2 담당
root = ComplexTask(..., query_unit_ids=[0, 1, 2])

# 자식 생성 시 부분 할당
spec = TaskSpec(
    description="...",
    query_unit_ids=[0, 1],  # 부모의 [0,1,2] 중 [0,1] 담당
)
# Scheduler가 검증: unknown_ids가 없어야 함
```
