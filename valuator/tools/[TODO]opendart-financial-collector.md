# TS-006: OpenDART 재무제표 수집 — Collector 레이어 도입

## Context

**문제:** 한국 기업 재무제표를 yfinance(Yahoo Finance)에서 가져오는 현재 구조는 데이터 정확성과 커버리지에 한계가 있다. OpenDART는 금감원 공시 원본 데이터를 제공하며, 이미 회사 식별(corp_code lookup)에 사용 중이지만 재무제표 API(`fnlttSinglAcntAll`)는 미연동 상태.

**근본 원인:** 외부 데이터 수집 책임이 `tools/`와 `infra/`에 혼재. yfinance 도구는 API 호출 + 파싱 + 비율 계산을 하나의 tool 클래스에서 수행. 데이터 수집(경계)과 도구 오케스트레이션(business logic)이 분리되지 않음.

**목표:**
1. `valuator/collectors/` 레이어 신설 — 외부 데이터 수집 경계 전담
2. OpenDART 재무제표 collector 구현 — BS/IS/CF 전체, 연결재무제표 우선
3. `opendart_financial_tool` 도구 추가 — KRX 기업 전용, planner가 자동 선택
4. `Listing`에 `vendor_ids` 추가 — corp_code를 도메인 타입으로 전달

**참조:** [stockelper-kg/collectors/dart.py](https://github.com/Stockelper-Lab/stockelper-kg/blob/main/src/stockelper_kg/collectors/dart.py)

## Data Flow

```
현재:
  Tool(yfinance_balance_sheet) → yfinance API → 파싱 + 비율계산 → ToolResult
  (한국 기업도 yfinance .KS/.KQ 심볼로 조회)

목표:
  Collector(OpenDartFinancialCollector) → dart-fss fnltt_singl_acnt_all() → 도메인 dict 반환
                                                                    ↓
  Tool(opendart_financial_tool) → Collector 호출 → 비율계산 → ToolResult
  (KRX 기업은 이 도구가 선택됨, yfinance는 valuation info 용도로 유지)
```

## Changes

### 1. `Listing`에 `vendor_ids` 필드 추가

**File:** [company.py:50-57](valuator/domain/company.py#L50-L57)

```python
# before
@dataclass(frozen=True, slots=True)
class Listing:
    listing_id: str
    company_id: str
    security_code: str
    exchange: str
    vendor_symbols: dict[str, str]
    aliases: tuple[str, ...] = ()
    is_primary: bool = False

# after
@dataclass(frozen=True, slots=True)
class Listing:
    listing_id: str
    company_id: str
    security_code: str
    exchange: str
    vendor_symbols: dict[str, str]
    vendor_ids: dict[str, str] = field(default_factory=dict)
    aliases: tuple[str, ...] = ()
    is_primary: bool = False
```

- `vendor_symbols`(거래 심볼: yahoo 등)과 대칭적인 외부 시스템 식별자 dict
- KRX: `{"opendart": "01358463"}`, 향후 SEC CIK 등도 동일 패턴

**File:** [company.py:428-452](valuator/domain/company.py#L428-L452) — `_load_krx_listing_seeds`

```python
vendor_ids = {"opendart": str(record.get("corp_code", "")).strip()}
# Listing(..., vendor_ids=vendor_ids)
```

**File:** [opendart_client.py](valuator/infra/opendart_client.py) — `SecurityRecord` → `Listing` 생성 경로에서도 `corp_code`를 `vendor_ids`에 포함

### 2. `SubjectProjection`에 `corp_code` 노출

**File:** [specs.py:31-58](valuator/tools/specs.py#L31-L58)

```python
# SubjectProjection에 property 추가
@property
def corp_code(self) -> str:
    if self.listing is None:
        return ""
    return self.listing.vendor_ids.get("opendart", "")
```

**File:** [specs.py:95-108](valuator/tools/specs.py#L95-L108) — `ToolExecutionContext.values()`

```python
return {
    ...
    "corp_code": projection.corp_code,  # 추가
}
```

### 3. Collector 레이어 신설

**Directory:** `valuator/collectors/` (신규)

```
valuator/collectors/
├── __init__.py
├── base.py              # BaseCollector ABC
└── opendart_financial.py # OpenDartFinancialCollector
```

**`base.py`:**
```python
from abc import ABC, abstractmethod
from typing import Any

class BaseCollector(ABC):
    @abstractmethod
    def collect(self, **kwargs) -> Any:
        ...
```

**`opendart_financial.py`:**

경계 함수. `dart-fss` 라이브러리의 `fnltt_singl_acnt_all()` 사용 → 도메인 canonical dict 반환.

기존 `opendart_client.py`의 dart-fss lazy import 패턴(`_load_dart_fss_modules`, `_bootstrap_dart_fss_namespace`, `_configure_dart_fss`)을 재사용.

```python
from dart_fss.api.finance.fnltt_singl_acnt_all import fnltt_singl_acnt_all

class OpenDartFinancialCollector(BaseCollector):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def collect(self, *, corp_code: str, year: int) -> dict[str, float | None]:
        """연간 → 3Q → 반기 → 1Q 순으로 fallback. CFS 우선, OFS fallback."""
        _ensure_dart_fss_configured(self.api_key)  # opendart_client.py 패턴 재사용
        for reprt_code in _REPRT_CODE_FALLBACK:
            items = self._fetch(corp_code, year, reprt_code, fs_div="CFS")
            if not items:
                items = self._fetch(corp_code, year, reprt_code, fs_div="OFS")
            if items:
                result = _parse_items(items)
                result["_reprt_code"] = reprt_code
                return result
        raise OpenDartCollectorError(f"No data: corp_code={corp_code}, year={year}")

    def _fetch(self, corp_code, year, reprt_code, fs_div) -> list[dict]:
        try:
            data = fnltt_singl_acnt_all(
                corp_code=corp_code,
                bsns_year=str(year),
                reprt_code=reprt_code,
                fs_div=fs_div,
                api_key=self.api_key,
            )
            return data.get("list", [])
        except NoDataReceived:
            return []  # 해당 보고서 미제출 → 다음 reprt_code로 fallback
```

**dart-fss 동작 방식:**
- `api_request` helper가 내부적으로 파라미터 검증 + `requests` 호출 + `check_status()` 수행
- `status == "000"` → 정상 반환 (dict)
- `status == "013"` → `NoDataReceived` 예외 발생 (데이터 없음)
- 기타 status → `APIKeyError`, `OverQueryLimit` 등 예외 → **이건 catch하지 않고 전파** (fail fast)

따라서 `body.get("status")` 직접 체크 불필요. `NoDataReceived`만 catch하고 나머지는 전파.

`_REPRT_CODE_FALLBACK = ("11011", "11014", "11012", "11013")` — 사업보고서(연간)→3분기→반기→1분기

`_parse_items`: `account_nm` → `OPENDART_ACCOUNT_MAP` 매핑, `thstrm_amount` 쉼표 제거 + float 변환. 매핑 안 되는 항목은 무시.

### 4. 한국어 계정명 → canonical 매핑

**File:** [financial.py](valuator/domain/knowledge/financial.py)

```python
OPENDART_ACCOUNT_MAP: dict[str, str] = {
    # BS
    "자산총계": "total_assets",
    "부채총계": "total_liabilities",
    "자본총계": "total_equity",
    "유동자산": "current_assets",
    "유동부채": "current_liabilities",
    # IS
    "매출액": "total_revenue",
    "수익(매출액)": "total_revenue",
    "매출총이익": "gross_profit",
    "영업이익": "operating_income",
    "이자비용": "interest_expense",
    "당기순이익": "net_income",
    # CF
    "영업활동현금흐름": "operating_cash_flow",
    "영업활동으로인한현금흐름": "operating_cash_flow",
    "유형자산의취득": "capex",
}
```

- EBITDA는 OpenDART에서 직접 제공하지 않음 → `None`으로 유지 (파생 계산으로 보완 가능하나 1차에서는 생략)
- yfinance 도구의 13개 canonical key 중 12개 매핑 가능

### 5. 도구 구현

**File:** `valuator/tools/opendart_financial_tool.py` (신규)

```python
class OpenDartFinancialTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="opendart_financial_tool",
            description="Fetch financial statements (BS/IS/CF) for Korean companies from DART filings.",
        )

    async def execute(self, **kwargs) -> ToolResult:
        corp_code = str(kwargs.get("corp_code", "")).strip()
        year = str(kwargs.get("year", "")).strip()
        if not corp_code:
            return ToolResult(success=False, result=None, error="'corp_code' required")
        if not year:
            return ToolResult(success=False, result=None, error="'year' required")

        from ..collectors.opendart_financial import OpenDartFinancialCollector
        from ..utils.config import get_opendart_api_key

        collector = OpenDartFinancialCollector(get_opendart_api_key(required=True))
        raw = collector.collect(corp_code=corp_code, year=int(year))

        # 파생 비율 계산 (DERIVED_RATIOS, DERIVED_DIFFERENCES — yfinance와 동일)
        for metric in DERIVED_RATIOS:
            ...  # 동일 로직
        for metric in DERIVED_DIFFERENCES:
            ...

        # findings summary
        raw["findings"] = ", ".join(f"{k}={v}" for k, v in raw.items() if not k.startswith("_"))
        return ToolResult(
            success=True,
            result=raw,
            metadata={"source": "opendart", "reprt_code": raw.get("_reprt_code")},
        )
```

### 6. 도구 등록

**File:** [executor/service.py:17-26](valuator/core/executor/service.py#L17-L26)

```python
_TOOL_CLASS_PATHS에 추가:
"opendart_financial_tool": ("valuator.tools.opendart_financial_tool", "OpenDartFinancialTool"),
```

**File:** [specs.py:159-207](valuator/tools/specs.py#L159-L207)

```python
TOOL_SPECS에 추가:
"opendart_financial_tool": ToolSpec(
    name="opendart_financial_tool",
    required=("corp_code", "year"),
    capability="Korean company financial statements (BS/IS/CF) from DART filings",
    subject_requirement=SubjectRequirement(
        identity_level=SubjectIdentityLevel.LISTING,
        market="KRX",
    ),
),
```

## 파일 변경 요약

| 파일 | 변경 유형 | 설명 |
|---|---|---|
| `valuator/domain/company.py` | 수정 | `Listing.vendor_ids` 필드, KRX seed에 corp_code 포함 |
| `valuator/infra/opendart_client.py` | 수정 | `SecurityRecord→Listing` 경로에 vendor_ids 전달 |
| `valuator/tools/specs.py` | 수정 | `SubjectProjection.corp_code`, `values()`, `TOOL_SPECS` |
| `valuator/domain/knowledge/financial.py` | 수정 | `OPENDART_ACCOUNT_MAP` 추가 |
| `valuator/collectors/__init__.py` | **신규** | 패키지 init |
| `valuator/collectors/base.py` | **신규** | `BaseCollector` ABC |
| `valuator/collectors/opendart_financial.py` | **신규** | OpenDART 재무제표 수집 (dart-fss `fnltt_singl_acnt_all` 사용) |
| `valuator/tools/opendart_financial_tool.py` | **신규** | 도구 클래스 |
| `valuator/core/executor/service.py` | 수정 | `_TOOL_CLASS_PATHS` 등록 |

## Verification

```bash
python -m pytest tests/ -x
ruff check . && ruff format .
```

세션 재실행 후 검증:
1. 삼성전자(corp_code: 00126380) 쿼리 → `opendart_financial_tool` 선택 + 재무데이터 반환 확인
2. 연간보고서 미제출 연도 → 분기 fallback 동작 확인 (`NoDataReceived` → 다음 reprt_code)
3. CFS 없는 기업 → OFS fallback 동작 확인
4. yfinance 도구가 여전히 KRX 기업 valuation info 제공 가능한지 확인
