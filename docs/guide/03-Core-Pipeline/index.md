# 핵심 파이프라인 (server/core)

## 📁 구조

```
valuator/core/
├── planning/           # Plan 단계
│   ├── planner.py      # StepPlanner (의사 결정)
│   ├── prompts.py      # LLM 프롬프트 생성
│   ├── parser.py       # JSON 파싱
│   └── actions.py      # Action enum
├── agent/              # Execute 단계
│   ├── loop.py         # Agent 메인 루프
│   ├── context_builder.py # TaskContext 구성
│   └── trace.py        # 실행 추적
├── decomposition/      # Review 단계
│   ├── controller.py   # GateController
│   ├── critic.py       # DecompositionCritic (LLM)
│   ├── gate.py         # 분해 검증 로직
│   └── gate_config.py  # 설정
├── scheduler.py        # 작업 스케줄링
├── task.py             # Task, ComplexTask, AtomicTask
├── context.py          # TaskContext, TaskSummary
├── shared_state.py     # 팩트 저장소
├── types.py            # TaskState, Action, TaskDecision 등
└── __init__.py
```

## 📚 상세 문서

1. [작업 시스템 (Task & AtomicTask)](01-Task-System.md)
   - Task 기본 구조
   - AtomicTask vs ComplexTask
   - 상태 전이
   - 도구 실행 추적

2. [스케줄러 (Scheduler)](02-Scheduler.md)
   - 작업 등록 및 의존성 관리
   - 다음 실행 작업 선택
   - 상태 업데이트 적용
   - 교착 상태 감지/해제

3. [계획 (Planning & StepPlanner)](03-Planning.md)
   - TaskContext → TaskDecision 변환
   - 프롬프트 생성 전략
   - 허용된 행동 결정
   - JSON 파싱 및 복구

4. [에이전트 루프 (Agent Loop)](04-Agent-Loop.md)
   - 메인 루프 구현
   - 작업 선택 및 실행
   - 도구 실행 통합
   - 이벤트 발행

5. [분해 검증 (Decomposition & Gate)](05-Decomposition.md)
   - 과도한 분해 방지 (깊이, 단계 수)
   - LLM 품질 평가
   - 동적 임계값 조정
   - 거절 및 requery

6. [공유 상태 (SharedState)](06-Shared-State.md)
   - 팩트 저장 및 조회
   - 메타데이터 (시간, 출처, 근거)
   - 모든 작업에서 접근

## 🔄 처리 단계별 담당

### 단계 1: Plan
**파일**: `planning/planner.py`, `planning/prompts.py`
- 현재 Task와 Context 분석
- 허용된 Action 결정 (Gate에 의해 제한될 수 있음)
- LLM 호출 → TaskDecision

### 단계 2: Execute
**파일**: `agent/loop.py`, `../tools/*`
- AtomicTask인 경우 도구 실행
- Tool Registry에서 도구 선택
- 결과를 Task에 저장

### 단계 3: Aggregate
**파일**: `scheduler.py` (Action.AGGREGATE)
- 자식 작업들의 출력 병합
- 팩트를 SharedState에 발행
- 의존 작업 해제 (READY)

### 단계 4: Review
**파일**: `decomposition/controller.py`, `decomposition/gate.py`
- DECOMPOSE 결정 전 검증
- 깊이, 단계 수 체크
- LLM이 품질 평가
- 거절 시 requery_without_decompose

## 🎯 핵심 흐름

```python
# Agent.run()의 마운드 루프
while not scheduler.is_complete():
    # 1. 다음 실행할 작업 선택
    ready_tasks = scheduler.ready_tasks()
    
    for task in ready_tasks:
        # 2. 현재 상태 분석
        ctx = build_context(task)
        
        # 3. 의사 결정 (Plan)
        decision = await planner.decide(task, ctx)
        
        # 4. 검증 (Review)
        if decision.action == Action.DECOMPOSE:
            decision = await gate.gate(task, decision, ctx)
        
        # 5. 실행 (Execute)
        if decision.action == Action.EXECUTE:
            result = await execute_tool(decision.tool_request)
            scheduler.mark_tool_complete(task, result)
        
        # 6. 상태 업데이트 (Aggregate)
        newly_ready = scheduler.apply_decision(task, decision, shared)
```

## 💡 설계 특징

1. **단순성**: Task는 상태 머신. Scheduler는 순수 의존성 관리자
2. **확장성**: Tool 추가, LLM 모델 교체 용이
3. **관찰성**: 모든 단계를 이벤트로 발행 (session 저장)
4. **복원력**: 교착 상태 감지, 실패 전파, 도구 실패 처리

## 📊 데이터 흐름

```
TaskContext (입력)
    ↓ [Planning]
TaskDecision
    ↓ [Decomposition Gate]
TaskDecision (수정 가능)
    ↓ [Agent Execute]
ToolResult (또는 자식 TaskSpec)
    ↓ [Scheduler]
Task 상태 업데이트 + SharedState 변경
    ↓ [AgentEvent 발행]
next iteration
```
