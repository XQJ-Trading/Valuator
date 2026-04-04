# Post-Rebuild Cleanup: 구조 감사 및 제거/개선 항목

## A. 확실히 제거 가능한 파일 (dead code)

### A-1. `valuator/agent_runtime.py` (61줄) — 삭제

- `**valuator.runtime**` (65줄)과 `create_tool_registry`, `finalize_trace`가 거의 동일
- 차이: `agent_runtime`의 `final_output_text`에 markdown 렌더링 경로가 없음 (열등한 버전)
- **import 없음**: `from valuator.agent_runtime`을 쓰는 `.py` 파일이 0개
- `server/main.py`와 `scripts/run_recursive_agent_query.py` 모두 `from valuator.runtime import` 사용 중

### A-2. `valuator/core/step_planner.py` (5줄) — 삭제

```python
from valuator.core.planning import StepPlanner
__all__ = ["StepPlanner"]
```

- `valuator/core/__init__.py`의 lazy export가 이미 `(".planning", "StepPlanner")`로 연결
- `from valuator.core.step_planner`를 쓰는 `.py` 파일 0개
- 테스트도 `from valuator.core.planning import StepPlanner` 또는 `from valuator.core import StepPlanner` 사용

### A-3. `valuator/core/decomposition_critic.py` + `decomposition_gate.py` + `decomposition_types.py` (~398줄) — 삭제, 테스트 import 수정

패키지 `valuator/core/decomposition/` (canonical)과 루트의 3파일이 **중복**:


| 루트 파일 (old)                    | 패키지 파일 (canonical)              | 차이점                                                                                                   |
| ------------------------------ | ------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `decomposition_critic.py`      | `decomposition/critic.py`       | 패키지 버전: `_max_output_tokens` 전달, `decision=` 미포함, 시스템 프롬프트 "near-duplicate" 문구 추가                     |
| `decomposition_gate.py`        | `decomposition/gate.py`         | 패키지 버전: `critic_to_score`에서 `redundant_pairs` 가중치 0.35 vs 0.20, `_clamp` 함수 사용, `reason` 트레일링 세미콜론 포함 |
| `decomposition_types.py` (79줄) | `decomposition/types.py` (101줄) | 패키지 버전: `validate_gate_config` 추가 (config.py에서 사용)                                                    |


- **production** (`agent/loop.py`): `from ..decomposition import` (패키지)
- **테스트만** old 경로 사용:
  - `test_decomposition_critic.py` → `from valuator.core.decomposition_critic`
  - `test_decomposition_gate.py` → `from valuator.core.decomposition_gate`, `from valuator.core.decomposition_types`

**행동**: 루트 3파일 삭제 + 테스트 import를 `valuator.core.decomposition`으로 변경. 테스트가 old 구현의 미세한 차이(가중치 0.20 vs 0.35 등)에 의존하면 기대값 조정 필요.

### A-4. `tools/[TODO]opendart-financial-collector.md` — 삭제 또는 `docs/`로 이동

소스 패키지 안의 TODO 문서. 코드가 아님.

---

## B. 정리 가능한 코드 (in-file dead code)

### B-1. `tools/__init__.py` — `__all__` 수정 또는 lazy export

현재 `__all__`에 `DomainTool`, `ExecuteCodeTool` 등 9개 이름을 선언하지만 **실제로 import하지 않음**.
`from valuator.tools import DomainTool`은 `ImportError`가 아니라 `AttributeError`를 발생시킴.

**선택지**:

- (a) `__all__`을 비우거나 실제 public API만 남기기 (`TOOL_SPECS`, `ToolSpec`, `get_tool_spec` 정도)
- (b) `core/__init__.py`처럼 lazy export 패턴 적용

### B-2. `specs.py` 미사용 API — `filter_tool_names`, `registered_tool_names`, `ToolExecutionContext`, `ToolSpec.build_args`

- 이 4개를 호출하는 `.py`가 `specs.py` 자체 외에 **0개**
- `build_args`는 `ToolExecutionContext`에 의존하고, `ToolExecutionContext.values()`가 유일한 사용처
- `filter_tool_names` → `accepts` → `SubjectRequirement.accepts` 체인도 외부 호출 0개

아직 기능이 계획 중이라면 유지할 수 있으나, CLAUDE.md의 "요청받지 않은 동작은 구현하지 않는다"에 해당할 수 있음.

### B-3. `planning/parser.py`와 `planning/planner.py`의 `TASK_NAME_MAX_CHARS` 불일치

- `parser.py`: `TASK_NAME_MAX_CHARS = 40` (Pydantic `max_length`)
- `planner.py`: `TASK_NAME_MAX_CHARS = 30` (`_validate_decision_contract`)

파서가 40자를 허용하지만 플래너가 30자로 후검증하여 거부할 수 있음. 의도적이면 문서화, 아니면 통일.

---

## C. 구조 개선 (중기)

### C-1. `server/main.py` 2041줄 모놀리스 분할

현재 한 파일에:

- `SessionService` + DTO (~425줄, 332-757)
- `build_query_analysis` orchestration (~75줄)
- History/Sessions API handlers (~400줄)
- Valuator snapshot helpers (~150줄, 1352-1504)
- Task-rewrite handlers (~140줄)
- Dev Gemini log handlers/helpers (~120줄, 1721-2041)

이미 `session_viewer_api.py`, `services/valuator_snapshot.py`, `services/task_rewrite/`로 일부 분리됨.

**분할 방향**:

- `server/services/session_service.py` ← `SessionService` + DTOs
- `server/routers/history.py` ← history CRUD endpoints
- `server/routers/sessions.py` ← session CRUD + streaming
- `server/routers/valuator_views.py` ← snapshot/task/final endpoints + filesystem helpers
- `server/routers/dev.py` ← Gemini log endpoints
- `server/routers/task_rewrite.py` ← task-rewrite endpoints
- `server/main.py` ← app factory, CORS, lifespan, include_router만

### C-2. `domain/query_analysis.py` 838줄 — 경계 분리 검토

CLAUDE.md에 따르면 regex/normalize/coerce는 경계에서만. 이 모듈은 LLM 응답 파싱(경계)과 QueryAnalyzer 오케스트레이션(비즈니스)이 혼합되어 있음.

- `_canonicalize_target_period_raw`, `_coerce_iso_text_to_utc_date` 등 정규식/날짜 정규화 → `domain/boundary/` 하위로 이동 가능
- `QueryAnalyzer` 클래스 자체는 비즈니스 오케스트레이션

---

## D. 정리해야 할 "위생" 항목

### D-1. `docs/` 내 삭제된 파일 경로 참조

`rebuild-plan.md`, `valuator_package_refactoring_draft.plan.md`, `PR-valuator-recursive-agent.md` 등에서 `valuator/core/llm_usage`, `utils/session_trace`, `session_store.py`, `core/agent.py` 등 이미 삭제된 경로를 언급. 실행 코드에는 영향 없지만 오해 소지 있음.

### D-2. `conftest.py` 빈 파일 (0줄)

`tests/conftest.py`가 비어 있음. 불필요하면 삭제, pytest fixture가 필요하면 향후 활용.

---

## 요약: 영향도 × 난이도 매트릭스


| 항목                            | 제거 라인  | 난이도              | 비고          |
| ----------------------------- | ------ | ---------------- | ----------- |
| A-1 `agent_runtime.py` 삭제     | 61     | 즉시               | import 없음   |
| A-2 `step_planner.py` 삭제      | 5      | 즉시               | import 없음   |
| A-3 decomposition 루트 3파일 삭제   | ~398   | 테스트 import 수정 필요 | 가중치 차이 주의   |
| A-4 TODO.md 이동                | 0      | 즉시               |             |
| B-1 `tools/__init__.py` 정리    | ~12    | 즉시               |             |
| B-2 `specs.py` 미사용 API 제거     | ~50    | 의도 확인 필요         | 향후 사용 계획 여부 |
| B-3 `TASK_NAME_MAX_CHARS` 통일  | ~2     | 즉시               | 의도 확인 필요    |
| C-1 `server/main.py` 분할       | 0 (이동) | 중                | ~6개 모듈로 분할  |
| C-2 `query_analysis.py` 경계 분리 | 0 (이동) | 중                | 경계 원칙 적용    |
| D-1 docs 경로 업데이트              | ~30    | 낮음               |             |
| D-2 빈 conftest 정리             | 0      | 즉시               |             |

