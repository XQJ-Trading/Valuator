# 아키텍처

## 시스템 경계

**경계**: 외부 입력이 진입/이탈하는 지점
- HTTP 요청/응답
- LLM API 호출
- 파일/YAML 파싱
- 외부 API 호출

**경계의 역할**: 검증이 아니라 **원시 입력을 도메인 타입으로 변환**

경계를 통과한 후, 타입의 존재 자체가 검증 완료의 증거. 내부에서 재검증 금지.

## 데이터 흐름

### 단계 1: Plan (계획)
```
TaskContext (현재 상태)
    ↓
[StepPlanner]
  - 허용된 행동 결정
  - 프롬프트 생성
  - LLM 호출
    ↓
TaskDecision (의사 결정)
  - action: DECOMPOSE | EXECUTE | WAIT | AGGREGATE | FINALIZE | FAIL
  - children: 자식 작업 스펙 (분해 시)
  - tool_request: 도구 호출 정보 (실행 시)
  - facts: 발행할 팩트 (집계 시)
```

### 단계 2: Execute (실행)
```
AtomicTask (도구 실행 필요)
    ↓
[Tool]
  - 검색, 코드 실행, 재무 데이터 등
    ↓
ToolResult
  - success: bool
  - result: Any
  - error: str | None
    ↓
[Agent] Task에 결과 추가 → 다시 계획
```

### 단계 3: Aggregate (집계)
```
Task (완료)
  - child_outputs: {task_id: output}
  - published_facts: {key: value}
    ↓
SharedState
  - 팩트 발행
  - 타이 scope, 출처 URL 기록
    ↓
의존 작업들 해제 (READY)
```

### 단계 4: Review (검토)
```
TaskDecision (DECOMPOSE 행동)
    ↓
[Gate] 분해 검증
  1. pre_filter: 깊이, 단계 수 체크
  2. critic: LLM 품질 평가
  3. threshold 조정 (학습)
    ↓
TaskDecision (수정 또는 거절)
  - 거절 시: requery_without_decompose
```

## 상태 다이어그램

```
CREATED
  │ (의존성 없음)
  ↓
READY ←──────────────────────┐
  │                          │
  ├─→ [Plan] →─┐           │
  │            │            │
  │  ┌─────────┤            │
  │  │    [Execute] (RUNNING)
  │  │         │            │
  │  │    [Tool] (결과)     │
  │  │         │            │
  │  ├─→ [Aggregate] (DONE)
  │  │
  │  └─→ [Decompose] (WAITING)
  │         │
  │    자식 생성
  │    모든 자식 완료
  │         │
  │         └─→ READY ───┘
  │
  └─→ [FAILED]
```

## 핵심 컴포넌트

### Scheduler
**역할**: 작업 상태 관리, 의존성 추적, 다음 실행할 작업 결정

```python
# 등록
scheduler.register(task, depends_on=[dep1, dep2])

# 다음 실행할 작업들 (concurrency 제한)
ready_tasks = scheduler.ready_tasks(limit=4)

# 의사 결정 적용
newly_ready = scheduler.apply_decision(task, decision, shared_state)

# 실패 전파 (자식, 의존 작업들에게)
scheduler.mark_failed(task, reason)
```

### StepPlanner
**역할**: 현재 상태를 분석하여 다음 행동 결정

```python
# TaskContext → TaskDecision
decision = await planner.decide(task, ctx)
```

### Agent Loop
**역할**: 다음 실행할 작업 선택, 실행, 상태 업데이트 반복

```python
async def run(query: str, root_task: Task):
    # 스케줄러에 루트 작업 등록
    scheduler.register(root_task)
    
    # 반복: 작업 선택 → 계획 → 실행 → 상태 업데이트
    while not scheduler.is_complete():
        ready = scheduler.ready_tasks()
        for task in ready:
            decision = await planner.decide(task, ctx)
            newly_ready = scheduler.apply_decision(task, decision)
```

### SharedState
**역할**: 모든 작업이 접근 가능한 팩트 저장소

```python
# 팩트 발행
shared.publish(
    key="apple_revenue",
    value=195_000_000_000,
    source_task_id="task.1.0",
    grounded=True,  # 근거 있음
    source_urls=[...],
)

# 팩트 조회 (TaskContext에서)
ctx.shared.get("apple_revenue")
```

## 설계 원칙

### 1. 경계와 비즈니스 로직 분리

**경계에서만 허용**:
- validate, normalize, sanitize
- regex 파싱
- 타입 변환

**비즈니스 로직에서 금지**:
- ensure, check 반복
- 방어적 isinstance 검사
- 값 교정 (coerce, cast)
- get_or_default 에러 마스킹

**이유**: 경계가 완결되면, 타입의 존재 자체가 검증 증거. 재검증은 중복이고 복잡도 증가.

### 2. 단순한 함수 설계

- 한 가지 일만 함
- 깊은 중첩 금지
- Early return 사용
- 사이드이펙트와 I/O 순서 고정

### 3. 타입으로 의미 표현

```python
# ❌ 나쁜 예
task_kind = "complex"
if task_kind == "complex":
    decompose()

# ✅ 좋은 예
if isinstance(task, ComplexTask):
    task.add_child(...)
```

### 4. 에러 처리

- Fail fast: 에러를 즉시 전파
- 예외를 삼키지 않음
- Fallback 값으로 마스킹하지 않음

## 데이터 타입

### TaskContext
현재 작업 실행 시 필요한 모든 정보:
```python
@dataclass
class TaskContext:
    task_id: str
    description: str
    step_count: int
    tool_results: list[ToolResult]  # 지금까지 실행한 도구 결과
    child_outputs: dict[str, Any]   # 자식 작업들의 출력
    shared: SharedStateView         # 다른 작업들이 발행한 팩트
    query: str                      # 원래 질의
    query_analysis: QueryAnalysis   # 질의 분석 결과
    available_tools: list[str]      # 이 작업에서 사용 가능한 도구
```

### TaskDecision
의사 결정 결과:
```python
@dataclass(frozen=True)
class TaskDecision:
    action: Action              # DECOMPOSE, EXECUTE, AGGREGATE 등
    children: tuple[TaskSpec]   # 분해 시 생성할 자식들
    tool_request: ToolRequest   # 실행 시 호출할 도구
    wait_for: tuple[str]        # 대기할 작업 ID들
    output: Any                 # 최종 출력
    facts: dict[str, Any]       # 발행할 팩트
```

## 실행 흐름 예시

```python
# 1. 사용자 쿼리 → 루트 작업 생성
root = ComplexTask(
    id="root",
    description="분석하기",
)

# 2. Agent 초기화 및 실행
agent = Agent(...)
final_output = await agent.run(query, root)

# 내부 흐름:
# - Scheduler: root를 READY로 상태 변경
# - Agent Loop:
#   a) Scheduler: root_task 선택
#   b) StepPlanner: TaskDecision(DECOMPOSE, children=[spec1, spec2])
#   c) Scheduler: root를 ComplexTask로 승격, 자식 생성
#   d) Scheduler: 자식들을 READY로
#   e) Agent Loop 계속...

# 3. 결과 반환
```
