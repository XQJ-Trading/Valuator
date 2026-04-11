# SubjectContext: 회사 컨텍스트 + 실시간 시장 데이터 주입

## Context

매 LLM 호출이 로컬 버블에서 동작하여 세 가지 문제가 발생한다:
1. **회사 정보 누락**: ticker, exchange, currency가 프롬프트에 없어 task가 잘못된 ticker/통화를 사용
2. **시장 데이터 소실**: 현재 주가, 시가총액, PER/PBR 같은 기본 전제가 task tree 깊어질수록 truncation으로 소실
3. **중복 fetch**: 모든 task가 독립적으로 동일한 기초 데이터를 tool로 재요청

**해법**: 파이프라인 시작 시 yfinance로 시장 스냅샷을 1회 fetch하고, `[SUBJECT_CONTEXT]` 섹션을 매 프롬프트 최상단에 주입. 절대 truncation되지 않음.

## 설계

### 1. Ontology 노드별 dataclass — `domain/company.py` (Subject 뒤에 추가)

```python
@dataclass(frozen=True, slots=True)
class SecurityInfo:
    ticker: str
    exchange: str
    currency: str

@dataclass(frozen=True, slots=True)
class StockPrice:
    current_price: float | None

@dataclass(frozen=True, slots=True)
class Indicator:
    trailing_pe: float | None
    forward_pe: float | None
    price_to_book: float | None

@dataclass(frozen=True, slots=True)
class SubjectContext:
    company_name: str
    security: SecurityInfo
    price: StockPrice | None
    indicator: Indicator | None
    market_cap: float | None
    enterprise_value: float | None
    fetched_at: str  # ISO 8601 UTC
```

stockelper-kg ontology의 Security / StockPrice / Indicator 노드와 1:1 대응. 새 데이터 종류(Dividend, FinancialStatement 등) 추가 시 노드 dataclass 하나 + SubjectContext에 optional 필드 하나로 확장.

### 2. fetch_subject_contexts — 데이터 fetch

**파일 (신규)**: `domain/subject_context.py`

```python
async def fetch_subject_contexts(
    subjects: tuple[Subject, ...],
    as_of_utc: str,
) -> tuple[SubjectContext, ...]:
```

- 각 Subject의 `listing.yahoo_symbol`로 `yf.Ticker(symbol).info` 호출
- info dict → `SecurityInfo`, `StockPrice`, `Indicator` 노드로 변환하여 `SubjectContext` 조립
- `asyncio.to_thread` + `asyncio.gather`로 병렬 실행
- 실패한 subject는 skip (에러로 전체 파이프라인을 멈추지 않음)
- Listing 없는 Subject는 skip

### 3. 기존 타입에 필드 추가

| 파일 | 변경 |
|------|------|
| `domain/query.py` (QueryAnalysis) | `subject_contexts: tuple[SubjectContext, ...] = ()` 추가 |
| `valuator/core/context.py` (TaskContext) | `subject_contexts: tuple[SubjectContext, ...] = ()` 추가 |

### 4. 데이터 흐름

```
run_recursive_agent_query.py
  build_query_analysis() → analysis (with subjects)
  fetch_subject_contexts(analysis.query_intent.subjects) → contexts
  analysis.subject_contexts = contexts
      ↓
  Agent.__init__(query_analysis=analysis)
      ↓
  build_task_context() → ctx.subject_contexts = analysis.subject_contexts
      ↓
  build_step_prompt() → [SUBJECT_CONTEXT] 섹션 (sections[0])
```

### 5. 프롬프트 주입

**파일**: `valuator/core/planning/prompts.py`

`subject_context_text()` 함수 추가:
```
[SUBJECT_CONTEXT]
삼성전자 (005930.KS, KRX) | currency=KRW | price=67,400.00 | mkt_cap=402,652B | PER=12.45 | fwd_PER=10.23 | PBR=1.32 | EV=415,000B
```

`build_step_prompt()`에서 `sections.insert(0, ...)` — 최상단이므로 budget reduction 재귀에 의해 절대 truncation되지 않음.

`build_system_prompt()`에 한 줄 추가:
```
"[SUBJECT_CONTEXT] contains the subject company identity and current market data. Use these as baseline premises."
```

## 통합 지점

| 순서 | 파일 | 변경 내용 |
|------|------|-----------|
| 1 | `domain/company.py` | `SecurityInfo`, `StockPrice`, `Indicator`, `SubjectContext` dataclass 추가 (~25줄) |
| 2 | `domain/subject_context.py` (신규) | `fetch_subject_contexts` 함수 (~30줄) |
| 3 | `domain/query.py` | QueryAnalysis에 `subject_contexts` 필드 + import (~2줄) |
| 4 | `valuator/core/context.py` | TaskContext에 `subject_contexts` 필드 + import (~2줄) |
| 5 | `valuator/core/agent/context_builder.py` | `build_task_context()`에서 필드 전달 (1줄) |
| 6 | `valuator/core/planning/prompts.py` | `subject_context_text()` + sections.insert(0, ...) + system prompt 한 줄 (~22줄) |
| 7 | `scripts/run_recursive_agent_query.py` | fetch_subject_contexts 호출 + assignment (~5줄) |

**총 ~90줄. 신규 파일 1개. 기존 타입 변경 없음 (Company, Listing, Subject 유지).**

## 토큰 예산

| 대상 수 | 예상 크기 | 150K 대비 |
|---------|-----------|-----------|
| 1 subject | ~200 chars | 0.13% |
| 2 subjects | ~430 chars | 0.29% |
| 4 subjects | ~850 chars | 0.57% |

## 의도적으로 하지 않는 것

- Subject/Company/Listing 타입 변경 없음
- 캐싱 레이어 없음 — 스냅샷은 파이프라인 시작 시 1회 fetch, 이후 immutable
- 내부 비즈니스 로직에 validation 추가 없음
- Tool 동작 변경 없음 — 기존 yfinance_balance_sheet는 그대로 사용 가능
- Registry/coordinator/manager 패턴 없음

## 검증

1. `python -m pytest tests/` — 기존 테스트 regression 없음
2. 수동 검증: 실제 쿼리 실행 후 session trace에서 모든 step prompt에 `[SUBJECT_CONTEXT]` 존재 확인
3. yfinance 불가 환경에서도 파이프라인 정상 동작 (subject_contexts = 빈 tuple)
