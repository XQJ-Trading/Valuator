# Company Identification: LLM hallucination 방지

## Context
LLM이 query analysis에서 `security_code: "311430"`을 hallucinate하여 존재하지 않는 회사를 참조.
근본 원인: LLM에게 자유 텍스트로 identifier를 생성하게 하고, 검증 없이 `find_company`에 전달.
LLM의 해석 자율성(오타 교정, 별칭/ticker 해석)은 유지하면서 identifier 해석 책임은 시스템으로 이동.

## Changes

### 1. Schema에서 ticker/security_code 제거
**File**: [query_analysis.py](valuator/domain/query_analysis.py)

- `QueryIntentPayload`: `ticker`, `security_code` 필드 제거, `company_names`만 유지
- LLM JSON schema (`analyze` 메서드): `query_intent.properties`에서 `ticker`, `security_code` 제거
- `_build_query_analysis`: ticker/security_code 분기 제거, `company_names[0]`으로 `find_company(company_name=...)` 호출

### 2. Fuzzy fallback 추가
**File**: [company.py](valuator/domain/company.py)

`find_company`에서 name exact match 실패 시 fuzzy fallback:
- `difflib.SequenceMatcher` 사용 (stdlib, 외부 의존성 없음)
- `by_name` index의 모든 key에 대해 `_name_key(input)` vs key 비교
- threshold 0.7 이상 & 최고 점수 후보 선택
- 동점 다수 → ambiguous error
- threshold 미달 → 기존 unknown company error

위치: `find_company` 내부 `candidates = index.by_name.get(...)` 이후 fallback 경로

### 3. 테스트
- 기존 테스트 확인 및 수정
- fuzzy matching 케이스 추가: 오타, ticker as name, 정확한 이름

## Verification
```bash
python -m pytest tests/ -x
python3 -c "from valuator.domain.company import find_company; print(find_company(company_name='현대무벡스'))"
python3 -c "from valuator.domain.company import find_company; print(find_company(company_name='NVDA'))"
```
