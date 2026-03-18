# TS-002: Adaptive Pipeline & Domain Knowledge Restructure

**Status**: Draft
**Date**: 2026-03-17

---

## 1. Problem

세션 S-20260317-105509Z에서 실행한 "아마존 분석해줘" 쿼리 결과:
- 실행 시 ~9,000 words 수집 → 최종 보고서 ~3,500 words (**35-45% 정보 손실**)
- CEO 모듈 8개 분석 중 4개만 최종 포함, DCF segment 경로 전량 소실
- `about.md`가 3역할 혼합, `questions.yaml`은 dead code, 비개발자 편집 불가

**근본 원인**: 분석 관점(aspect)이 구조화된 타입으로 존재하지 않는다.
→ decomposition이 도메인 깊이를 모르고, aggregation이 aspect 단위 보존을 추적할 수 없다.

---

## 2. Architecture Overview

### 2.1 Component Map

시스템을 구성하는 컴포넌트와 경계, 의존 방향을 보여준다.

```
┌─────────────────────────────────────────────────────────────────────┐
│  BOUNDARY (외부 입력 → 도메인 타입 변환)                              │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │ DomainLoader │    │QueryAnalyzer │    │  StructuredExtractor │  │
│  │              │    │              │    │  (Map phase)         │  │
│  │ YAML/MD →    │    │ raw query →  │    │  raw text →          │  │
│  │ DomainModule │    │ QueryAnalysis│    │  AspectFacts[]       │  │
│  └──────┬───────┘    └──────┬───────┘    └──────────┬───────────┘  │
│         │                   │                       │              │
└─────────┼───────────────────┼───────────────────────┼──────────────┘
          │                   │                       │
          ▼                   ▼                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  BUSINESS LOGIC (도메인 타입으로만 작업)                               │
│                                                                     │
│  ┌──────────────┐  ┌─────────┐  ┌──────────┐  ┌─────────────────┐ │
│  │AspectExpander│→ │ Planner │→ │ Executor │→ │  Aggregation    │ │
│  │              │  │         │  │          │  │  (Reduce phase) │ │
│  │ QueryAnalysis│  │ Plan    │  │ Execution│  │  AspectFacts →  │ │
│  │ + rubric →   │  │         │  │ Result   │  │  Final Report   │ │
│  │ expanded     │  │         │  │          │  │                 │ │
│  │ QueryAnalysis│  │         │  │          │  │                 │ │
│  └──────────────┘  └─────────┘  └──────────┘  └─────────────────┘ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**핵심 원칙**: Boundary에서 변환을 완결한다. Business logic 내부에서는 재검증/재파싱하지 않는다.

- `DomainLoader` (boundary): YAML/Markdown 파일 → `DomainModule` 타입 (aspects 포함)
- `QueryAnalyzer` (boundary): raw query string → `QueryAnalysis` 타입
- `StructuredExtractor` (boundary): 비구조화 LLM 출력 → `AspectFacts[]` 타입
- `AspectExpander`, `Planner`, `Executor`, `Aggregation` (business logic): 도메인 타입만 사용

### 2.2 Data Flow: 타입 중심

각 단계에서 생성되는 타입과 소비하는 타입을 보여준다.

```
raw query: str
  │
  │  QueryAnalyzer (boundary)
  ▼
QueryAnalysis
  ├── query_intent: QueryIntent
  ├── domain_ids: [str]
  ├── units: [QueryUnit]          ← coarse 분해 (N개)
  └── requirements: [QueryRequirement]
  │
  │  AspectExpander (logic)
  │  읽기: DomainModule.rubric → [RubricAspect]
  ▼
QueryAnalysis (확장)
  └── units: [QueryUnit]          ← fine 분해 (M개, M ≥ N)
        └── parent_unit_id        ← 부모 unit 참조 (신규 필드)
  │
  │  Planner (logic)
  ▼
Plan
  ├── tasks: [Task]               ← task tree (leaf, module, merge)
  └── root_task_id: str
  │
  │  Executor (logic)
  ▼
ExecutionResult
  └── artifacts: [ExecutionArtifact]
        ├── content: str          ← 비구조화 텍스트 (여기까지 현재와 동일)
        ├── domain_id: str
        └── domain_payload: dict
  │
  │  StructuredExtractor (boundary)  ◀── RubricAspect[] 참조
  ▼
ExtractionResult (per artifact)
  ├── aspect_facts: [AspectFacts]
  │     ├── aspect_id: str
  │     ├── facts: {key: value}   ← 구조화된 정보 (손실 불가)
  │     └── evidence: str         ← 원문 발췌
  └── uncovered_aspects: [str]    ← 커버되지 않은 aspects
  │
  │  Aggregation.reduce (logic)
  │  Sub-Reduce: parent unit별 AspectFacts 통합
  │  Root Reduce: 전체 통합 + contract 검증
  ▼
AggregationResult
  ├── final_markdown: str
  ├── covered_requirement_ids: [str]
  ├── missing_requirement_ids: [str]
  └── aspect_coverage: {aspect_id: covered/uncovered}  ← 신규
```

### 2.3 Aspect가 파이프라인을 관통하는 방식

`RubricAspect`는 단일 타입이지만, 파이프라인의 4개 단계에서 각각 다른 역할을 수행한다:

```
RubricAspect (rubric.yaml에서 로드)
  │
  ├─① AspectExpander:  aspect 수 → unit 확장 깊이 결정
  │    "high-priority aspect가 3개 이상이면 unit을 분해한다"
  │
  ├─② DomainTool:      aspect list → 구조화된 분석 출력 유도
  │    "### [ASPECT:integrity] 헤더 아래 분석을 작성하라"
  │
  ├─③ Extractor (Map):  aspect ids → extraction 타겟 가이드
  │    "이 텍스트에서 integrity, capital_allocation에 해당하는 facts를 추출하라"
  │
  └─④ Contract 검증:    aspect ids → 커버리지 확인
       "integrity aspect가 최종 보고서에 포함되었는가?"
```

---

## 3. Domain Knowledge Structure

### 3.1 Module 파일 구조

```
modules/{id}/
  module.yaml    ← 메타데이터 + 파일 참조
  persona.md     ← 누구로서 분석하나 (LLM system prompt, 2-3문장)
  rubric.yaml    ← 무엇을 분석하나 (aspect flat list)
  format.md      ← 어떻게 출력하나 (마크다운 형식 지정)
  contract.yaml  ← 최소 충족 조건 (aspect ID 참조)
```

각 파일은 **하나의 역할**만 수행한다. 현재 `about.md`의 3역할 혼합을 해소.

### 3.2 RubricAspect 타입

```yaml
# rubric.yaml (CEO 예시)
aspects:
  - id: integrity
    label: 성실성·투명성
    description: 주주와의 소통 이력, 회계 투명성, 약속 이행 기록
    priority: high
  - id: capital_allocation
    label: 자본배분 역량
    description: M&A, CAPEX, 주주환원의 가치 창출/파괴 이력
    priority: high
  - id: governance
    label: 지배구조·이사회 독립성
    description: 이사회 구성, 특수관계자 거래, 보상 구조
    priority: medium
```

4개 필드만 있다. `questions.yaml`의 needs/outputs/depends_on/capability 같은 시스템 연결 구문이 없으므로, 비개발자가 편집 가능.

### 3.3 DomainModule 타입 변경

```python
# 삭제
class ModuleOutput      # dead code
class ModuleQuestion    # dead code
DomainModule.questions
DomainModule.capabilities
DomainModule.about

# 신규/변경
@dataclass(slots=True)
class RubricAspect:
    id: str
    label: str
    description: str
    priority: str = "medium"

class DomainModule(BaseModel):
    id: str
    name: str
    description: str = ""
    persona: str = ""                                         # persona.md
    rubric: list[RubricAspect] = Field(default_factory=list)  # rubric.yaml
    format_spec: str = ""                                     # format.md
    contract: list[AcceptanceCheck] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
```

### 3.4 비개발자 편집 시나리오

| 하고 싶은 것 | 편집 파일 | Python 수정 |
|-------------|----------|------------|
| 분석 관점 추가 (예: ESG) | `rubric.yaml`에 항목 추가 | 0줄 |
| 출력 형식 변경 | `format.md` 수정 | 0줄 |
| 필수 커버리지 추가 | `contract.yaml`에 체크 추가 | 0줄 |
| 분석 페르소나 변경 | `persona.md` 수정 | 0줄 |

---

## 4. AspectExpander: 적응적 Query 분해

### 4.1 역할

QueryAnalyzer가 생성한 coarse QueryUnit을, rubric aspects를 참조하여 finer sub-units로 확장한다.

### 4.2 위치: 파이프라인에서의 삽입점

```
DomainRouter.analyze()
  │
  ▼
QueryAnalysis (units × N)
  │
  │  ← 여기에 삽입
  ▼
AspectExpander.expand(analysis, modules)
  │
  ▼
QueryAnalysis (units × M, M ≥ N)
  │
  ▼
Planner.plan()
```

### 4.3 알고리즘

```
expand(analysis, modules):
    expanded_units = []
    for unit in analysis.units:
        aspects = collect_aspects(unit.domain_ids, modules)
        high = [a for a in aspects if a.priority == "high"]

        if len(high) <= THRESHOLD (3):
            expanded_units.append(unit)  # 확장 불필요
        else:
            for aspect_group in group_by_pairs(high):
                sub = QueryUnit(
                    id=f"{unit.id}_{aspect_group[0].id}",
                    objective=f"{unit.objective}: {aspect_group[0].label}",
                    retrieval_query=aspect에 맞는 검색 쿼리,
                    domain_ids=unit.domain_ids,
                    entity_ids=unit.entity_ids,
                    time_scope=unit.time_scope,
                    parent_unit_id=unit.id,        ← 부모 참조
                )
                expanded_units.append(sub)

    return replace(analysis, units=expanded_units)
```

**제약**: 원본 unit 수 × 2 까지만 확장. low-priority aspects는 확장하지 않고 parent에 포함.

### 4.4 Planner에 미치는 영향

`parent_unit_id`가 같은 sub-units를 하나의 merge node 아래로 그룹핑한다:

```
확장 전 (현재):                     확장 후:
T-ROOT                              T-ROOT
├── T-MERGE-1                       ├── T-MERGE-1 (parent: segment_analysis)
│   └── T-LEAF-1                    │   ├── T-LEAF-1-A (aspect: revenue_trend)
├── T-MERGE-2                       │   └── T-LEAF-1-B (aspect: profitability)
│   └── T-LEAF-2                    ├── T-MERGE-2 (parent: core_deep_dive)
├── T-MOD-CEO                       │   ├── T-LEAF-2-A (aspect: supply_chain)
├── T-MOD-DCF                       │   └── T-LEAF-2-B (aspect: demand)
└── T-MOD-RISK                      ├── T-MOD-CEO
                                    ├── T-MOD-DCF
                                    └── T-MOD-RISK
```

Tree가 한 단계 깊어지면서 각 merge node가 처리하는 context가 줄어든다.

---

## 5. Aspect Map-Reduce: 정보 보존 전략

현재 aggregation의 근본 문제: merge가 **aspect-unaware**. 비구조화 텍스트를 합성하므로 LLM이 임의로 축약한다.

### 5.1 Map Phase: StructuredExtractor

Executor 출력(비구조화 텍스트)을 aspect별 구조화된 facts로 변환한다. **Boundary**에 위치.

```python
@dataclass(slots=True)
class AspectFacts:
    aspect_id: str
    facts: dict[str, str]    # {revenue_growth: "13.5%", aws_share: "18%"}
    evidence: str             # "AWS는 전체 매출의 18%를 차지하며..."

@dataclass(slots=True)
class ExtractionResult:
    aspect_facts: list[AspectFacts]
    uncovered_aspects: list[str]
```

**동작 방식 — 두 가지 경로**:

```
경로 A: Domain Tool 출력 (구조화된 출력)
─────────────────────────────────────────
domain_tool은 rubric aspects를 프롬프트로 받아
`### [ASPECT:{id}]` 태그를 포함한 출력을 생성한다.

  입력:                               출력:
  [RUBRIC_ASPECTS]                    ### [ASPECT:integrity]
  - integrity (high): ...             CEO는 5년간 분기 실적에서 과대 광고 없이...
  - capital_allocation (high): ...    - ceo_rating: Excellent
                                      - communication_score: A
                                      ### [ASPECT:capital_allocation]
                                      AWS CapEx $78.5B, ROIC 18.5%...

  → Extractor: 태그 기준 파싱 (LLM 호출 불필요)


경로 B: 일반 Tool 출력 (비구조화 텍스트)
─────────────────────────────────────────
sec_tool, web_search 등은 aspect-unaware한 자유 텍스트를 반환한다.

  입력:                               출력:
  sec_tool 결과:                      AspectFacts[
  "Amazon revenue by segment:           {aspect: revenue_trend,
   North America $426.3B..."              facts: {na_revenue: "$426.3B",
                                                   intl_revenue: "$161.9B"},
   + rubric aspects:                      evidence: "Amazon revenue..."},
   [revenue_trend, profitability]        {aspect: profitability,
                                           facts: {aws_margin: "37.6%"},
                                           evidence: "AWS operating..."}
                                        ]

  → Extractor: LLM에 aspect mapping 요청 (소형 모델, 병렬)
     프롬프트: "다음 텍스트에서 각 aspect에 해당하는 facts를 JSON으로 추출하라"
     구조화된 JSON response schema 제공
```

**매핑 불가 정보**: `_uncategorized` aspect로 수집 — 정보 손실 방지.

### 5.2 Reduce Phase: Hierarchical Aspect Merge

Aggregation의 `_build_prompt()`를 재구성한다. 입력이 비구조화 텍스트에서 `AspectFacts[]`로 바뀐다.

```
현재 Merge Prompt (비구조화):

  [MATERIALS]
  --- source: T-LEAF-1 ---
  Amazon revenue by segment: North America $426.3B,
  International $161.9B, AWS $128.7B. Operating income...
  (3,000 tokens의 자유 텍스트)
  --- source: T-LEAF-2 ---
  (2,000 tokens의 자유 텍스트)
  → LLM이 무엇을 포함/제외할지 임의 결정


변경 후 Merge Prompt (aspect-structured):

  [ASPECT_FACTS]
  ### integrity
  - facts:
    - ceo_rating: Excellent
    - communication_score: A
    - audit_record: clean 5yr
  - evidence: "CEO는 2021-2025 5년간 분기 실적 발표에서..."

  ### capital_allocation
  - facts:
    - aws_capex: $78.5B
    - roic: 18.5%
    - buyback_total: $25B
  - evidence: "자본배분 이력: AWS CapEx..."

  ### _uncategorized
  - facts:
    - employee_count: 1.5M
  - evidence: "기타 참고 사항..."

  [INSTRUCTION]
  각 aspect의 facts와 evidence를 통합하여 aspect별 섹션으로 작성하라.
  모든 facts key-value를 본문에 포함하라.
  → facts는 key-value이므로 누락 구조적으로 불가
```

### 5.3 Reduce 전체 시퀀스

```
Phase 1: Map (병렬, Executor 직후)
─────────────────────────────────
  T-LEAF-1-A (3,000 tokens)
    → extract → AspectFacts[revenue_trend, profitability]     ~350 tokens
  T-LEAF-1-B (2,000 tokens)
    → extract → AspectFacts[segment_composition]              ~200 tokens
  T-LEAF-2-A (2,500 tokens)
    → extract → AspectFacts[supply_chain]                     ~150 tokens
  T-MOD-CEO (3,000 tokens, 이미 aspect-tagged)
    → parse → AspectFacts[integrity, capital_allocation, ...]  ~400 tokens

Phase 2: Sub-Reduce (per parent unit)
─────────────────────────────────────
  T-MERGE-1 (segment_analysis):
    input: AspectFacts from LEAF-1-A + LEAF-1-B     ~550 tokens
    → LLM: aspect별 narrative 통합
    → output: AspectReport                          ~400 tokens

  T-MERGE-2 (core_deep_dive):
    input: AspectFacts from LEAF-2-A + LEAF-2-B     ~350 tokens
    → LLM: aspect별 narrative 통합
    → output: AspectReport                          ~300 tokens

Phase 3: Root Reduce
────────────────────
  input:
    AspectReport-1 (segment)      ~400 tokens
    AspectReport-2 (deep_dive)    ~300 tokens
    AspectReport-3 (governance)   ~350 tokens
    AspectReport-4 (outlook)      ~300 tokens
    MOD-CEO AspectFacts           ~400 tokens
    contract requirements         ~200 tokens
    ────────────────────────────
    합계                         ~1,950 tokens  (현재 ~21,000의 9%)

  → LLM: 최종 보고서 합성
  → [CONTRACT_COVERAGE] 태깅
  → aspect_coverage 리포팅
```

### 5.4 정보 보존 보장 메커니즘

| 메커니즘 | 보장 수준 |
|---------|----------|
| `AspectFacts.facts` (key-value) | **구조적 보존** — LLM 입력에 명시적으로 나열됨 |
| `AspectFacts.evidence` (발췌) | Sub-reduce에서 통합, root에 도달 |
| `uncovered_aspects` | **명시적 경고** — contract 검증과 연결 |
| `_uncategorized` facts | 가장 관련 깊은 aspect에 배치 — 유실 방지 |

### 5.5 Token Budget Fallback

극단적 경우 (15+ aspects × 5+ modules) root context가 클 수 있다.
Priority 기반 **구조적 절삭** (LLM 임의 축약과 질적으로 다름):

| Priority | 절삭 방식 |
|----------|----------|
| high | 전량 유지 |
| medium | evidence 1문장 축약, facts 전량 유지 |
| low | evidence 제거, facts만 유지 |

---

## 6. DomainTool 변경

현재: `about.md` 전체를 system prompt → 자유 텍스트 출력 (aspect 추적 불가)

변경:

```
System Prompt:
  persona.md 내용

User Prompt:
  [ANALYSIS_TARGET]
  {company_name} ({ticker})

  [RUBRIC_ASPECTS]
  - integrity (high): 주주와의 소통 이력, 회계 투명성...
  - capital_allocation (high): M&A, CAPEX, 주주환원...

  [FORMAT]
  format.md 내용

  [INSTRUCTION]
  각 aspect별로 `### [ASPECT:{aspect_id}]` 헤더 아래 분석을 작성하라.
  high priority aspects는 반드시 커버하라.
```

출력이 aspect-tagged → Extractor가 태그 기준 파싱 (LLM 추가 호출 불필요).

---

## 7. Concrete Walkthrough: "아마존 분석해줘"

현재 시스템 vs 변경 후 시스템의 동작을 비교한다.

### 7.1 Query Decomposition

```
현재:
  QueryAnalyzer → 4 units (segment, deep_dive, governance, outlook)
  → unit당 leaf 1개 = tool 호출 1회

변경 후:
  QueryAnalyzer → 4 units (동일)
  AspectExpander:
    CEO rubric: 5 aspects (high 2, medium 2, low 1) → high 2 ≤ 3 → 확장 안 함
    DCF rubric: 4 aspects (high 2, medium 2) → high 2 ≤ 3 → 확장 안 함
    governance unit의 domain_ids=[ceo, risk_transmission]:
      CEO high aspects 2 + Risk high aspects 2 = 4 > 3
      → 2개 sub-units로 분할:
        governance_ceo (integrity, capital_allocation)
        governance_risk (risk_transmission aspects)
  결과: 5 units (4 → 5, 1개만 확장)
```

### 7.2 Execution & Extraction

```
현재:
  T-LEAF-3 (governance) → sec_tool → 2,500 tokens 자유 텍스트
    "Cash $123.0B, OCF $139.5B, FCF $11.2B, Security Committee..."
  → Aggregation에 전체 텍스트 전달

변경 후:
  T-LEAF-3-A (governance_ceo) → sec_tool → 1,500 tokens
  T-LEAF-3-B (governance_risk) → sec_tool → 1,200 tokens
  → Map phase (병렬):
    LEAF-3-A → AspectFacts[
      {integrity: {audit_committee: "independent", disclosure_quality: "A"}},
      {capital_allocation: {fcf: "$11.2B", ocf: "$139.5B"}}
    ]
    LEAF-3-B → AspectFacts[
      {regulatory_risk: {ftc_settlement: "$2.5B", probability: "60%"}},
      {supply_chain_risk: {gpu_constraint: "-3-7% AWS rev"}}
    ]
```

### 7.3 Aggregation

```
현재:
  Root merge receives ~21,000 tokens of raw text
  → LLM drops: 이사회 독립성 상세, 특수관계자 거래, 센티먼트 데이터
  → 최종 보고서: 부채비율 미산출, governance 상세 누락

변경 후:
  Sub-merge-3: AspectFacts from LEAF-3-A + LEAF-3-B
    → AspectReport (~350 tokens, 모든 facts key-value 보존)
  Root merge receives ~1,950 tokens of structured AspectReports
    → 모든 facts가 key-value로 명시됨 → 누락 불가
    → uncovered_aspects: ["debt_ratio", "current_ratio"]
       → contract에서 "재무비율 미산출" 명시적 경고
```

---

## 8. Implementation Roadmap

### Phase 1: Dead Code 제거

`ModuleQuestion`, `ModuleOutput`, `DomainModule.questions`, `capabilities` 삭제.
`questions.yaml` 로딩/검증 코드 삭제.

파일: `types.py`, `loader.py`, `__init__.py`, `test_domain_loader.py`

### Phase 2: about.md → persona/rubric/format 분리

`RubricAspect` 추가, `DomainModule` 재구성, 모듈별 3파일 생성.
`domain_tool.py`에서 persona + rubric 기반 프롬프트로 전환.
`aggregator/service.py`에서 guidance에 persona 사용.

파일: `types.py`, `loader.py`, `domain_tool.py`, `aggregator/service.py`, `modules/*/`

### Phase 3: AspectExpander

`QueryUnit.parent_unit_id` 추가. `AspectExpander` 생성.
Engine에 통합 (router → expander → planner).
Planner에서 sub-unit 그룹핑.

파일: `query.py`, `domain/expander.py` (신규), `engine.py`, `planner/service.py`

### Phase 4: Aspect Map-Reduce

`AspectFacts`, `ExtractionResult` 추가.
`StructuredExtractor` 생성 (Map phase).
`_build_prompt()` 재구성 (aspect-based merge prompt).
domain_tool에 `### [ASPECT:{id}]` 태깅.
Token budget fallback.

파일: `contracts/plan.py`, `aggregator/extractor.py` (신규), `aggregator/service.py`, `materials.py`, `domain_tool.py`

### Phase 5: Validation

`python -m pytest tests/`
S-20260317-105509Z 쿼리 재실행 → root context: ~21,000 → ~2,000 tokens 확인.
high-priority aspects 전량 포함 확인. uncovered_aspects 리포팅 확인.

---

## 9. Decisions

| 결정 | 선택 | 근거 |
|------|------|------|
| questions.yaml 활용 | **삭제** | Dead code. Flat aspect list가 단순하고 비개발자 편집 가능 |
| Aggregation 전략 | **Aspect Map-Reduce** | Token budget은 LLM 재량 축약. Map-reduce는 facts를 key-value로 보존 |
| about.md 분할 | **3파일** | 1파일 1역할. 혼합 책임 방지 |
| Extraction 방식 | **LLM 기반** | Extraction 정확도가 파이프라인 정보 보존율을 결정. 소형 모델, 병렬, leaf당 ~$0.005 |

---

## 10. Risks

| 리스크 | 완화 |
|--------|------|
| Aspect expansion 과다 | 최대 2x, low priority 제외 |
| Map extraction 누락 | uncovered_aspects 명시, _uncategorized 보존 |
| Map LLM latency (+2-3초) | 병렬 실행, root context 89% 감소로 상쇄 |

---

## 11. Design Notes / FAQ

### 11.1 AspectExpander 위치: 왜 별도 컴포넌트인가?

질문: Domain Expander(AspectExpander)는 왜 따로 두고, Planner 안에서 바로 unit을 늘리면 안 되는가?

답변:

- **역할 분리**:
  - QueryAnalyzer: LLM 경계. raw query + `index.yaml` → coarse `QueryAnalysis` 생성.
  - AspectExpander: 도메인 로직. `QueryAnalysis + DomainModule.rubric`을 이용해 units를 aspect-aware하게 보정/세분화하되, 타입은 그대로 `QueryAnalysis`를 유지한다.
  - Planner: 이미 확정된 `QueryAnalysis`를 받아 task graph만 생성한다.
- **Planner 비대화 방지**:
  - Expander를 Planner 안에 섞으면 Planner가 도메인 지식(rubric)과 경계 후처리(LLM 산출물 보정)까지 떠안게 되어, 역할이 비대해진다.
  - QueryAnalyzer 개선과 Expander 정책 변경을 Planner와 독립적으로 조정하기 어려워진다.
- **경계/도메인 원칙 일관성**:
  - 경계(LLM)는 “원시 입력 → 도메인 타입” 변환까지만 책임진다.
  - 그 이후의 도메인 정책(예: 어떤 unit을 쪼갤지)은 별도의 도메인 레이어(AspectExpander)에서 수행하고,
  - Planner는 “이미 믿을 수 있는 `QueryAnalysis`를 소비하는 컴포넌트”로 남긴다.

### 11.2 AspectExpander 파라미터: EXPANSION_THRESHOLD, MAX_EXPANSION_FACTOR

질문: `EXPANSION_THRESHOLD = 3`, `MAX_EXPANSION_FACTOR = 2`는 어떤 트레이드오프를 전제로 한 값인가?

답변:

- **EXPANSION_THRESHOLD (기본값 3)**:
  - 의미: 한 `QueryUnit`에 붙은 high priority aspect 개수가 이 값을 넘으면 “과밀한 unit”으로 보고 sub-unit으로 확장한다.
    - high priority 개수 ≤ 3: unit을 그대로 둔다 (확장 없음).
    - high priority 개수 > 3: AspectExpander가 rubric을 기준으로 sub-units를 생성한다.
  - 트레이드오프:
    - 값이 너무 낮으면(1~2): 거의 모든 unit이 잘게 쪼개져 정보 보존은 좋지만, unit/leaf/tool 호출 수가 폭증한다.
    - 값이 너무 높으면(5~6 이상): 실행은 빠르지만, 핵심 aspect 여러 개가 한 unit에 몰려 현재의 정보 손실 문제가 반복된다.
  - 기본값 3은 “사람이 한 번에 다루기 편한 high-priority 관점 수”를 기준으로 잡은 실험적 기본값이다. 실제 세션 로그에서 unit당 high aspect 분포와 latency를 보면서 2~4 사이에서 조정한다.

- **MAX_EXPANSION_FACTOR (기본값 2)**:
  - 의미: 확장 후 unit 수 \(M\)이 원래 unit 수 \(N\)의 2배를 넘지 않도록 상한을 둔다 (\(M \le 2N\)).
  - 트레이드오프:
    - 값이 너무 낮으면(1.5 근처): unit 폭발은 잘 막지만, 진짜로 세분화가 필요한 케이스도 충분히 쪼개지 못한다.
    - 값이 너무 높으면(3~4): 세분화는 잘 되지만, 최악 케이스에서 leaf/tool 호출 수가 과도하게 늘어날 수 있다.
  - 기본값 2는 “단일 쿼리에 대해 unit/leaf/tool 호출 수를 최악에도 2배 이내로 제한한다”는 비용 상한이다.
  - 튜닝 전략:
    - 먼저 rubric에서 high priority 비율을 조정해 과도한 expansion을 줄이고,
    - 여전히 latency/비용이 문제면 `MAX_EXPANSION_FACTOR`를 1.5~1.7 정도로 낮춰 글로벌 상한을 더 보수적으로 가져간다.

### 11.3 StructuredExtractor 역할

질문: StructuredExtractor는 무엇을 하는 컴포넌트인가?

답변:

- **정의**:
  - StructuredExtractor는 Executor가 생성한 비구조화 텍스트 artifact를, rubric 기반의 `AspectFacts[]`로 변환하는 Map 단계 컴포넌트이다.
  - 입력: artifact content (텍스트), 해당 도메인의 `RubricAspect[]`.
  - 출력: `ExtractionResult` (`aspect_facts`, `uncovered_aspects`).
- **두 가지 경로**:
  - 경로 A (domain_tool 출력, aspect-tagged):
    - domain_tool이 `### [ASPECT:{id}]` 헤더로 섹션을 구분해주면, StructuredExtractor는 이 태그를 파싱해 각 섹션을 해당 aspect의 `facts`/`evidence`로 매핑한다.
    - 이 경우 LLM 추가 호출이 필요 없다.
  - 경로 B (일반 tool 출력, 비구조화 텍스트):
    - `sec_tool`, `web_search_tool` 등은 aspect-unaware한 자유 텍스트를 반환한다.
    - StructuredExtractor는 소형 LLM을 호출하여 “이 텍스트에서 rubric에 정의된 각 aspect에 해당하는 key-value facts를 JSON으로 추출”하도록 요청하고, 그 JSON을 `AspectFacts[]`로 변환한다.
- **Aggregation과의 관계**:
  - Aggregation은 더 이상 raw 텍스트 덩어리를 합치는 대신, StructuredExtractor가 만든 `AspectFacts[]`를 입력으로 받아 aspect-aware Reduce를 수행한다.
  - 이 구조 덕분에:
    - 모든 수치·팩트가 key-value로 구조화되어 토큰 절삭 과정에서 누락되기 어렵고,
    - 최종 보고서에서 어떤 aspect가 covered/uncovered인지 `aspect_coverage`로 계산할 수 있다.
