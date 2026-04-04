# Speed Optimization Plan: 10min → ~4-5min

## Context

쿼리당 실행 시간이 ~10분(686s, Amazon 분석 기준)으로 길다. 트레이스 분석 결과 두 가지 주요 병목:
- **LLM 오케스트레이션 오버헤드: 392s (57%)** — 74개 step마다 LLM 호출 + 34회 decomposition gate 평가(29회 reject → requery LLM 재호출)
- **Tool 실행: 283s (41%)** — domain_tool 176s(11회), web_search 86s(11회)

---

## Optimization 1: depth_cost 수식 교체 + gate 보정 (예상 -100~160s)

### 1-A. depth_cost 수식 교체

**문제**: `(d/max_depth)²`는 max_depth=4일 때 depth 3에서 0.5625로 과도 → depth 3-4 도달 불가. max_depth 설정이 무의미.

**해결**: `(d/max_depth) ** max_depth`로 교체. Self-calibrating — max_depth-1 지점이 항상 ~1/e(0.368)에 수렴하므로 max_depth 변경 시 별도 튜닝 불필요.

```
현재 (d/max_depth)²           → 교체 (d/max_depth)^max_depth
depth 1: 0.063                → 0.004
depth 2: 0.250                → 0.063
depth 3: 0.563                → 0.316
depth 4: 1.000                → 1.000
```

**변경 파일**: [gate.py:18-20](valuator/core/decomposition/gate.py#L18-L20)

```python
# 변경 전
def depth_cost(depth: int, max_depth: int) -> float:
    d = min(depth, max_depth)
    return (d / max_depth) ** 2

# 변경 후
def depth_cost(depth: int, max_depth: int) -> float:
    d = min(depth, max_depth)
    return (d / max_depth) ** max_depth
```

### 1-B. reject_bound 보정

depth_cost 완화로 depth 3이 gate를 통과하려면 reject_bound도 조정 필요.

depth 3 + children 2 기준 총 penalty:
```
depth:   0.4 × 0.316 = 0.127
breadth: 0.35 × 0.333 = 0.117
token:   0.25 × 0.400 = 0.100
total = 0.344 → score = -0.344
```

`reject_bound`를 `-0.3` → `-0.4`으로 조정하면 depth 3이 UNCERTAIN zone으로 들어가 critic이 판단.

**변경 파일**: [gate_config.py:24](valuator/core/decomposition/gate_config.py#L24)

```python
reject_bound: float = -0.4  # was -0.3
```

### 1-C. Decomposition 사전 차단

LLM이 DECOMPOSE 제안 → gate reject → `requery_without_decompose` LLM 재호출. 이 2배 낭비를 방지.

static filter를 LLM 호출 **전에** 실행하여, reject 확실한 경우 처음부터 DECOMPOSE를 schema에서 제거.

**변경 파일**:
- [gate.py](valuator/core/decomposition/gate.py) — `would_reject_decompose()` 추가
- [planner.py](valuator/core/planning/planner.py) — `decide()`에서 LLM 호출 전 사전 확인

```python
# gate.py — 추가
def would_reject_decompose(
    task_depth: int,
    max_steps_per_task: int,
    config: GateConfig,
    estimated_children: int = 3,
) -> bool:
    """LLM 호출 전에 decompose가 reject될지 예측. 보수적 기본값 사용."""
    result = pre_filter(
        task_depth=task_depth,
        children=[TaskSpec(task_name="x", description="x")] * estimated_children,
        max_steps_per_task=max_steps_per_task,
        config=config,
    )
    return result.verdict is FilterVerdict.REJECT
```

```python
# planner.py decide() — gate_config와 scheduler 참조 필요
# StepPlanner 생성 시 gate_config, max_steps_per_task를 주입받는 방식 결정 필요
should_block = would_reject_decompose(
    task_depth=len(ctx.ancestry),
    max_steps_per_task=...,
    config=gate_config,
)
# should_block이면 allow_decompose=False로 prompt/schema 생성
```

> **주의**: `StepPlanner`가 현재 gate_config/max_steps를 모른다. 주입 방식은 구현 시 결정.

**위험**: 낮음. depth_cost 수식 변경으로 사전 차단 대상이 진짜 한계(depth=max_depth) 근처로 한정됨.

---

## Optimization 2: Concurrency 증가 (예상 -80~120s)

**문제**: I/O-bound tool 호출(Gemini API, Perplexity API, SEC EDGAR)이 concurrency 제한에 묶여 대기.

**변경 파일**:
- [config.py:221](valuator/utils/config.py#L221) — `AGENT_CONCURRENCY` 기본값 `8` → `10`
- `.env` — `AGENT_CONCURRENCY=10` 추가

**위험**: 없음. 모든 tool이 stateless I/O. SharedState 쓰기는 AGGREGATE에서만 발생하고 dependency로 순서 보장.

---

## Optimization 3: Atomic Task Fast-Path Aggregate (예상 -60~100s)

**문제**: AtomicTask가 tool 실행 성공 후, 유일한 유효 action이 AGGREGATE임에도 LLM을 호출하여 결정.
- [loop.py:200-213](valuator/core/agent/loop.py#L200-L213)에서 EXECUTE 차단 → AGGREGATE가 결정적.

**변경 파일**: [loop.py:109](valuator/core/agent/loop.py#L109) — `_step_one` 시작부에 fast-path 분기

```python
# _step_one() — ctx 생성 후, task.step(ctx) 호출 전
from ..task import AtomicTask

if (
    isinstance(task, AtomicTask)
    and task.last_tool_success is True
    and task.tool_results
):
    decision = TaskDecision(
        action=Action.AGGREGATE,
        output=task.tool_results[-1].data,
        facts={},
        children=[],
    )
    # LLM 호출 건너뛰고 기존 apply_decision 로직으로 직행
```

**위험**: 중간. LLM이 tool result를 요약/정제하던 경우 품질 차이 가능. 단, AtomicTask AGGREGATE는 대부분 tool result 그대로 전달.

---

## Optimization 4: Prompt 크기 축소 (예상 -60~80s)

**문제**: 74회 LLM 호출마다 대형 prompt. child output budget 50K, shared facts 전체 포함.

**변경 파일**: [planner.py:18-23](valuator/core/planning/planner.py#L18-L23)

```python
_decision_max_output_tokens = 8_192      # non-FINALIZE step은 4_096으로 분기
_prompt_value_preview_chars = 400        # was 600
_prompt_child_output_budget_chars = 30_000  # was 50_000
```

추가로 [prompts.py](valuator/core/planning/prompts.py)에서 FINALIZE guidance를 root task에서만 포함하도록 조건 추가.

**위험**: 낮음~중간. 30K에서 시작하여 측정 후 조정.

---

## Optimization 5: Web Search 배치 병합 (예상 -40~50s)

**문제**: web_search_tool이 batch `queries` 파라미터를 지원하지만 agent가 개별 task로 분리하여 호출.

**변경 파일**: [prompts.py](valuator/core/planning/prompts.py) — system prompt에 batch search 가이드 추가. 같은 부모의 children이 모두 web_search_tool 대상일 때 단일 task + `queries`(복수) 사용 유도.

**위험**: 낮음. `_execute_batch_search`가 이미 존재.

---

## 구현 순서

| 순서 | 최적화 | 예상 절감 | 난이도 |
|------|--------|----------|--------|
| 1 | Concurrency 증가 | 80-120s | 매우 낮음 |
| 2 | depth_cost 수식 + reject_bound + 사전 차단 | 100-160s | 낮음 |
| 3 | Prompt 크기 축소 | 60-80s | 낮음 |
| 4 | Fast-path aggregate | 60-100s | 중간 |
| 5 | Web search 배치 | 40-50s | 중간 |

**보수적 예상**: 중복/감쇄 고려 시 총 250-350s 절감 → **686s → 330~430s (5.5~7분)**

---

## 검증 방법

1. 기존 Amazon 분석 쿼리로 실행: `python scripts/run_recursive_agent_query.py`
2. trace `events.jsonl`에서 비교:
   - 총 실행 시간
   - step 수 (74 → 목표 40 이하)
   - decomposition gate reject 수 (29 → 목표 5 이하)
   - tool 실행 총 시간
3. 최종 보고서 품질을 기존 결과와 비교
4. `python -m pytest tests/` 기존 테스트 통과 확인
