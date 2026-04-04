# Valuator 전체 재구현 계획

## Context

`git reset --hard`로 **tracked 파일의 uncommitted 수정**이 소실. 현재 디스크 상태:

| 파일 유형 | 상태 | 원인 |
|-----------|------|------|
| `??` untracked (core/agent/, core/planning/, core/decomposition/, session/, models/factory.py 등) | **디스크에 생존** | reset은 tracked 파일만 영향 |
| ` M` tracked (scheduler.py, step_planner.py, agent.py, types.py 등) | **HEAD 커밋 상태로 롤백** | 수정 내용 소실 |

**HEAD = `7cf900e`** (agent.py 885L, step_planner.py 846L 상태).

목표: `docs/`의 모든 설계 문서를 기준으로 완전한 구현 달성.

---

## 관련 문서 지도

| 문서 | 요점 |
|------|------|
| `docs/valuator_package_refactoring_draft.plan.md` | **8 PR**: 구조 리팩토링 (dead code, 레이어 위반, 이중 시스템 해소). 8 PR 모두 `pending`. |
| `docs/refactoring-plan.md` | **PR-A/PR-B**: 8 PR 완료 후 후속. agent.py → core/agent/, step_planner.py → core/planning/ 서브패키지화. session/trace 분해. |
| `docs/remove-fact-wait.md` | `wait_for_facts` 제거 (scheduler.py, types.py) |
| `docs/remove-reason-plan.md` | `reason` 필드 제거 + `max_output_tokens` 추가 |
| `docs/agent-step-decision-protocol.md` | `normalize_decision_raw` — parser 경계 단일 정규화 |
| `docs/fix-deadlock-and-retry-plan.md` | 순환 WAIT 검증, `break_deadlock()`, web_search retry |
| `docs/openrouter-integration-spec.md` | OpenRouter 클라이언트 (models/openrouter.py) |
| `docs/browse-tree-plan.md` | `task_name` + `session/browse_tree.py` |

---

## 현재 디스크 상태 (구현 시작 전 반드시 확인)

### 생존한 untracked 파일들 (검증 필요)

아래 파일들은 디스크에 있지만 내용 완성도를 확인해야 한다.

| 파일 | 목표 크기 | 핵심 확인 사항 |
|------|-----------|----------------|
| `valuator/core/agent/loop.py` | ~519줄 | `Agent`, `run`, `_step_one`, `_fail_task`, `_reject_step` |
| `valuator/core/agent/trace.py` | ~192줄 | `log_step_decision`, `log_tool_execution`, payload 5개 함수 |
| `valuator/core/agent/context_builder.py` | ~143줄 | `build_task_context`, `enrich_tool_request`, `domain_context` |
| `valuator/core/planning/planner.py` | ~200줄 | `StepPlanner`, `decide`, `_generate_decision` |
| `valuator/core/planning/prompts.py` | ~380줄 | `build_system_prompt`, `build_step_prompt`, `build_repair_prompt` |
| `valuator/core/planning/parser.py` | ~260줄 | `StepIntentPayload`, `normalize_decision_raw`, `parse_decision` |
| `valuator/core/planning/actions.py` | — | 액션 관련 (내용 확인 필요) |
| `valuator/core/decomposition/types.py` | ~79줄 | `GateConfig`, `validate_gate_config` (config.py에서 이동) |
| `valuator/core/decomposition/gate.py` | ~177줄 | `static_pre_filter`, `BackpropagationTracker` |
| `valuator/core/decomposition/critic.py` | ~142줄 | LLM critic, `CriticVerdict` |
| `valuator/core/decomposition/controller.py` | ~140줄 | `GateController.gate_decompose` |
| `valuator/session/store.py` | ~700줄 | session_store.py 이전 완료 여부 |
| `valuator/session/trace.py` | ~417줄 | session_trace.py 이전 + 마크다운 분리 완료 여부 |
| `valuator/session/trace_markdown.py` | ~136줄 | 마크다운 렌더링 6개 함수 |
| `valuator/session/browse_tree.py` | ~210-227줄 | `build_browse_tree`, task 폴더 생성 |
| `valuator/models/factory.py` | ~33줄 | `create_llm_client(backend, model)` |
| `valuator/models/protocol.py` | ~65줄 | `LlmClient`, `UsageWriter` Protocol |
| `valuator/models/openrouter.py` | ~170줄 | `OpenRouterClient`, retry, price cache |
| `valuator/runtime.py` | ~62줄 | agent_runtime.py 이전 |
| `valuator/utils/time_utils.py` | ~45줄 | `utc_isoformat`, `compact_utc_timestamp`, `Measurement` |
| `valuator/utils/llm_usage.py` | ~120줄 | `ModelPrice`, frozen `TokenUsage.__add__`, `LLMUsageWriter` |

---

## 구현 순서 (의존성 레이어 순)

레이어 아래에서 위로 구현. 기능 변경과 구조 변경을 동일 파일에서 함께 처리.

---

### L0: utils/ (leaf — 의존 없음)

**`valuator/utils/time_utils.py`** (untracked, 검증/완성)
```python
def utc_isoformat(value=None) -> str: ...
def compact_utc_timestamp(value=None) -> str: ...
@dataclass(frozen=True)
class Measurement:
    started_at: str; started_perf: float
    @classmethod def start(cls) -> Measurement: ...
    def latency_seconds(self) -> float: ...
```
출처: `session/trace.utc_isoformat`, `llm_usage.Measurement` 통합.

**`valuator/utils/llm_usage.py`** (untracked, 검증/완성)
- `ModelPrice` frozen dataclass + `cost()` + `MODEL_PRICES` dict
- `TokenUsage` frozen + `__add__` (from_raw 제거)
- `LLMUsageWriter.append_call` → `usage: TokenUsage`로 좁힘
- `_append_row` inner lock 제거
- `PRICING` ClassVar 삭제

**`valuator/utils/json_ready.py`** (NEW, ~24줄)
- `json_ready(obj) -> Any` — 재귀 직렬화 (Enum, Path, dataclass, Pydantic)
- `session/trace.py`의 `_json_ready` private 메서드에서 이동
- 출처: `docs/refactoring-plan.md` Part 2

**`valuator/utils/config.py`** (tracked, 수정 필요)
- `LLM_BACKEND`, `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL` 추가
- `WEB_SEARCH_RETRY_COUNT`, `WEB_SEARCH_RETRY_BASE_DELAY` 추가
- 모델 alias 로직 → `models/naming.py`로 이동 후 import
- `_validate_decomposition_gate_config` → `core/decomposition/types.py`로 이동 후 lazy import

---

### L1: core/types.py (tracked, 수정 필요)

현재 HEAD: 85줄. 목표: ~80줄 (+ToolResult, EventType, frozen, 필드 변경).

변경 목록:
- `TaskDecision`: `frozen=True`, `children: list → tuple`, **`reason` 필드 제거**
- `TaskSpec`: **`wait_for_facts: tuple[str, ...]` 필드 제거**, **`task_name: str` 필드 추가**
- `EventType(str, Enum)` 추가 (8개: `step_started`, `step_completed`, `decomposed`, `tool_executed`, `aggregated`, `finalized`, `failed`, `decomposition_gated`)
- `AgentEvent.type: str → EventType`
- `ToolResult` 추가 (tools/base.py에서 이동, re-export 유지)

출처: `docs/valuator_package_refactoring_draft.plan.md` PR1/PR2, `docs/remove-reason-plan.md`, `docs/remove-fact-wait.md`, `docs/browse-tree-plan.md`

---

### L2: models/ (untracked, 검증/완성)

**`valuator/models/naming.py`** (untracked or NEW, ~25줄)
```python
MODEL_ALIASES: dict[str, str] = {"gemini-2.5-flash": "gemini-3-flash-preview", ...}
def canonical_model_name(value: str) -> str: ...
def is_openrouter_model_name(value: str) -> bool: return "/" in value.strip()
```
leaf 모듈 — valuator 내부 의존 없음.

**`valuator/models/protocol.py`** (untracked, 검증/완성 ~65줄)
- `LlmClient` Protocol: `generate()`, `generate_json()`
- `UsageWriter` Protocol: `append_call(*, method, model, usage: TokenUsage, ...)`, `log_llm_call(...)`
- `bind_usage_writer` 타입 수정 (`Any` → 구체 타입)

**`valuator/models/factory.py`** (untracked, 검증/완성 ~33줄)
- `create_llm_client(backend: str, model: str) -> LlmClient`
- `backend`: `"google_genai"` → `GeminiClient`, `"openrouter"` → `OpenRouterClient`

**`valuator/models/gemini_direct.py`** (tracked, 수정 필요 ~300줄)
- `TokenUsage` 직접 생성 (from_raw 대체)
- `_record_call` 헬퍼 추출 (성공/실패 로깅 중복 제거)
- `getattr(writer, 'log_llm_call')` → `UsageWriter` Protocol 직접 호출
- `Measurement` import → `utils.time_utils`

**`valuator/models/openrouter.py`** (untracked, 검증/완성 ~170줄)
- `AsyncOpenAI` 사용, JSON schema 강제
- retry with exponential backoff
- 동적 가격 fetch + `openrouter_model_prices.json` 캐싱
- `_record_call` 헬퍼, `UsageWriter` Protocol, `TokenUsage` 직접 생성

출처: `docs/openrouter-integration-spec.md`, `docs/valuator_package_refactoring_draft.plan.md` PR6/PR7

---

### L3: tools/ (tracked, 수정 필요)

**`valuator/tools/context_tool.py`** → **삭제**

**`valuator/tools/base.py`** (tracked, 대폭 축소 192→~90줄)
- `ObservationData` 삭제
- `BaseTool.validate_parameters()` 삭제
- `ToolRegistry.execute_tool` 내 validate_parameters 호출 삭제
- `ToolRegistry.unregister()` 삭제
- `ReActBaseTool` 통계 제거 (execution_time만 유지)
- `get_schema()` abstract method 제거
- `get_info()` → `TOOL_SPECS[self.name].to_llm_schema(self.description)` 위임
- `ToolResult` → re-export from `core.types`

**`valuator/tools/specs.py`** (tracked, 확장 293→~320줄)
```python
@dataclass(frozen=True)
class ToolSpec:
    param_descriptions: Mapping[str, str] = field(default_factory=dict)  # NEW
    def to_llm_schema(self, description: str) -> dict[str, Any]: ...
```
- 110행 `"code": "# placeholder"` 제거
- 5개 tool의 param_descriptions 데이터 추가 (기존 get_schema() description 보존)

**5개 tool** (tracked, 각 get_schema() 구현 삭제)
- `domain_tool.py` ~35줄 삭제
- `sec_tool.py` ~25줄 삭제
- `web_search_tool.py` ~35줄 삭제 + **retry 루프 추가** (`web_search_retry_count`, `web_search_retry_base_delay`)
- `code_execute_tool.py` ~25줄 삭제
- `yfinance_tool.py` ~35줄 삭제

출처: `docs/valuator_package_refactoring_draft.plan.md` PR1/PR8, `docs/fix-deadlock-and-retry-plan.md`

---

### L4: core/decomposition/ (untracked, 검증/완성)

**`core/decomposition/types.py`** (~79줄)
- `GateConfig` dataclass (weights: depth, breadth, tool_resolvability, token_pressure)
- `validate_gate_config(...)` 함수 (config.py 138-156행에서 이동)
- `FilterResult`: ACCEPT / REJECT / UNCERTAIN
- `CriticVerdict`: ACCEPT / REJECT
- `DecompositionOutcome`

**`core/decomposition/gate.py`** (~177줄)
- `static_pre_filter(children, task, config) -> FilterResult`
- `BackpropagationTracker.record_prediction()`, `observe_outcome()`, `update_threshold()`

**`core/decomposition/critic.py`** (~142줄)
- LLM critic — UNCERTAIN일 때만 호출
- `evaluate(children, task, ctx) -> CriticVerdict`

**`core/decomposition/controller.py`** (~140줄)
- `GateController.__init__(gate, critic, tracker, config)`
- `GateController.gate_decompose(children, task, ctx) -> TaskDecision | None`
  - pre_filter → (UNCERTAIN) → critic → outcome tracking

출처: `docs/PR-valuator-recursive-agent.md` TS-004, `docs/valuator_package_refactoring_draft.plan.md` PR4

---

### L5: core/ 로직 파일 (tracked, 수정 필요)

**`valuator/core/scheduler.py`** (tracked, 수정)

제거:
- `_fact_waiters: dict` 속성
- `_wake_fact_waiters()` 메서드
- `apply_decision()` 내 `wait_for_facts` 처리 블록

추가:
- `_validate_no_cycle(task_id, wait_for)` — BFS 순환 WAIT 탐지
- `apply_decision()` 내 decompose 시 cycle 검증 호출
- `break_deadlock()` — stale dependency 해소 (no READY/RUNNING 감지)
- `run_until_done()` deadlock 감지 후 `break_deadlock()` 호출

출처: `docs/remove-fact-wait.md`, `docs/fix-deadlock-and-retry-plan.md`

---

### L6: core/planning/ (untracked, 검증/완성)

step_planner.py 847줄을 3파일로 분해 (`docs/refactoring-plan.md` PR-B).

**`core/planning/parser.py`** (~260줄)
- `StepIntentPayload` (Pydantic — LLM raw output 경계 모델)
- `_ToolRequestPayload`, `_TaskSpecPayload`, `_TaskDecisionPayload`
- `normalize_decision_raw(raw: dict) -> TaskDecision` — 단일 정규화
  - `aggregate` + `wait_for` + no output → implicit aggregation
  - WAIT → AGGREGATE (safe state)
  - 누락 필드 기본값 처리
- `parse_decision(task, raw) -> TaskDecision`
- JSON 복구 파이프라인 (`salvage_decision_candidates`, `embedded_json_objects`)

**`core/planning/prompts.py`** (~380줄)
- `build_system_prompt(task, ctx, ...) -> str`
- `build_step_prompt(task, ctx, ...) -> str` — `wait_for_facts` 텍스트 제거, `task_name` 안내 추가
- `build_repair_prompt(task, raw, ...) -> str` — `reason` 관련 텍스트 제거
- 헬퍼 12개 (query units, children 요약, shared facts 등)

**`core/planning/planner.py`** (~200줄)
- `StepPlanner` class: `decide(task, ctx) -> TaskDecision`
- `_generate_decision(task, user_prompt, system) -> TaskDecision` — `max_output_tokens` 파라미터 추가
- `_allowed_actions(task) -> list[Action]`
- `_decision_schema()`

**`core/planning/actions.py`** (내용 확인 후 판단)

**`core/planning/__init__.py`**: `from .planner import StepPlanner`

출처: `docs/refactoring-plan.md` PR-B, `docs/agent-step-decision-protocol.md`, `docs/remove-reason-plan.md`

---

### L7: core/agent/ (untracked, 검증/완성)

agent.py 885줄을 3파일로 분해 (`docs/refactoring-plan.md` PR-A).

**`core/agent/trace.py`** (~192줄)
- 상태 없는 모듈 함수 8개:
  `log_step_decision`, `log_tool_execution`, `log_task_result`,
  `decision_input_payload`, `decision_payload`, `task_runtime_payload`, `task_summary_payload`, `planned_child_records`

**`core/agent/context_builder.py`** (~143줄)
- 모듈 함수 7개:
  `build_task_context`, `build_ancestry`, `build_siblings`,
  `registered_tools`, `query_units_for_task`, `enrich_tool_request`, `domain_context`

**`core/agent/loop.py`** (~519줄)
- `Agent` class, `run()`, `_step_one()`
- `_fail_task()` 헬퍼 (에러 처리 중복 ~60줄 제거)
- `_reject_step()` 헬퍼 (invalid decision 처리 중복 ~60줄 제거)
- `GateController` 위임 (gate 로직 ~140줄 제거)
- `agent_trace`, `context_builder` import 사용

**`core/agent/__init__.py`**: `from .loop import Agent`

**`valuator/core/agent.py`** (tracked) → import redirect로 축소:
```python
from valuator.core.agent.loop import Agent
__all__ = ["Agent"]
```

출처: `docs/refactoring-plan.md` PR-A

---

### L8: core/step_planner.py (tracked) → redirect

`core/planning/` 서브패키지 완성 후:
```python
from valuator.core.planning import StepPlanner
__all__ = ["StepPlanner"]
```

---

### L9: session/ (untracked, 검증/완성)

**`session/store.py`** (~700줄)
- session_store.py 내용 이전 완료 여부 확인
- browse tree 8개 메서드 (~210줄) → session/browse_tree.py로 이전 확인

**`session/trace.py`** (~417줄)
- session_trace.py에서 이전
- `_json_ready` → `utils/json_ready.py`로 이전
- 마크다운 렌더링 6개 메서드 → `session/trace_markdown.py`로 이전
- `utc_isoformat`, `compact_utc_timestamp` → `utils.time_utils` import

**`session/trace_markdown.py`** (~136줄)
- `write_task_markdown`, `task_markdown_block`, `child_markdown_lines`
- `result_preview`, `timeline_summary`, `display_time`

**`session/browse_tree.py`** (~210-227줄)
- `build_browse_tree(session_dir, tasks) -> None`
- `_write_task_folder(task_dir, task) -> None`
- `_render_task_markdown(task) -> str`
- 세션 완료 훅에서 호출

**삭제할 tracked 파일들** (session/ 완성 후):
- `valuator/session_store.py`
- `valuator/utils/session_trace.py`

---

### L10: runtime.py + import 업데이트

**`valuator/runtime.py`** (untracked, 검증/완성 ~62줄)
- `ToolRegistry`, 출력 포매팅 (agent_runtime.py에서 이전)

**Import 경로 업데이트** (~22 파일):
- `utc_isoformat/compact_utc_timestamp`: session/trace.py, core/agent/loop.py, session/store.py, runtime.py
- `Measurement`: core/agent/loop.py, models/openrouter.py, models/gemini_direct.py, tools/web_search_tool.py
- `llm_usage`: models/openrouter.py, models/gemini_direct.py, session/trace.py
- `ToolResult`: core/task.py, core/context.py, core/scheduler.py (→ from core.types)
- `validate_gate_config`: utils/config.py (lazy import from core.decomposition.types)
- `canonical_model_name`, `is_openrouter_model_name`: config.py, factory.py

---

### L11: 테스트

**수정 필요** (feature 변경 반영):
- `tests/test_recursive_agent_run.py` — `EventType` enum, `reason` 제거, `wait_for_facts` 제거
- `tests/test_recursive_agent_scheduler.py` — `wait_for_facts` 테스트 삭제, deadlock/cycle 테스트 추가
- `tests/test_step_planner.py` — `reason` 필드 제거, `normalize_decision_raw` 테스트

**신규 필요** (기존에 없거나 새 기능):
- `tests/test_parser_normalize.py` — `normalize_decision_raw` 모든 케이스 (implicit aggregate, WAIT→AGGREGATE 등)
- `tests/test_decomposition_gate.py` — `static_pre_filter`, `GateController`, threshold learning
- `tests/test_openrouter_client.py` — `OpenRouterClient` (retry, price cache)
- `tests/test_llm_factory.py` — backend 분기 (`google_genai` / `openrouter`)
- `tests/test_browse_tree.py` — `build_browse_tree` 출력 폴더 구조

---

## 의존성 레이어 (위반 없는 목표)

```
utils/ (leaf: config, logger, time_utils, llm_usage, json_ready)
       ↑ ↑ ↑
core/  models/  tools/
       ↑
session/
       ↑
runtime.py
```

**해소되는 위반** (완료 후):
- `utils/session_trace → core/llm_usage` 역방향 → session/trace → utils/llm_usage
- `core/task → tools/base.ToolResult` → core/task → core/types.ToolResult
- `Measurement`가 core/ → utils/time_utils (tools/models가 core 의존 방지)

---

## 보류 (docs에서도 명시적으로 범위 밖)

- **Task 가변성 축소** (15+ mutable 속성) — Scheduler/Agent 전면 변경 필요. PR-A 이후 착수.
- **Config God Class** (39필드) — DI 전환과 함께.
- **SessionTraceWriter 잔여** — 마크다운/유틸 추출 후 남는 I/O 로직은 현 수준이 적정.
- **domain_tool.py 프롬프트** — 관리 가치 낮음.
- **전체 MCTS rollout** (UCT·시뮬레이션) — TS-004 Non-Goal.

---

## 검증

```bash
# 각 레이어 완성마다 실행
python -m pytest tests/
ruff check .
ruff format .

# Import 레이어 확인
python -c "from valuator.core import Agent, Scheduler, SharedState"
python -c "from valuator.session import ValuatorSessionStore"
python -c "from valuator.models.factory import create_llm_client"
python -c "import valuator.utils.time_utils; import valuator.utils.llm_usage"

# 기능 통합 테스트
python scripts/run_recursive_agent_query.py --query "삼성전자 기업가치 분석" --model gemini-2.5-flash
```

---

## 순 효과 (8 PR + PR-A/PR-B 완료 후)

| 항목 | 전 | 후 |
|------|----|----|
| core/agent.py | 885줄 | redirect (~5줄) |
| core/step_planner.py | 846줄 | redirect (~5줄) |
| core/agent/loop.py | — | ~519줄 |
| core/planning/ (3파일) | — | ~840줄 |
| session/store.py | (session_store.py 508줄) | ~700줄 |
| tools/base.py | 180줄 | ~90줄 |
| tools/context_tool.py | 91줄 | 삭제 |
| models/openrouter.py | — | ~170줄 |
| 코드 순 감소 | — | **~-666줄** |
| 레이어 위반 | 3건 | **0건** |
| 스키마 이중 관리 | 있음 | **TOOL_SPECS 단일** |
