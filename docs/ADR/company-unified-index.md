# Company-only 리팩토링: 통합 인덱스 기반

## Context

ADR 결정: `resolve_company() -> Company | None`.
현재 문제: KRX 시드 2개, US name 검색 불가, KRX/US 분기+별도 예외 타입+normalize 함수 등 구조 과잉.

**핵심 전환**: "KRX resolver / US resolver 분기" → "하나의 통합 인덱스에서 lookup"

## 설계: 통합 CompanyIndex

KRX (~2,600개) + SEC (~10,300개) = ~13,000개를 하나의 인덱스에 올린다.
LLM이 ticker를 주든, security_code를 주든, company_name을 주든, 같은 인덱스에서 찾는다.

```
CompanyIndex
├── by_id: dict[str, Company]     ← 모든 식별자 (ticker, code, yahoo symbol)
│   "005930"    → 삼성전자 Company
│   "005930.KS" → 삼성전자 Company
│   "AAPL"      → Apple Company
│   "NVDA"      → NVIDIA Company
│
└── by_name: dict[str, Company]   ← 정규화된 이름/별칭
    "삼성전자"   → 삼성전자 Company
    "SAMSUNGELECTRONICS" → 삼성전자 Company
    "APPLEINC"  → Apple Company
    "NVIDIACORP" → NVIDIA Company
```

### find_company() — resolve_company 대체

```python
def find_company(
    *, ticker: str = "", security_code: str = "", company_name: str = "",
) -> Company | None:
    ticker = ticker.strip().upper()
    security_code = security_code.strip().upper()
    company_name = company_name.strip()

    if not any((ticker, security_code, company_name)):
        return None

    idx = _company_index()
    by_id = idx.by_id.get(security_code) or idx.by_id.get(ticker)
    by_name = idx.by_name.get(_name_key(company_name)) if company_name else None

    # 두 경로가 다른 회사를 가리키면 → ValueError (conflict)
    if by_id and by_name and by_id.listing_id != by_name.listing_id:
        raise ValueError(
            f"identifier conflict: {security_code or ticker} ≠ {company_name}"
        )

    company = by_id or by_name
    if company is None:
        raise ValueError(f"unknown company: {ticker or security_code or company_name}")
    return company
```

**핵심: 분기 없음.** KRX인지 US인지 판단하지 않는다. 인덱스가 알아서 매칭한다.

### 인덱스 구축

```python
@lru_cache(maxsize=1)
def _company_index() -> _CompanyIndex:
    idx = _CompanyIndex()

    # KRX: data/krx_securities.json (~2,600개)
    for record in _load_json(KRX_PATH):
        company = Company(
            issuer_name=record["issuer_name"],
            security_code=record["security_code"],
            exchange=record["exchange"],
            listing_id=record["listing_id"],
            vendor_symbols=record["vendor_symbols"],
            aliases=tuple(record["aliases"]),
        )
        idx.by_id[company.security_code] = company
        for symbol in company.vendor_symbols.values():
            idx.by_id[symbol.upper()] = company
        for alias in company.aliases:
            idx.add_name(alias, company)

    # US: data/sec_company_tickers.json (~10,300개)
    for record in _load_json(SEC_PATH):
        ticker = str(record.get("ticker", "")).strip().upper()
        title = str(record.get("title", "")).strip()
        if not ticker:
            continue
        company = Company(
            issuer_name=title or ticker,
            security_code=ticker,
            exchange="USA",
            listing_id=f"USA:{ticker}",
            vendor_symbols={"yahoo": ticker},
            aliases=(title, ticker) if title else (ticker,),
        )
        idx.by_id[ticker] = company
        if title:
            idx.add_name(title, company)

    return idx
```

### 검색 전략: 효율성

| 조회 유형 | 입력 예시 | 경로 | 복잡도 |
|-----------|----------|------|--------|
| KRX code | "005930" | `by_id["005930"]` | O(1) |
| KRX Yahoo ticker | "005930.KS" | `by_id["005930.KS"]` | O(1) |
| US ticker | "AAPL" | `by_id["AAPL"]` | O(1) |
| 한국 회사명 | "삼성전자" | `by_name["삼성전자"]` | O(1) |
| 영문 회사명 | "Apple Inc." | `by_name["APPLEINC"]` | O(1) |
| code + name 일치 | "005930" + "삼성전자" | 둘 다 같은 Company → OK | O(1) |
| code + name 불일치 | "005930" + "LG전자" | 다른 Company → ValueError | O(1) |

**메모리**: ~13,000 Company + ~40,000 index entries ≈ ~5MB. 로드 <100ms.

## 삭제 대상

| 삭제 | 이유 |
|------|------|
| `CompanyHint` | 인라인 strip/upper로 대체 |
| `CompanyResolution` | Company 직접 반환 |
| `CompanyResolutionStatus` | ValueError 하나로 통합 |
| `LegacySubjectAdapter` | intent.company 직접 접근 |
| `_normalize_hint()` | 인라인 |
| `_is_krx_hint()` | 통합 인덱스로 불필요 |
| `_resolve_us_company()` | 인덱스 구축 시 처리 |
| `_KRXMaster` 클래스 | `_CompanyIndex`로 통합 |
| `_load_us_titles()` | 인덱스에 통합 |
| `company_resolution` 필드 | QueryIntent에서 삭제 |

## 구현 단계

### 1. KRX 종목 다운로드 스크립트

**새 파일: `scripts/download_krx_securities.py`**

`requests`(기존 의존성)로 KRX 데이터 포털 조회. `data/krx_securities.json` 갱신.
기존 스키마(issuer_name, security_code, exchange, listing_id, vendor_symbols, aliases) 그대로.

**파일:** `scripts/download_krx_securities.py` (신규)

### 2. company.py 재작성

- `CompanyHint`, `CompanyResolution`, `CompanyResolutionStatus` 삭제
- `_KRXMaster`, `_normalize_hint`, `_is_krx_hint`, `_resolve_us_company`, `_load_us_titles` 삭제
- `_CompanyIndex` + `find_company()` 추가 (위 설계대로)
- `Company`, `legacy_market_for_exchange` 유지

**파일:** [company.py](valuator/domain/company.py)

### 3. query.py 단순화

`company_resolution` 필드 삭제. `concrete_values()`에서 `company_resolution.raw.*` 분기 삭제.

```python
@dataclass(slots=True)
class QueryIntent:
    query: str
    company: Company | None = None
    entities: list[str] = field(default_factory=list)
```

**파일:** [query.py](valuator/domain/query.py)

### 4. legacy_subject.py 삭제 → specs.py/planner에 인라인

```python
# specs.py SubjectRequirement.accepts()
company = intent.company
if company is None:
    return self.identity_level is None
if self.market and legacy_market_for_exchange(company.exchange) != self.market:
    return False
if self.identity_level is SubjectIdentityLevel.NAME:
    return bool(company.issuer_name)
if self.identity_level is SubjectIdentityLevel.CANONICAL:
    return True
return bool(company.vendor_symbols.get("yahoo"))
```

```python
# specs.py ToolExecutionContext.values()
company = self.intent.company
ticker = company.vendor_symbols.get("yahoo", company.security_code) if company else ""
company_name = company.issuer_name if company else ""
security_code = company.security_code if company else ""
```

```python
# planner/service.py
@property
def _ticker(self) -> str:
    company = self._intent.company
    return company.vendor_symbols.get("yahoo", company.security_code) if company else ""

def _has_concrete_subject(self) -> bool:
    return self._intent.company is not None
```

**파일:** [legacy_subject.py](valuator/domain/legacy_subject.py) (삭제), [specs.py](valuator/tools/specs.py), [service.py](valuator/core/planner/service.py)

### 5. query_analysis.py boundary 업데이트

`resolve_company` → `find_company`. ValueError는 자연스럽게 전파.

```python
from .company import find_company

company = find_company(
    ticker=raw.query_intent.ticker,
    security_code=raw.query_intent.security_code,
    company_name=company_names[0] if company_names else "",
)
query_intent = QueryIntent(query=query, company=company)
```

`market` 파라미터 제거 — 통합 인덱스에서 시장 구분 없이 검색.

**파일:** [query_analysis.py](valuator/domain/query_analysis.py)

### 6. router.py 업데이트

`company_resolution` merge 삭제. `_intent_labels()`에서 `company_resolution.raw` fallback 삭제.

**파일:** [router.py](valuator/domain/router.py)

### 7. domain/__init__.py 정리

삭제: `CompanyHint`, `CompanyResolution`, `CompanyResolutionStatus`, `LegacySubjectAdapter`, `resolve_company`
추가: `find_company`

**파일:** [__init__.py](valuator/domain/__init__.py)

### 8. 테스트 업데이트

- `resolve_company` → `find_company`
- `CompanyResolutionStatus` → 삭제
- `LegacySubjectAdapter` → `intent.company` 직접 접근
- `company_resolution` → 삭제
- CONFLICTED/UNRESOLVED 테스트 → `pytest.raises(ValueError)`

**파일:** [test_company.py](tests/test_company.py), [test_query_pipeline.py](tests/test_query_pipeline.py), [test_semantic_requirements.py](tests/test_semantic_requirements.py), [test_tree_plan_and_aggregation.py](tests/test_tree_plan_and_aggregation.py)

## 구현 순서

1. `scripts/download_krx_securities.py` — KRX 전체 종목 다운로드
2. `data/krx_securities.json` — 스크립트 실행으로 갱신
3. `valuator/domain/company.py` — 통합 인덱스 + find_company
4. `valuator/domain/query.py` — company_resolution 삭제
5. `valuator/domain/legacy_subject.py` — 삭제
6. `valuator/tools/specs.py` — 인라인
7. `valuator/domain/query_analysis.py` — find_company 사용
8. `valuator/domain/router.py` — 단순화
9. `valuator/core/planner/service.py` — adapter 제거
10. `valuator/domain/__init__.py` — export 정리
11. 테스트 업데이트

## 검증

```bash
python scripts/download_krx_securities.py
python -m pytest tests/
ruff check . && ruff format .
```
