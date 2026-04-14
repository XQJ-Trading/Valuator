# TS-006: OpenDART 재무제표 수집

## 문제 정의

**현 상태:**
- 한국 기업 재무제표를 yfinance에서 조회 → 정확성·커버리지 한계
- OpenDART는 금감원 공시 원본 제공 + `krx_ticker_resolve.py`에서 corp_code lookup에 이미 사용 중
- 재무제표 API(`fnlttSinglAcntAll`) 미연동

**목표:**
1. **경계 함수** (`domain/boundary/opendart_financial.py`) — OpenDART 재무제표 API 호출 + 응답을 canonical dict로 변환
2. **계정명 매핑** (`domain/knowledge/financial.py`) — 한국어 계정명 → canonical key
3. **Tool** (`valuator/tools/opendart_financial_tool.py`) — LLM이 호출하는 도구
4. **Tool 등록** (`valuator/tools/specs.py`, `valuator/runtime.py`)

---

## 아키텍처

### 경계 위치

```
LLM Tool 호출
    ↓
OpenDartFinancialTool          [tool — 결과 조립, ToolResult 반환]
    ↓
fetch_opendart_financial()     [경계 — API 호출, 파싱, canonical 변환]
    ↓
OpenDART fnlttSinglAcntAll API
```

경계 함수는 `domain/boundary/` 아래 단일 모듈. 기존 `krx_ticker_resolve.py`, `sec_ticker_resolve.py`와 동일 레벨.
경계의 책임: API 호출 → DataFrame 수신 → `dict[str, float | None]` 변환. 실패 시 `None` 반환.

### 데이터 흐름

```
opendart_financial_tool.execute(corp="005930", year="2024")
    ↓
OpenDartFinancialRequest.from_kwargs(kwargs)     # Pydantic 경계: 원시 입력 → 도메인 타입
    ↓
corp_code = resolve_corp_code(stock_code)        # krx corp records에서 stock_code → corp_code lookup
    ↓
fetch_opendart_financial(corp_code, year, reprt_code, fs_div)
    ├─ API 호출 (requests.get)
    ├─ DataFrame 파싱
    └─ OPENDART_ACCOUNT_MAP으로 canonical dict 변환
    ↓
_apply_derived_metrics(result)                   # yfinance_tool과 동일 로직 재사용
    ↓
ToolResult(success=True, result=result, metadata={"source": "opendart"})
```

### corp_code 해석

새 resolve 로직을 만들지 않는다. `krx_ticker_resolve.py`의 `fetch_krx_corp_records()`가 이미 OpenDART corp code 테이블을 가져온다.
경계에서 stock_code(6자리 종목코드) → corp_code(8자리) 매핑은 이 records에서 직접 lookup한다.

```python
def resolve_corp_code(stock_code: str) -> str | None:
    """stock_code(6자리 종목코드) → 8자리 DART corp_code. 순수 lookup, API 호출 없음."""
    records = fetch_krx_corp_records()
    for record in records:
        if record.get("stock_code", "").upper() == stock_code.upper():
            return record.get("corp_code")
    return None
```

---

## 구현 계획

### 1. 한국어 계정명 매핑

**File:** `domain/knowledge/financial.py` (기존 파일에 추가)

기존 `StatementField`의 aliases는 영문(yfinance 행 이름). OpenDART 응답의 `account_nm`은 한국어이므로 별도 매핑이 필요하다.
`StatementField`에 한국어 alias를 섞지 않는다 — 데이터 소스가 다르고, 매핑 로직이 다르다(행 이름 매칭 vs 딕셔너리 키 매칭).

```python
# OpenDART account_nm → canonical key
OPENDART_ACCOUNT_MAP: dict[str, str] = {
    # --- Balance Sheet ---
    "자산총계": "total_assets",
    "유동자산": "current_assets",
    "현금및현금성자산": "cash_and_equivalents",
    "부채총계": "total_liabilities",
    "유동부채": "current_liabilities",
    "장기차입금": "long_term_debt",
    "단기차입금": "short_term_debt",
    "자본총계": "total_equity",
    "이익잉여금": "retained_earnings",
    # --- Income Statement ---
    "매출액": "total_revenue",
    "수익(매출액)": "total_revenue",
    "매출원가": "cost_of_revenue",
    "매출총이익": "gross_profit",
    "판매비와관리비": "sga_expense",
    "영업이익": "operating_income",
    "영업손익": "operating_income",
    "이자비용": "interest_expense",
    "법인세비용": "tax_expense",
    "당기순이익": "net_income",
    "기본주당이익": "eps_basic",
    "주당순자산": "bps",
    # --- Cash Flow ---
    "영업활동현금흐름": "operating_cash_flow",
    "영업활동으로인한현금흐름": "operating_cash_flow",
    "유형자산의취득": "capex",
    "배당금의지급": "dividends_paid",
    "배당금지급": "dividends_paid",
    "자기주식의취득": "share_buyback",
    "감가상각비": "depreciation",
    "무형자산상각비": "amortization",
}
```

동일 value 매핑(6쌍)은 OpenDART 응답의 `account_nm` 변형을 경계에서 흡수하기 위해 유지.

### 2. 경계 함수

**File:** `domain/boundary/opendart_financial.py` (신규)

`krx_ticker_resolve.py`와 동일 패턴: 모듈 레벨 캐시, `clear_*_cache()` 테스트 훅, API 키 없으면 빈 결과 반환.

```python
"""Boundary: fetch financial statements from OpenDART fnlttSinglAcntAll API."""

from __future__ import annotations

import requests

from domain.boundary.krx_ticker_resolve import fetch_krx_corp_records
from domain.knowledge.financial import OPENDART_ACCOUNT_MAP
from valuator.utils.config import get_opendart_api_key

OPENDART_FINSTATE_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"

# reprt_code: 사업보고서=11011, 반기=11012, 1분기=11013, 3분기=11014
REPRT_CODES: dict[str, str] = {
    "annual": "11011",
    "half": "11012",
    "q1": "11013",
    "q3": "11014",
}

_fs_cache: dict[str, dict[str, float | None]] = {}


def clear_opendart_financial_cache() -> None:
    """Test hook."""
    _fs_cache.clear()


def resolve_corp_code(stock_code: str) -> str | None:
    """stock_code(6자리 종목코드) → 8자리 DART corp_code. 순수 lookup, API 호출 없음."""
    records = fetch_krx_corp_records()
    for record in records:
        if record.get("stock_code", "").upper() == stock_code.upper():
            return record.get("corp_code")
    return None


def fetch_opendart_financial(
    corp_code: str,
    year: int,
    reprt_code: str = "11011",
    fs_div: str = "CFS",
) -> dict[str, float | None] | None:
    """
    OpenDART 재무제표 단일 호출 → canonical dict 변환.

    실패 시 None 반환. 예외를 삼키지 않는다 — ConnectionError 등은 전파.
    """
    api_key = get_opendart_api_key()
    if not api_key:
        return None

    cache_key = f"fs:{corp_code}:{year}:{reprt_code}:{fs_div}"
    if cache_key in _fs_cache:
        return _fs_cache[cache_key]

    response = requests.get(
        OPENDART_FINSTATE_URL,
        params={
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": reprt_code,
            "fs_div": fs_div,
        },
        timeout=10,
    )
    response.raise_for_status()

    body = response.json()
    if body.get("status") != "000":
        return None

    items = body.get("list", [])
    if not items:
        return None

    result = _parse_items(items)
    _fs_cache[cache_key] = result
    return result


def _parse_items(items: list[dict]) -> dict[str, float | None]:
    """OpenDART 응답 list → canonical dict."""
    result: dict[str, float | None] = {}
    for item in items:
        canonical = OPENDART_ACCOUNT_MAP.get(item.get("account_nm", ""))
        if not canonical:
            continue
        raw = item.get("thstrm_amount", "")
        if not raw or raw == "-":
            continue
        result[canonical] = float(str(raw).replace(",", ""))
    return result
```

**기존 문서와의 차이:**
- `OpenDartBoundaryError` 제거 — 기존 boundary는 예외 클래스를 만들지 않는다. API 키 없으면 `None`, 데이터 없으면 `None`. `ConnectionError`는 전파.
- SQLite 캐시 제거 — 기존 패턴은 모듈 레벨 dict 캐시. 재무제표는 확정 공시이므로 프로세스 수명 캐시로 충분.
- `opendartreader` 의존성 제거 — `requests.get` 직접 호출. 외부 패키지 하나 줄임.
- `resolve_corp_code`는 `fetch_krx_corp_records()`를 재사용하여 stock_code → corp_code 순수 lookup. 새 API 호출 없음.
- cascade/fallback 로직 제거 — 호출자(tool)가 `reprt_code`와 `fs_div`를 명시. 경계는 한 번만 호출.

### 3. Tool

**File:** `valuator/tools/opendart_financial_tool.py` (신규)

`YFinanceBalanceSheetTool` 패턴을 따른다: Pydantic request model → 경계 호출 → 파생 지표 계산 → `ToolResult`.

```python
"""OpenDART financial statement tool for Korean companies."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from domain.boundary.opendart_financial import (
    fetch_opendart_financial,
    resolve_corp_code,
)
from domain.knowledge.financial import DERIVED_DIFFERENCES, DERIVED_RATIOS
from .base import BaseTool, ToolResult


class OpenDartFinancialRequest(BaseModel):
    corp: str       # 회사명 또는 6자리 종목코드
    year: str
    fs_div: str = "CFS"

    @classmethod
    def from_kwargs(cls, kwargs: dict[str, Any]) -> "OpenDartFinancialRequest":
        corp = str(kwargs.get("corp") or "").strip()
        if not corp:
            raise ValueError("'corp' is required")
        year = str(kwargs.get("year") or "").strip()
        if not year:
            raise ValueError("'year' is required")
        fs_div = str(kwargs.get("fs_div") or "CFS").strip().upper()
        return cls.model_validate({"corp": corp, "year": year, "fs_div": fs_div})


class OpenDartFinancialTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="opendart_financial_tool",
            description="Fetch Korean company financial statements (BS/IS/CF) from DART.",
        )

    async def execute(self, **kwargs) -> ToolResult:
        try:
            request = OpenDartFinancialRequest.from_kwargs(kwargs)
        except ValueError as exc:
            return ToolResult(success=False, result=None, error=str(exc))

        corp_code = resolve_corp_code(request.corp)
        if corp_code is None:
            return ToolResult(
                success=False,
                result=None,
                error=f"Corp code not found: {request.corp}",
                metadata={
                    "fallback": {
                        "tool_name": "web_search_tool",
                        "tool_args": {
                            "query": f"{request.corp} financial statements {request.year}",
                        },
                    },
                },
            )

        result = fetch_opendart_financial(
            corp_code=corp_code,
            year=int(request.year),
            fs_div=request.fs_div,
        )
        if result is None:
            # CFS 없으면 OFS 시도
            if request.fs_div == "CFS":
                result = fetch_opendart_financial(
                    corp_code=corp_code,
                    year=int(request.year),
                    fs_div="OFS",
                )

        if not result:
            return ToolResult(
                success=False,
                result=None,
                error=f"No financial data: corp={request.corp}, year={request.year}",
                metadata={
                    "fallback": {
                        "tool_name": "yfinance_balance_sheet",
                        "tool_args": {"ticker": request.corp, "year": request.year},
                    },
                },
            )

        result["corp"] = request.corp
        result["year"] = request.year
        _apply_derived_metrics(result)
        result["findings"] = _build_findings(result)

        return ToolResult(
            success=True,
            result=result,
            metadata={"source": "opendart", "corp_code": corp_code},
        )


def _apply_derived_metrics(result: dict[str, Any]) -> None:
    # 기존 DERIVED_RATIOS / DERIVED_DIFFERENCES 적용
    for metric in DERIVED_RATIOS:
        numerator = result.get(metric.numerator)
        denominator = result.get(metric.denominator)
        if numerator is None or denominator in (None, 0):
            continue
        denom = abs(denominator) if metric.abs_denominator else denominator
        if not denom:
            continue
        result[metric.name] = numerator / denom

    for metric in DERIVED_DIFFERENCES:
        minuend = result.get(metric.minuend)
        subtrahend = result.get(metric.subtrahend)
        if minuend is None or subtrahend is None:
            continue
        result[metric.name] = minuend - subtrahend

    # OpenDART 확장 필드로 계산 가능한 추가 지표
    _calc_ebitda(result)
    _calc_operating_margin(result)
    _calc_net_margin(result)
    _calc_effective_tax_rate(result)
    _calc_working_capital(result)
    _calc_net_debt(result)
    _calc_shareholder_return(result)
    _calc_per_pbr(result)


def _calc_ebitda(r: dict[str, Any]) -> None:
    oi = r.get("operating_income")
    dep = r.get("depreciation", 0)
    amor = r.get("amortization", 0)
    if oi is not None:
        r["ebitda"] = oi + (dep or 0) + (amor or 0)


def _calc_operating_margin(r: dict[str, Any]) -> None:
    oi, rev = r.get("operating_income"), r.get("total_revenue")
    if oi is not None and rev:
        r["operating_margin"] = oi / rev


def _calc_net_margin(r: dict[str, Any]) -> None:
    ni, rev = r.get("net_income"), r.get("total_revenue")
    if ni is not None and rev:
        r["net_margin"] = ni / rev


def _calc_effective_tax_rate(r: dict[str, Any]) -> None:
    tax = r.get("tax_expense")
    pretax = None
    if r.get("net_income") is not None and tax is not None:
        pretax = r["net_income"] + tax
    if pretax:
        r["effective_tax_rate"] = tax / pretax


def _calc_working_capital(r: dict[str, Any]) -> None:
    ca, cl = r.get("current_assets"), r.get("current_liabilities")
    if ca is not None and cl is not None:
        r["working_capital"] = ca - cl


def _calc_net_debt(r: dict[str, Any]) -> None:
    short = r.get("short_term_debt", 0) or 0
    long = r.get("long_term_debt", 0) or 0
    bonds = r.get("bonds_payable", 0) or 0
    cash = r.get("cash_and_equivalents", 0) or 0
    st_inv = r.get("short_term_investments", 0) or 0
    total_debt = short + long + bonds
    if total_debt:
        r["total_debt"] = total_debt
        r["net_debt"] = total_debt - cash - st_inv


def _calc_shareholder_return(r: dict[str, Any]) -> None:
    div = r.get("dividends_paid")
    buyback = r.get("share_buyback")
    if div is not None or buyback is not None:
        r["total_shareholder_return"] = abs(div or 0) + abs(buyback or 0)


def _calc_per_pbr(r: dict[str, Any]) -> None:
    """current_price가 있을 때 PER/PBR 계산. current_price는 SubjectContext에서 주입."""
    price = r.get("current_price")
    if price is None:
        return
    eps = r.get("eps_basic")
    if eps and eps > 0:
        r["per"] = price / eps
    bps = r.get("bps")
    if bps and bps > 0:
        r["pbr"] = price / bps


def _build_findings(result: dict[str, Any]) -> str:
    keys = [
        "corp", "year",
        # 규모
        "total_assets", "total_equity", "total_revenue", "net_income",
        # 수익성
        "operating_income", "ebitda", "gross_margin", "operating_margin", "net_margin",
        # 재무건전성
        "debt_to_equity", "current_ratio", "net_debt", "interest_coverage",
        # 현금흐름
        "operating_cash_flow", "free_cash_flow", "total_shareholder_return",
        # 주당·밸류에이션
        "eps_basic", "eps_diluted", "bps", "per", "pbr",
    ]
    return ", ".join(f"{k}={result.get(k)}" for k in keys if result.get(k) is not None)
```

**CFS→OFS fallback은 tool에 위치한다** — 경계가 아닌 비즈니스 판단이다. 경계는 주어진 파라미터로 1회 호출만 한다.

### 4. Tool 등록

**File:** `valuator/tools/specs.py` (기존 `TOOL_SPECS`에 추가)

```python
"opendart_financial_tool": ToolSpec(
    name="opendart_financial_tool",
    required=("corp", "year"),
    optional=("fs_div",),
    capability="Korean company financial statements (BS/IS/CF) from DART filings",
    param_descriptions={
        "corp": "회사명 또는 KRX 종목코드 6자리 (e.g., '삼성전자', '005930')",
        "year": "Target year (e.g., '2024')",
        "fs_div": "'CFS' (연결, default) or 'OFS' (별도)",
    },
),
```

**File:** `valuator/runtime.py` (기존 `create_tool_registry`에 추가)

```python
from .tools.opendart_financial_tool import OpenDartFinancialTool

# registry.register(...) 블록에 추가:
OpenDartFinancialTool(),
```

---

## 파일 변경 요약

| 파일 | 변경 유형 | 설명 |
|---|---|---|
| `domain/knowledge/financial.py` | 수정 | `OPENDART_ACCOUNT_MAP` 추가 |
| `domain/boundary/opendart_financial.py` | **신규** | `fetch_opendart_financial()`, `resolve_corp_code()` |
| `valuator/tools/opendart_financial_tool.py` | **신규** | `OpenDartFinancialTool` |
| `valuator/tools/specs.py` | 수정 | `TOOL_SPECS`에 `opendart_financial_tool` 추가 |
| `valuator/runtime.py` | 수정 | `create_tool_registry`에 등록 |

기존 문서 대비 제거된 파일:
- ~~`valuator/domain/boundary/opendart/exceptions.py`~~ — 예외 클래스 불필요
- ~~`valuator/domain/boundary/opendart/cache.py`~~ — SQLite 불필요, 모듈 dict 캐시로 대체
- ~~`valuator/domain/boundary/opendart/client.py`~~ — 단일 모듈 `opendart_financial.py`로 통합

---

## 검증 계획

```bash
python -m pytest tests/ -x
ruff check . && ruff format .
```

### 검증 시나리오

1. **정상 흐름**: 삼성전자(stock_code: 005930, corp_code: 00126380) 2024년
   - `opendart_financial_tool(corp="005930")` → `resolve_corp_code("005930")` → `fetch_opendart_financial("00126380", 2024)` → canonical dict → 파생 비율 → ToolResult
2. **CFS→OFS fallback**: CFS 미제공 기업 → tool에서 OFS 재시도
3. **API 키 미설정**: `fetch_opendart_financial` → `None` → tool에서 `ToolResult(success=False, fallback=web_search_tool)`
4. **네트워크 오류**: `ConnectionError` 전파 → tool에서 미포착 → agent loop의 기존 에러 처리로 위임

---

## 외부 데이터 소스 매핑

### 온톨로지 노드별 매핑

| 온톨로지 노드 | SubjectContext 필드 | KIS API | 비고 |
|---------------|-------------------|---------|------|
| `Security` | `security.ticker`, `exchange`, `currency` | KRX 메타 또는 KIS 종목정보 | 국내 상장: KRW 고정, ticker = `stock_code.KS` |
| `StockPrice` | `stock_price.current_price`, `market_cap` | KIS `inquire-price` | 당일 현재가 + 시가총액 |
| `Indicator` | `indicator.trailing_pe`, `eps`, `pbr` 등 | KIS `inquire-price` | 동일 API 응답에 포함 |

### Valuator에서 이미 쓰는 것

| 항목 | 출처 |
|------|------|
| `stock_code` (6자리) | OpenDart → `Listing.security_code` |
| 시장 구분 | OpenDart `corp_cls` → `Listing.exchange` (KOSPI/KOSDAQ/KONEX) |
| 야후 심볼 | `Listing.vendor_symbols["yahoo"]` (e.g., `005930.KS`) |
| 회사명 | `Company.company_name` |

### KIS inquire-price (국내주식 현재가)

**API 명**: 주식현재가 시세 / `inquire-price`

| 항목 | 값 |
|------|-----|
| **REST path** | `/uapi/domestic-stock/v1/quotations/inquire-price` |
| **TR ID** | 포털에서 확인 (예: `FHKST01010100` — 배포 전 재확인 **필수**) |
| **query** | `FID_COND_MRKT_DIV_CODE`=`J` (주식), `FID_INPUT_ISCD`=종목코드 |

**응답 필드 (일반적)**:

| StockPrice / Indicator 필드 | KIS 필드명 |
|-----------------------------|-----------|
| `current_price` | `stck_prpr` (현재가) |
| `market_cap` | `total_mkt_cap` 또는 계산값 |
| `trailing_pe` | `per` 또는 `eps` 기반 계산 |
| `eps` | `eps` |
| `pbr` | `pbr` 또는 `bps` 기반 계산 |
| `bps` | `bps` |

**주의**: KIS TR ID와 응답 필드명은 [KIS Developers 포털](https://apiportal.koreainvestment.com/) 최신 스펙 기준.
배포 전 반드시 해당 API 상세에서 재확인한다.

### forward_pe 처리

`forward_pe` (예상 PER)는 KIS 단일 호출에 없는 경우가 많다.
- 생략 가능 (`Indicator.forward_pe = None`)
- 또는 다른 출처(FnGuide 등) 추가

### ISIN (선택)

온톨로지 `Security.isin`이 필요하면:
- [금융위원회 KRX상장종목정보](https://www.data.go.kr/) (공공데이터포털)
- 또는 KIS **종목정보** 계열 API

Valuator는 당장 OpenDart + Listing으로 충분한 경우가 많으므로, ISIN은 선택적.

### 구현 순서 제안

1. **기본**: `Listing` 기존 정보 활용 (stock_code, yahoo_symbol, exchange, currency)
2. **KIS 연동** (선택):
   - `inquire-price` 1회 호출로 `StockPrice` + `Indicator` 채우기
   - 필요 시 `inquire-daily-price`로 시계열 추가
3. **ISIN** (선택): 공공데이터 또는 KIS 종목정보 API로 보강

### 참고 링크

- [KIS Developers 포털](https://apiportal.koreainvestment.com/) — API 목록에서 `inquire-price`, `inquire-daily-price` 검색
- [한국투자 GitHub](https://github.com/koreainvestment/open-trading-api) — TR ID, 예제 코드
- [금융위원회 KRX상장종목정보](https://www.data.go.kr/) — 공공데이터포털
