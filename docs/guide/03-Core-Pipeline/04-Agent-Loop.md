# 에이전트 루프 (Agent Loop)

에이전트 루프는 전체 시스템을 구동하는 메인 프로세스로, **작업 선택 → 계획 → 실행 → 상태 업데이트**의 과정을 반복하며 최종 해답을 도출합니다.



## 1. Agent 클래스 구조
에이전트는 스케줄러, 도구 레지스트리 및 플래너를 하나로 묶어 관리합니다.

```python
class Agent:
    def __init__(self, *, scheduler, tool_registry, llm_client, ...):
        self._scheduler = scheduler      # 작업 우선순위 및 상태 관리
        self._tools = tool_registry      # 사용 가능한 도구 집합
        self._step_planner = StepPlanner(llm_client, ...) # LLM 기반 의사결정기
        self._gate = GateController(...) # 분해(Decomposition) 결과 검증 및 필터링
```

---

## 2. 메인 루프 (Main Loop)
스케줄러에 실행 가능한 작업이 없을 때까지 지속적으로 루프를 돕니다.

```python
async def run(self, query: str, root_task: Task) -> Any:
    self._root_task = root_task
    # 루트 작업에 LLM 플래너 바인딩
    root_task.bind_step(self._step_planner.decide)
    self._scheduler.register(root_task)  # 초기 상태: READY
    
    while not self._scheduler.is_complete():
        # 1. 실행 가능한 작업 추출 (의존성이 해결된 작업들)
        ready_tasks = self._scheduler.ready_tasks()
        
        # 교착 상태(Deadlock) 해결
        if not ready_tasks and self._scheduler.has_deadlock():
            self._scheduler.break_deadlock()
            continue
        
        # 2. 작업 처리 (동시성 제어가 가능하지만 기본적으로 순차 처리)
        for task in ready_tasks:
            await self._process_task(task)
    
    return self._finalize_output()
```

---

## 3. 작업 처리 상세 (`_process_task`)
개별 작업이 LLM에 의해 계획되고 실제 동작으로 이어지는 5단계 프로세스입니다.

1.  **Context Builder:** 작업 상태, 부모/자식 관계, 증거, 도구 결과를 모아 LLM에 전달할 컨텍스트를 구성합니다.
2.  **Decision (계획):** `StepPlanner`를 호출하여 다음 행동(실행, 분해, 대기 등)을 결정합니다.
3.  **Gate (검토):** 복잡한 작업 분해가 제안될 경우, 깊이 제한이나 정책에 맞는지 검증합니다.
4.  **Validation:** 결정된 행동이 논리적으로 유효한지(예: 없는 도구 호출 등) 확인합니다.
5.  **Execution:** 실제 도구를 실행하거나 스케줄러 상태를 업데이트합니다.

---

## 4. 도구 실행 및 실패 관리 (`_execute_tool`)
도구 실행 시 발생할 수 있는 예외와 반복적인 실패를 방지하는 로직을 포함합니다.

* **Signature Check:** 동일한 인자로 실패했던 기록이 있다면 중복 실행을 차단합니다.
* **Consecutive Failures:** 특정 도구가 연속해서 실패하면 해당 도구를 `blocked_tools`에 추가하여 더 이상 사용하지 못하게 격리합니다.
* **State Transition:** 성공 여부에 관계없이 결과를 스케줄러에 보고하여 `RUNNING → READY/COMPLETE` 상태 전이를 유도합니다.

---

## 5. 특수 케이스 처리 전략

### 교착 상태 (Deadlock)
모든 작업이 서로의 결과를 기다리며 `WAITING` 상태에 빠진 경우, 스케줄러가 의존 관계를 강제로 해제하거나 실패 처리하여 루프가 멈추지 않도록 합니다.

### 최대 단계 제한 (Max Steps)
무한 루프 방지를 위해 `GateController`에서 특정 작업의 `step_count`를 체크합니다. 제한에 도달하면 더 이상의 작업 분해를 금지하고 결과를 요약하도록 강제합니다.

### 이벤트 발행 (Event Emission)
루프의 모든 주요 시점(`STEP_STARTED`, `TOOL_EXECUTED`, `DECOMPOSED`)에서 이벤트를 발행하여 실시간 트레이싱 및 디버깅 로그를 생성합니다.

---

## 6. 호출 예시 (Usage)
서버 레이어에서 에이전트를 생성하고 구동하는 전형적인 코드 흐름입니다.

```python
# API 핸들러 내부
root = ComplexTask(id=f"{session_id}.root", description="분석 요청")

agent = Agent(
    scheduler=Scheduler(),
    tool_registry=create_tool_registry(model),
    llm_client=get_llm_client(model)
)

# 에이전트 실행 및 최종 결과 수신
final_output = await agent.run(user_query, root)
```
