# Phase 4 — 캐싱·자동화

전체 아키텍처: [overview.md](overview.md). 선행: [Phase 3](phase-3-domain-enrichment.md).

## 목표

문서 해시 → 트리 매핑을 영속화해 재인덱싱을 회피한다. cron으로 주요 기업의 최신 공시를 사전 인덱싱하여 사용자 질의 시점에 캐시 hit을 가정할 수 있게 한다.

## 변경 파일

| 파일 | 역할 |
|------|-----|
| [`/valuator/documents/store.py`](../../valuator/documents/store.py) | 캐시 조회·저장 로직 강화 (Phase 1에서 기본 골격, 여기서 TTL/사이즈 정책 추가) |
| [`/valuator/documents/cache.py`](../../valuator/documents/cache.py) (신규) | 캐시 정책: TTL, LRU eviction (필요 시) |
| [`/scripts/index_recent_filings.py`](../../scripts/index_recent_filings.py) (신규) | cron 진입점. 주요 기업 신규 공시 fetch → 인덱싱 |

## 캐싱 정책

- 캐시 키 = 문서 SHA256 (기존 `sec_tool.py`의 URL SHA256 패턴 확장 — 같은 URL이라도 내용이 바뀌면 키가 달라짐)
- TTL: 무한. 문서 내용이 변하지 않는 한 트리도 변하지 않음 (인덱싱 비결정성을 받아들임)
- 저장 위치: SQLite `IndexStore` 테이블
- 노드 텍스트는 별도 blob 저장 (트리에는 page_range만)

## 자동화

cron 정책:
- 매일 새벽 1회 실행
- 주요 기업 화이트리스트 (예: Valuator에서 자주 분석되는 회사 상위 50개) 기준
- SEC EDGAR / DART API에서 신규 공시 fetch
- doc_hash 새로 확인되면 인덱싱 후 `IndexStore`에 저장

## 사용자 질의 시점

1. `SECTool`/`DARTTool`이 doc_hash 계산
2. `IndexStore.get(doc_hash)` 캐시 조회
3. **hit**: 트리 즉시 반환 → `TreeRetriever`로 진행
4. **miss**: 인덱싱 트리거 (Phase 1 경로). 사용자가 잠시 기다림.

cron이 잘 돌면 대부분 hit, 신규 회사·신규 공시만 miss.

## 검증 방법

1. **재요청 hit 확인**: 동일 문서를 두 번 요청해 두 번째가 캐시 hit인지 로그로 확인
2. **cron 안정성**: 1주일 운영 후 cron 실패율, 인덱싱 실패율 측정
3. **적중률**: 실제 사용자 질의 트래픽에서 캐시 hit 비율

## 산출 지표

- 캐시 적중률 (전체, 신규 회사 분리)
- cron 실패율
- 사전 인덱싱된 문서 수 (누적)
- 저장소 크기 증가율 (월 단위)
