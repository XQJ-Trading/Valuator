# ADR: Company 도메인 타입 도입

## Status
🔄 **Proposed**

## Context

### 문제점

현재 시스템은 LLM이 추출한 raw 문자열(`ticker`, `security_code`, `company_names`)을 검증 없이 파이프라인 전체에 전파합니다.

```
LLM → "현대무벡스" = "311690" (hallucination) → 검증 없이 yfinance 호출 → 잘못된 데이터
```

**구체적 문제:**
- LLM이 company_name과 security_code를 잘못 매핑해도 잡을 수 없음
- `ticker`라는 필드명이 vendor symbol과 종목코드를 구분하지 못함 — `319400.KS`가 canonical key처럼 쓰임
- yfinance_tool.py 내부에 KS/KQ suffix 추측 로직이 묻혀 있음 (도메인 로직이 도구에 침투)
- `market` 필드가 거래소(KOSDAQ)와 국가(USA)를 혼용

### 도메인 요구사항

정규 식별자 체계를 도입하여 한 방향으로만 흐르게 해야 합니다:

```
회사명 → security_code → exchange → vendor_symbol
현대무벡스 → 319400 → KOSDAQ → 319400.KQ (yahoo)
```

## Decision

### Company 도메인 타입을 도입하고 QueryIntent에 통합

별도 SecuritySubject 타입 없이, `Company` 하나로 canonical identity를 표현합니다.

```python
@dataclass(frozen=True, slots=True)
class Company:
    issuer_name: str                # "현대무벡스", "Apple Inc."
    security_code: str              # "319400", "AAPL"
    exchange: str                   # "KOSDAQ", "NASDAQ"
    listing_id: str                 # "KRX:319400", "NASDAQ:AAPL"
    vendor_symbols: dict[str, str]  # {"yahoo": "319400.KQ"}
    aliases: tuple[str, ...]        # ("현대무벡스", "HYUNDAI MOVEX")
```

한국과 미국 주식이 동일한 구조를 사용합니다:

```python
# 한국 주식
Company(
    issuer_name="현대무벡스",
    security_code="319400",
    exchange="KOSDAQ",
    listing_id="KRX:319400",
    vendor_symbols={"yahoo": "319400.KQ"},   # KOSPI→.KS, KOSDAQ→.KQ
    aliases=("현대무벡스", "HYUNDAI MOVEX"),
)

# 미국 주식
Company(
    issuer_name="Apple Inc.",
    security_code="AAPL",
    exchange="NASDAQ",
    listing_id="NASDAQ:AAPL",
    vendor_symbols={"yahoo": "AAPL"},         # ticker 그대로
    aliases=("Apple", "Apple Inc.", "AAPL"),
)
```

### QueryIntent 통합

`QueryIntent`는 canonical company와 "아직 canonical로 승격되지 못한 concrete subject"를 함께 표현합니다.

```python
@dataclass(frozen=True, slots=True)
class CompanyHint:
    ticker: str = ""
    market: str = ""
    security_code: str = ""
    company_name: str = ""


@dataclass(frozen=True, slots=True)
class CompanyResolution:
    status: Literal["resolved", "unresolved", "conflicted"]
    raw: CompanyHint
    company: Company | None = None
    reason: str = ""


@dataclass(slots=True)
class QueryIntent:
    query: str
    company: Company | None = None
    company_resolution: CompanyResolution | None = None
    entities: list[str] = field(default_factory=list)
```

상태 의미:

- `company_resolution is None`: concrete subject 자체가 없음 (추천/섹터/매크로)
- `status="resolved"`: canonical identity 확보
- `status="unresolved"`: concrete subject는 있으나 master 미등록/미식별
- `status="conflicted"`: 이름↔코드가 모순되어 canonical identity 승격 차단

이렇게 하면 미등록 종목도 raw subject를 잃지 않으므로 name 기반 검색/도메인 tool은 계속 사용할 수 있습니다.

### resolve_company()를 경계에서 호출

`resolve_company()`를 `_build_query_analysis` (LLM 경계)에서 호출하여 변환을 완결합니다. router에서의 resolve가 불필요해집니다.

```
Before:
LLM → QueryIntentPayload → QueryIntent(raw 문자열) → router merge(raw) → pipeline
                                                        ↑ 검증 없음

After:
LLM → QueryIntentPayload → resolve_company() → CompanyResolution → QueryIntent(company=..., company_resolution=...) → router → pipeline
                            ↑ 경계에서 완결
```

```python
# company.py — 유일한 public API
def resolve_company(
    *, ticker: str = "", market: str = "",
    security_code: str = "", company_name: str = "",
) -> CompanyResolution | None:
```

내부 로직:
1. concrete subject 없음 → `None`
2. 6자리 숫자 코드 or KRX계열 market → KRX master 조회
3. KRX master 일치 → `resolved`
4. KRX master 미등록 → `unresolved`
5. KRX master 모순 (이름↔코드 불일치) → `conflicted`
6. 알파벳 ticker → US resolver 또는 규칙 기반 생성 후 `resolved`

KRX master는 company.py 내부 lazy singleton. 외부에 노출하지 않습니다.

### Resolution 전략

| 상황 | 동작 |
|------|------|
| Concrete subject 없음 (추천, 섹터, 매크로) | `company_resolution=None`, `company=None` |
| KRX + Master 매칭 | `resolved`, `company` 채움 |
| KRX + Master 미등록 | `unresolved`, raw subject 보존 |
| KRX + Master 모순 (이름↔코드 불일치) | `conflicted`, canonical 승격 차단 |
| US ticker | `resolved`, `company` 채움 |

### Tool subject requirement를 식별 수준으로 분리

tool은 단순히 `ticker` 문자열 유무가 아니라 필요한 식별 수준을 선언합니다.

```python
class SubjectIdentityLevel(StrEnum):
    NAME = "name"
    CANONICAL = "canonical"
    VENDOR_SYMBOL = "vendor_symbol"
```

예시:

- `web_search_tool`, narrative `domain_tool`: `NAME`
- `yfinance_balance_sheet`: `VENDOR_SYMBOL`
- `sec_tool`: `CANONICAL` + `exchange == "USA"`

이 규칙을 쓰면 KRX 시드에 없는 종목도 `company_resolution.status="unresolved"`인 동안 검색 기반 경로는 유지되고, identity가 꼭 필요한 tool만 차단됩니다.

### 레거시 호환은 adapter로 격리

backward compatibility는 `QueryIntent` property가 아니라 별도 adapter에서 담당합니다.

```python
@dataclass(frozen=True, slots=True)
class LegacySubjectAdapter:
    intent: QueryIntent

    @property
    def ticker(self) -> str:
        company = self.intent.company
        if company is None:
            return ""
        return company.vendor_symbols.get("yahoo", company.security_code)

    @property
    def market(self) -> str:
        return self.intent.company.exchange if self.intent.company else ""

    @property
    def security_code(self) -> str:
        return self.intent.company.security_code if self.intent.company else ""

    @property
    def company_name(self) -> str:
        if self.intent.company is not None:
            return self.intent.company.issuer_name
        if self.intent.company_resolution is not None:
            return self.intent.company_resolution.raw.company_name
        return ""
```

adapter는 `tools/specs.py`, planner 경계 같은 통합 지점에서만 사용합니다. 도메인 코어는 `Company`와 `CompanyResolution`만 다룹니다.

### router.py 단순화

field-by-field merge가 한 줄로 축소됩니다:

```python
# Before:
updated_intent = QueryIntent(
    query=intent.query,
    ticker=intent.ticker or analyzed_intent.ticker,
    market=intent.market or analyzed_intent.market,
    security_code=intent.security_code or analyzed_intent.security_code,
    company_names=(intent.company_names or analyzed_intent.company_names or concrete_labels),
    entities=list(dict.fromkeys([...])),
)

# After:
updated_intent = QueryIntent(
    query=intent.query,
    company=intent.company or analyzed_intent.company,
    company_resolution=(
        intent.company_resolution or analyzed_intent.company_resolution
    ),
    entities=list(dict.fromkeys([
        *analysis.entities.values(),
        *(
            [analyzed_intent.company.issuer_name]
            if analyzed_intent.company is not None
            else []
        ),
        *intent.entities,
    ])),
)
```

## Consequences

### 긍정적

- **Hallucination 차단**: KRX master와 모순되는 LLM 출력을 경계에서 즉시 차단
- **Vendor 표기 분리**: `319400.KQ`가 canonical key가 아닌 파생값이 됨
- **필드명 명확화**: `ticker`(모호) → `vendor_symbols["yahoo"]`(명시적), `market`(모호) → `exchange`(명시적)
- **도구 로직 정리**: yfinance_tool의 KS/KQ 추측 로직 제거 — upstream에서 이미 올바른 vendor symbol 전달
- **router 단순화**: field-by-field merge 제거
- **미해결 subject 보존**: KRX 시드에 없는 종목도 raw subject와 실패 이유를 잃지 않음
- **점진적 이행 가능**: 레거시 필드는 adapter에만 남아 도메인 모델 오염 최소화

### 잔여 제약

- **KRX master 시드 의존은 남음**: 초기에는 수동 시드 데이터로 커버리지가 제한됩니다. 다만 미등록 종목은 `unresolved` 상태로 보존되어 검색/서술형 tool은 사용 가능합니다.
- **하류 마이그레이션 필요**: legacy property를 없애는 대신 adapter와 identity-level 규칙으로 planner/tool 경계를 옮겨야 합니다.
- **US 식별도 resolver 아래로 수렴 필요**: 초기에는 규칙 기반 생성으로 시작하더라도 장기적으로는 US master/source를 추가해 동일한 검증 모델로 맞춰야 합니다.

### 완화 전략

- **Seed refresh 경로 추가**: `data/krx_securities.json`은 수동 시드로 시작하되, 추후 snapshot 갱신 스크립트나 운영 배치로 교체합니다.
- **Unresolved fallback 명시**: `company_resolution.status != "resolved"`이면 vendor-symbol 필요 tool만 제외하고, 웹 검색/도메인 분석은 raw `company_name`으로 계속 수행합니다.
- **Legacy adapter 단계적 제거**: adapter 사용처를 telemetry로 추적하고, planner/tool 경계 이행이 끝나면 adapter를 삭제합니다.

## 변경 대상

### 신규 파일

| 파일 | 내용 |
|------|------|
| `valuator/domain/company.py` | Company, CompanyHint, CompanyResolution, resolve_company(), 내부 _KRXMaster |
| `valuator/domain/legacy_subject.py` | LegacySubjectAdapter |
| `data/krx_securities.json` | KRX 시드 데이터 |
| `tests/test_company.py` | resolve_company 테스트 |

### 수정 파일

| 파일 | 변경 |
|------|------|
| `valuator/domain/query.py` | QueryIntent: raw 필드 제거 → `company`, `company_resolution` |
| `valuator/domain/query_analysis.py` | _build_query_analysis: resolve_company() 호출 |
| `valuator/domain/router.py` | merge 단순화 |
| `valuator/tools/specs.py` | identity-level 기반 tool gating + adapter 사용 |
| `valuator/tools/yfinance_tool.py` | KS/KQ 추측 제거 |
| `valuator/core/planner/service.py` | concrete subject 판정에 resolution/adapter 반영 |
| `valuator/domain/__init__.py` | Company, CompanyResolution export |

### 변경 없는 파일

engine.py, executor, aggregator — planner/tool 경계에서 adapter를 쓰므로 직접 변경 없이 유지 가능.
