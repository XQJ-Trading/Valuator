# 아키텍처 재검토: Atomic task 즉시 승격 + Reconcile

## 탑다운 진단

### 현재 데이터 흐름

```
Tool 실행 → raw result
  ├─ SharedState.publish(key, value)  → LLM context ([SHARED_FACTS], [CONFLICTS])
  ├─ EvidenceStore.record()           → dedup + LLM context ([EVIDENCE])  
  └─ session_store.write_execution_result() → disk (report용)

AGGREGATE/FINALIZE 시:
  ├─ task.output = decision.output
  ├─ SharedState.publish(facts)       → 다음 task의 LLM context
  └─ session_store.write_aggregation_report() → disk (report용)
```

세 경로는 합류하지 않는다. 특히 **SharedState의 conflict 정보는 report_artifacts에 전달되지 않는다.**

### 문제 2번 근본 원인: early-return이 LLM 해석을 우회

`loop.py:300-315`에서 atomic task tool 성공 시 LLM 호출 없이 즉시 AGGREGATE한다.
이것은 `actions.py:13-14`의 정책(`last_tool_success → EXECUTE 금지`)과 짝이다.
tool 성공 후 LLM이 할 수 있는 건 AGGREGATE뿐이므로, 비용 절약을 위해 early-return이 존재한다.

**하지만 이 최적화가 치명적 부작용을 만든다:**
- LLM이 raw result를 해석할 기회가 없다
- `decision.output = task.tool_results[-1].result` — raw payload 그대로
- `decision.facts = {}` — **facts가 비어있다** → SharedState에 아무것도 publish되지 않는다
- 따라서 같은 metric에 대해 서로 다른 값이 들어와도 **conflict 탐지 자체가 불가능**

이것이 핵심이다. early-return은 비용 절약이 아니라 **conflict 탐지 경로를 완전히 끊는다.**

### 문제 3번 근본 원인: report_artifacts가 SharedState를 읽지 않는다

`render_aggregation_report`는 child_sources (disk의 markdown/json)만 읽고, SharedState의 conflict 정보는 참조하지 않는다. LLM이 AGGREGATE 시 conflict을 해소했더라도, report에는 child markdown이 그냥 concat된다.

**그러나** — LLM이 AGGREGATE할 때 `[CONFLICTS]`를 보고 판단한 결과가 `decision.output`에 반영되고, 이것이 report의 summary 부분이 된다. child markdown concat은 "Supporting Evidence" 섹션이다. 즉 **summary는 LLM 판단 결과이고, evidence는 원본 나열**이라는 구조다.

이 구조 자체는 합리적이다. 문제는 **문제 2번 때문에 facts가 비어서 conflict이 애초에 탐지되지 않는다**는 것이다.

### 최선의 해법은 무엇인가?

두 가지 접근을 비교한다:

**접근 A: early-return 제거 + 프롬프트 보강 (기존 계획)**
- early-return을 제거하여 LLM이 raw result를 해석하게 한다
- LLM이 facts를 추출하면 SharedState에 publish → conflict 탐지 복구
- source_type을 tool metadata로 추가하여 conflict context 강화
- reconcile은 LLM에 위임 (기존 `[CONFLICTS]` 경로)

**접근 B: early-return의 output/facts 생성 로직만 보강**
- early-return 구조는 유지하되, `facts={}`가 아니라 raw result에서 key-value를 추출
- 하지만 raw result의 구조가 tool마다 다르므로 범용 추출이 어렵다
- 결국 LLM 없이는 의미 있는 facts 추출이 불가능

**결론: 접근 A가 맞다.** early-return 제거가 유일한 구조적 해법이다.

단, 기존 계획에서 불필요했던 부분:
- ~~별도 reconcile.py 모듈~~ → 기존 SharedState conflict + LLM 판단으로 충분
- ~~report_artifacts에서 conflict 렌더링~~ → LLM이 AGGREGATE output에 반영하면 됨. report 구조 변경 불필요
- ~~source_type을 Fact/SharedState에 추가~~ → 유용하지만 **핵심 문제 해결과 무관**. 별도 작업으로 분리

---

## 최종 계획

### 변경 1: early-return 제거 (핵심)

**파일:** `valuator/core/agent/loop.py` L300-315

```python
# 삭제할 코드:
if (
    isinstance(task, AtomicTask)
    and task.last_tool_success is True
    and task.tool_results
):
    return (
        ctx,
        TaskDecision(
            action=Action.AGGREGATE,
            output=task.tool_results[-1].result,
            facts={},
            children=[],
        ),
        ...
    )
```

제거 후 `task.step(ctx)` → `StepPlanner.decide`로 진입하여 LLM이:
1. raw tool result를 해석
2. 핵심 수치를 facts dict로 추출
3. AGGREGATE 결정과 함께 output + facts 반환

이렇게 되면 `Scheduler.apply_decision`에서 facts가 `SharedState.publish`되고, 같은 key에 다른 값이 오면 Conflict가 탐지된다.

### 변경 2: AGGREGATE 프롬프트 보강

**파일:** `valuator/core/planning/prompts.py`

현재 L129-131에서 `last_tool_success is True`일 때 "You must not return EXECUTE"만 안내한다. 여기에 추가:

```
"tool 결과에서 핵심 수치를 facts dict의 key-value로 추출하라."
"key는 '{company}:{metric}:{fiscal_period}' 형식을 사용하라."
"output에는 해석과 맥락을 포함하고, facts에는 수치만 넣어라."
```

이 지시가 있어야 LLM이 일관된 key 형식으로 facts를 publish하고, SharedState에서 같은 metric의 conflict을 탐지할 수 있다.

### 변경 3: conflict 발생 시 AGGREGATE 지시문 보강

**파일:** `valuator/core/planning/prompts.py` L80-91 (AGGREGATE 지시문)

현재 `[CONFLICTS]` 섹션이 context에 주입되지만, LLM에게 어떻게 해소하라는 지시가 없다. 추가:

```
"[CONFLICTS]가 있으면: 출처의 신뢰도(공시 > 거래소 > IR > 뉴스 > 증권사 > 커뮤니티)를 기준으로 판단하라."
"동일 신뢰도에서 값이 다르면 [INFORMATION GAPS]로 분류하라."
```

### 구현 순서

1. `loop.py` — early-return 분기 삭제 (L300-315)
2. `prompts.py` — tool 성공 후 facts 추출 지시 추가 (L129 부근)
3. `prompts.py` — AGGREGATE 지시에 conflict 해소 가이드 추가 (L80 부근)
4. 테스트 — 기존 `python -m pytest tests/` 통과 확인

### 검증

- `python -m pytest tests/` 통과
- atomic task tool 성공 후 LLM 호출이 발생하는지 로그 확인
- 같은 metric에 다른 값이 publish될 때 `[CONFLICTS]`에 나타나는지 확인
- 최종 리포트에서 모순 수치가 정리되었는지 확인

### 향후 작업 (이번 범위 밖)

- tool별 `source_type` metadata 추가 → conflict context 강화
- `render_aggregation_report`에서 conflict 섹션 렌더링 (LLM 판단이 부족할 경우 fallback)
