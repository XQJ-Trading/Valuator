# OpenDART FSS 단일 소스로 KRX 증권 데이터 리팩토링

## Context

현재 `scripts/download_krx_securities.py`는 KRX KIND HTML 스크래핑을 primary로, OpenDART를 보강용으로 사용한다.
HTML 스크래핑은 불안정하고(포맷 변경에 취약), OpenDART가 이미 동일 데이터를 구조화된 API로 제공하므로,
OpenDART FSS를 단일 소스로 전환하여 HTML 파싱 의존성을 완전히 제거한다.

**핵심 전략**: Snapshot 중심 + 증분 갱신. 전체 데이터는 snapshot으로 관리하고, 실행 시에는 신규/변경분만 API 호출.

## 변경 사항

### 1. 스크립트 리네이밍

- `scripts/download_krx_securities.py` → `scripts/download_opendart_securities.py`
- 출력 파일 `data/krx_securities.json`은 호환성을 위해 유지 (consumer: `_load_krx_listing_seeds()`)

### 2. 통합 스냅샷 도입

기존 2개 스냅샷(`opendart_corp_codes.json.gz`, `opendart_company_names.json.gz`) → 단일 `opendart_companies.json.gz`

```json
{
  "generated_at": "...",
  "entries": {
    "005930": {
      "corp_code": "00126380",
      "corp_name": "삼성전자",
      "corp_name_eng": "SAMSUNG ELECTRONICS CO.,LTD",
      "stock_name": "삼성전자",
      "stock_code": "005930",
      "corp_cls": "Y"
    }
  }
}
```

### 3. 새로운 메인 플로우

```
corpCode.xml (전체 상장사 목록)
  → snapshot과 diff → 신규/변경분만 company.json 호출
  → snapshot 갱신
  → SecurityRecord 생성 → data/krx_securities.json 출력
```

- `corp_cls`로 거래소 매핑: `Y=KOSPI`, `K=KOSDAQ`, `N=KONEX`, `E` 제외
- `stock_name`을 `issuer_name`으로 사용 (KRX의 종목명과 동일 역할)
- `corp_code`는 항상 존재 (optional → 필수)
- `--allow-krx-only` 플래그 제거 (OpenDART 필수)
- **tqdm 진행률 표시**: 각 주요 단계에 tqdm 적용
  - corpCode.xml 파싱 (단일 스텝, 시작/완료 표시)
  - company.json 증분 fetch (건별 진행률 — `tqdm(total=len(missing_codes))`)
  - SecurityRecord 생성 (전체 목록 변환)

### 4. 제거 대상

- KRX KIND 관련 전체: `KIND_URL`, `MARKET_TYPES`, `ENGLISH_NAME_COLUMNS`, `USER_AGENT`
- `_KindDownloadRow`, `_kind_session()`, `_fetch_kind_rows()`, `_kind_row()`
- `_TableParser` HTML 파서 클래스, `_parse_html_table()`, `_row_map()`, `_value()`
- 분리된 캐시/스냅샷 경로 (`OPENDART_CORP_CODES_CACHE_PATH`, `OPENDART_ENGLISH_NAMES_CACHE_PATH` 등)
- `html.parser` import

### 5. 유지/재사용 대상

- `SecurityRecord` dataclass + `to_payload()` (출력 포맷 호환)
- `_fetch_opendart_corp_codes()` (corpCode.xml 파싱)
- `_OpenDartLookupError` + retry 로직
- `ThreadPoolExecutor` 병렬 호출 패턴
- `_vendor_symbols()` (exchange → Yahoo suffix 매핑)
- `_dedupe_strings()` alias 중복 제거
- `_write_string_map()` / `_read_string_map()` → 통합 스냅샷용으로 확장

### 6. `refresh_opendart_snapshot.py` 업데이트

- 리네이밍된 스크립트에서 import
- 전체 company.json 데이터를 통합 스냅샷으로 저장

### 7. 테스트 업데이트

- **제거**: KRX HTML 파싱 테스트 (`KindBoundaryTests` 등)
- **유지/수정**: OpenDART 관련 테스트 (archive 파싱, retry, snapshot fallback)
- **추가**: `corp_cls` → exchange 매핑, `E` 필터링, 증분 갱신 로직

## 수정 대상 파일

| 파일 | 작업 |
|------|------|
| `scripts/download_krx_securities.py` | 삭제 (리네이밍) |
| `scripts/download_opendart_securities.py` | 신규 (OpenDART 단일 소스) |
| `scripts/refresh_opendart_snapshot.py` | import 경로 + 통합 스냅샷 |
| `tests/test_download_krx_securities.py` | 리네이밍 + KRX 테스트 제거 |
| `scripts/snapshots/README.md` | 새 스냅샷 파일명 반영 |

## Verification

1. `python scripts/refresh_opendart_snapshot.py` — 통합 스냅샷 생성 확인
2. `python scripts/download_opendart_securities.py` — `data/krx_securities.json` 출력 확인
3. 출력 JSON에 KOSPI/KOSDAQ/KONEX 종목 포함, `corp_code` 전부 존재 확인
4. `python -m pytest tests/test_download_opendart_securities.py` — 테스트 통과
5. `valuator/domain/company.py`의 `_load_krx_listing_seeds()`가 정상 동작하는지 기존 테스트로 확인
