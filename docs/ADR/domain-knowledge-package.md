# domain/knowledge 패키지 분리

## Context

도메인 지식이 여러 곳에 흩어져 있다:
- 분석 모듈 콘텐츠 → `domain/{ceo,dcf,risk_transmission}/`
- 재무 어휘 (필드명, 비율 공식) → `yfinance_tool.py` 하드코딩
- IR 추출 규칙 → `ir.py` domain_id별 if 분기
- 모듈별 IR 타입 → `types.py`에 DcfSummary, CeoSummary 등

목표: `domain/knowledge/`로 지식 콘텐츠를 분리하여, 새 도메인 모듈 추가 시 YAML/MD만으로 완결되게 한다.

## 최종 디렉터리 구조

```
valuator/domain/
  __init__.py           # export 갱신
  company.py            # 유지 (경계 — find_company)
  loader.py             # 루트 경로를 knowledge/modules/로 변경
  query.py              # 유지
  query_analysis.py     # 유지
  router.py             # 유지
  types.py              # DomainModule에 IrConfig 추가, 모듈별 Summary 타입 제거
  ir.py                 # 하드코딩 제거 → 제네릭 프로젝터로 재작성
  knowledge/
    __init__.py
    index.yaml          # ← domain/index.yaml 이동
    financial.py        # 재무 어휘: 필드 매핑, 비율 정의
    modules/
      ceo/
        guide.md
        module.yaml     # +ir 섹션
      dcf/
        guide.md
        module.yaml     # +ir 섹션
        pipeline.yaml
        prompts/
        schemas/
        scripts/
      risk_transmission/
        guide.md
        module.yaml     # +ir 섹션
```

## 변경 항목

### 1. 모듈 디렉터리 이동

`domain/ceo/`, `domain/dcf/`, `domain/risk_transmission/` → `domain/knowledge/modules/`로 이동
`domain/index.yaml` → `domain/knowledge/index.yaml`로 이동

**수정 파일:**
- `valuator/domain/loader.py` — `self._root` 기본값을 `Path(__file__).parent / "knowledge"` 계열로 변경. 모듈 탐색 경로: `self._root / "modules" / module_id / "module.yaml"` (또는 기존 `_root / module_id`와 호환 유지)

### 2. financial.py — 재무 어휘 추출

`valuator/tools/yfinance_tool.py`에서 하드코딩된 필드명과 비율 공식을 추출한다.

```python
# domain/knowledge/financial.py
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class StatementField:
    canonical: str                # "total_assets"
    aliases: tuple[str, ...]      # ("Total Assets", "Total Assets Net Minority Interest", ...)
    statement: str                # "balance_sheet" | "income" | "cash_flow"

# 재무제표 필드 레지스트리
STATEMENT_FIELDS: tuple[StatementField, ...] = (
    StatementField("total_assets", ("Total Assets", "Total Assets Net Minority Interest", "Total Assets USD"), "balance_sheet"),
    StatementField("total_liabilities", ("Total Liabilities Net Minority Interest", "Total Liabilities", "Total Liabilities & Stockholders' Equity"), "balance_sheet"),
    StatementField("total_equity", ("Stockholders Equity", "Total Stockholder Equity", "Total Equity Gross Minority Interest", "Total Equity Net Minority Interest"), "balance_sheet"),
    StatementField("current_assets", ("Total Current Assets", "Current Assets", "Total Current Assets USD"), "balance_sheet"),
    StatementField("current_liabilities", ("Total Current Liabilities", "Current Liabilities", "Total Current Liabilities USD"), "balance_sheet"),
    StatementField("operating_income", ("Operating Income", "Operating Income or Loss"), "income"),
    StatementField("interest_expense", ("Interest Expense", "Interest Expense and Debt", "Interest Expense, Net"), "income"),
    StatementField("operating_cash_flow", ("Total Cash From Operating Activities", "Cash Flow From Continuing Operating Activities"), "cash_flow"),
    StatementField("capex", ("Capital Expenditures", "Capital Expenditure"), "cash_flow"),
)

@dataclass(frozen=True, slots=True)
class DerivedMetric:
    name: str           # "debt_to_equity"
    numerator: str      # "total_liabilities"
    denominator: str    # "total_equity"
    abs_denominator: bool = False

@dataclass(frozen=True, slots=True)
class DerivedDifference:
    name: str           # "free_cash_flow"
    minuend: str        # "operating_cash_flow"
    subtrahend: str     # "capex"

DERIVED_RATIOS: tuple[DerivedMetric, ...] = (
    DerivedMetric("debt_to_equity", "total_liabilities", "total_equity"),
    DerivedMetric("current_ratio", "current_assets", "current_liabilities"),
    DerivedMetric("interest_coverage", "operating_income", "interest_expense", abs_denominator=True),
)

DERIVED_DIFFERENCES: tuple[DerivedDifference, ...] = (
    DerivedDifference("free_cash_flow", "operating_cash_flow", "capex"),
)

# 벤더 info 키 (yfinance t.info에서 가져오는 밸류에이션 좌표)
VALUATION_INFO_KEYS: tuple[tuple[str, str], ...] = (
    ("market_cap", "marketCap"),
    ("current_price", "currentPrice"),
    ("trailing_pe", "trailingPE"),
    ("forward_pe", "forwardPE"),
    ("price_to_book", "priceToBook"),
    ("enterprise_value", "enterpriseValue"),
    ("currency", "currency"),
)
```

**수정 파일:**
- `valuator/tools/yfinance_tool.py` — 하드코딩된 `pick()` 호출의 row 튜플들을 `STATEMENT_FIELDS`에서 참조. 비율 계산을 `DERIVED_RATIOS`/`DERIVED_DIFFERENCES`로. `info.get()` 호출을 `VALUATION_INFO_KEYS`로.

### 3. IR 추출 선언화

각 모듈의 `module.yaml`에 `ir` 섹션을 추가하고, `ir.py`를 제네릭 프로젝터로 재작성한다.

**module.yaml ir 섹션 예시 (dcf):**
```yaml
ir:
  summary_path: findings
  key_values:
    enterprise_value:
      path: calculation.output.enterprise_value
      format: "{:.2f}"
    pv_explicit:
      path: calculation.output.pv_explicit
      format: "{:.2f}"
    terminal_value:
      path: calculation.output.terminal_value
      format: "{:.2f}"
    terminal_pv:
      path: calculation.output.terminal_pv
      format: "{:.2f}"
  payload_paths:
    company_name: company_name
    assumptions: assumptions
    dcf: calculation.output
```

**module.yaml ir 섹션 예시 (ceo):**
```yaml
ir:
  summary_path: findings
  key_values:
    subject:
      path: corp
      format: "{}"
      default: "CEO / Leadership"
  payload_paths:
    corp: corp
    findings: findings
```

**수정 파일:**
- `valuator/domain/types.py`:
  - `IrFieldSpec`, `IrConfig` Pydantic 모델 추가
  - `DomainModule`에 `ir_config: IrConfig | None = None` 필드 추가
  - `DcfSummary`, `CeoSummary`, `RiskTransmissionItem`, `RiskTransmissionSummary` 제거 (선언적 ir로 대체)
- `valuator/domain/loader.py`: `_build_module()`에서 `ir` 섹션 파싱 → `IrConfig`
- `valuator/domain/ir.py`: 하드코딩된 `_dcf_artifact_fields`/`_ceo_artifact_fields` 제거. `build_domain_artifact_fields()`가 `DomainModule.ir_config`를 받아 제네릭 추출. dot-path로 nested dict 탐색.

### 4. 소비자 갱신

- `valuator/core/executor/service.py`: `build_domain_artifact_fields` 호출 시 `DomainModule`(또는 `ir_config`)을 추가 전달
- `valuator/domain/__init__.py`: `DcfSummary`, `CeoSummary` 등 제거. `IrConfig` 추가. lazy export 경로 갱신
- `tests/test_tree_plan_and_aggregation.py`: `build_domain_artifact_fields` 호출 시그니처 갱신

### 5. knowledge/__init__.py

```python
# domain/knowledge/__init__.py
from pathlib import Path

KNOWLEDGE_ROOT = Path(__file__).resolve().parent
MODULES_ROOT = KNOWLEDGE_ROOT / "modules"
INDEX_PATH = KNOWLEDGE_ROOT / "index.yaml"
```

`DomainLoader`가 이 경로를 기본값으로 사용.

## 경계 정의

| 영역 | 역할 | 위치 |
|------|------|------|
| **지식** | 분석 콘텐츠, 재무 어휘, IR 추출 규칙 | `domain/knowledge/` |
| **인프라** | 로더, 라우터, 쿼리 분석, 타입 | `domain/{loader,router,query*,types}.py` |
| **참조 데이터 경계** | 회사 식별 + 시장 구조 | `domain/company.py` (유지) |
| **도구 경계** | 외부 API 호출 + 응답 변환 | `tools/{yfinance,sec,web_search}_tool.py` |

## 실행 순서

1. `domain/knowledge/` 패키지 생성 + `__init__.py`
2. 모듈 디렉터리 + `index.yaml` 이동
3. `financial.py` 작성
4. `types.py`에 `IrConfig` 추가 + 모듈별 Summary 타입 제거
5. 각 `module.yaml`에 `ir` 섹션 추가
6. `loader.py` 경로 + ir 파싱 갱신
7. `ir.py` 제네릭 프로젝터로 재작성
8. `yfinance_tool.py`에서 `financial.py` 참조
9. `executor/service.py` 시그니처 갱신
10. `domain/__init__.py` export 갱신
11. 테스트 갱신 + 실행

## 검증

```bash
# 전체 테스트
python -m pytest tests/

# 특히 IR 관련 테스트
python -m pytest tests/test_tree_plan_and_aggregation.py -v

# 린트
ruff check .
ruff format .

# DomainLoader가 새 경로에서 정상 로드하는지 확인
python -c "from valuator.domain import DomainLoader; idx, mods = DomainLoader().load(); print(list(mods.keys()))"
```
