# Open DART API Tool 구현 계획

## Context

한국 기업의 재무제표, 기업 개황, 공시 목록 등을 Open DART API를 통해 조회하는 tool을 추가한다.
현재 DART 관련 코드는 `krx_ticker_resolve.py`에 corp_code 조회만 있고, 실제 재무 데이터를 가져오는 tool은 없다.
또한 `valuator/infra/opendart_client` 모듈을 참조하는 dead script들, 주석 처리된 DomainTool 잔재 등 정리가 필요하다.

---

## Phase 1: Dead Code 정리

### 1a. 삭제: 깨진 스크립트 2개
- `scripts/download_opendart_securities.py` — 존재하지 않는 `valuator.infra.opendart_client` import
- `scripts/refresh_opendart_snapshot.py` — 동일

### 1b. 삭제: `scripts/snapshots/` 디렉토리 전체
- `scripts/snapshots/opendart_companies.json.gz` + `README.md`
- 어떤 프로덕션 코드도 이 파일을 로드하지 않음

### 1c. DomainTool lazy export 제거
- `valuator/tools/__init__.py`: `__all__`과 `_LAZY_EXPORTS`에서 `"DomainTool"` 항목 제거
- `domain_tool.py` 파일 자체와 테스트는 유지 (향후 활성화 가능성)
- `specs.py`, `runtime.py`의 주석은 그대로 유지 (이미 비활성)

### 1d. `query.py` 주석 정리
- `query.py:228` 의 `# "domain_tool"` 주석 라인 제거

---

## Phase 2: corp_code 모델링 — Listing에 필드 추가

### 2a. `domain/company.py` — Listing dataclass 확장
```python
@dataclass(frozen=True, slots=True)
class Listing:
    ...
    corp_code: str = ""   # DART 8-digit corporate code (KRX only)
```

### 2b. `domain/boundary/krx_ticker_resolve.py` — `load_seeds()` 에서 corp_code 읽기
- `krx_securities.json` 레코드에서 `record.get("corp_code", "")` 읽어서 Listing 생성 시 전달
- 기존 JSON 스키마에 이미 `corp_code` 필드 존재 (현재 무시 중)

### 2c. `domain/boundary/krx_ticker_resolve.py` — `_listing_seed_from_record()` 수정
- `record["corp_code"]`를 Listing 생성 시 `corp_code=` 인자로 전달

### 2d. `domain/boundary/krx_ticker_resolve.py` — `resolve_corp_code()` 함수 추가
DART tool이 사용할 단일 진입점:
- 입력: surface_form (회사명 or 종목코드)
- entity index에서 Listing 찾아 corp_code 반환 → 없으면 `fetch_records()`로 fallback
- 반환: 8자리 corp_code string, 실패 시 ValueError

---

## Phase 3: OpenDartReader 기반 DART Tool 구현

### 라이브러리 선택: OpenDartReader
- 사용자 결정에 따라 `opendartreader` 패키지 사용
- `pip install opendartreader` (또는 requirements에 추가)
- `OpenDartReader(api_key)` 인스턴스를 tool 내부에서 생성

### 3a. 새 파일: `valuator/tools/opendart_tool.py`

**클래스**: `OpenDartTool(BaseTool)`
- `name = "opendart_tool"`
- OpenDartReader 인스턴스를 내부에서 lazy 생성 (API key from config)

**지원 data_type**:
1. `financial_statement` (기본값) — `OpenDartReader.finstate(corp, bsns_year, reprt_code)`
   - reprt_code 매핑: annual→"11011", q1→"11013", q2→"11012", q3→"11014"
   - 연결재무제표 우선, 없으면 개별재무제표 fallback
   - 핵심 항목: 매출액, 영업이익, 당기순이익, 자산총계, 부채총계, 자본총계
2. `disclosure_list` — `OpenDartReader.list(corp_code, ...)`
   - 최근 공시 목록 검색

**인자 해석 (경계)**:
- `corp` → `resolve_corp_code()` 로 corp_code 획득
- `year` → int
- `report_type` → reprt_code 매핑
- `data_type` → 엔드포인트 선택

**반환**: `ToolResult(success, result={findings, ...structured data...}, metadata)`

### 3b. `valuator/tools/specs.py` — ToolSpec 등록
```python
"opendart_tool": ToolSpec(
    name="opendart_tool",
    required=("corp", "year"),
    optional=("report_type", "data_type"),
    capability="Korean corporate financial statements and disclosures via FSS Open DART",
    arg_choices={
        "report_type": ("annual", "q1", "q2", "q3"),
        "data_type": ("financial_statement", "disclosure_list"),
    },
    param_descriptions={
        "corp": "Korean company name or 6-digit stock code",
        "year": "Business year (e.g., 2024)",
        "report_type": "Report period: annual, q1, q2, q3",
        "data_type": "Data type: financial_statement or disclosure_list",
    },
    param_properties={
        "year": {"type": "integer"},
        "report_type": {"type": "string", "enum": ["annual", "q1", "q2", "q3"]},
        "data_type": {"type": "string", "enum": ["financial_statement", "disclosure_list"]},
    },
),
```

### 3c. `valuator/runtime.py` — 레지스트리 등록
```python
from .tools.opendart_tool import OpenDartTool
# registry loop에 OpenDartTool() 추가
```

### 3d. `valuator/tools/__init__.py` — lazy export 추가
```python
"OpenDartTool": (".opendart_tool", "OpenDartTool"),
```

### 3e. `domain/query.py` — DEFAULT_GENERIC_TOOLS에 추가
```python
DEFAULT_GENERIC_TOOLS = [
    "web_search_tool",
    "sec_tool",
    "yfinance_balance_sheet",
    "code_execute_tool",
    "opendart_tool",
]
```
`fill_routing_defaults()`의 sorted set에도 `"opendart_tool"` 추가.

### 3f. `valuator/core/planning/prompts.py` — LLM 가이드 추가
기존 sec_tool/yfinance 가이드 근처에:
```
"Use opendart_tool for Korean company financial statements (재무제표). Requires Korean company name or stock code and year."
```

---

## Phase 4: `krx_securities.json` 갱신 스크립트 (선택)

삭제한 2개 스크립트를 대체하는 `scripts/refresh_krx_securities.py` 작성:
- `fetch_records()` + `_fetch_corp_cls()` 조합으로 전체 KRX 상장사를 `data/krx_securities.json`에 기록
- 실행하면 현재 1건짜리 JSON이 전체 상장사(~2500개)로 채워짐
- 이는 정적 인덱스 성능 향상 (on_miss 없이 바로 조회)

---

## Phase 5: company.py 리팩터링 (DART tool 완성 후)

DART tool이 동작 확인된 후, company.py의 경계 코드를 분리한다.

### 5a. SEC 경계 로직을 `sec_ticker_resolve.py`로 이동
- `seed_from_record()` + `_sec_company_name`, `_sec_company_aliases`, `_sec_trimmed_aliases`, `_display_sec_name`, `_title_words`, `_trim_trailing_words` (~60줄)
- 이미 `sec_ticker_resolve.py`가 이 함수를 import해서 쓰고 있으므로, 이동하면 import 방향이 정리됨

### 5b. KRX/SEC 파일 로딩을 각 boundary 모듈로 이동
- `load_seeds()` → `krx_ticker_resolve.py`
- `load_seeds()` → `sec_ticker_resolve.py`
- `_load_json_records()` → 유틸 또는 각 boundary에 인라인

### 5c. `ListingSeed`를 경계 전용 타입으로 재배치
- `ListingSeed`는 외부 소스 → 도메인 변환의 중간체이므로 경계 모듈 쪽에 위치가 적절
- 다만 `index()`가 `ListingSeed`를 소비하므로, index 구축 인터페이스 조정 필요

### 5d. Entity index를 별도 모듈로 분리 (선택)
- `index()`, `_bind_listing`, `_bind_company`, `ingest_seeds()`, `_rebuild_company_name_index` → `domain/company_index.py`
- company.py에는 도메인 타입 + 공개 resolution API만 남김

---

## 수정 대상 파일 요약

| 파일 | 변경 |
|------|------|
| `scripts/download_opendart_securities.py` | 삭제 |
| `scripts/refresh_opendart_snapshot.py` | 삭제 |
| `scripts/snapshots/` | 디렉토리 삭제 |
| `valuator/tools/__init__.py` | DomainTool export 제거, OpenDartTool export 추가 |
| `domain/query.py` | domain_tool 주석 제거, opendart_tool 추가 |
| `domain/company.py` | Listing에 corp_code 필드 추가 |
| `domain/boundary/krx_ticker_resolve.py` | `load_seeds()`, `resolve_corp_code()` 구현 |
| `valuator/tools/opendart_tool.py` | 신규: OpenDartTool 클래스 |
| `valuator/tools/specs.py` | opendart_tool ToolSpec 등록 |
| `valuator/runtime.py` | OpenDartTool 레지스트리 등록 |
| `valuator/core/planning/prompts.py` | opendart_tool LLM 가이드 추가 |
| `scripts/refresh_krx_securities.py` | 신규: KRX 전체 상장사 JSON 갱신 스크립트 |

## 검증

1. `python -m pytest tests/` — 기존 테스트 통과 확인
2. `ruff check . && ruff format .` — lint/format
3. OpenDartTool 단위 테스트: mock 응답으로 financial_statement, disclosure_list 검증
4. resolve_corp_code 단위 테스트: stock_code, 회사명, fuzzy 매칭 케이스
5. 수동 통합: `OPENDART_API_KEY` 설정 후 서버 기동, 한국 기업 쿼리로 opendart_tool 호출 확인
