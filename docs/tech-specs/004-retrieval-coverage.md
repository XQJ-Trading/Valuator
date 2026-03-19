# TS-004: Retrieval Coverage 개선

**Status**: Draft
**Date**: 2026-03-19

---

## 1. Problem

세션 S-20260319-053942855691Z (NVTS) 기준으로, 본 TS는 다음 3가지를 **우선 해결**한다.

1) **RC1**: replan이 이전 round에서 **무엇이 커버됐고 무엇이 비어있는지** 모르기 때문에 동일 의미를 반복 검색하고 source가 편향된다.
2) **RC3**: DCF 필수 입력(매출/매출총이익/순이익/EBITDA)이 누락되어 valuation 품질이 떨어진다.
3) **RC4**: domain/aggregation 단계에서 근거 없는 정량 수치가 생성될 수 있다.

RC2(metadata 파이프라인)는 RC1을 지원하는 **필수 보조 조건**으로 포함한다.

| 증상 | 근본 원인 |
|:---|:---|
| Round 간 동일 내용 재검색 | **RC1**: `replan()`이 aspect 커버리지를 모른다 |
| CEO 소스 편향 | **RC1**: 어떤 aspect가 비어있는지 모르니 보완적 도구를 선택할 수 없다 |
| sec_tool 단일 청크 | **RC2**: `ToolResult.metadata`가 executor에서 유실된다 |
| Review 검증 미흡 | **RC2**: reviewer가 retrieval 품질을 모른다 |
| DCF 재무제표 부족 | **RC3**: yfinance가 income statement 핵심 필드를 추출하지 않는다 |
| 검색 없는 생성 | **RC4**: domain_tool/aggregation에 grounding 제약이 없다 |

---

## 2. Architecture

### 2.1 경계(Boundary)와 내부 책임

- **Boundary**: `Executor`가 tool 결과(`ToolResult`)를 수신하는 지점
  - 여기서만 외부 payload를 구조화한다.
  - 여기서만 retrieval 품질 신호를 추출한다.
- **Business logic**: `Planner`, `Reviewer`, `Aggregator`
  - boundary에서 확정된 구조를 사용한다.
  - 내부에서 raw tool payload를 재파싱/재검증하지 않는다.

### 2.2 데이터 흐름 (현재 vs 변경)

```
Engine._run_round()
  → executor.execute_batch()        → ExecutionArtifact[]
  → aggregator.build_task_report()  → extraction → AspectFacts per material
  → aggregator.finalize()           → AggregationResult (aspect_coverage 포함)
  → reviewer.review()               → ReviewResult
  ──────────────────────────────────────────────
  현재 반환: (ReviewResult, final_path, review_path)
  변경 반환: (ReviewResult, AggregationResult, final_path, review_path)
                                  │
Engine._execute_plan()            │
  → planner.replan(plan, review) ─┘
                          ↓ 변경
    planner.replan(plan, review, aggregation)
      → aggregation.aspect_coverage에서 uncovered aspect 추출
        → [ASPECT_COVERAGE] 섹션: domain별 uncovered aspect 목록
        → planner가 uncovered aspect를 타겟하는 검색을 설계
```

핵심 전환: **”무엇을 검색했는가”(query signature)** 대신 **”무엇이 비어있는가”(aspect gap)**로 planner를 구동한다. 기존 extraction 파이프라인(`StructuredExtractor`)이 이미 aspect별 fact를 추출하고 `uncovered_aspects`를 계산하며, `_aspect_coverage_summary`가 `finalize_aggregation`에서 이를 `{aspect_id: “covered”|”uncovered”}`로 집약한다. 이 기존 출력을 planner에 전달할 뿐이다.

### 2.3 RC 간 의존 관계

```
RC1 (aspect coverage → replan)  ←── RC2 (metadata 파이프라인, support)
  │                                    │
  │  uncovered aspect로                │  selected_count == 0이면
  │  planner 구동                      │  fallback replan 트리거
  ▼                                    ▼
  gap 타겟 검색 설계                   thin retrieval unit 강제 재검색

RC3 (yfinance 필드, primary)    독립
RC4 (grounding, primary)        독립
```

---

## 3. RC1. Aspect coverage → replan

**문제**: planner는 이전 round의 결과 품질을 모르기 때문에 동일 의미 재검색을 반복한다.

**해법**: aggregation이 이미 계산하는 `AggregationResult.aspect_coverage`를 replan에 주입한다. planner는 “무엇이 비어있는가”를 보고 gap-targeted 검색을 설계한다.

### 3.0 왜 query signature가 아니라 aspect coverage인가

query signature 접근은 “같은 걸 또 검색했나”만 답한다:
- 표면 형태가 달라지면 의미적 중복을 못 잡는다
- **무엇이 빠졌는지** 알 수 없어 planner가 gap을 볼 수 없다

aspect coverage는 “무엇을 알고 무엇을 모르는지”를 답한다:
- `RubricAspect` 전체 집합이 스키마 역할 → uncovered aspect가 자동으로 보인다
- 중복 검색이 원천 차단된다 — covered aspect를 다시 검색할 이유가 없다
- 새 인프라 없이 기존 `_aspect_coverage_summary` 출력을 그대로 사용한다

### 3.1 데이터 계약

**새 타입 없음.** 기존 `AggregationResult.aspect_coverage: dict[str, str]`을 그대로 사용한다. 값은 `”covered”` 또는 `”uncovered”`.

### 3.2 `core/orchestrator/engine.py`

`_run_round`이 `AggregationResult`를 추가 반환한다.

```python
# engine.py:257 — 반환 타입
) -> tuple[ReviewResult, AggregationResult, Path, Path]:

# engine.py:283-294 — 반환
execution = state.execution_result()
aggregation = self.aggregator.finalize_aggregation(...)
final_path = self.workspace.write_final(aggregation.final_markdown)
review = await self.reviewer.review(plan, execution, aggregation)
review_path = self.workspace.write_review(review)
return review, aggregation, final_path, review_path

# engine.py:115 — 호출부
review_payload, aggregation, final_path, review_path = await self._run_round(...)

# engine.py:131 — replan 호출
next_plan = await self.planner.replan(plan, review_payload, aggregation)
```

### 3.3 `core/planner/service.py`

replan 시그니처 확장 + uncovered aspects 주입.

`replan()` 시그니처 (`service.py:85`):
```python
async def replan(
    self,
    current_plan: Plan,
    review: ReviewResult,
    aggregation: AggregationResult | None = None,
) -> Plan:
```

`_refresh()` 내부 — `_focused_unit_text`에 전달:
```python
aspect_coverage_hint = self._aspect_coverage_text(aggregation)

focused_query = self._focused_unit_text(
    ...,
    aspect_coverage_hint=aspect_coverage_hint,
)
```

신규 메서드 — `AggregationResult.aspect_coverage`에서 uncovered만 추출:
```python
def _aspect_coverage_text(
    self,
    aggregation: AggregationResult | None,
) -> str:
    if aggregation is None or not aggregation.aspect_coverage:
        return “”
    uncovered = [
        aid for aid, status in aggregation.aspect_coverage.items()
        if status == “uncovered”
    ]
    if not uncovered:
        return “”
    return “\n”.join(f”- {aid}” for aid in uncovered)
```

`_focused_unit_text()` (`service.py:666`) — `aspect_coverage_hint` 파라미터 추가:
```python
def _focused_unit_text(
    self,
    *,
    unit: QueryUnit,
    items: list[Any],
    reasons: list[str],
    domain_coverage_hint: str = “”,
    aspect_coverage_hint: str = “”,
) -> str:
    chunks: list[str] = [...]
    # 기존 chunks 구성 그대로
    if aspect_coverage_hint:
        chunks.append(
            “[ASPECT_COVERAGE]\n”
            “아래 aspect는 이전 round에서 커버되지 않았다. “
            “이 aspect를 타겟하는 검색을 설계하라.\n”
            + aspect_coverage_hint
        )
    return “\n\n”.join(chunks)
```

### 3.4 설계 결정

**왜 이것으로 충분한가**:
- planner에게 필요한 정보는 “뭘 또 검색할까”가 아니라 “뭐가 비었나”다.
- `aspect_coverage`는 `finalize_aggregation`에서 이미 계산된다. 새 계산 없음.
- 새 타입, 새 정규화 로직, 새 regex 없음. `AggregationResult`를 한 단계 위로 전달할 뿐이다.

---

## 4. RC2. Metadata 파이프라인 복원

**문제**: executor가 `ToolResult.metadata`를 meta.json에 저장하지 않아 유실. reviewer가 retrieval 품질(selected_count 등)을 볼 수 없다.

### 4.1 `core/contracts/plan.py:50`

ExecutionArtifact에 필드 1개 추가.

```python
@dataclass(slots=True)
class ExecutionArtifact:
    ...
    domain_payload: dict[str, Any] = field(default_factory=dict)
    tool_metadata: dict[str, Any] = field(default_factory=dict)  # 추가
```

### 4.2 `core/executor/service.py:244-259`

metadata 저장 + artifact 전달.

meta.json 저장:
```python
# service.py:244-250
meta = {"tool": tool_name, "args_hash": args_hash}
if result.metadata:
    meta["retrieval"] = result.metadata  # 추가 (1줄)
workspace.write_output_metadata(leaf_output_path, meta)
```

ExecutionArtifact 생성:
```python
# service.py:251-260
return ExecutionArtifact(
    ...,
    tool_metadata=result.metadata or {},  # 추가 (1줄)
)
```

cached path (`service.py:197-205`): cached 결과는 이전 round에서 이미 검증됨. `tool_metadata={}` (빈 dict).

### 4.3 `core/reviewer/service.py`

thin retrieval을 기존 fallback 로직에 통합. **신규 메서드/클래스 없음**.

`review()` 내부, `_fallback_action_nodes` 호출 전 (`service.py:163` 부근):
```python
art_by_task = {a.task_id: a for a in execution.artifacts}
thin_unit_ids = [
    uid
    for task in leaf_tasks.values()
    if (meta := (art_by_task.get(task.id) and art_by_task[task.id].tool_metadata)
    and meta.get("selected_count", -1) == 0
    for uid in task.query_unit_ids
]
```

`_fallback_action_nodes()` (`service.py:427`) — 파라미터 1개 추가:
```python
def _fallback_action_nodes(self, *, ..., thin_retrieval_unit_ids: list[int] = ()) -> list[int]:
    ...
    nodes.update(thin_retrieval_unit_ids)  # 기존 nodes set에 추가 (1줄)
    ...
```

### 4.4 설계 결정

**`selected_count == 0`만 감지하는 이유**: "0개 선택"은 도구에 무관하게 검색 실패를 의미한다. selected_count가 낮지만 0이 아닌 경우(예: 1/500)는 RC1이 처리한다 — planner가 prior retrieval에서 "1개만 찾았다"는 것을 보고 보완 쿼리를 설계한다. 임의 threshold (예: 0.05)를 도입하지 않는다.

---

## 5. RC3. yfinance income statement 필드 추가

**문제**: yfinance_tool이 `t.financials`에서 `operating_income`, `interest_expense`만 추출. DCF에 필수적인 revenue, gross_profit, net_income, ebitda가 누락.

### 5.1 `domain/knowledge/financial.py:67`

STATEMENT_FIELDS에 4개 추가 (`interest_expense` 엔트리 뒤):

```python
StatementField(
    "total_revenue",
    ("Total Revenue", "Total Revenue USD"),
    "income",
),
StatementField(
    "gross_profit",
    ("Gross Profit",),
    "income",
),
StatementField(
    "net_income",
    ("Net Income Common Stockholders", "Net Income"),
    "income",
),
StatementField(
    "ebitda",
    ("EBITDA", "Normalized EBITDA"),
    "income",
),
```

DERIVED_RATIOS에 `gross_margin` 추가:
```python
DerivedMetric("gross_margin", "gross_profit", "total_revenue"),
```

alias 출처: yfinance `Ticker.financials` DataFrame의 실제 row label. `"Net Income Common Stockholders"`가 1순위인 이유는 yfinance가 이 label을 우선 사용하기 때문.

### 5.2 `tools/yfinance_tool.py:161-180`

pick 호출 + result dict + summary (기존 패턴과 동일):

```python
# yfinance_tool.py:163-166 뒤에 추가
total_revenue, _ = pick(fin, field_map["total_revenue"].aliases)
gross_profit, _ = pick(fin, field_map["gross_profit"].aliases)
net_income, _ = pick(fin, field_map["net_income"].aliases)
ebitda, _ = pick(fin, field_map["ebitda"].aliases)
```

result dict에 4개 키 추가:
```python
"total_revenue": total_revenue,
"gross_profit": gross_profit,
"net_income": net_income,
"ebitda": ebitda,
```

summary_parts에 추가:
```python
f"total_revenue={result.get('total_revenue')}",
f"net_income={result.get('net_income')}",
f"gross_margin={result.get('gross_margin')}",
```

---

## 6. RC4. Grounding 제약

**문제**: domain_tool이 `[CONTEXT]`에 없는 수치를 자유 생성. aggregation에서도 LEAF 근거 없는 팩트가 구분 없이 합성.

### 6.1 `tools/domain_tool.py:39-43`

`[INSTRUCTION]` 블록에 grounding 규칙 추가:

```python
"[INSTRUCTION]\n"
"각 aspect별로 `### [ASPECT:{aspect_id}]` 헤더 아래 분석을 작성하라.\n"
"high priority aspects는 반드시 커버하라.\n"
"정량 데이터와 절대 시점은 그대로 유지하라.\n"
"[CONTEXT]에 없는 정량 수치(금액, 비율, 날짜)는 생성하지 마라.\n"
"정량 근거가 부족하면 '데이터 부족'으로 표시하고 필요한 추가 소스를 명시하라.\n"
```

### 6.2 `core/aggregator/service.py:401`

ROOT 규칙 블록 마지막에 추가:

```python
"- `[SUPPORTING_MATERIALS]`에 근거가 없는 정량 수치는 생성하지 않는다.\n"
"- 근거 부족 수치는 '데이터 부족'으로 명시한다.\n"
```

### 6.3 설계 결정

기존 규칙 "정량 데이터와 절대 시점은 그대로 유지하라"와의 관계:
- 기존 규칙: 있는 값을 보존
- 신규 규칙: 없는 값은 생성 금지
- 결과적으로 정량 수치는 항상 source-backed 또는 explicitly missing 상태만 허용한다.

---

## 7. 변경하지 않는 것

- **sec_tool CHUNK_SIZE** — RC1+RC2로 파이프라인 수준에서 자가 교정
- **새 도구 (proxy_tool, earnings_call_tool)** — RC1로 기존 도구 조합 다각화가 먼저
- **reviewer prompt 변경** — thin retrieval은 deterministic fallback으로 처리. LLM prompt에 추가 규칙을 넣지 않는다

---

## 8. 수정 파일 목록 (Concrete Scope)

| 파일 | RC | 변경 | 추가 줄 수 |
|:---|:---|:---|:---|
| `core/orchestrator/engine.py` | RC1 | `_run_round` 반환에 `AggregationResult` 추가 + replan 호출 | ~4 |
| `core/planner/service.py` | RC1 | `_aspect_coverage_text()` + `_focused_unit_text()` 확장 | ~15 |
| `core/contracts/plan.py` | RC2 | `ExecutionArtifact.tool_metadata` | 1 |
| `core/executor/service.py` | RC2 | meta.json + artifact에 metadata 전달 | 2 |
| `core/reviewer/service.py` | RC2 | thin_unit_ids 계산 + fallback 파라미터 | ~6 |
| `domain/knowledge/financial.py` | RC3 | STATEMENT_FIELDS 4개 + DERIVED_RATIOS 1개 | ~18 |
| `tools/yfinance_tool.py` | RC3 | pick() 4개 + result + summary | ~10 |
| `tools/domain_tool.py` | RC4 | 정량 생성 금지 + 데이터 부족 표기 규칙 | 2 |
| `core/aggregator/service.py` | RC4 | ROOT에서 ungrounded 정량 생성 금지 규칙 | 2 |

---

## 9. 검증

1. `python -m pytest tests/`
2. **RC1**:
   - round-02 replan 시 `[ASPECT_COVERAGE]` 섹션에 uncovered aspect 목록 포함
   - round-02 신규 leaf가 uncovered aspect를 타겟 (round-01에서 이미 covered된 aspect를 재검색하지 않음)
3. **RC2**:
   - `execution/**/result.md.meta.json`에 `retrieval.selected_count` 존재
   - reviewer fallback 노드에 `selected_count==0` unit이 포함
4. **RC3**:
   - `python -c "from valuator.domain.knowledge.financial import STATEMENT_FIELDS; print([f.canonical for f in STATEMENT_FIELDS])"`
   - 출력에 `total_revenue`, `gross_profit`, `net_income`, `ebitda` 포함
5. **RC4**:
   - final.md 정량값 샘플링 시, 각 값이 `[SUPPORTING_MATERIALS]` 근거를 갖거나 `데이터 부족`으로 표기됨

### 9.1 최소 테스트 케이스 (추가 권장)

- `tests/planner/test_aspect_coverage_text.py`
  - `AggregationResult.aspect_coverage`에 uncovered aspect가 있을 때 텍스트 생성 검증
  - 모두 covered일 때 빈 문자열 반환 검증
- `tests/reviewer/test_thin_retrieval_fallback.py`
  - `selected_count==0` 입력 시 fallback node 생성 검증
- `tests/tools/test_yfinance_income_fields.py`
  - 신규 income 필드가 result에 포함되는지 검증
