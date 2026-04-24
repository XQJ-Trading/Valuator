# 계획 (Planning & StepPlanner)

현재 작업의 상태를 분석하여 다음 행동을 결정하는 단계. **TaskContext → TaskDecision**

## StepPlanner

```python
class StepPlanner:
    async def decide(self, task: Task, ctx: TaskContext) -> TaskDecision:
        # TaskContext 분석 → LLM 호출 → TaskDecision 생성
```

## 흐름

### 1단계: 허용된 행동 결정

```python
allowed = self._allowed_actions(
    task,
    allow_decompose=True,  # Gate에 의해 거절될 수 있음
)

# Task 종류에 따라:
# - AtomicTask: EXECUTE, AGGREGATE, FINALIZE, WAIT, FAIL
# - ComplexTask: DECOMPOSE, AGGREGATE, FINALIZE, WAIT, FAIL
# - 상태에 따라 제한 가능
```

### 2단계: 프롬프트 생성

```python
base_prompt = prompts.build_step_prompt(
    task=task,
    ctx=ctx,
    allowed_actions=allowed,
    max_prompt_chars=150_000,
    # ... 다양한 제약
)

system_prompt = prompts.build_system_prompt(
    task=task,
    ctx=ctx,
    allow_decompose=allow_decompose,
    task_name_max_chars=30,
    allowed_actions=allowed,
)
```

**프롬프트 내용**:
- Task description
- 지금까지의 증거들 (evidence) — 부모로부터 축적된 정보
- 지금까지의 도구 결과 (tool_results)
- 자식 작업들의 출력 (child_outputs) — 예산 제한 있음
- 질의 내용
- 사용 가능한 도구 목록
- JSON 스키마 (응답 형식)

### 3단계: LLM 호출

```python
response = await self._generate_decision(...)
# Claude API 호출
# JSON 응답 파싱
```

### 4단계: 응답 파싱 및 복구

```python
decision = parse_decision(response)

# 파싱 실패 시:
# 1. repair_retries 횟수만큼 재시도
# 2. LLM에 에러 메시지 전달
# 3. 최대 재시도 초과 시 에러
```

## TaskContext 구성

```python
@dataclass(frozen=True)
class TaskContext:
    task_id: str
    description: str
    step_count: int                    # 이 작업의 단계 수
    
    # 정보 축적
    evidence: list[EvidenceRow] = field(default_factory=list)  # 부모로부터 전달된 증거
    tool_results: list[ToolResult]     # 이 작업이 실행한 도구 결과들
    child_outputs: dict[str, TaskSummary]  # 자식 작업들의 결과
    as_of_kst: str = ""                # 정보 기준 시각 (KST)
    
    # 작업 구조
    current_children: list[TaskSummary] # 현재 자식들 (상태 포함)
    ancestry: list[TaskSummary]        # 부모들 (루트까지)
    siblings: dict[str, TaskSummary]   # 형제들 (상태 포함)
    
    # [deprecated] SharedState: 현재 no-op
    # 모든 정보는 evidence와 child_outputs를 통해 명시적으로 전달됨
    shared: SharedStateView            
    
    # 질의
    query: str                         # 원래 질의
    query_analysis: QueryAnalysis      # 질의 구조 분석
    query_units: list[QueryUnit]       # 질의의 세부 단위들
    available_tools: list[str]         # 사용 가능한 도구 목록
```

## TaskDecision 스키마

```python
@dataclass(frozen=True)
class TaskDecision:
    action: Action                  # 행동 선택
    
    # DECOMPOSE 시
    children: tuple[TaskSpec, ...]  
    # TaskSpec = (description, task_name, tool_hint, depends_on_siblings, query_unit_ids)
    
    # EXECUTE 시
    tool_request: ToolRequest | None
    # ToolRequest = (tool_name, args)
    
    # WAIT 시
    wait_for: tuple[str, ...]       # task id들
    
    # AGGREGATE 또는 FINALIZE 시
    output: Any                     # 최종 결과
    facts: dict[str, Any]           # 발행할 팩트
```

## Action별 의미

| Action | 의미 | 사전조건 |
|--------|------|---------|
| DECOMPOSE | 자식 작업으로 분해 | allow_decompose=True |
| EXECUTE | 도구 실행 | AtomicTask 또는 tool_hint 있음 |
| WAIT | 다른 작업 완료까지 대기 | wait_for 작업들이 진행 중 |
| AGGREGATE | 자식 결과 병합 + 팩트 발행 | 모든 자식 완료 |
| FINALIZE | 완료 + 의존 작업 해제 | 최종 답변 |
| FAIL | 실패 | 복구 불가능 |

## 프롬프트 최적화 전략

### 예산 관리

```python
_max_prompt_chars = 150_000         # 최대 프롬프트 크기
_prompt_child_output_budget_chars = 50_000  # 자식 출력 예산
_prompt_value_preview_chars = 600   # 값 미리보기 크기
_prompt_query_chars = 3_000         # 질의 크기
```

### 동적 크기 조정

```python
def build_step_prompt(..., max_prompt_chars):
    prompt = f"Task: {task.description}"
    
    # tool_results 추가 (공간 있으면)
    for result in task.tool_results:
        if len(prompt) < max_prompt_chars * 0.6:
            prompt += format_tool_result(result)
    
    # child_outputs 추가 (제한된 예산)
    for child_id, output in task.child_outputs.items():
        child_budget = ...
        prompt += truncate(str(output), child_budget)
```

## 오류 처리 및 복구

### 파싱 실패

```python
async def _generate_decision(...):
    for attempt in range(self._repair_retries + 1):
        try:
            decision = parse_decision(response)
            return decision
        except ParseError as e:
            if attempt < self._repair_retries:
                # LLM에 에러 메시지와 함께 재시도
                response = await self._generate_decision_with_error(e)
            else:
                raise
```

### 유효하지 않은 결정

```python
# StepPlanner.decide() 호출 후
error = scheduler.validate_decomposition(task, decision.children)
if error:
    # Gate에서 거절된 경우
    decision = await planner.requery_without_decompose(
        task, ctx, error
    )
    # DECOMPOSE 금지하고 다시 계획
```

### 최대 단계 도달

```python
if task.step_count >= self._max_steps_per_task:
    # Gate에서 DECOMPOSE 차단
    allow_decompose = static_rejects_minimal_decomposition(...)
```

## 내부 구현 세부사항

### _allowed_actions(task, allow_decompose)

```python
def _allowed_actions(self, task, allow_decompose):
    allowed = []
    
    if isinstance(task, ComplexTask):
        if allow_decompose and task.state == TaskState.READY:
            allowed.append(Action.DECOMPOSE)
    
    if isinstance(task, AtomicTask):
        if task.state == TaskState.READY:
            allowed.append(Action.EXECUTE)
    
    # 항상 가능
    allowed.extend([
        Action.AGGREGATE,
        Action.FINALIZE,
        Action.WAIT,
        Action.FAIL,
    ])
    
    return allowed
```

### _decision_schema(task, allow_decompose)

LLM 응답의 JSON 스키마:

```json
{
  "action": "decompose|execute|wait|aggregate|finalize|fail",
  "children": [
    {
      "description": "...",
      "task_name": "...",
      "tool_hint": "web_search|code_execute|...",
      "depends_on_siblings": [0, 1],
      "query_unit_ids": [0, 1]
    }
  ],
  "tool_request": {
    "tool_name": "web_search",
    "args": {"query": "..."}
  },
  "wait_for": ["task.1.0", "task.2.0"],
  "output": "...",
  "facts": {
    "key": {
      "value": "...",
      "grounded": true,
      "source_urls": ["..."]
    }
  }
}
```

## 기본 설정

```python
config.agent_step_repair_retries = 3    # 파싱 재시도
config.agent_max_steps_per_task = 20    # 단계 제한
config.agent_max_invalid_decisions_per_task = 5
config.agent_max_consecutive_tool_failures = 3
```

## 실행 예시

```python
# TaskContext 준비
ctx = TaskContext(
    task_id="task.1.0",
    description="Apple의 2024 재정 상태 분석",
    step_count=0,
    tool_results=[],
    query="Apple의 가치는?",
    available_tools=["web_search", "yfinance", "sec_tool"],
)

# 의사 결정
planner = StepPlanner(llm_client)
decision = await planner.decide(task, ctx)

# 결과
# TaskDecision(
#   action=Action.DECOMPOSE,
#   children=(
#     TaskSpec("2024 수익 조회", tool_hint="web_search", ...),
#     TaskSpec("주요 사업부 분석", tool_hint="web_search", ...),
#   )
# )
```
