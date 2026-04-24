# 공유 상태 및 작업 통신

Task 간의 정보 흐름을 이해하기 위한 실제 통신 메커니즘입니다. `SharedState`는 현재 no-op stub이며, 모든 정보는 Task의 `outputs` 필드와 `TaskSummary`를 통해 계층 구조로 전달됩니다.

---

## 1. 핵심 개념: 계층적 정보 흐름

### 정보가 흐르는 방향

```
     Parent Task
         ↑
    [child_outputs]
         ↑
   ┌─────┴─────┬─────────┬──────┐
   ↓           ↓         ↓      ↓
Child 1    Child 2   Child 3  Child 4
```

- **Parent → Children**: `TaskContext`를 통해 부모 작업의 `evidence` 및 배경 정보 전달
- **Children → Parent**: 각 자식의 `outputs` (TaskSummary)가 부모의 `child_outputs`에 수집됨
- **Siblings**: 같은 부모의 자식들은 직접 통신 불가. 부모 또는 LLM을 통해서만 상호 참조 가능

---

## 2. Task 데이터 구조

### TaskSummary (자식이 부모로 반환)

```python
@dataclass
class TaskSummary:
    task_id: str
    name: str
    output: str                    # 핵심: 자식의 실행 결과
    work_phase: str                # COLLECT, SYNTHESIZE
    consumed_tokens: dict[str, int]
```

자식 Task가 완료되면 `TaskSummary` 형태로 부모의 `child_outputs` 딕셔너리에 저장됩니다.

### TaskContext (부모에서 자식으로 전달)

```python
@dataclass(frozen=True)
class TaskContext:
    task_id: str
    evidence: list[EvidenceRow] = field(default_factory=list)  # 축적된 증거
    as_of_kst: str = ""                                         # 타임스탬프
    shared: SharedStateView = field(...)                        # [현재 미사용]
    # ... 기타 필드
```

---

## 3. 실제 통신 흐름 (예시)

### 시나리오: "애플 주가 분석" 작업 분해

```
[Query: 애플 주가 분석]
        ↓
[Parent Task] (id: "root", name: "Apple Stock Analysis")
        ↓
    [DECOMPOSE 결정]
        ↓
    ┌───────────────────────────────────────┐
    │   3개 자식 작업 생성                    │
    └───────────────────────────────────────┘
        ↓
    ┌─────────────────┬─────────────────┬─────────────────┐
    ↓                 ↓                 ↓                 ↓
[Child 1]        [Child 2]        [Child 3]        [Parent]
(5yr Revenue)    (PE Ratio)       (Analyst Report)
    ↓                 ↓                 ↓
 [EXECUTE]        [EXECUTE]        [EXECUTE]
 YFinance         SEC Filing       Web Search
    ↓                 ↓                 ↓
 $195B            PE: 28x          Bullish
    ↓                 ↓                 ↓
┌──────────────────────────────────────────────┐
│  Parent의 child_outputs에 수집               │
│  {                                            │
│    "root-c1": TaskSummary("5yr Revenue", "$195B"),
│    "root-c2": TaskSummary("PE Ratio", "PE: 28x"),
│    "root-c3": TaskSummary("Analyst", "Bullish")
│  }                                            │
└──────────────────────────────────────────────┘
    ↓
[AGGREGATE]
부모 Task는 child_outputs를 조회하고,
LLM에 요청: "이 세 정보를 종합하여 분석 결론을 도출하시오"
    ↓
최종 output: "종합 분석 결과: ..."
```

---

## 4. 정보 접근 패턴

### Task가 자신의 자식들 정보 조회

```python
class ComplexTask:
    def __init__(self, ...):
        self.child_outputs: dict[str, TaskSummary] = {}  # 자식들의 결과 저장
    
    async def process(self, ctx: TaskContext) -> TaskSummary:
        # 자식들이 완료될 때까지 기다림
        # (Scheduler가 의존성 추적)
        
        # 자식들의 output을 조회
        for child_id, summary in self.child_outputs.items():
            print(f"{child_id}: {summary.output}")
        
        # LLM에 자식들 정보 주입
        child_info = "\n".join(
            f"- {s.name}: {s.output}"
            for s in self.child_outputs.values()
        )
        
        # LLM에 요청
        final_output = await llm.generate(
            system="종합 분석가",
            user=f"다음 정보들을 종합하시오:\n{child_info}"
        )
        
        return TaskSummary(
            task_id=self.id,
            name=self.name,
            output=final_output
        )
```

### Task가 부모 Task의 evidence 조회

```python
class AtomicTask:
    async def process(self, ctx: TaskContext) -> TaskSummary:
        # evidence: 부모가 누적한 증거들
        for evidence in ctx.evidence:
            print(f"기존 증거: {evidence.content}")
        
        # 기존 증거를 바탕으로 새로운 조사 수행
        # ...
```

---

## 5. SharedState는 왜 no-op인가?

**설계 변경 (2026-04-21 커밋 e7f3f77)**

초기 설계에서는 모든 Task가 `SharedState.publish(key, value)`를 통해 사실을 중앙 저장소에 기록하고, 다른 Task가 `shared.view()`로 조회하도록 했습니다.

**문제점:**
- 모든 Task가 SharedState에 접근하면서 경합(contention) 발생
- Task 간 암시적 의존성이 증가 (언제 어느 사실이 발행될지 불명확)
- 디버깅 어려움 (사실의 출처를 추적하기 어려움)

**현재 접근법 (명시적 계층 구조):**
- Parent → Child: `TaskContext.evidence` (명시적 인자)
- Child → Parent: `TaskSummary.output` (명시적 반환값)
- Sibling: 직접 통신 불가 (부모를 통해서만)

**장점:**
- ✅ 의존성이 명시적이며 Task 그래프로 시각화 가능
- ✅ 정보 출처가 명확함 (어느 Task가 생성했는지 추적 가능)
- ✅ 동시성 문제 없음 (계층 구조 자체가 직렬화를 강제)

---

## 6. Evidence: 부모에서 자식으로의 정보 전달

EvidenceRow는 Task가 축적한 증거(팩트)를 다음 단계로 전달합니다.

```python
@dataclass
class EvidenceRow:
    content: str                    # 실제 정보
    source: str                     # 어디서 나왔는가 (task_id, tool_name 등)
    grounded: bool                  # 도구 결과 기반인가 아니면 LLM 추론인가
    urls: list[str] = field(...)    # 참조 URL
```

### 사용 예시

```python
# 부모 Task: planning/execution 단계에서 증거 축적
parent_ctx = TaskContext(
    task_id="root",
    evidence=[
        EvidenceRow(
            content="2024 수익: $195B",
            source="sec_tool",
            grounded=True,
            urls=["https://sec.gov/..."]
        ),
        EvidenceRow(
            content="분기별 성장률 4%",
            source="analysis_summary",
            grounded=False,
            urls=[]
        )
    ]
)

# 자식 Task: parent_ctx.evidence를 읽고, 기존 증거 위에 새로운 분석 추가
child_summary = await child_task.process(parent_ctx)

# 자식이 새로운 증거를 추가한다면?
# → TaskSummary.output에 포함하고, 부모가 다시 집계할 때 LLM이 병합
```

---

## 7. 정보 보존 원칙

| 항목 | 책임 | 방법 |
|------|------|------|
| **출처 추적** | 각 Task | EvidenceRow.source, TaskSummary.task_id |
| **신뢰도 표시** | 각 Task | EvidenceRow.grounded |
| **시간 정보** | TaskContext | as_of_kst, evidence의 타임스탬프 |
| **URL 참조** | 각 Task | EvidenceRow.urls |

---

## 8. 마이그레이션 가이드 (SharedState 사용 코드)

기존에 `SharedState`를 사용하던 코드가 있다면:

```python
# ❌ 이전 (더 이상 작동하지 않음)
await shared.publish(key="apple_revenue", value=195_000_000_000)
revenue = shared.view().get("apple_revenue")

# ✅ 새로운 방식
# 1. 부모 Task에서:
ctx.evidence.append(EvidenceRow(
    content="$195B",
    source="yfinance",
    grounded=True
))

# 2. 자식 Task에서 output으로 반환:
return TaskSummary(..., output="분석 결과: ...")

# 3. 부모에서 child_outputs 조회:
for child_id, summary in self.child_outputs.items():
    use_data(summary.output)
```

---

## 요약

**SharedState는 더 이상 활성 메커니즘이 아닙니다.** 대신:

- ✅ **명시적 계층 구조** (Parent → Children → Outputs)
- ✅ **Evidence 기반 정보 전달** (출처 명확)
- ✅ **TaskSummary를 통한 결과 수집** (부모가 child_outputs에서 조회)

이 접근법은 **의존성이 명확하고, 디버깅이 쉽고, 동시성 문제가 없는** 설계입니다.
