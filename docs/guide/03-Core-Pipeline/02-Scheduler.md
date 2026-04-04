# 스케줄러 (Scheduler)

작업 상태 관리와 의존성 추적 담당. **순수 의존성 관리자**.

## 핵심 책임

1. 작업 등록 및 상태 관리
2. 다음 실행할 작업 선택 (concurrency 제한)
3. 작업 간 의존성 추적
4. 의사 결정(TaskDecision) 적용
5. 교착 상태(deadlock) 감지 및 해제

## 초기화

```python
scheduler = Scheduler(
    max_steps_per_task=20,      # 작업당 최대 단계 수
    concurrency=4,               # 동시 실행 작업 수
)
```

## API

### register(task, depends_on)
작업 등록 및 의존성 설정:

```python
scheduler.register(root_task)
scheduler.register(child_task, depends_on=["parent.0", "parent.1"])

# 내부:
# 1. task를 저장
# 2. 의존성 있으면 _dependencies[task.id] 설정
# 3. 의존성 없으면 task.state = READY
# 4. task를 _ready_queue에 추가
```

### ready_tasks(limit)
다음 실행할 작업들 반환 (concurrency 제한):

```python
ready = scheduler.ready_tasks()        # 최대 4개 (concurrency)
ready = scheduler.ready_tasks(limit=2) # 최대 2개

# 내부:
# 1. _ready_queue에서 task_id 꺼냄
# 2. task.state == READY 확인
# 3. max_ready만큼만 반환
```

### apply_decision(task, decision, shared_state)
TaskDecision을 적용하여 상태 업데이트:

```python
newly_ready = scheduler.apply_decision(
    task,
    TaskDecision(action=Action.DECOMPOSE, children=(...)),
    shared_state,
)
# newly_ready: 새로 READY 상태가 된 task id들
```

**각 Action별 처리**:

| Action | 효과 |
|--------|------|
| DECOMPOSE | task 승격 (Atomic→Complex) + 자식 생성 + task 상태 WAITING |
| EXECUTE | task 상태 RUNNING |
| WAIT | task 상태 WAITING + 의존성 설정 |
| AGGREGATE | task 상태 DONE + 팩트 발행 + 의존 작업 해제 |
| FINALIZE | task 상태 DONE + 의존 작업 해제 |
| FAIL | task 상태 FAILED + 자식/의존 작업에 전파 |

### mark_tool_complete(task, result)
도구 실행 완료 처리:

```python
scheduler.mark_tool_complete(task, tool_result)
# 내부: task.tool_results에 추가 + task 상태 READY
```

### mark_failed(task, reason)
작업 실패 처리 (사실 전파):

```python
scheduler.mark_failed(task, "timeout")
# 내부:
# 1. task.state = FAILED
# 2. 모든 자식에게 재귀적으로 mark_failed
# 3. 의존 작업들 처리:
#    - WAITING이면 의존성 정리
#    - 다른 상태면 mark_failed 재귀
```

## 의존성 관리

### 내부 자료구조

```python
_tasks: dict[str, Task]              # task_id → Task
_dependencies: dict[str, set[str]]   # task_id → 의존 task_id들
_dependents: dict[str, set[str]]     # task_id → 이 task를 의존하는 task들
_ready_queue: deque[str]             # READY 상태의 task_id들
```

### 시블링 의존성

자식들 간 의존성 (같은 부모의 children):

```python
# TaskSpec으로 명세
children = [
    TaskSpec(description="A"),           # 0
    TaskSpec(description="B"),           # 1
    TaskSpec(description="C", depends_on_siblings=[0, 1]),  # 2
]
# → A, B 완료 후 C 시작
```

**Scheduler의 검증**:
```python
# 순환 의존성 감지
def _validate_sibling_dependency_cycles(specs):
    # DFS로 순환 확인
    # self-dependency, invalid index 감지
```

### 크로스 태스크 의존성

WAIT 행동:

```python
TaskDecision(
    action=Action.WAIT,
    wait_for=("task.1.0", "task.2.0"),
)
# → Scheduler가 의존성 설정
# → task가 WAITING 상태로
```

**Scheduler의 검증**:
```python
def validate_wait(task_id, wait_for):
    # 이미 완료된 작업: 의존성 불필요
    # 실패한 작업: 영원히 기다릴 수 없음
    # 순환 의존성: 감지
```

## 교착 상태 처리

### 감지

```python
def has_deadlock(self) -> bool:
    # 완료되지 않았으나
    # READY 작업 없고
    # RUNNING 작업도 없음
    # = 교착 상태
```

### 해제

```python
def break_deadlock(self, shared: SharedState) -> bool:
    # WAITING 작업들 순회
    for task_id in waiting_tasks:
        # 의존성이 모두 terminal (DONE/FAILED)인가?
        if all_deps_terminal:
            # 의존성 정리 + READY로 전환
            self._clear_task_dependencies(task_id)
            self._maybe_ready(task_id)
```

## 유효성 검사

### validate_decomposition(task, specs)

```python
error = scheduler.validate_decomposition(task, [spec1, spec2])

# 검사 사항:
# 1. query_unit_ids 유효성
# 2. 시블링 의존성 순환 감지
# 3. 이미 존재하는 자식과 중복
# 4. 제안된 자식들 간 중복
```

**반환**: 에러 메시지 (또는 None이면 OK)

### validate_wait(task_id, wait_for)

```python
error = scheduler.validate_wait(task_id, wait_for)

# 검사 사항:
# 1. 모두 DONE이면: 기다릴 게 없음
# 2. 일부 FAILED: 영원히 기다림
# 3. 순환 의존성
```

## 상태 질의

```python
# 전체 완료?
if scheduler.is_complete():
    break

# 교착 상태?
if scheduler.has_deadlock():
    scheduler.break_deadlock(shared_state)

# 특정 작업 조회
task = scheduler.get_task(task_id)
```

## 내부 헬퍼

### _promote(task)

AtomicTask를 ComplexTask로 승격:

```python
# DECOMPOSE 시
promoted = scheduler._promote(atomic_task)
# → ComplexTask 인스턴스로 교체
# → 부모/자식 관계 유지
```

### _propagate_completion(task)

작업 완료 시 부모에게 전파:

```python
# task가 DONE되면
# 1. parent.child_outputs[task.id] = task.completion_payload()
# 2. parent가 WAITING이고 모든 자식이 terminal?
#    → parent를 READY로
```

### _release_dependents(task_id)

작업 완료 시 의존 작업 해제:

```python
# task.1.0이 DONE되면
# 1. task.1.0을 의존하는 모든 작업 찾음
# 2. 그들의 dependencies에서 task.1.0 제거
# 3. 의존성이 모두 충족되면 READY로
```

## 실행 예시

```python
scheduler = Scheduler(concurrency=2)

# 루트 등록
root = ComplexTask(id="root", ...)
scheduler.register(root)

# 루트가 READY이므로
assert root.state == TaskState.READY

# Step 1: 루트 실행
ready = scheduler.ready_tasks()  # [root]
decision = await planner.decide(root, ctx)
# → TaskDecision(DECOMPOSE, children=[child1, child2])

newly_ready = scheduler.apply_decision(root, decision, shared)
# → root 승격 (AtomicTask → ComplexTask)
# → child1, child2 생성
# → [child1.id, child2.id] 반환
# → root 상태 WAITING

# Step 2: 자식 실행
ready = scheduler.ready_tasks()  # [child1, child2]
for child in ready:
    decision = await planner.decide(child, ctx)
    scheduler.apply_decision(child, decision, shared)
    # child1이 DONE되면
    # → child2도 DONE이면 root가 READY로
```
