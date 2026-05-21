# Phase 3 — 도메인 보강

전체 아키텍처: [overview.md](overview.md). 선행: [Phase 2](phase-2-retrieval-integration.md).

## 목표

`verify_toc`(PageIndex 원안)는 "추출된 제목이 페이지에 실제 등장하는지"만 확인해 누락된 섹션을 잡지 못한다. 도메인 지식(10-K Item 1~15, DART 양식별 expected sections)을 화이트리스트로 주입해 누락을 자동 검출하고, 발견 시 해당 페이지 범위를 재인덱싱한다.

## 변경 파일

| 파일 | 역할 |
|------|-----|
| [`/valuator/documents/schemas.py`](../../valuator/documents/schemas.py) (신규) | 문서 양식별 expected sections 화이트리스트 |
| [`/valuator/documents/indexer.py`](../../valuator/documents/indexer.py) | 인덱싱 직후 화이트리스트 대조 단계 추가 |
| [`/valuator/documents/retriever.py`](../../valuator/documents/retriever.py) | 누락 노드 발견 시 해당 페이지 범위 재인덱싱 트리거 |

## 화이트리스트 예시

### SEC 10-K
Item 1, 1A, 1B, 2, 3, 4, 5, 6, 7, 7A, 8, 9, 9A, 9B, 10, 11, 12, 13, 14, 15

### DART 사업보고서
- I. 회사의 개요
- II. 사업의 내용
- III. 재무에 관한 사항
- IV. 이사의 경영진단 및 분석의견
- V. 감사인의 감사의견 등
- VI. 이사회 등 회사의 기관에 관한 사항
- ...

화이트리스트는 문서 양식 식별자(예: `"sec_10k"`, `"dart_business_report"`) 기준으로 조회. 양식 식별자는 `DocumentIngest` 단계에서 부여.

## 누락 검출 로직

```
expected_sections = schemas[doc_form_id]
found = {node.title for node in walk(tree)}
missing = [s for s in expected_sections if not _fuzzy_match(s, found)]
```

`_fuzzy_match`는 LLM이 추출한 제목과 expected 제목 사이의 의미적 일치를 판단 — 한국어 양식은 띄어쓰기/조사 변동이 있으므로 단순 문자열 비교 X.

## 재인덱싱 트리거

누락 발견 시:
1. 인접 노드의 `page_range`로 누락 섹션의 페이지 범위 추정
2. 해당 페이지 범위만 `process_no_toc`로 재인덱싱
3. 결과 노드를 트리에 병합

메커니즘적으로 이는 [재귀 분할](phase-1-indexing-poc.md#재귀-분할-process_large_node_recursively)과 동일한 원리 — 부분 페이지 범위에 `process_no_toc`를 재호출한다. 차이는 트리거 조건뿐(재귀 분할은 노드 크기 위반, 누락 보강은 화이트리스트 미발견). 따라서 재귀 분할의 보호 장치(`max_recursion_depth`, 단일 페이지 보호)가 그대로 적용된다.

## 검증 방법

1. **누락 검출 정확도**: Apple FY24 10-K 트리에 화이트리스트 적용 → 검출된 누락이 실제 누락인지 수동 확인 (false positive 체크)
2. **재인덱싱 효과**: 누락 노드 재인덱싱 후 트리가 보완되었는지 확인
3. **최종 누락률**: 5% 미만 목표

## 산출 지표

- 화이트리스트 항목별 발견율 (사전/사후)
- 재인덱싱 호출 수, 추가 비용
- 보완 후 최종 누락률
- false positive 비율 (fuzzy match 정확도)
