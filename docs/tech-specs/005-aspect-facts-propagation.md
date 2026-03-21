# TS-005: AspectFacts 전파 — Aggregation 파이프라인 구조적 팩트 보존

## Context

**문제:** Leaf 노드에서 추출된 `AspectFacts`(aspect_id, facts: dict, evidence: str)가 merge 경계를 넘지 못한다. `TaskReport`가 `(task_id, markdown)`만 보유하므로, merge 노드는 child의 구조화된 팩트 없이 비구조적 마크다운만 LLM에 전달한다. 결과: 수치 hallucination, 팩트 변형, evidence 유실.

**근본 원인:** 경계 미완결. `TaskReport`가 구조적 데이터를 전달하는 도메인 타입 역할을 하지 못함.

**세션 증거:** `S-20260318-050249Z` — Round-01 EV 4,250억 → Round-02 EV 7,090억. LLM이 마크다운만 받고 수치를 자유롭게 변형.

## Data Flow (현재 vs 목표)

```
현재:
LEAF → ExtractAspectFacts → ReportMaterial(aspect_facts=✓)
     → TaskReport(markdown only) ──────────────────────────┐
                                                           ↓
MERGE → collect_materials() → ReportMaterial(aspect_facts=∅) → LLM → hallucination
        + descendant_leaf_artifacts() → 동일 데이터 이중 전달

목표:
LEAF → ExtractAspectFacts → ReportMaterial(aspect_facts=✓)
     → TaskReport(markdown + aspect_facts=✓) ─────────────┐
                                                           ↓
MERGE → collect_materials() → ReportMaterial(aspect_facts=✓) → LLM → 팩트 보존
```

## Changes

### 1. `TaskReport`에 `aspect_facts` 필드 추가

**File:** [plan.py:84-88](valuator/core/contracts/plan.py#L84-L88)

```python
# before
@dataclass(frozen=True, slots=True)
class TaskReport:
    task_id: str
    markdown: str

# after
@dataclass(frozen=True, slots=True)
class TaskReport:
    task_id: str
    markdown: str
    aspect_facts: tuple[AspectFacts, ...] = ()
```

- `tuple`로 `frozen=True` 의미론 유지
- `default=()`로 기존 `TaskReport(task_id=..., markdown=...)` 호출 하위호환
- 영향받는 호출처: `_leaf_passthrough()`, `_synthesize()` — Change 3에서 수정

### 2. Merge 경계에서 `aspect_facts` 전파

**File:** [materials.py:50-58](valuator/core/aggregator/materials.py#L50-L58)

`collect_materials()`에서 child report → ReportMaterial 변환 시 aspect_facts 전달:

```python
# before (line 57)
materials.append(ReportMaterial(source=source, content=child_report.markdown, facts={}))

# after
materials.append(ReportMaterial(
    source=source,
    content=child_report.markdown,
    facts={},
    aspect_facts=list(child_report.aspect_facts),
))
```

**효과:** `_aspect_facts_section()` ([service.py:539-589](valuator/core/aggregator/service.py#L539-L589))이 `materials`의 `aspect_facts`를 순회하므로, 이 변경만으로 merge 노드의 LLM 프롬프트 `[ASPECT_FACTS]` 섹션에 구조화된 팩트가 포함됨.

### 3. `TaskReport` 생성 시 `aspect_facts` 수집

**File:** [service.py](valuator/core/aggregator/service.py)

#### 3-a. `_leaf_passthrough()` (line 232-259)

materials에서 aspect_facts를 수집하여 TaskReport에 전달:

```python
# before (line 259)
return TaskReport(task_id=task.id, markdown="\n".join(lines).strip())

# after
all_facts: list[AspectFacts] = []
for mat in materials:
    all_facts.extend(mat.aspect_facts)
return TaskReport(
    task_id=task.id,
    markdown="\n".join(lines).strip(),
    aspect_facts=tuple(all_facts),
)
```

#### 3-b. `_synthesize()` (line 290-320)

동일하게 materials에서 수집:

```python
# before (line 320)
return TaskReport(task_id=task.id, markdown=markdown)

# after
all_facts: list[AspectFacts] = []
for mat in materials:
    all_facts.extend(mat.aspect_facts)
return TaskReport(
    task_id=task.id,
    markdown=markdown,
    aspect_facts=tuple(all_facts),
)
```

`_synthesize()`는 `materials` 파라미터를 이미 받고 있으므로 시그니처 변경 불필요.

### 4. Evidence 절삭 제거

**File:** [service.py:701-711](valuator/core/aggregator/service.py#L701-L711)

```python
# before
def _evidence_by_priority(self, evidence: str, priority: str) -> str:
    text = " ".join((evidence or "").split())
    if not text:
        return ""
    normalized = priority.strip().lower()
    if normalized == "low":
        return ""
    if normalized == "medium":
        sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip()
        return sentence or text
    return text

# after
def _evidence_text(self, evidence: str) -> str:
    return " ".join((evidence or "").split())
```

priority 기반 분기와 priority 표기를 모두 제거한다. 모든 evidence 전문을 유지하고, aggregation 경로에서는 aspect priority를 더 이상 계산하거나 출력하지 않는다.

### 5. Descendant leaf 이중 수집 제거

**File:** [materials.py:60-64](valuator/core/aggregator/materials.py#L60-L64)

```python
# before
    for item in descendant_leaf_artifacts(task.id, task_map, leaf_artifacts, descendant_cache):
        if item.source in seen_sources:
            continue
        materials.append(replace(item))
        seen_sources.add(item.source)
    return materials

# after
    return materials
```

**근거:** Child report의 aspect_facts가 전파되므로 (Change 2) descendant leaf를 중복 수집할 필요 없음. 이중 수집은 LLM에 동일 데이터를 (1) child report의 markdown (2) raw leaf artifact로 두 번 전달하여 가중치 왜곡.

**`_supporting_materials_section` 영향:** child report의 `content` (= child의 markdown)에 leaf의 findings/sources가 이미 포함되어 있으므로 정보 손실 없음. `_leaf_passthrough()`가 `mat.content`를 그대로 출력하기 때문.

**미사용 코드 정리:**
- `descendant_leaf_artifacts()` ([graph_ops.py:27-52](valuator/core/aggregator/graph_ops.py#L27-L52)): `collect_materials()`에서만 호출됨. 제거.
- `collect_materials()`의 `descendant_cache` 파라미터: 더 이상 불필요. 제거.
- `materials.py` import: `from .graph_ops import descendant_artifact_task_ids, descendant_leaf_artifacts` → `descendant_leaf_artifacts` 제거.
- `materials.py` import: `from dataclasses import replace` → 미사용 시 제거.

호출처 시그니처 변경:
- [service.py:132-138](valuator/core/aggregator/service.py#L132-L138): `collect_materials(task, task_map, artifact_materials, reports, {})` → `collect_materials(task, task_map, artifact_materials, reports)`
- [service.py:75](valuator/core/aggregator/service.py#L75) (`aggregate` 메서드 내): 동일 패턴 확인 필요

## 수정 파일 요약

| File | Change |
|---|---|
| `valuator/core/contracts/plan.py` | `TaskReport.aspect_facts: tuple[AspectFacts, ...]` 추가 |
| `valuator/core/aggregator/materials.py` | child report aspect_facts 전파, descendant 이중 수집 제거, `descendant_cache` 파라미터 제거 |
| `valuator/core/aggregator/graph_ops.py` | `descendant_leaf_artifacts()` 함수 제거 |
| `valuator/core/aggregator/service.py` | `_leaf_passthrough`/`_synthesize`에서 aspect_facts 수집, evidence 절삭 제거, `collect_materials` 호출 시그니처 업데이트 |

## Verification

```bash
python -m pytest tests/ -x
```

세션 재실행 후 검증:
1. merge 노드의 LLM 프롬프트에 `[ASPECT_FACTS]` 섹션이 populated 되는지 확인
2. final.md에서 leaf 원본 수치가 보존되는지 확인
3. evidence가 priority와 무관하게 전문 유지되는지 확인
