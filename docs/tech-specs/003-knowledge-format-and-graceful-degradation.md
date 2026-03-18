# TS-003: Domain Knowledge Format & Graceful Degradation

**Status**: Draft
**Date**: 2026-03-18
**Depends on**: TS-002 (Adaptive Pipeline & Knowledge Restructure)

---

## 1. Problem

TS-002에서 도입한 domain knowledge module 구조(5파일/모듈)는 파이프라인의 정보 보존 문제를 해결했지만, 두 가지 새로운 문제를 남겼다:

### 1.1 비개발자 편집 장벽

| 현재 | 문제 |
|------|------|
| 5개 파일 (module.yaml, persona.md, rubric.yaml, format.md, contract.yaml) | 인지 부하. "어떤 파일을 편집해야 하지?" |
| 2개 포맷 (YAML + MD) | YAML 구문 학습 필요 (들여쓰기, `- ` 리스트, 따옴표 규칙) |
| rubric.yaml ↔ contract.yaml ID 참조 | 오타 시 조용히 실패. 교차 검증 없음 |
| 코드 데이터 모델 노출 | `aspects:`, `checks:`, `requires:` 같은 필드명이 Pydantic 모델 구조를 반영 |
| 검증/템플릿 없음 | "내 수정이 맞는가?" 확인 불가. 새 모듈 생성 시 기존 모듈 복사 |

### 1.2 모듈 품질 의존도

TS-002의 `RubricAspect`가 파이프라인 4곳(AspectExpander, DomainTool, StructuredExtractor, Contract)을 관통한다.
모듈이 불완전하면 개발자가 만든 파이프라인 기능도 제대로 동작하지 않는다.
개발자가 파이프라인 기능을 테스트하려면 "좋은 모듈"이 필요한데, 모듈은 도메인 전문가가 작성한다.

**근본 원인**: 모듈이 "필수 설정"으로 설계되어 있다.
→ 내용이 많아야 동작 → 포맷이 복잡 → 비개발자 진입장벽 ↑ → 개발자 테스트 장벽 ↑

---

## 2. Architecture: 현재 vs 변경

### 2.1 현재 (TS-002)

```
modules/ceo/
├── module.yaml      # 메타데이터 + 파일 참조 (8줄)
├── persona.md       # LLM 역할 정의 (산문)
├── rubric.yaml      # 분석 관점 [{id, label, description, priority}]
├── format.md        # 출력 형식 규칙 (산문)
└── contract.yaml    # 품질 기준 [{id, text, requires: [aspect_ids]}]
```

**모듈 = 필수 설정**: 5파일 모두 있어야 로드 성공.

### 2.2 변경

```
modules/ceo/
├── module.yaml      # 개발자 영역: id, name, description, depends_on (4줄)
└── knowledge.md     # 도메인 전문가 영역: 가이드 문서 (필수: Persona, Aspects)
```

**모듈 = 선택적 향상제**: Persona + Aspects 1개만 있어도 파이프라인 동작. Checks, Format은 선택.

### 2.3 경계 변경

```
변경 전:
  DomainLoader (boundary)
    ├── _read_yaml(module.yaml)      → 메타데이터
    ├── _read_text(persona.md)       → persona: str
    ├── _load_rubric(rubric.yaml)    → rubric: list[RubricAspect]
    ├── _read_text(format.md)        → format_spec: str
    └── _load_contract(contract.yaml)→ contract: list[AcceptanceCheck]

변경 후:
  DomainLoader (boundary)
    ├── _read_yaml(module.yaml)      → 메타데이터 (id, name, depends_on)
    └── _parse_knowledge_md(knowledge.md)
          ├── ## Persona 섹션     → persona: str
          ├── ## Aspects 섹션     → rubric: list[RubricAspect]
          ├── ## Checks 섹션      → contract: list[AcceptanceCheck]  (선택)
          └── ## Format 섹션      → format_spec: str  (선택)
```

출력 타입 `DomainModule`은 **변경 없음**. 다운스트림 코드 변경 없음.

---

## 3. knowledge.md Format Specification

### 3.1 섹션 구조

| 섹션 | 필수 | 역할 | 없을 때 기본값 |
|------|------|------|----------------|
| `## Persona` | 필수 | LLM에 주입할 분석가 역할 정의 | — (로드 에러) |
| `## Aspects` | 필수 | 분석 관점 정의 (최소 1개) | — (로드 에러) |
| `## Checks` | 선택 | 출력 품질 기준 | 빈 리스트 |
| `## Format` | 선택 | 출력 형식 규칙 | 빈 문자열 |

섹션 순서는 자유. 인식되지 않는 `## ` 섹션은 무시 (향후 확장 가능).

### 3.2 Persona 섹션

```markdown
## Persona

당신은 Philip Fisher, Warren Buffett, Charlie Munger의 철학을 따르는
장기 투자 분석가입니다. CEO와 senior leadership team의 질, 조직 문화,
거버넌스, 자본배분의 일관성을 장기 복리 관점에서 평가하십시오.
홍보성 수사는 배제하고 근거와 투자 의미를 직접 연결하십시오.
```

- `## Persona` 이후 다음 `## ` 헤더까지의 텍스트 전체.
- 그대로 `DomainModule.persona`에 할당. 파싱 없음.

### 3.3 Aspects 섹션

```markdown
## Aspects

### integrity — 성실성·투명성 [HIGH]
주주와의 소통 이력, 회계 투명성, 약속 이행 기록, 실수 인정과 수정 능력

### capital_allocation — 자본배분 역량 [HIGH]
M&A, CAPEX, 주주환원, retained earnings 재투자의 가치 창출 또는 파괴 이력

### governance — 지배구조·이사회 독립성 [MEDIUM]
이사회 구성, 독립성, 보상 구조, 특수관계자 거래, 규제 대응 태도
```

**헤딩 포맷**: `### {id} — {label} [{priority}]`
- `id`: 영문 소문자 + 밑줄. `[a-z][a-z0-9_]*`
- `—` 또는 `-` 모두 허용 (em dash, hyphen)
- `label`: 한글/영문 자유 텍스트
- `priority`: `HIGH`, `MEDIUM`, `LOW` (대소문자 무관)
- 헤딩 이후 다음 `### ` 또는 `## `까지의 텍스트 = `description`

**매핑:**
```
### {id} — {label} [{priority}]  →  RubricAspect(id, label, description, priority)
{body text}                         description = body text
```

### 3.4 Checks 섹션 (선택)

```markdown
## Checks

- **rating_defined**: CEO와 leadership quality rating이 제시되어야 한다.
  → integrity
- **risks_explained**: leadership 관련 핵심 리스크가 정리되어야 한다.
  → governance
- **investment_view_defined**: 장기 투자 관점 결론과 트리거가 제시되어야 한다.
  → capital_allocation, strategic_vision
```

**포맷**: 2줄 구조
- 1줄: `- **{id}**: {text}`
- 2줄: `  → {aspect_id1}, {aspect_id2}, ...` (들여쓰기 + `→` 또는 `>`)

**매핑:**
```
- **{id}**: {text}           →  AcceptanceCheck(id, text, requires)
  → {aspect_id}, ...            requires = [aspect_id, ...]
```

### 3.5 Format 섹션 (선택)

```markdown
## Format

- 불릿 리스트 중심의 한글 마크다운으로 작성한다.
- 각 aspect는 반드시 `### [ASPECT:{aspect_id}] {label}` 헤더 아래에 작성한다.
- high priority aspect는 누락 없이 커버한다.
```

- `## Format` 이후 텍스트 전체.
- 그대로 `DomainModule.format_spec`에 할당. 파싱 없음.

### 3.6 최소 knowledge.md (개발자 테스트용)

```markdown
## Persona
기업 가치 분석가입니다.

## Aspects
### revenue — 매출 분석 [HIGH]
매출 추이, 세그먼트 구성, 성장 동인
```

4줄. Checks/Format 없음 → 시스템 기본값으로 동작.

---

## 4. Parser Design (Loader Boundary)

### 4.1 파싱 알고리즘

```
_parse_knowledge_md(text: str) → (persona, rubric, format_spec, contract)

1. 섹션 분리
   text를 ^## (.+)$ 기준으로 분리.
   결과: dict[section_name_lower, section_body]

2. 필수 섹션 검증
   "persona" ∉ sections → ValueError("knowledge.md에 '## Persona' 섹션이 필요합니다")
   "aspects" ∉ sections → ValueError("knowledge.md에 '## Aspects' 섹션이 필요합니다")

3. Persona 추출
   persona = sections["persona"].strip()

4. Aspects 파싱
   sections["aspects"]에서 ^###\s+([a-z][a-z0-9_]*)\s*[—\-]\s*(.+?)\s*\[(\w+)\]\s*$ 매칭.
   각 매치: id, label, priority 추출.
   매치 사이 텍스트: description.
   매칭 실패한 ### 헤딩 → ValueError("aspect 형식이 올바르지 않습니다: '{line}'\n올바른 형식: ### aspect_id — 라벨 [HIGH]")
   중복 id → ValueError
   aspects 0개 → ValueError("최소 1개의 aspect가 필요합니다")

5. Checks 파싱 (선택)
   "checks" ∉ sections → contract = []
   있으면: ^-\s+\*\*(\w+)\*\*:\s*(.+)$ 로 id, text 추출.
   다음 줄 ^\s*[→>]\s*(.+)$ 로 requires 추출.
   requires의 각 aspect_id가 step 4의 aspect ids에 존재하는지 교차 검증.

6. Format 추출 (선택)
   "format" ∉ sections → format_spec = ""
   있으면: format_spec = sections["format"].strip()
```

### 4.2 Regex 목록 (2개)

```python
ASPECT_HEADING = re.compile(
    r"^###\s+([a-z][a-z0-9_]*)\s*[—\-]\s*(.+?)\s*\[(\w+)\]\s*$",
    re.MULTILINE,
)
CHECK_ITEM = re.compile(
    r"^-\s+\*\*(\w+)\*\*:\s*(.+)$",
    re.MULTILINE,
)
```

### 4.3 에러 메시지 (한글, 예시 포함)

| 상황 | 메시지 |
|------|--------|
| Persona 섹션 없음 | `knowledge.md에 '## Persona' 섹션이 필요합니다.` |
| Aspects 섹션 없음 | `knowledge.md에 '## Aspects' 섹션이 필요합니다.` |
| Aspect 0개 | `'## Aspects' 섹션에 최소 1개의 aspect가 필요합니다. 형식: ### aspect_id — 라벨 [HIGH]` |
| Aspect 헤딩 포맷 | `aspect 형식이 올바르지 않습니다: '{line}'. 올바른 형식: ### my_aspect — 분석 관점 [HIGH]` |
| 중복 aspect id | `aspect id '{id}'가 중복됩니다.` |
| Check requires 미존재 | `check '{check_id}'의 참조 '{bad_id}'가 aspects에 없습니다. 사용 가능: {valid_ids}` |

### 4.4 에러 격리

섹션 단위 독립 파싱. Persona 편집 실수가 Aspects 파싱을 깨뜨리지 않음.
파서는 먼저 모든 섹션을 분리한 후, 각 섹션을 독립적으로 파싱한다.

---

## 5. Graceful Degradation

### 5.1 파이프라인 단계별 동작

코드 탐색 결과, 대부분의 graceful degradation이 **이미 구현되어 있다**:

| 단계 | 코드 위치 | aspects 있음 | aspects 없음 | 현재 상태 |
|------|-----------|-------------|-------------|-----------|
| AspectExpander | `expander.py:27` | high aspect 기준 unit 분해 | `len(high) <= THRESHOLD` → no-op | ✓ 이미 동작 |
| Executor._rubric_text | `service.py:299-301` | aspect 리스트 포맷팅 | 빈 문자열 반환 | ✓ 이미 동작 |
| DomainTool | `domain_tool.py:31-36` | persona 주입 | persona 없으면 에러 | ❌ 수정 필요 |
| DomainTool prompt | `domain_tool.py:42-43` | rubric/format 주입 | `(none)` 대체 | ✓ 이미 동작 |
| Extractor | `extractor.py:176-186` | aspect별 facts 추출 | `_uncategorized`로 수집 | ✓ 이미 동작 |
| Aggregator contract | `service.py:464-481` | check별 검증 | 빈 섹션 반환 | ✓ 이미 동작 |

### 5.2 수정 필요: DomainTool persona 요구사항

**현재** (`domain_tool.py:31-36`):
```python
persona = str(kwargs.get("domain_persona") or "").strip()
guide = str(kwargs.get("domain_guide") or "").strip()
if not persona and not guide:
    return {"error": "'domain_persona' or 'domain_guide' is required"}
```

**변경**: persona가 빈 문자열이면 generic fallback 사용:
```python
system_prompt = persona or guide or "당신은 기업 가치 분석가입니다."
```

knowledge.md에서 Persona는 필수 섹션이므로 실제로 빈 persona가 도달할 일은 없지만,
하위 호환(기존 5파일 모듈에서 persona.md가 빈 경우)과 방어적 설계를 위해 fallback 추가.

### 5.3 동작 매트릭스

| 모듈 수준 | Persona | Aspects | Checks | Format | 결과 |
|-----------|---------|---------|--------|--------|------|
| 최소 | ✓ | 1개 | - | - | 현재 시스템과 동일한 출력 |
| 기본 | ✓ | 3-5개 | - | - | aspect-aware 분석 + 기본 형식 |
| 풍부 | ✓ | 5+개 | ✓ | ✓ | TS-002 완전 구조화 (정보 보존 최대) |

---

## 6. DCF 호환성

DCF 모듈은 knowledge.md 외에 추가 파일이 있다:

```
modules/dcf/
├── module.yaml       # id, name, depends_on: [risk_transmission]
├── knowledge.md      # persona + aspects + checks + format (새로 통합)
├── pipeline.yaml     # 5단계 실행 워크플로우 (DomainLoader 범위 밖)
├── prompts/          # 단계별 시스템 프롬프트 (DomainLoader 범위 밖)
├── schemas/          # JSON 스키마 (DomainLoader 범위 밖)
└── scripts/          # Python 계산 코드 (DomainLoader 범위 밖)
```

- `pipeline.yaml`, `prompts/`, `schemas/`, `scripts/`는 DomainLoader가 로드하지 않음 (별도 실행기가 사용)
- DCF의 persona, rubric, format, contract는 다른 모듈과 동일하게 knowledge.md로 통합 가능
- **변경 없음**: pipeline.yaml 등은 그대로 유지

---

## 7. CLI Tools

### 7.1 validate (`python -m valuator.domain.validate`)

```
$ python -m valuator.domain.validate

✓ ceo          — 5 aspects (2 high, 2 medium, 1 low), 3 checks
✓ dcf          — 6 aspects (3 high, 3 medium), 3 checks
✓ risk_transmission — 5 aspects (3 high, 2 medium), 3 checks

모든 모듈 로드 성공. 교차 참조 검증 통과.
```

에러 시:
```
$ python -m valuator.domain.validate

✗ ceo  knowledge.md
  check 'rating_defined'의 참조 'intgrity'가 aspects에 없습니다.
  사용 가능한 aspect ids: integrity, capital_allocation, governance, strategic_vision, talent_culture
```

**구현**: `DomainLoader.load()` 호출 + 예외 catch + 한글 포맷팅.
새 파일: `valuator/domain/validate.py` (~40줄)

### 7.2 scaffold (`python -m valuator.domain.scaffold <module_id>`)

```
$ python -m valuator.domain.scaffold esg

생성됨:
  modules/esg/module.yaml
  modules/esg/knowledge.md

index.yaml에 'esg' 추가됨.
검증 통과 ✓
```

생성되는 knowledge.md 템플릿:
```markdown
<!-- 이 파일은 AI 분석가에게 보내는 가이드 문서입니다. -->
<!-- 각 섹션을 편집하여 분석 방식을 설정하세요. -->

## Persona

당신은 기업 가치 분석 전문가입니다.
[여기에 분석가의 역할과 관점을 작성하세요]

## Aspects

<!-- 분석 관점을 추가하세요. 형식: ### id — 라벨 [HIGH/MEDIUM/LOW] -->

### example_aspect — 예시 관점 [HIGH]
이 관점에서 분석할 내용을 설명합니다.

## Checks

<!-- (선택) 출력에 반드시 포함되어야 할 품질 기준. 없으면 이 섹션을 삭제하세요. -->

- **example_check**: 예시 품질 기준 설명
  → example_aspect

## Format

<!-- (선택) 출력 형식 규칙. 없으면 이 섹션을 삭제하세요. -->

- 한글 마크다운으로 작성한다.
- 각 aspect는 `### [ASPECT:{aspect_id}] {label}` 헤더로 작성한다.
```

새 파일: `valuator/domain/scaffold.py` (~60줄)

---

## 8. Loader 변경 상세

### 8.1 _build_module 로드 우선순위

```python
def _build_module(self, data: dict, *, path: Path) -> DomainModule:
    base_dir = path.parent
    knowledge_path = base_dir / (self._ref(data, "knowledge") or "knowledge.md")

    if knowledge_path.is_file():
        # 새 방식: knowledge.md에서 전부 추출
        persona, rubric, format_spec, contract = self._parse_knowledge_md(
            knowledge_path.read_text(encoding="utf-8")
        )
    else:
        # 기존 방식: 개별 파일에서 로드 (하위 호환)
        persona = self._read_text(base_dir / (self._ref(data, "persona", "persona_file") or "persona.md"))
        rubric = self._load_rubric(...)
        format_spec = self._read_text(...)
        contract = self._load_contract(...)

    # 교차 참조 검증 (양쪽 경로 모두)
    self._validate_contract_references(rubric, contract, path=path)

    return DomainModule(
        id=..., name=..., description=...,
        persona=persona, rubric=rubric,
        format_spec=format_spec, contract=contract,
        depends_on=...,
    )
```

### 8.2 _validate_module_keys 확장

```python
allowed = {
    "id", "name", "description",
    "persona", "persona_file",
    "rubric", "rubric_file",
    "format", "format_file",
    "contract", "contract_file",
    "knowledge",          # ← 추가
    "depends_on",
}
```

### 8.3 _validate_contract_references (신규)

```python
def _validate_contract_references(
    self, rubric: list[RubricAspect], contract: list[AcceptanceCheck], *, path: Path,
) -> None:
    aspect_ids = {a.id for a in rubric}
    for check in contract:
        for ref in check.requires:
            if ref not in aspect_ids:
                raise ValueError(
                    f"check '{check.id}'의 참조 '{ref}'가 aspects에 없습니다. "
                    f"사용 가능: {', '.join(sorted(aspect_ids))}"
                )
```

이 검증은 knowledge.md와 기존 5파일 **양쪽 경로 모두**에 적용.
현재 로더에 없는 검증으로, 기존 모듈에서도 즉시 가치를 제공한다.

---

## 9. Migration

### 9.1 CEO 모듈 마이그레이션 예시

**변경 전** (5파일):
```
modules/ceo/
├── module.yaml       (8줄: id, name, description, persona, rubric, format, contract, depends_on)
├── persona.md        (1단락)
├── rubric.yaml       (22줄: aspects 5개)
├── format.md         (7줄)
└── contract.yaml     (15줄: checks 3개)
```

**변경 후** (2파일):
```
modules/ceo/
├── module.yaml       (4줄: id, name, description, depends_on)
└── knowledge.md      (~40줄: persona + aspects 5개 + checks 3개 + format)
```

### 9.2 module.yaml 변경

```yaml
# 변경 전
id: ceo
name: CEO·리더십 분석
description: 장기 투자 관점에서 CEO·경영진 품질, 조직 문화, 거버넌스를 평가한다.
persona: persona.md
rubric: rubric.yaml
format: format.md
contract: contract.yaml
depends_on: []

# 변경 후
id: ceo
name: CEO·리더십 분석
description: 장기 투자 관점에서 CEO·경영진 품질, 조직 문화, 거버넌스를 평가한다.
depends_on: []
```

파일 참조 제거. knowledge.md는 컨벤션 기반 탐색 (명시적 `knowledge: knowledge.md` 지정도 가능).

### 9.3 마이그레이션 대상

| 모듈 | persona.md → | rubric.yaml → | format.md → | contract.yaml → | 추가 파일 |
|------|-------------|---------------|-------------|-----------------|-----------|
| ceo | knowledge.md | knowledge.md | knowledge.md | knowledge.md | — |
| dcf | knowledge.md | knowledge.md | knowledge.md | knowledge.md | pipeline.yaml, prompts/, schemas/, scripts/ 유지 |
| risk_transmission | knowledge.md | knowledge.md | knowledge.md | knowledge.md | — |

---

## 10. Concrete Walkthrough

### 10.1 비개발자가 CEO 모듈에 "ESG" aspect를 추가하는 경우

**1. knowledge.md 열기** (GitHub 웹에디터 또는 로컬 에디터)

**2. `## Aspects` 섹션에 추가:**
```markdown
### esg — ESG·지속가능성 [MEDIUM]
환경·사회·거버넌스 리스크, ESG 등급 변화, 지속가능성 보고서 품질
```

**3. (선택) `## Checks`에 추가:**
```markdown
- **esg_covered**: ESG 관련 리스크와 기회가 정리되어야 한다.
  → esg
```

**4. 검증:**
```
$ python -m valuator.domain.validate
✓ ceo — 6 aspects (2 high, 3 medium, 1 low), 4 checks
```

**5. PR 제출.** 코드 변경 0줄.

### 10.2 개발자가 새 파이프라인 기능을 테스트하는 경우

```python
# test_new_feature.py
def test_expansion_with_minimal_module(tmp_path):
    # 최소 모듈 생성
    (tmp_path / "module.yaml").write_text("id: test\nname: Test\ndepends_on: []")
    (tmp_path / "knowledge.md").write_text(
        "## Persona\nAnalyst.\n\n## Aspects\n### rev — Revenue [HIGH]\nRevenue analysis"
    )

    loader = DomainLoader(root=tmp_path)
    index, modules = loader.load()
    # → 1 module, 1 aspect, 0 checks, empty format
    # 파이프라인 기능 테스트 가능
```

---

## 11. Implementation Roadmap

### Phase 1: 교차 참조 검증 + DomainTool fallback

즉시 가치를 제공하는 변경. knowledge.md 도입 전에도 적용 가능.

| 파일 | 변경 |
|------|------|
| [valuator/domain/loader.py](valuator/domain/loader.py) | `_validate_contract_references()` 추가. `_build_module()` 끝에서 호출 |
| [valuator/tools/domain_tool.py](valuator/tools/domain_tool.py) | persona 빈 문자열 시 generic fallback |
| [tests/test_domain_loader.py](tests/test_domain_loader.py) | 교차 참조 검증 테스트 (일치/불일치) |

### Phase 2: knowledge.md 파서

| 파일 | 변경 |
|------|------|
| [valuator/domain/loader.py](valuator/domain/loader.py) | `_parse_knowledge_md()`, `_parse_aspects_md()`, `_parse_checks_md()` 추가 |
| [valuator/domain/loader.py](valuator/domain/loader.py) | `_build_module()`에 knowledge.md 분기 추가 |
| [valuator/domain/loader.py](valuator/domain/loader.py) | `_validate_module_keys()` allowed set에 `knowledge` 추가 |
| [tests/test_domain_loader.py](tests/test_domain_loader.py) | knowledge.md 파싱 테스트 (정상, 최소, 선택 섹션 누락, 포맷 에러, 교차 참조) |

### Phase 3: 기존 모듈 마이그레이션

| 파일 | 변경 |
|------|------|
| `modules/ceo/knowledge.md` | 신규 — persona+rubric+format+contract 통합 |
| `modules/dcf/knowledge.md` | 신규 — 동일 |
| `modules/risk_transmission/knowledge.md` | 신규 — 동일 |
| `modules/*/module.yaml` | 간소화 (파일 참조 제거) |
| `modules/*/{persona,format}.md` | 삭제 |
| `modules/*/{rubric,contract}.yaml` | 삭제 |

### Phase 4: CLI 도구

| 파일 | 변경 |
|------|------|
| [valuator/domain/validate.py](valuator/domain/validate.py) | 신규 — CLI 검증 |
| [valuator/domain/scaffold.py](valuator/domain/scaffold.py) | 신규 — 스캐폴드 + 템플릿 |

### Phase 5: 하위 호환 테스트

| 파일 | 변경 |
|------|------|
| [tests/test_domain_loader.py](tests/test_domain_loader.py) | 기존 5파일 모듈 로드 테스트 (하위 호환 확인) |
| [tests/test_domain_loader.py](tests/test_domain_loader.py) | DCF 혼합 모듈 테스트 (knowledge.md + pipeline.yaml) |

---

## 12. Decisions

| 결정 | 선택 | 근거 |
|------|------|------|
| 모듈 포맷 | **knowledge.md** (단일 마크다운) | 비개발자가 "문서 편집" 멘탈 모델로 접근. YAML 노출 제거. GitHub 미리보기 가능 |
| Checks/Format | **선택 섹션** | 최소 모듈로 시작 가능 → 진입장벽 ↓. graceful degradation과 맞물림 |
| 파서 방식 | **커스텀 (regex 2개)** | 의존성 추가 불필요. `python-frontmatter` 등 불필요. 파서 ~60줄 |
| 하위 호환 | **기존 5파일도 계속 로드** | `_build_module()`에서 knowledge.md 우선 탐색, 없으면 기존 경로 |
| 교차 참조 검증 | **양쪽 경로 모두 적용** | 기존 5파일 모듈에서도 즉시 가치 제공 |
| DomainTool persona | **generic fallback 추가** | 빈 persona 시 `"당신은 기업 가치 분석가입니다."` |
| module.yaml description | **유지** | index.yaml의 module_summaries 폴백용. knowledge.md에 중복하지 않음 |

---

## 13. Risks

| 리스크 | 영향 | 완화 |
|--------|------|------|
| 마크다운 헤딩 컨벤션 미준수 | aspect 파싱 실패 | scaffold가 올바른 형식 생성. validate가 형식 오류 + 올바른 예시 즉시 표시 |
| `—`(em dash) 입력 어려움 | 헤딩 포맷 실패 | `-`(hyphen)도 허용. regex에서 `[—\-]`로 처리 |
| 섹션명 오타 (`## Pesona`) | 필수 섹션 누락 에러 | 명시적 에러: `'## Persona' 섹션이 필요합니다` |
| 코드 블록 안에 `## ` 포함 | 잘못된 섹션 분리 | 파서가 fenced code block (```) 내부의 `## `는 무시 |
| 기존 5파일 모듈 호환 깨짐 | 마이그레이션 강제 | knowledge.md 없으면 기존 경로 사용. 양립 가능 |

---

## 14. 구현 후 파일 구조 전후 비교

```
변경 전 (TS-002):                    변경 후 (TS-003):

modules/ceo/                         modules/ceo/
├── module.yaml     (8줄)            ├── module.yaml     (4줄)
├── persona.md                       └── knowledge.md    (~40줄)
├── rubric.yaml
├── format.md
└── contract.yaml

modules/dcf/                         modules/dcf/
├── module.yaml     (10줄)           ├── module.yaml     (4줄)
├── persona.md                       ├── knowledge.md    (~50줄)
├── rubric.yaml                      ├── pipeline.yaml   (유지)
├── format.md                        ├── prompts/        (유지)
├── contract.yaml                    ├── schemas/        (유지)
├── pipeline.yaml                    └── scripts/        (유지)
├── prompts/
├── schemas/
└── scripts/

valuator/domain/                     valuator/domain/
├── loader.py                        ├── loader.py       (수정: 파서 + 검증)
├── types.py                         ├── types.py        (변경 없음)
├── router.py                        ├── router.py       (변경 없음)
├── expander.py                      ├── expander.py     (변경 없음)
├── query.py                         ├── query.py        (변경 없음)
└── query_analysis.py                ├── query_analysis.py (변경 없음)
                                     ├── validate.py     (신규)
                                     └── scaffold.py     (신규)
```

---

## 15. Verification

1. `python -m pytest tests/test_domain_loader.py` — knowledge.md 파싱, 최소 모듈, 선택 섹션, 에러, 교차 참조, 하위 호환
2. `python -m valuator.domain.validate` — 전체 모듈 로드 성공
3. `python -m valuator.domain.scaffold test_module` → validate 통과
4. 최소 knowledge.md (Persona + 1 Aspect)로 전체 파이프라인 실행 → 에러 없이 완료
5. `python -m pytest tests/` — 전체 회귀 테스트
6. 기존 5파일 모듈을 하나 남겨두고 loader가 양쪽 모두 로드하는지 확인
