# TS-004: MCTS-inspired Decomposition Gate

## 1. Problem

현재 recursive agent는 `StepPlanner.decide()`가 `Action.DECOMPOSE`를 반환하면
`Scheduler.apply_decision()`이 자식 태스크를 즉시 생성한다.
시스템 프롬프트의 "Prefer shallow decomposition"은 소프트 가이던스일 뿐이며,
LLM이 이를 무시하면 과잉 분해가 그대로 실행 비용으로 이어진다.

**과잉 분해 패턴**:

| 패턴 | 예시 | 비용 |
|------|------|------|
| 단일 도구로 충분한 태스크를 분해 | "Amazon 2024 매출" → 자식 3개 | 최소 3N 추가 LLM 호출 |
| 중복 자식 | "매출 분석", "revenue analysis", "top-line growth" | 동일 정보 반복 수집 |
| 불필요한 깊이 | depth 3+에서 재분해 | 지수적 태스크 증가 |
| 실행 불가능한 자식 | 허용되지 않은 `tool_hint`, 또는 `tool_hint` 없는 자식 다수 | 연쇄 분해 증가 |

**핵심 구조적 문제**:

- `DECOMPOSE`는 자식 생성 전에 검토되지 않는다.
- 실제 실행 가능한 도구 집합(`ctx.available_tools`)이 분해 판단에 반영되지 않는다.
- 분해의 실제 품질은 aggregation 이후에야 드러나지만, 현재는 그 결과가 다음 분해 기준에 반영되지 않는다.

**비용 모델**:

자식 `N`개 분해는 최소 `3N`개의 추가 호출을 유발한다.

- 자식 결정
- 자식 실행 또는 재분해
- 부모 AGGREGATE

depth 2에서 각 자식이 3개씩 재분해되면 루트 하나에서 `3 + 9 + 27 = 39`회 호출이 발생할 수 있다.

## 2. Goal

MCTS의 selection/backpropagation 관점을 차용해, `DECOMPOSE`에 **사전 게이트**와
**사후 학습**을 추가한다.

- **Layer 1 (Static Pre-filter)**: 깊이, breadth, token pressure, 실행 가능 도구 비율로 즉시 판정한다.
- **Layer 2 (Pre-decompose Critic)**: gray zone에서만 LLM 1회로 의미적 평가를 수행한다.
- **Layer 3 (Outcome Evaluation / Backpropagation)**: `AGGREGATE` 시점에 실제 분해 효율을 관측해 threshold를 조정한다.
- 기각 시에는 `DECOMPOSE`를 제외한 선택지만 허용한 재질의를 1회 수행한다.

이 ADR의 핵심은 다음 역할 분리다.

- **Layer 2는 gate다.** 자식 생성 전에 실행되어 현재 비용을 막는다.
- **Layer 3는 evaluator다.** aggregation 이후의 실제 결과를 학습에 반영한다.

### Non-Goal

- 전체 MCTS rollout
- 세션 간 threshold 지속
- `EXECUTE`, `WAIT`, `AGGREGATE`, `FINALIZE`, `FAIL`에 대한 별도 게이트
- aggregation 시점에 추가 LLM critic을 호출하는 것

aggregation은 이 ADR에서 **후향적 outcome evaluation**만 담당한다.
현재 분해를 막는 책임은 agent의 pre-decompose gate에 둔다.

## 3. Architecture

### 3.1 System Boundary 관점

```text
┌──────────────────────────────── Boundary ────────────────────────────────┐
│                                                                          │
│  StepPlanner                  DecompositionCritic        GeminiClient    │
│  (LLM -> TaskDecision)       (LLM -> CriticVerdict)     (LLM generate)   │
│                                                                          │
└────────────┬──────────────────────────────┬──────────────────────┬────────┘
             │ decide()                     │ evaluate()           │
             │ requery_without_decompose()  │                      │
             ▼                              ▼                      │
┌──────────────────────────── Business Logic ───────────────────────────────┐
│                                                                          │
│  DecompositionGate                                                       │
│  ├─ pre_filter(...) -> FilterResult                                      │
│  │   ├─ depth_cost()                                                     │
│  │   ├─ breadth_cost()                                                   │
│  │   ├─ tool_resolvability()                                             │
│  │   └─ token_pressure()                                                 │
│  ├─ critic_to_score(...) -> float                                        │
│  └─ combine(...) -> GateDecision                                         │
│                                                                          │
│  BackpropagationTracker                                                  │
│  ├─ record_prediction(...)                                               │
│  ├─ observe_outcome(...)                                                 │
│  └─ current_threshold() -> float                                         │
│                                                                          │
│  Agent                Scheduler              SharedState / Task graph     │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### 3.2 책임 분리

| 레이어 | 시점 | 책임 | 결과 |
|--------|------|------|------|
| Static Pre-filter | `DECOMPOSE` 직후 | 구조적 비용 검사 | 확정 허용 / 확정 기각 / gray zone |
| Pre-decompose Critic | gray zone에서만 | 제안된 분해의 의미적 품질 평가 | 최종 허용 / 기각 |
| Outcome Evaluation | `AGGREGATE` 시점 | 실제 실행 결과 평가 | threshold 업데이트 |

### 3.3 왜 gate는 agent에 있어야 하는가

`Scheduler.apply_decision()`이 `Action.DECOMPOSE`를 적용하는 순간 자식 생성 비용은 이미 커밋된다.
따라서 aggregation 시점의 평가는 정확할 수는 있어도, 현재 분해를 막을 수는 없다.

정리하면:

- **자식 생성을 막고 싶으면** agent에서 검토해야 한다.
- **실제 품질을 학습하고 싶으면** aggregation에서 관측해야 한다.

이 ADR은 이 둘을 분리한다.

### 3.4 Static / Critic / Outcome Evaluation 신호 분리

| 신호 | Static | Pre-decompose Critic | Outcome Evaluation | 근거 |
|------|--------|----------------------|--------------------|------|
| depth_cost | O | - | - | 메타데이터 |
| breadth_cost | O | - | - | 메타데이터 |
| token_pressure | O | - | - | 산술 |
| tool_resolvability | O | - | - | 현재 실행 가능한 도구 집합 기준 |
| 자식 간 의미적 중복 | - | O | - | 의미 추론 |
| 부모 목적 커버리지 | - | O | - | 의미 추론 |
| 단일 도구 해결 가능성 | - | O | - | 의미 추론 |
| 최소 필요 자식 수 | - | O | - | 의미 추론 |
| 실제 재분해 발생 여부 | - | - | O | 실행 결과 |
| 실제 atomic 완료 비율 | - | - | O | 실행 결과 |
| 실제 child step cost | - | - | O | 실행 결과 |

### 3.5 데이터 흐름

```text
Agent._step_one(task)
  |
  |- 1. ctx = _build_context(task, query)
  |- 2. decision = await task.step(ctx)
  |
  |- 3. if decision.action is DECOMPOSE:
  |      |
  |      |- 3a. filter_result = gate.pre_filter(...)
  |      |
  |      |- 3b. if ACCEPT:
  |      |      -> allow immediately
  |      |
  |      |- 3c. if REJECT:
  |      |      -> requery_without_decompose()
  |      |
  |      |- 3d. if UNCERTAIN:
  |             |- critic_verdict = await critic.evaluate(...)
  |             |- gate_decision = gate.combine(...)
  |             |- if rejected -> requery_without_decompose()
  |
  |- 4. if final decision is accepted DECOMPOSE:
  |      -> tracker.record_prediction(...)
  |
  |- 5. scheduler.apply_decision(...)
  |
  \- 6. if decision.action is AGGREGATE and tracker has prediction(task.id):
         -> tracker.observe_outcome(task.id, task.children())
```

핵심 규칙:

- `record_prediction()`은 **허용된 분해에만** 수행한다.
- 기각된 분해는 outcome이 없으므로 tracker에 남기지 않는다.
- aggregation은 **gate를 대체하지 않는다**.

## 4. Component Design

### 4.1 Domain Types — `valuator/core/decomposition_types.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FilterVerdict(Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class PenaltyWeights:
    depth: float = 0.3
    breadth: float = 0.2
    tool_resolvability: float = 0.3
    token_pressure: float = 0.2


@dataclass(frozen=True)
class GateConfig:
    enabled: bool = True
    weights: PenaltyWeights = field(default_factory=PenaltyWeights)
    initial_threshold: float = 0.0
    learning_rate: float = 0.1
    max_depth: int = 4
    max_children: int = 8
    accept_bound: float = 0.4
    reject_bound: float = -0.3
    static_weight: float = 0.4
    critic_weight: float = 0.6


@dataclass(frozen=True)
class StaticBreakdown:
    depth_cost: float
    breadth_cost: float
    tool_resolvability: float
    token_pressure: float


@dataclass(frozen=True)
class FilterResult:
    verdict: FilterVerdict
    static_score: float
    breakdown: StaticBreakdown
    reason: str


@dataclass(frozen=True)
class CriticVerdict:
    allow: bool
    single_tool_possible: bool
    redundant_pairs: list[tuple[int, int]]
    coverage_pct: int
    min_children: int
    reason: str


@dataclass(frozen=True)
class GateDecision:
    net_score: float
    threshold: float
    rejected: bool
    used_critic: bool
    reason: str
    static_result: FilterResult
    critic_verdict: CriticVerdict | None = None


@dataclass
class DecompositionOutcome:
    task_id: str
    predicted_score: float
    child_count: int
    depth: int
    used_critic: bool
    actual_efficiency: float = 0.0
```

### 4.2 Decomposition Critic — `valuator/core/decomposition_critic.py`

`DecompositionCritic`는 경계 어댑터다.
제안된 분해가 실제 expansion으로 들어가기 전에, gray zone 케이스에 대해서만 의미적 평가를 수행한다.

```python
class _CriticPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow: bool
    single_tool_possible: bool
    redundant_pairs: list[list[int]] = Field(default_factory=list)
    coverage_pct: int = Field(ge=0, le=100)
    min_children: int = Field(ge=0)
    reason: str


class DecompositionCritic:
    def __init__(self, llm_client: Any) -> None:
        self._llm = llm_client

    async def evaluate(
        self,
        task: Task,
        decision: TaskDecision,
        ctx: TaskContext,
    ) -> CriticVerdict:
        prompt = self._build_prompt(task, decision, ctx)
        raw = await self._llm.generate_json(
            prompt=prompt,
            system_prompt=self._system_prompt(),
            response_json_schema=_CriticPayload.model_json_schema(),
            trace_method=f"agent.gate.critic.{task.id}",
        )
        payload = _CriticPayload.model_validate(raw)
        return self._to_verdict(payload)
```

**Critic 평가 기준**:

1. 부모 태스크가 단일 도구 호출로 끝날 수 있는가
2. 제안된 자식들 사이에 의미적 중복이 있는가
3. 자식들이 부모 목적을 얼마나 커버하는가
4. 실제로 필요한 최소 자식 수는 몇 개인가
5. 이 분해를 허용해야 하는가

**입력 컨텍스트**:

- 부모 태스크 설명
- 제안된 자식 목록
- 조상 체인
- 현재 실행 가능한 도구 목록

### 4.3 Decomposition Gate — `valuator/core/decomposition_gate.py`

순수 비즈니스 로직이다.
LLM 호출, config 로딩, task mutation은 포함하지 않는다.

```python
def depth_cost(depth: int, max_depth: int) -> float:
    """(depth / max_depth) ** 2"""


def breadth_cost(child_count: int, max_children: int) -> float:
    """log2(child_count) / log2(max_children)"""


def tool_resolvability(
    children: list[TaskSpec],
    executable_tools: frozenset[str],
) -> float:
    """child.tool_hint가 현재 실행 가능한 도구 집합에 속하는 비율."""


def token_pressure(
    child_count: int,
    depth: int,
    max_steps_per_task: int,
    avg_tokens_per_step: int = 2000,
) -> float:
    """estimated_tokens / budget_per_branch"""


def pre_filter(
    *,
    task_depth: int,
    children: list[TaskSpec],
    executable_tools: frozenset[str],
    max_steps_per_task: int,
    config: GateConfig,
) -> FilterResult:
    """구조적 신호만으로 확정 허용 / 확정 기각 / gray zone을 나눈다."""


def critic_to_score(
    verdict: CriticVerdict,
    actual_children: int,
) -> float:
    """CriticVerdict -> scalar critic score"""


def combine(
    *,
    filter_result: FilterResult,
    critic_verdict: CriticVerdict,
    config: GateConfig,
    threshold: float,
) -> GateDecision:
    """static_score + critic_score -> GateDecision"""
```

**구체화 규칙**:

- `tool_resolvability`는 `TOOL_SPECS` 전체가 아니라 `ctx.available_tools` 기준으로 계산한다.
- `pre_filter()`는 threshold를 직접 참조하지 않는다.
- threshold는 `combine()`과 static-only fallback에서만 사용한다.

### 4.4 Backpropagation Tracker — `valuator/core/decomposition_gate.py`

```python
class BackpropagationTracker:
    def __init__(self, initial_threshold: float, learning_rate: float) -> None:
        self._threshold = initial_threshold
        self._lr = learning_rate
        self._predictions: dict[str, DecompositionOutcome] = {}

    def current_threshold(self) -> float:
        return self._threshold

    def record_prediction(self, outcome: DecompositionOutcome) -> None:
        self._predictions[outcome.task_id] = outcome

    def has_prediction(self, task_id: str) -> bool:
        return task_id in self._predictions

    def observe_outcome(self, task_id: str, children: list[Task]) -> None:
        """
        actual_efficiency = atomic_done_children / total_children

        predicted_signal = clamp(predicted_score, -0.5, 0.5)
        actual_signal = actual_efficiency - 0.5

        threshold += learning_rate * (predicted_signal - actual_signal)
        threshold = clamp(threshold, -0.5, 0.5)
        """
```

**여기서 atomic_done child의 정의**:

- `AtomicTask`
- `state == DONE`
- `step_count <= 2`

즉, 한 번의 tool 실행과 한 번의 aggregate 정도로 끝난 자식만 효율적인 decomposition leaf로 본다.
중간에 재분해되어 `ComplexTask`로 승격된 자식은 효율 자식으로 계산하지 않는다.

### 4.5 StepPlanner 확장 — `valuator/core/step_planner.py`

```python
async def requery_without_decompose(
    self,
    task: Task,
    ctx: TaskContext,
    rejection_reason: str,
) -> TaskDecision:
    """
    DECOMPOSE 기각 후 1회만 대체 결정을 요청한다.

    - system prompt에서 DECOMPOSE 설명 제거
    - [DECOMPOSITION_REJECTED] 섹션 추가
    - repair loop 없이 단일 generate_json 호출
    - 응답이 다시 DECOMPOSE면 ValueError
    """
```

이 경로는 "gate에 걸린 분해를 다른 action으로 바꾸는 것"이 목적이다.
같은 step 안에서 gate를 재귀적으로 다시 돌리지 않는다.

### 4.6 Agent 통합 — `valuator/core/agent.py`

```python
class Agent:
    def __init__(
        self,
        *,
        scheduler: Scheduler,
        shared_state: SharedState,
        tool_registry: ToolRegistry,
        llm_client: Any,
        query_analysis: QueryAnalysis,
        on_event: Callable[[AgentEvent], Awaitable[None]] | None = None,
        step_planner: StepPlanner | None = None,
        trace_writer: Any | None = None,
        gate_config: GateConfig | None = None,
        decomposition_critic: DecompositionCritic | None = None,
    ) -> None:
        self._gate_config = gate_config or GateConfig(...)
        self._critic = decomposition_critic
        if self._gate_config.enabled and self._critic is None:
            self._critic = DecompositionCritic(llm_client)
        self._tracker = BackpropagationTracker(
            initial_threshold=self._gate_config.initial_threshold,
            learning_rate=self._gate_config.learning_rate,
        )
```

`Agent`는 이미 `llm_client`를 받고 있으므로, gate가 켜져 있을 때 기본 critic을 직접 생성한다.
이 ADR에서는 runner 스크립트에 별도 critic 주입 코드를 요구하지 않는다.

**`_step_one()` 변경 위치**:

```text
현재:
  ctx = _build_context(...)
  decision = await task.step(ctx)
  validation
  apply_decision

변경 후:
  ctx = _build_context(...)
  decision = await task.step(ctx)
  if decision.action is DECOMPOSE:
      decision = await _gate_decompose(task, decision, ctx)
  validation
  apply_decision
  if decision.action is AGGREGATE and tracker.has_prediction(task.id):
      tracker.observe_outcome(task.id, task.children())
```

**`_gate_decompose()` 동작 요약**:

1. `pre_filter()`
2. `ACCEPT`면 즉시 통과
3. `REJECT`면 `requery_without_decompose()`
4. `UNCERTAIN`이면 critic 호출
5. critic 실패 시 static-only fallback
6. 최종 허용된 분해만 `record_prediction()`
7. 기각 시 `AgentEvent(type="decomposition_gated", ...)` 발행

**`decomposition_gated` 이벤트 payload**:

```json
{
  "static_verdict": "reject|uncertain",
  "used_critic": true,
  "static_score": -0.12,
  "net_score": -0.21,
  "threshold": 0.0,
  "reason": "children overlap and a single tool call is sufficient"
}
```

## 5. Penalty, Scoring, and Learning

### 5.1 Static Score

```text
penalty = w_d * depth_cost + w_b * breadth_cost + w_t * token_pressure
bonus = w_tr * tool_resolvability
static_score = bonus - penalty
```

### 5.2 Static 각 항

**depth_cost**:

```text
(depth / max_depth) ** 2
```

예:

```text
depth=0 -> 0.0000
depth=1 -> 0.0625
depth=2 -> 0.2500
depth=3 -> 0.5625
depth=4 -> 1.0000
```

**breadth_cost**:

```text
log2(child_count) / log2(max_children)
```

예:

```text
children=2 -> 0.333
children=3 -> 0.528
children=5 -> 0.774
children=8 -> 1.000
```

**tool_resolvability**:

```text
count(child.tool_hint in executable_tools) / len(children)
```

여기서 `executable_tools = frozenset(ctx.available_tools)`다.
즉, 지금 이 task에서 실제로 허용된 도구만 bonus 대상으로 본다.

**token_pressure**:

```text
estimated_tokens = child_count * avg_tokens_per_step
budget_per_branch = max_steps_per_task * avg_tokens_per_step / (depth + 1)
token_pressure = estimated_tokens / budget_per_branch
```

### 5.3 Critic Score

```python
def critic_to_score(verdict: CriticVerdict, actual_children: int) -> float:
    score = 0.0
    if verdict.single_tool_possible:
        score -= 0.5
    score -= 0.2 * len(verdict.redundant_pairs)
    score += verdict.coverage_pct / 100.0
    excess = actual_children - verdict.min_children
    if excess > 0:
        score -= 0.1 * excess
    score += 0.3 if verdict.allow else -0.3
    return score
```

### 5.4 최종 결합

```text
net_score = static_weight * static_score + critic_weight * critic_score
rejected = net_score <= threshold
```

Static-only 경로는 다음과 같이 처리한다.

```text
net_score = static_score
rejected = net_score <= threshold
```

### 5.5 Backpropagation

raw efficiency와 predicted score의 스케일이 다르므로, threshold 업데이트 전 신호를 정렬한다.

```text
predicted_signal = clamp(predicted_score, -0.5, 0.5)
actual_efficiency = atomic_done_children / total_children
actual_signal = actual_efficiency - 0.5

threshold_{t+1} = clamp(
    threshold_t + alpha * (predicted_signal - actual_signal),
    -0.5,
    0.5,
)
```

예:

| 상황 | predicted_score | actual_efficiency | actual_signal | threshold 변화 |
|------|-----------------|-------------------|---------------|----------------|
| 허용했는데 비효율 | 0.30 | 0.10 | -0.40 | 상승 |
| 허용했고 효율적 | 0.30 | 0.80 | 0.30 | 유지 또는 소폭 하락 |
| 허용했는데 매우 효율적 | 0.10 | 1.00 | 0.50 | 하락 |
| 기각 | - | - | - | 변화 없음 |

## 6. File Changes

### 새 파일

| 파일 | 역할 |
|------|------|
| `valuator/core/decomposition_types.py` | 게이트 관련 도메인 타입 |
| `valuator/core/decomposition_gate.py` | static score, critic 결합, tracker |
| `valuator/core/decomposition_critic.py` | LLM critic boundary adapter |
| `tests/test_decomposition_gate.py` | static/combine/tracker 테스트 |
| `tests/test_decomposition_critic.py` | critic payload/prompt 테스트 |

### 수정 파일

| 파일 | 변경 내용 |
|------|-----------|
| `valuator/core/agent.py` | gate 삽입, tracker 연동, 기본 critic 생성, 이벤트 발행 |
| `valuator/core/step_planner.py` | `requery_without_decompose()` 추가 |
| `valuator/utils/config.py` | gate 관련 env 로딩 |

Runner 스크립트 변경은 이 ADR의 필수 범위가 아니다.
기본 critic 생성은 `Agent` 내부에서 처리한다.

## 7. Configuration

```bash
# 전체 on/off
DECOMPOSITION_GATE_ENABLED=true

# 학습 초기값
DECOMPOSITION_GATE_INITIAL_THRESHOLD=0.0
DECOMPOSITION_GATE_LEARNING_RATE=0.1

# Static 경계
DECOMPOSITION_GATE_ACCEPT_BOUND=0.4
DECOMPOSITION_GATE_REJECT_BOUND=-0.3

# 정규화 기준
DECOMPOSITION_GATE_MAX_DEPTH=4
DECOMPOSITION_GATE_MAX_CHILDREN=8

# Static 가중치
DECOMPOSITION_GATE_WEIGHT_DEPTH=0.3
DECOMPOSITION_GATE_WEIGHT_BREADTH=0.2
DECOMPOSITION_GATE_WEIGHT_TOOL=0.3
DECOMPOSITION_GATE_WEIGHT_TOKEN_PRESSURE=0.2

# 결합 가중치
DECOMPOSITION_GATE_STATIC_WEIGHT=0.4
DECOMPOSITION_GATE_CRITIC_WEIGHT=0.6
```

`DECOMPOSITION_GATE_ENABLED=false`면 gate 전체를 bypass한다.

구성 검증 규칙:

- `accept_bound > reject_bound`
- `static_weight + critic_weight > 0`
- `max_depth >= 1`
- `max_children >= 2`

## 8. Edge Cases

| 케이스 | 처리 |
|--------|------|
| root task | depth=0으로 계산 |
| child가 1개뿐인 분해 | critic은 redundancy보다 `single_tool_possible`과 `min_children`에 집중 |
| `tool_hint` 전원 없음 | `tool_resolvability=0`; gray zone 또는 reject 가능성 증가 |
| critic 호출 실패 | static-only fallback |
| critic JSON 파싱 실패 | static-only fallback |
| reject된 분해 | tracker에 기록하지 않음 |
| 재질의 결과가 다시 `DECOMPOSE` | `ValueError`; 같은 step에서 무한 루프 방지 |
| 자식이 중간에 재분해됨 | `ComplexTask`로 간주되므로 atomic efficiency에서 제외 |
| threshold 극단화 | `[-0.5, 0.5]`로 clamp |

## 9. Verification

### Unit Tests

`tests/test_decomposition_gate.py`

- `depth_cost()`
- `breadth_cost()`
- `tool_resolvability()`
- `token_pressure()`
- `pre_filter()`의 `ACCEPT`, `REJECT`, `UNCERTAIN`
- `critic_to_score()`
- `combine()`
- `BackpropagationTracker.observe_outcome()`

### Critic Tests

`tests/test_decomposition_critic.py`

- 정상 JSON -> `CriticVerdict`
- invalid JSON -> 예외
- prompt에 parent / children / ancestry / available tools 포함 확인

### Integration Tests

- `DECOMPOSE -> Static REJECT -> requery`
- `DECOMPOSE -> Static UNCERTAIN -> critic allow`
- `DECOMPOSE -> Static UNCERTAIN -> critic reject -> requery`
- critic 실패 -> static-only fallback
- 허용된 분해만 tracker 기록
- `AGGREGATE` 시 threshold 업데이트
- `decomposition_gated` 이벤트 detail 검증

## 10. Decisions

| 항목 | 결정 | 근거 |
|------|------|------|
| gate 위치 | agent의 `DECOMPOSE` 직후 | 자식 생성 전에 비용 차단 필요 |
| aggregation 역할 | outcome evaluation + backpropagation | 실제 실행 결과로 기준 학습 |
| aggregation LLM critic | 이번 ADR에서는 도입 안 함 | 추가 비용 대비 변화 범위 과다 |
| tool_resolvability 기준 | `ctx.available_tools` | 실제 실행 가능성 기준이 더 직접적 |
| critic 기본 생성 위치 | `Agent` 내부 | 호출부 변경 최소화 |
| prediction 기록 시점 | 허용된 분해 직후 | 기각된 분해는 관측값 없음 |
| critic 실패 처리 | static-only fallback | critic은 보조 신호 |
| gate 재적용 | 같은 step 안에서는 1회만 | 무한 루프 방지 |
