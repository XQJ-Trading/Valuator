# ADR: Company / Listing / Subject 식별 분리

## Status
🔄 **Proposed**

## Context

현재 `valuator/domain/company.py`의 `Company`는 서로 다른 수준의 의미를 한 타입에 함께 담고 있다.

```python
@dataclass(frozen=True, slots=True)
class Company:
    issuer_name: str
    security_code: str
    exchange: str
    listing_id: str
    issuer_id: str
    vendor_symbols: dict[str, str]
    aliases: tuple[str, ...]
```

이 구조는 단일 상장 기업에는 동작하지만, 아래 시점부터 모델이 흔들린다.

- `Alphabet`처럼 회사 하나에 `GOOG`, `GOOGL` 두 listing이 존재
- `Berkshire Hathaway`, `JPMorgan Chase`처럼 동일 회사 아래 여러 class/preferred/security가 공존
- 사용자는 회사를 말했는데 시스템은 너무 이르게 특정 listing을 골라야 함
- `Amazon vs Microsoft`, `GOOG vs GOOGL` 같은 비교 쿼리를 일반 규칙이 아니라 예외처럼 다루게 됨
- `AWS가 Amazon valuation에 미치는 영향`처럼 비증권 엔티티가 함께 등장하면 company/listing 의미가 더 흐려짐

숨은 가정은 이것이다.

> "회사 하나 = listing 하나"

이 가정이 깨지는 순간:

- `Alphabet`를 ambiguous로 막는 것은 과도하고
- `Alphabet -> GOOGL`처럼 임의로 대표 ticker를 고정하는 것도 과도하다

또한 `QueryIntent.company`, `QueryIntent.listing`처럼 optional 필드를 여러 곳에 퍼뜨리는 방식도 충분하지 않다.

- `listing`이 있으면 반드시 `company`도 있어야 한다
- `listing.company_id == company.company_id`가 항상 성립해야 한다
- 비교/추천/스크리닝 쿼리는 단수 필드보다 컬렉션이 자연스럽다
- `subjects[0]`로 축약하는 순간 다중 subject 정보가 손실된다

즉 문제는 "대표 ticker를 어떻게 고를까"가 아니라, 회사 식별과 종목 식별을 같은 개념으로 모델링하고 있다는 점이다.

## Decision

### 1. 엔티티는 `Company`와 `Listing`으로 분리한다

```python
@dataclass(frozen=True, slots=True)
class Company:
    company_id: str
    company_name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Listing:
    listing_id: str
    company_id: str
    security_code: str
    exchange: str
    vendor_symbols: dict[str, str]
    aliases: tuple[str, ...] = ()
    is_primary: bool = False
```

- `Company`는 "어느 회사인가?"에 답한다
- `Listing`은 "어느 상장 종목인가?"에 답한다

`canonical_name` 대신 `company_name`을 사용한다. 현재 코드베이스와 사용자 언어에 더 자연스럽기 때문이다.

`company_id` 생성은 시장별 데이터 현실을 따른다.

- SEC 계열은 `CIK`를 기준으로 `SEC:{cik}`를 사용한다
- KRX 계열은 현재 issuer-level master id가 없으므로 당분간 `KRX:{security_code}`를 사용한다

즉 KRX에서는 지금 단계에서 `company_id == listing_id`일 수 있다.  
이것은 모델 결함이 아니라 **현재 참조 데이터의 한계**를 명시적으로 드러내는 것이다.

### 2. `QueryIntent`는 단수 필드가 아니라 `subjects`를 가진다

```python
@dataclass(frozen=True, slots=True)
class Subject:
    company: Company
    listing: Listing | None = None
```

```python
@dataclass(slots=True)
class QueryIntent:
    query: str
    subjects: tuple[Subject, ...] = ()
    entities: tuple[str, ...] = ()
```

이 방식이 `QueryIntent.company`, `QueryIntent.listing`, `QueryIntent.subject` 단수 모델보다 낫다.

- 단일 회사, 다중 회사, 다중 listing 비교를 같은 구조로 표현할 수 있다
- `listing`이 있으면 `company`가 반드시 있다는 불변식을 타입으로 표현한다
- company/listing 조합 검증을 한 곳에 모은다
- application/service/tool 계층에 `None` 조합 규칙을 흩뿌리지 않는다
- 내부 로직이 `subjects[0]` 전제에 기대지 않게 만든다

의미:

- `subjects=()` : concrete capital-market subject 없음
- `subjects=(company-level subject,)` : 회사는 알지만 특정 종목은 아직 고르지 않음
- `subjects=(listing-level subject,)` : 특정 종목까지 확정됨
- `subjects=(...)` 여러 개 : 비교, pair trade, multi-subject analysis

### 3. `entities`는 비증권 엔티티만 담는다

`subjects`는 자본시장 대상을 표현한다.

- 회사
- 상장 종목

`entities`는 비증권 엔티티를 표현한다.

- 사업부
- 제품
- CEO
- 테마
- 거시 변수

예:

- `AWS가 Amazon valuation에 미치는 영향`
  - `subjects = (Amazon company-level subject,)`
  - `entities = ("AWS",)`

### 4. 식별 정책은 여전히 도메인 로직이다

다음 규칙은 knowledge/data가 아니라 **entity resolution domain policy**다.

- listing exact match면 `company + listing` 확정
- exact/fuzzy alias 후보가 여러 개여도 모두 같은 `company_id`면 company-level subject로 성공
- 동일 회사에 대한 company-level subject와 listing-level subject가 함께 발견되면 listing-level subject 하나로 collapse
- 동일 listing을 여러 surface form이 가리키면 하나로 dedupe
- 서로 다른 `company_id`가 섞이면 ambiguous
- 비증권 엔티티는 `subjects`로 올리지 않고 `entities`에 남긴다

핵심은 "surface form별 해석"이 아니라 "해석 결과를 어떤 도메인 타입으로 수렴시키는가"다.

예:

```text
Alphabet
-> [Subject(company=Alphabet, listing=None)]

GOOG
-> [Subject(company=Alphabet, listing=GOOG)]

Alphabet + GOOG
-> [Subject(company=Alphabet, listing=GOOG)]

Amazon vs Microsoft
-> [Amazon company-level, Microsoft company-level]

GOOG vs GOOGL
-> [Alphabet/GOOG, Alphabet/GOOGL]

AWS가 Amazon valuation에 미치는 영향
-> subjects=[Amazon company-level], entities=["AWS"]

반도체 추천
-> subjects=[]

Target valuation
-> ambiguous if multiple distinct company_id candidates survive
```

이 규칙은 특정 예시를 위한 분기 모음이 아니라, 아래 일반 규칙으로 환원된다.

1. 입력 surface form을 모두 수용한다
2. 각 surface form을 company 또는 listing 후보로 resolve한다
3. 같은 listing은 dedupe한다
4. 같은 company의 company-level subject와 listing-level subject가 함께 있으면 listing-level subject를 남긴다
5. 서로 다른 company 후보가 충돌하면 ambiguous로 실패한다
6. 비증권 엔티티는 별도 컬렉션으로 분리한다

### 5. Resolution 단계는 결코 `subjects[0]`으로 축약하지 않는다

`subjects[0]`은 시스템의 일반 규칙이 아니다.

- resolution 결과는 항상 `0 / 1 / N`개의 `Subject` 전체를 보존한다
- router, planner, reviewer, aggregator는 기본적으로 `subjects` 컬렉션을 본다
- `single_subject`, `multi_subject` 같은 태그도 subject 개수 기준으로 계산한다

단수 투영은 오직 **특정 tool이 단수 subject만 받을 수 있는 boundary**에서만 허용된다.

### 6. 대표 listing 선택은 resolution이 아니라 tool boundary의 투영 책임이다

핵심은 "회사 식별"과 "종목 선택"을 섞지 않는 것이다.

- `domain_tool`, `web_search_tool`: subject가 없어도 실행 가능하며, subject가 있으면 company-level 정보만으로도 충분하다
- `yfinance_balance_sheet`: 단일 listing-level subject 또는 vendor symbol이 필요한 tool이다
- `sec_tool`: 단일 미국 listing-level subject가 필요하다

따라서 `Alphabet` 같은 질의는 resolution 단계에서 특정 ticker로 강제하지 않는다.

대표 listing 선택은 작은 utility 여러 개가 아니라, **tool boundary의 단일 projection 함수**가 맡는다.

예시:

```python
def project_subject_for_tool(
    *,
    subjects: tuple[Subject, ...],
    requirement: SubjectRequirement,
) -> ProjectedSubject | None:
    ...
```

이 projection 함수의 책임은 다음뿐이다.

- tool이 subject를 요구하는지 여부 판단
- `0 / 1 / N` subject cardinality 판단
- company-level sufficiency 여부 판단
- listing-level sufficiency 여부 판단
- 명시적 `is_primary`가 있거나 사용자가 listing-level 식별자를 준 경우에만 대표 listing 선택

반대로 아래는 하지 않는다.

- resolution 단계에서 임의 ticker 고정
- business logic 내부에서 `subjects[0]` 사용
- helper chain으로 조건을 여러 계층에 분산

즉 "helper가 필요한가?"에 대한 답은 다음과 같다.

> 예. 다만 `pick_primary_listing()` 같은 좁은 helper가 중심이 되어서는 안 된다.  
> 최선은 tool boundary에 하나의 명시적 projection 함수를 두고, 단수 실행 가능성 판단을 그 안에 모으는 것이다.

### 7. Transitional adapter는 두지 않는다

`LegacyCompanyAdapter` 같은 compatibility adapter는 이번 결정에 포함하지 않는다.

이유:

- 잘못된 단수 모델을 다른 이름으로 연장할 가능성이 큼
- 새 코드가 다시 `company_name`, `ticker`, `subjects[0]` 전제에 붙게 됨
- 현재 변경 범위의 주요 호출부는 직접 마이그레이션 가능한 수준이다

필요한 것은 legacy 타입 유지가 아니라, 경계에서의 명시적 투영이다.

즉 business logic는 `Subject`, `Company`, `Listing`을 직접 다루고,  
tool 호출 직전 경계에서만 평면 인자(`ticker`, `company_name`, `corp`)로 투영한다.

### 8. `domain/knowledge` 패키지로 보내지 않는다

이 결정은 `domain knowledge base`의 관심사가 아니다.

- `domain/knowledge/`의 역할: valuation, governance, risk 같은 분석 지식
- entity resolution의 역할: company/listing 식별 정책

다만 entity resolution이 참조하는 사실 데이터는 더 풍부해질 수 있다.

- alias
- cik
- share class
- primary listing 여부
- vendor symbol

이 데이터는 `data/` 또는 별도 entity registry source로 둘 수 있다.  
하지만 "같은 company면 collapse한다", "서로 다른 company면 ambiguous다",  
"tool 실행 시 단수 listing이 필요한가" 같은 규칙은 계속 도메인 코드 안에 남는다.

## Why This Is Cleaner

clean architecture는 타입과 파일을 많이 만드는 것이 아니라, **변경 이유가 다른 것을 분리하는 것**이다.

이번 변경에서 바로 분리해야 하는 것은 다섯 가지다.

1. 회사와 종목은 다른 개념이다
2. `Subject`는 그 둘의 유효한 조합이다
3. 쿼리는 `0 / 1 / N`개의 capital-market subject를 가질 수 있다
4. 비증권 엔티티는 `subjects`와 별도 컬렉션으로 관리해야 한다
5. 단수 tool 실행을 위한 축약은 tool boundary에서만 수행해야 한다

반대로 지금 당장 하지 않아도 되는 것은:

- 별도 repository port
- 별도 master interface
- 별도 selection policy 클래스 다층 분리
- compatibility adapter

즉 이번 ADR의 목표는:

- **잘못된 모델을 바로잡되**
- **단수 shortcut과 adapter로 문제를 다시 숨기지 않고**
- **추상화를 앞당겨 시스템을 더 복잡하게 만들지 않는 것**

이다.

## Implementation Scope

### 1. `company.py` 재구성

**File**: `valuator/domain/company.py`

- 기존 `Company` 단일 타입 제거
- 새 `Company`, `Listing`, `Subject` 추가
- unified index를 company-view와 listing-view로 재구성
- resolver는 당분간 `company.py` 안에 유지

예시:

```python
def resolve_subjects(
    *,
    ticker: str = "",
    security_code: str = "",
    company_names: tuple[str, ...] = (),
) -> tuple[Subject, ...]:
```

이 함수는 boundary에서 입력을 받아 `Subject` 컬렉션으로 변환하는 유일한 진입점이 된다.

### 2. QueryIntent 마이그레이션

**Files**:
- `valuator/domain/query.py`
- `valuator/domain/router.py`
- `valuator/domain/query_analysis.py`

변경:

- `QueryIntent.company` 제거
- `QueryIntent.subjects` 추가
- analyzer boundary에서 `resolve_subjects(...)` 호출
- `company_names[0]` 같은 단수 shortcut 제거
- `single_subject`, `multi_subject` 판단을 resolved subject 개수 기준으로 변경

### 3. Tool spec / arg projection 갱신

**Files**:
- `valuator/tools/specs.py`
- `valuator/core/planner/service.py`

변경:

- `ToolExecutionContext`가 `subjects`에서 company/listing 값을 투영
- tool requirement가 company-level / listing-level / cardinality 요구를 명시
- 단수 tool 실행 가능성 판단을 boundary projection 함수 하나로 처리
- `subjects[0]` 접근 제거

### 4. 테스트 갱신

**Files**:
- `tests/test_company.py`
- `tests/test_query_pipeline.py`
- `tests/test_semantic_requirements.py`
- `tests/test_tree_plan_and_aggregation.py`

추가/수정 대상:

- company-level resolution
- listing-level resolution
- 동일 company 내 multi-listing collapse
- multi-subject comparison 보존
- 비증권 entity 분리
- 단수 tool boundary projection 성공/실패 조건

## Consequences

### 긍정적

- `Alphabet` 같은 동일 company multi-class 문제를 모델 수준에서 해결
- 회사 식별과 종목 식별을 분리하여 정책이 명확해짐
- 단일 분석, 비교, 추천, multi-subject 쿼리를 한 모델로 다룰 수 있음
- `entities`와 `subjects`의 의미가 분리됨
- tool별 요구사항이 더 정확해짐
- `domain/knowledge`와 entity resolution 경계가 선명해짐
- `subjects[0]`나 adapter에 기대는 숨은 단수 가정을 제거함

### 비용

- `QueryIntent`, planner, tool arg projection 전반의 마이그레이션 필요
- 기존 `Company` 단수 모델에 기대는 테스트와 helper를 정리해야 함
- tool boundary projection 함수를 명시적으로 추가해야 함
- KRX issuer-level master data가 없으므로 일부 시장에서는 company/listing 분리가 데이터적으로 제한됨

## Decision Boundary Summary

이 ADR의 핵심 판단은 다음 네 줄이다.

> company/listing 관계를 설명하는 사실은 data에 둘 수 있지만,  
> company collapse / ambiguous / tool projection 규칙은 domain logic다.

> resolution은 항상 `subjects` 전체를 보존해야 하며,  
> `subjects[0]`으로 축약하는 것은 tool boundary에서만 허용된다.

> compatibility adapter로 잘못된 단수 모델을 연장하지 않는다.

> clean architecture적으로 더 좋은 방향은 추상화를 많이 추가하는 것이 아니라,  
> `Company`, `Listing`, `Subject`, `subjects[]`, boundary projection 다섯 수준만 명확히 분리하는 것이다.
