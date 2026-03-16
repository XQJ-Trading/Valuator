# ADR-001: Domain Knowledge → guide.md 통합 + 통합 DomainTool

**Status**: Accepted
**Date**: 2026-03-16

---

## Context

도메인 지식이 두 곳에 산재:
1. `domain/*.yaml`의 `prompt_fragment` — aggregator/planner 용 압축 가이드 (2-3줄)
2. `tools/domain_prompts.py` — tool 실행 시 LLM system prompt (상세 방법론)

동일한 도메인 지식이 두 형태로 존재하고, 수정 시 양쪽을 동기화해야 한다.

**목표**: 도메인별 `guide.md`로 단일화. 비개발자가 파일만으로 에이전트 행동 통제.

- 단순 도메인: `module.yaml` + `guide.md` (Python 0줄)
- 복잡 도메인(multi-stage): + `pipeline.yaml` + `prompts/` + `scripts/`

---

## 1. 도메인별 변경 범위

| 도메인 | 현재 domain_tools | 변경 | 근거 |
|--------|------------------|------|------|
| ceo | `ceo_analysis_tool` | → `domain_tool` (simple) | LLM 1회 호출, guide.md가 system prompt |
| dcf | `dcf_pipeline_tool` | → `domain_tool` (pipeline) | 5-stage 파이프라인, pipeline.yaml로 선언 |
| balance_sheet | `[]` (없음) | 변경 없음 | MODULE task 없음, leaf task만 사용 |
| risk_transmission | `sec_tool` | 변경 없음 | sec_tool 직접 호출 유지 |

4개 도메인 모두 서브디렉토리 + guide.md 구조로 이동하되, `domain_tools`는 ceo/dcf만 변경.

---

## 2. 디렉토리 구조

```
domain/
├── index.yaml                  (변경 없음)
├── ceo/
│   ├── module.yaml
│   └── guide.md                ← domain_prompts.ceo_analysis_system + ceo.yaml prompt_fragment 통합
├── dcf/
│   ├── module.yaml
│   ├── guide.md                ← dcf.yaml prompt_fragment 확장
│   ├── pipeline.yaml           ← 5-stage 파이프라인 + result_mapping
│   ├── prompts/
│   │   ├── create_form.md      ← domain_prompts.create_dcf_form_system
│   │   ├── fill_form.md        ← domain_prompts.fill_dcf_form_system
│   │   └── calculate.md        ← domain_prompts.calculate_dcf_system
│   ├── schemas/
│   │   └── assumptions.json    ← _extract_assumptions의 response_json_schema
│   └── scripts/
│       └── dcf_calculation.py  ← dcf_model._DCF_CALCULATION_RUNTIME (217행 그대로)
├── balance_sheet/
│   ├── module.yaml
│   └── guide.md
└── risk_transmission/
    ├── module.yaml
    └── guide.md
```

---

## 3. guide.md의 이중 역할과 흐름 분리

guide.md는 loader가 읽어 `DomainModule.prompt_fragment`에 저장. 이후 두 경로로 흐른다:

| 소비자 | 사용하는 필드 | 용도 |
|--------|-------------|------|
| **DomainTool** (execution) | `prompt_fragment` (guide.md 전문) | LLM system prompt |
| **Aggregator** | `prompt_fragment` (guide.md 전문) | `[DOMAIN_GUIDANCE]` 섹션 |
| **Planner** | `description` (1줄 요약) | `_domain_context_block()` tool 선택 컨텍스트 |

**개선**: 현재 planner도 `prompt_fragment`를 사용하는데, guide.md가 30-50줄로 길어지면 planner context가 비대해짐.
→ `_domain_context_block()`에서 `prompt_fragment` 대신 `description`을 사용하도록 변경. planner는 이미 `tools`, `report_requirement`도 받으므로 description만으로 충분.

```python
# planner/service.py _domain_context_block() 변경
# 기존: f"  - prompt_fragment={module.prompt_fragment}"
# 변경: f"  - description={module.description}"
```

---

## 4. DomainTool 설계

### 4-1. 경계 정의와 도메인 타입

DomainTool.execute()는 경계다 — executor로부터 raw kwargs를 받아 도메인 타입으로 변환한다.
`_execute_stage()`도 경계다 — LLM API/코드 실행(외부 I/O)을 호출하고 결과를 도메인 타입으로 변환한다.

경계가 생성하는 도메인 타입:

```python
# domain/types.py

@dataclass(slots=True)
class StageOutput:
    """Pipeline stage 실행 결과. _execute_stage(경계)에서 생성."""
    raw: Any      # typed value: str (llm), dict (llm_json/code_execute)
    text: str     # 템플릿 치환용 string 표현


class PipelineStage(BaseModel):
    """pipeline.yaml의 단일 stage. Loader(경계)가 파일 참조를 콘텐츠로 해석 완료."""
    id: str
    action: Literal["llm", "llm_json", "code_execute"]
    user_prompt: str = ""
    system_prompt_content: str = ""
    output_schema_content: dict[str, Any] | None = None
    code_content: str = ""
    inject_vars: dict[str, str] = Field(default_factory=dict)  # var_name → stage_id
    output_key: str = ""

class PipelineConfig(BaseModel):
    """pipeline.yaml 전체. Loader(경계)에서 Pydantic 변환 완료."""
    stages: list[PipelineStage]
    result_mapping: dict[str, str] = Field(default_factory=dict)  # key → 템플릿 문자열
```

`result_mapping`은 `dict[str, str]`로 유지한다. `{stages.xxx}` 직접 참조와 `{corp}` 같은 builtin 참조를 구분하는 건 `_build_result`의 단일 regex — 이 분기를 제거하기 위해 `StageRef`/`BuiltinRef` 타입을 도입하면 타입 2개 + union + loader 파싱 + pattern matching이 추가되어 분기보다 복잡해진다.

Loader(경계)가 pipeline.yaml → `PipelineConfig`로 변환하면서:
1. `inject_vars` 값의 stage_id 유효성 검증
2. `result_mapping` 값의 stage 참조 유효성 검증
3. 파일 참조(`system_prompt_file` 등) → 콘텐츠 인라인 (`_content` 키)

경계를 통과한 후, DomainTool은 도메인 타입(`PipelineConfig`, `StageOutput`)으로 동작한다.

### 4-2. Stage output — 경계에서 StageOutput 생성

`_execute_stage()`는 LLM API/코드 실행의 경계. 결과를 StageOutput으로 변환:

| action | raw | text |
|--------|-----|------|
| `llm` | `str` (LLM 텍스트) | 동일 |
| `llm_json` | `dict` (Python dict) | `json.dumps(dict)` |
| `code_execute` | `dict` `{"output": stdout}` | stdout string |

```python
# _execute_stage 내부 (경계):
# llm
return StageOutput(raw=text, text=text)
# llm_json
return StageOutput(raw=data, text=json.dumps(data, ensure_ascii=False))
# code_execute
return StageOutput(raw={"output": stdout}, text=stdout)
```

경계 이후 코드는 `output.text`(문자열)와 `output.raw`(원본 타입)만 사용. isinstance 불필요.

### 4-3. 템플릿 치환 — 단일 pass

`user_prompt`, `system_prompt` 내의 `{corp}`, `{stages.xxx}` 등을 치환한다.

```python
# WHY regex: 텍스트 보간(text interpolation)이며, 포맷 기반 분기가 아닌 균일 치환.
# str.format()은 YAML 내 literal braces와 충돌하므로 사용 불가.
_PLACEHOLDER_RE = re.compile(r"\{(stages\.(\w+)|corp|company_name|context|today)\}")

def _resolve_template(self, template: str, outputs: dict[str, StageOutput], *, corp: str, context: str) -> str:
    builtins = {
        "corp": corp,
        "company_name": corp,
        "context": context,
        "today": datetime.utcnow().date().isoformat(),
    }
    def _replacer(match: re.Match) -> str:
        full_key = match.group(1)
        stage_id = match.group(2)
        if stage_id is not None:
            return outputs[stage_id].text  # StageOutput.text — isinstance 없음
        return builtins.get(full_key, match.group(0))
    return _PLACEHOLDER_RE.sub(_replacer, template)
```

- 단일 pass → stage output에 `{corp}`가 있어도 2차 치환 불가능
- `outputs[stage_id].text` — 타입이 직렬화를 보증하므로 isinstance/json.dumps 불필요
- 알 수 없는 placeholder는 원본 유지

### 4-4. inject_vars — stage output의 Python 리터럴 주입

inject_vars는 `{var_name: stage_id}` 매핑. Loader(경계)가 stage_id 유효성을 검증 완료.

```python
for var_name, stage_id in stage.inject_vars.items():
    value = outputs[stage_id].raw  # dict (from llm_json) or str
    inject_lines.append(f"{var_name} = {repr(value)}")
```

- `repr()`: Python 리터럴 생성 (`True/False/None` 안전, `json.dumps`의 `true/false/null` 문제 없음)
- 경계(loader)가 stage_id를 검증했으므로 KeyError는 프로그래밍 오류 → fail fast
- try/except 없음, json.loads 없음

### 4-5. result_mapping — 템플릿 문자열로 result dict 조립

`result_mapping`은 `dict[str, str]` — 값은 `_resolve_template`과 동일한 템플릿 문자열.
직접 stage 참조(`{stages.xxx}` 단독)인 경우 `.raw`(typed output)를 그대로 전달해야 ir.py 호환이 유지된다.

```python
# WHY regex: _resolve_template과 동일한 텍스트 보간. 직접 stage 참조를 식별하여 typed output 보존.
_STAGE_DIRECT_RE = re.compile(r"^\{stages\.(\w+)\}$")

def _build_result(
    self,
    mapping: dict[str, str],
    outputs: dict[str, StageOutput],
    *,
    corp: str,
    context: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, template in mapping.items():
        m = _STAGE_DIRECT_RE.match(template.strip())
        if m:
            result[key] = outputs[m.group(1)].raw  # typed output 그대로 (dict/str)
        else:
            result[key] = self._resolve_template(template, outputs, corp=corp, context=context)
    return result
```

- `_STAGE_DIRECT_RE`는 `_PLACEHOLDER_RE`와 동일한 텍스트 보간 범주. 이 단일 분기를 제거하기 위해 `StageRef`/`BuiltinRef` 타입을 도입하면 오히려 복잡도가 증가한다.
- `outputs[...].raw` → dict는 dict로, str은 str로 전달
- **ir.py 코드 변경 0줄**

`result_mapping`이 없는 simple mode는 기존대로 `{"corp": corp, "findings": report}` 반환.

pipeline.yaml 선언:
```yaml
result_mapping:
  company_name: "{corp}"
  form: "{stages.create_form}"
  filled_form: "{stages.fill_form}"
  assumptions: "{stages.extract_assumptions}"   # → outputs[...].raw (dict)
  calculation: "{stages.calculate}"             # → outputs[...].raw ({"output": str})
  findings: "{stages.summarize}"                # → outputs[...].raw (str)
```

### 4-6. execute() — 경계에서 kwargs → 명시적 인자

```python
async def execute(self, **kwargs) -> ToolResult:
    # 경계: raw kwargs → 명시적 인자 추출. normalize는 여기서 1회만.
    corp = _extract_corp(kwargs)
    context = str(kwargs.get("context") or "").strip()
    domain_id = str(kwargs.get("domain_id") or "").strip()
    pipeline_config: PipelineConfig | None = kwargs.get("pipeline_config")

    if pipeline_config is not None:
        return await self._run_pipeline(corp, context, domain_id, pipeline_config)

    domain_guide = str(kwargs.get("domain_guide") or "").strip()
    return await self._run_simple(corp, context, domain_id, domain_guide)
```

- kwargs 추출/정규화는 execute()(경계)에서 1회만 수행
- `_run_simple`, `_run_pipeline`은 이미 변환된 값만 받음 — 내부 normalize 없음
- pipeline_config 분기: executor(상류 경계)가 module의 pipeline 유무를 결정하여 주입

### 4-7. _run_pipeline 전체 흐름

```
execute(**kwargs)                    ← 경계: kwargs normalize
  → pipeline_config is not None
  → _run_pipeline(corp, context, domain_id, pipeline_config)
      → for stage in pipeline_config.stages:
          _execute_stage(stage, outputs, ...)  ← 경계: LLM/코드 실행
            llm      → StageOutput(raw=str, text=str)
            llm_json → StageOutput(raw=dict, text=json_str)
            code_execute → StageOutput(raw={"output": stdout}, text=stdout)
      → _build_result(pipeline_config.result_mapping, outputs, ...)
          "{stages.xxx}" 단독 템플릿 → output.raw (typed 그대로)
          그 외 템플릿 → _resolve_template(template, outputs, ...)
      → ToolResult(result=result_dict, metadata={"domain": domain_id})
```

### 4-8. _run_simple

```python
async def _run_simple(self, corp: str, context: str, domain_id: str, domain_guide: str) -> ToolResult:
    prompt = f"[Company Name]\n{corp}\n\n[Context]\n{context or '(none)'}\n"
    report = await self.client.generate(
        prompt=prompt,
        system_prompt=domain_guide,
        trace_method="domain_tool.simple",
    )
    return ToolResult(
        success=True,
        result={"corp": corp, "findings": report.strip()},
        metadata={"tool_type": "domain", "domain": domain_id},
    )
```

- 명시적 인자만 받음. kwargs 파싱/normalize 없음 (execute 경계에서 완료).

---

## 5. pipeline.yaml 스펙

### 5-1. Stage 액션 타입

| action | 입력 | 출력 타입 | 설명 |
|--------|------|----------|------|
| `llm` | `user_prompt`, `system_prompt_file`(선택) | `str` | LLM 텍스트 생성 |
| `llm_json` | `user_prompt`, `output_schema_file` | `dict` | LLM JSON 생성 → Python dict |
| `code_execute` | `code_file`, `inject_vars`(선택) | `dict` `{"output": str}` | Python 코드 실행 |

### 5-2. 파일 참조 → Loader에서 콘텐츠 인라인

| YAML 키 | Loader가 추가하는 키 | 타입 |
|---------|---------------------|------|
| `system_prompt_file` | `system_prompt_content` | str |
| `output_schema_file` | `output_schema_content` | dict (JSON parse) |
| `code_file` | `code_content` | str |

DomainTool은 파일 I/O 없이 `_content` 키만 사용. 파일 해석 책임은 loader(경계)에 집중.

### 5-3. Loader의 pipeline 변환 (경계)

Loader는 경계다. pipeline.yaml(외부 입력)을 `PipelineConfig`(도메인 타입)으로 변환한다.

**구조 검증**: `PipelineConfig`, `PipelineStage`가 Pydantic 모델이므로 타입/필수 필드/enum 제약은 `model_validate()` 한 줄로 완료. 수동 isinstance/get/in 검증 없음.

**의미 검증**: Pydantic이 표현할 수 없는 cross-reference(stage_id 존재 여부, inject_vars 참조 유효성)만 Loader가 수행.

```python
_STAGE_REF_RE = re.compile(r"^\{stages\.(\w+)\}$")

def _build_pipeline_config(self, raw: dict[str, Any], *, base_dir: Path) -> PipelineConfig:
    """경계: raw YAML dict → PipelineConfig 도메인 타입으로 변환."""
    # 1. 파일 참조 → 콘텐츠 인라인 (외부 I/O)
    self._resolve_pipeline_files(raw, base_dir=base_dir)

    # 2. Pydantic 변환 — 구조 검증 자동 수행 (타입, 필수 필드, Literal action)
    config = PipelineConfig.model_validate(raw)

    # 3. 의미 검증: cross-reference (Pydantic이 표현 불가)
    stage_ids = {s.id for s in config.stages}
    for stage in config.stages:
        for var_name, stage_id in stage.inject_vars.items():
            if stage_id not in stage_ids:
                raise ValueError(f"inject_vars '{var_name}' references unknown stage '{stage_id}'")
    for key, template in config.result_mapping.items():
        m = _STAGE_REF_RE.match(template.strip())
        if m and m.group(1) not in stage_ids:
            raise ValueError(f"result_mapping '{key}' references unknown stage '{m.group(1)}'")

    return config
```

- Pydantic `model_validate()`가 실패하면 `ValidationError` → fail fast. try/except 감싸지 않음.
- cross-reference 검증의 regex는 경계에서 외부 입력(YAML string)을 파싱하는 용도.

### 5-4. DCF pipeline.yaml

```yaml
stages:
  - id: create_form
    action: llm
    system_prompt_file: prompts/create_form.md
    user_prompt: "Design a spreadsheet-style DCF template for 15 forecast years."
    output_key: form

  - id: fill_form
    action: llm
    system_prompt_file: prompts/fill_form.md
    user_prompt: |
      Fill the DCF form below with researched values.
      If a complex calculation is required, keep it as a math expression.

      [CONTEXT]
      {context}

      [DCF_FORM]
      {stages.create_form}
    output_key: filled_form

  - id: extract_assumptions
    action: llm_json
    user_prompt: |
      Extract normalized DCF assumptions from the filled form.
      Return JSON only with required numeric fields.

      [COMPANY]
      {corp}

      [FILLED_DCF_FORM]
      {stages.fill_form}
    output_schema_file: schemas/assumptions.json
    output_key: assumptions

  - id: calculate
    action: code_execute
    code_file: scripts/dcf_calculation.py
    inject_vars:
      assumptions: "{stages.extract_assumptions}"
    output_key: calculation

  - id: summarize
    action: llm
    system_prompt_file: prompts/calculate.md
    user_prompt: |
      [COMPANY]
      {corp}

      [CONTEXT]
      {context}

      [FILLED_FORM]
      {stages.fill_form}

      [ASSUMPTIONS]
      {stages.extract_assumptions}

      [DCF_CALCULATION_OUTPUT]
      {stages.calculate}
    output_key: findings

result_mapping:
  company_name: "{corp}"
  form: "{stages.create_form}"
  filled_form: "{stages.fill_form}"
  assumptions: "{stages.extract_assumptions}"
  calculation: "{stages.calculate}"
  findings: "{stages.summarize}"
```

---

## 6. ir.py 호환성 계약

### CEO — result 키 매핑

`_ceo_artifact_fields()` 사용 키: `raw_result["corp"]`, `raw_result["findings"]`
DomainTool._run_simple() 반환: `{"corp": corp, "findings": text}` → **동일, 호환 OK**

### DCF — result 키 매핑

`_dcf_artifact_fields()` 사용 키:
- `raw_result["company_name"]` — `result_mapping`의 `company_name: "{corp}"` → string
- `raw_result["findings"]` — `result_mapping`의 `findings: "{stages.summarize}"` → string
- `raw_result["assumptions"]` — `result_mapping`의 `assumptions: "{stages.extract_assumptions}"` → **dict** (llm_json output 그대로)
- `raw_result["calculation"]` — `result_mapping`의 `calculation: "{stages.calculate}"` → **dict** `{"output": stdout}` (code_execute output 그대로)
- `calculation["output"]` → string → `literal_eval()` → DcfSummary

**ir.py 코드 변경 0줄**. result_mapping이 typed output을 직접 전달하므로 타입이 자연스럽게 일치.

---

## 7. 비개발자 Instruction 작성 가이드

### 7-1. 단순 도메인 추가 (예: "competitive_moat")

**작성할 파일 2개:**

`domain/competitive_moat/module.yaml`:
```yaml
id: competitive_moat
name: 경쟁 우위(Moat) 분석
description: 기업의 지속 가능한 경쟁 우위를 Morningstar moat 프레임워크로 평가한다.
tools:
  - domain_tool
  - web_search_tool
  - sec_tool
domain_tools:
  - tool: domain_tool
    enabled: true
prompt_file: guide.md
report_contract:
  - Moat 유형(Network/Intangible/Switching/Cost/Scale)과 근거를 제시한다.
  - Moat 지속 가능성(Stable/Narrowing/Widening)과 3-5년 전망을 제시한다.
  - 투자 관점 결론을 제시한다.
tasks:
  - id: moat_analysis
    name: 경쟁 우위 분석 리포트
depends_on: []
```

`domain/competitive_moat/guide.md`:
```markdown
You are an expert investment-analysis assistant.
Evaluate a public company's sustainable competitive advantages using
the Morningstar moat framework.

Input: Company name

Output: Bulleted list format. Each item at least one paragraph.

## Stage 1: Moat Source Identification
- Network Effects
- Intangible Assets (brands, patents, regulatory licenses)
- Switching Costs
- Cost Advantage
- Efficient Scale

## Stage 2: Moat Durability Assessment
- Historical trend (widened or narrowed over 5-10 years?)
- Competitive threats
- Reinvestment effectiveness

## Stage 3: Integrated Judgment
- Overall moat rating: Wide / Narrow / None
- Moat trend: Stable / Narrowing / Widening
- Investment rationale from moat perspective
```

+ `domain/index.yaml`의 `modules`에 `competitive_moat` 추가.

**Python 코드: 0줄.** 새 도메인의 ir.py handler는 불필요 — default handler가 `findings`를 자동 추출.

### 7-2. 수정 가능/불가 범위

| 비개발자가 수정 가능 | 대상 파일 |
|-------------------|----------|
| 분석 방법론/톤 변경 | `guide.md` |
| 보고서 요구사항 변경 | `module.yaml`의 `report_contract` |
| 도메인 의존성 변경 | `module.yaml`의 `depends_on` |
| DCF 프롬프트 수정 | `prompts/*.md` |
| DCF JSON 스키마 수정 | `schemas/assumptions.json` |
| 새 단순 도메인 추가 | `module.yaml` + `guide.md` 작성 |

| 개발자 필요 | 이유 |
|------------|------|
| 새 pipeline action 타입 | DomainTool 코드 변경 |
| 새 도메인별 ir.py 추출기 | Python 코드 (단, default handler가 있어 대부분 불필요) |
| 새 base tool 추가 | Python 코드 |
| Python 스크립트 작성/수정 | `scripts/*.py` |

### 7-3. Pipeline 도메인 추가 시 진입 장벽

DCF 수준의 multi-stage pipeline을 새로 만드는 경우:
- `module.yaml` + `guide.md`: 접근 가능
- `pipeline.yaml`: action 타입 3가지, `{stages.xxx}` 템플릿 이해 필요 → **기존 DCF 참고하여 복제/수정 가능**
- `prompts/*.md`: 자연어 → 접근 가능
- `schemas/*.json`: JSON Schema → 진입 장벽 있음
- `scripts/*.py`: Python → **개발자 도움 필요**

**결론**: 순수 비개발자가 pipeline을 처음부터 작성하기는 어렵지만, 기존 DCF를 복제하여 프롬프트와 스키마를 수정하는 것은 가능.

---

## 8. 파일별 변경 상세

### 8-1. `domain/types.py`

신규 도메인 타입 추가 (Section 4-1에서 정의):

```python
from dataclasses import dataclass
from typing import Any, Literal

# --- Pipeline 도메인 타입 ---

@dataclass(slots=True)
class StageOutput:
    """Pipeline stage 실행 결과. _execute_stage(경계)에서 생성되는 실행 시점 값."""
    raw: Any      # typed value: str (llm), dict (llm_json/code_execute)
    text: str     # 템플릿 치환용 string 표현


class PipelineStage(BaseModel):
    """pipeline.yaml의 단일 stage 선언. 실행 시에도 그대로 사용되는 불변 설정."""
    id: str
    action: Literal["llm", "llm_json", "code_execute"]
    user_prompt: str = ""
    system_prompt_content: str = ""
    output_schema_content: dict[str, Any] | None = None
    code_content: str = ""
    inject_vars: dict[str, str] = Field(default_factory=dict)
    output_key: str = ""

class PipelineConfig(BaseModel):
    """pipeline.yaml 전체 선언. Loader(경계)에서 Pydantic 변환이 끝난 불변 설정."""
    stages: list[PipelineStage]
    result_mapping: dict[str, str] = Field(default_factory=dict)  # key → 템플릿 문자열
```

DomainModule 변경:

```python
class DomainModule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # ... 기존 필드 ...
    pipeline_config: PipelineConfig | None = None  # dict[str, Any] 가 아닌 도메인 타입
```

### 8-2. `domain/loader.py`

**load()**: 서브디렉토리 우선 탐색

```python
for module_id in index.modules:
    subdir_path = self._root / module_id / "module.yaml"
    flat_path = self._root / f"{module_id}.yaml"
    if subdir_path.is_file():
        module_path = subdir_path
    elif flat_path.is_file():
        module_path = flat_path
    else:
        raise FileNotFoundError(...)
```

**_build_module()**: prompt_file 경로를 `path.parent` 기준으로 해석 + pipeline 로드

```python
# 기존: (self._root / str(prompt_file)).resolve()
# 변경: (path.parent / str(prompt_file)).resolve()

pipeline_path = path.parent / "pipeline.yaml"
if pipeline_path.is_file():
    raw_pipeline = self._read_yaml(pipeline_path)
    # 경계: raw dict → PipelineConfig 도메인 타입 (Section 5-3)
    payload["pipeline_config"] = self._build_pipeline_config(raw_pipeline, base_dir=path.parent)
```

**_resolve_pipeline_files()**: 파일 참조 → 콘텐츠 인라인 (신규)

**_build_pipeline_config()**: raw YAML → `PipelineConfig` Pydantic 변환 + cross-reference 검증 (신규, Section 5-3)

### 8-3. `tools/domain_tool.py` (신규)

핵심 메서드:
- `execute()` → pipeline_config 유무로 dispatch
- `_run_simple()` → guide.md를 system_prompt로 LLM 1회 호출
- `_run_pipeline()` → stages 순차 실행 → `_build_result(result_mapping)` → ToolResult
- `_execute_stage()` → action별 실행 (llm/llm_json/code_execute)
- `_resolve_template()` → 단일 pass regex 치환
- `_build_result()` → result_mapping에 따라 typed output을 result dict에 배치

### 8-4. `tools/specs.py`

```python
# 제거: "ceo_analysis_tool", "dcf_pipeline_tool"
# 추가:
"domain_tool": ToolSpec(
    name="domain_tool",
    optional=("corp", "company_name", "ticker", "query", "context",
              "domain_guide", "domain_id", "pipeline_config"),
    capability="domain analysis (guide-based or pipeline-based)",
    subject_requirement=SubjectRequirement(
        any_of=("company_name", "ticker", "security_code")
    ),
),
```

### 8-5. `core/executor/service.py`

**_TOOL_CLASSES:**
```python
# 제거: "ceo_analysis_tool": CEOAnalysisTool, "dcf_pipeline_tool": DCFPipelineTool
# 추가: "domain_tool": DomainTool
```

**_tool_args_for_task()**: domain_tool에 domain_guide/domain_id/pipeline_config 주입

```python
if task.tool.name == "domain_tool" and self._domain_context and task.domain_id:
    module = self._domain_context.modules.get(task.domain_id)
    if module:
        tool_args["domain_guide"] = module.prompt_fragment
        tool_args["domain_id"] = task.domain_id
        if module.pipeline_config:
            tool_args["pipeline_config"] = module.pipeline_config
```

### 8-6. `core/planner/service.py`

`_domain_context_block()`: `prompt_fragment` → `description` 변경 (1줄)

### 8-7. `tools/balance_sheet_extraction_tool.py`

`domain_prompts.balance_sheet_extraction` 텍스트를 파일 내 상수로 이동.
import 제거.

---

## 9. 삭제 대상

| 파일 | 사유 |
|------|------|
| `tools/ceo_analysis_tool.py` | DomainTool._run_simple()로 대체 |
| `tools/dcf_pipeline_tool.py` | DomainTool._run_pipeline()로 대체 |
| `tools/dcf_model.py` | `domain/dcf/scripts/dcf_calculation.py`로 이동 |
| `tools/domain_prompts.py` | ceo→guide.md, DCF→prompts/*.md, balance_sheet_extraction→tool inline |
| `domain/ceo.yaml` | → `domain/ceo/module.yaml` |
| `domain/dcf.yaml` | → `domain/dcf/module.yaml` |
| `domain/balance_sheet.yaml` | → `domain/balance_sheet/module.yaml` |
| `domain/risk_transmission.yaml` | → `domain/risk_transmission/module.yaml` |

---

## 10. 구현 순서

1. `domain/types.py` — `pipeline_config` 필드 추가
2. 도메인 서브디렉토리 + 파일 생성 (module.yaml, guide.md, pipeline.yaml, prompts, schemas, scripts)
3. `domain/loader.py` — 서브디렉토리 탐색, prompt_file 경로 변경, pipeline 로드/검증/파일 해석
4. `tools/domain_tool.py` — 신규 (typed outputs, regex 템플릿, repr() inject, result_mapping)
5. `tools/specs.py` — tool spec 교체
6. `core/executor/service.py` — _TOOL_CLASSES, _tool_args_for_task 변경
7. `core/planner/service.py` — _domain_context_block description 전환
8. `tools/balance_sheet_extraction_tool.py` — 프롬프트 인라인
9. 기존 파일 삭제
10. import 정리 + ruff check/format

---

## 11. 검증

1. `ruff check . && ruff format .`
2. `python -m pytest tests/` — 특히 `test_semantic_requirements.py` (DomainLoader 직접 사용)
3. Loader: 4개 서브디렉토리에서 module.yaml + guide.md 정상 로드
4. Loader: DCF pipeline.yaml 파일 참조 해석 + 구조 검증
5. Executor: `set(_TOOL_CLASSES) == set(TOOL_SPECS)` 통과
6. ir.py 호환: DomainTool result → _dcf_artifact_fields, _ceo_artifact_fields 경로 정상 동작
