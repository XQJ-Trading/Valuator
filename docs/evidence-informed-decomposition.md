# Plan: Evidence-Informed Task Decomposition

**현재 문제: 플래너가 세션에서 이미 무엇을 수집했는지 모른다.**

task A가 "LS전선 2024 연결 재무제표"를 이미 가져왔는데, sibling task B가 똑같은 데이터를 또 요청한다. task C에서 웹 검색이 실패했는데, task D가 같은 검색을 또 시도한다. 깊이만 늘어나고 같은 실패를 반복한다.

근본 원인은 **분해 시점의 정보 부족**이다. 플래너는 DECOMPOSE 결정을 내릴 때 "지금까지 세션에서 무엇이 수집되었고, 무엇이 실패했는지"를 전혀 보지 못한다. 기존에는 사후 방어 장치(중복 시그니처 차단, 도구 차단, 거절 메시지)로 대응했지만, 이것은 이미 나쁜 분해가 만들어진 뒤의 증상 치료일 뿐이다.

## 해법: 플래너에게 증거를 보여준다

```
                      ┌─────────────────────────┐
                      │     Evidence Store       │
                      │  (session-wide 수집 현황) │
                      └──────┬──────────┬────────┘
                             │          │
                    읽기(분해 시점)   쓰기(실행 직후)
                             │          │
                             ▼          │
┌──────────────────────────────────┐    │
│          Step Planner            │    │
│                                  │    │
│  [EVIDENCE] 섹션을 보고          │    │
│  이미 수집된 데이터는 건너뛰고    │    │
│  실패한 접근은 피해서             │    │
│  children을 구성한다              │    │
└──────────┬───────────────────────┘    │
           │ DECOMPOSE / EXECUTE        │
           ▼                            │
┌──────────────────────────────────┐    │
│        Tool Execution            │────┘
│  실행 결과를 evidence로 기록      │
└──────────────────────────────────┘
```

핵심은 **피드백 루프**다. 도구 실행 → 결과 저장 → 다음 분해 시 참조 → 더 나은 분해. 플래너가 스스로 "이건 이미 있으니 안 해도 된다"고 판단할 수 있게 된다.

## 자율성이란

현재 구조에서 플래너는 **눈을 감고 계획을 세우는 것**과 같다. 세션에서 무슨 일이 일어났는지 모르니, 외부 장치(gate, critic, signature checker)가 나쁜 결정을 사후에 걸러내야 한다. 플래너는 수동적이고, 방어 장치들이 실질적 판단을 대행한다.

이 계획 후에는 플래너가 **세션의 전체 수집 현황을 보고 스스로 판단**한다:
- "LS전선 재무제표는 이미 수집됨 → 이 child는 불필요"
- "웹 검색 'LS전선 경쟁사'는 실패함 → 다른 검색어나 다른 도구를 써야"
- "3개 중 2개는 이미 있으니, 나머지 1개만 child로 만들면 충분"

**자율성 = 판단에 필요한 정보를 가지고 있는 것.** 정보가 없으면 규칙(gate, critic)에 의존할 수밖에 없고, 정보가 있으면 상황에 맞게 스스로 결정할 수 있다. MCTS gate/critic은 유용한 보강이지만, 꺼져 있어도 플래너 혼자 합리적인 분해를 할 수 있어야 한다.

---

## 아키텍처

```
valuator/
├── domain/
│   └── evidence.py          ← EvidenceRow (도메인 타입)
├── evidence/
│   └── store.py             ← EvidenceStore Protocol + SqliteEvidenceStore
├── core/
│   ├── agent/
│   │   ├── loop.py          ← 실행 직후 evidence 기록 + cross-task 중복 차단
│   │   └── context_builder.py ← TaskContext에 evidence 주입
│   ├── planning/
│   │   └── prompts.py       ← [EVIDENCE], [FAILED_ATTEMPTS] 섹션
│   ├── context.py           ← evidence 필드 추가
│   ├── task.py              ← failed_attempts 필드 추가
│   ├── types.py             ← FailedAttempt 타입
│   └── decomposition/
│       ├── protocol.py      ← DecompositionGate Protocol (신규)
│       └── controller.py    ← MCTSGateController (리네임)
```

---

## Phase 1: 증거 저장소

> 도구 실행 결과를 구조화하여 저장하는 인프라. 모든 후속 Phase의 선행 조건.

### 1-1: `EvidenceRow` 도메인 타입
- **파일**: `valuator/domain/evidence.py` 생성
- frozen dataclass: `session_id`, `tool_name`, `stable_args_hash`, `status`("satisfied"|"empty"|"failed"), `value_summary`, `value_ref`, `task_id`, `unit_objective`, `created_at`, `updated_at`
- `stable_args(tool_name, args) -> dict`: args 전체 유지 (web_search query 포함)
- `stable_args_hash(tool_name, args) -> str`: `tool_name + ":" + json.dumps(stable_args(...), sort_keys=True)`

### 1-2: `EvidenceStore` Protocol + `SqliteEvidenceStore`
- **파일**: `valuator/evidence/store.py` 생성
- Protocol: `record()`, `lookup()`, `list_for_session()`
- SQLite: session별 DB, UNIQUE `(session_id, tool_name, stable_args_hash)`, UPSERT
- 동기 SQLite + threading (기존 session_store 패턴)

### 1-3: 경계에서 쓰기
- **파일**: `valuator/core/agent/loop.py`
- `_execute_tool_step()` — 도구 실행 직후 `evidence_store.record()`
- status 매핑: success → "satisfied", success+empty → "empty", error → "failed"

### 1-4: 단위 테스트
- stable_args 추출, record→lookup 왕복, UPSERT 동작

---

## Phase 2: 분해 시점 증거 주입 (핵심)

> 플래너가 세션의 수집 현황을 보고 자율적으로 중복 없는 분해를 구성한다.

### 2-1: step 프롬프트에 `[EVIDENCE]` 섹션
- **파일**: `valuator/core/planning/prompts.py`
- `[SHARED_FACTS]` 다음에 `[EVIDENCE]` 추가
- 포맷 예시:
  ```
  opendart_financial_tool(corp=LS,year=2024,fs_div=CFS): satisfied — "연결 재무제표 BS/IS/CF"
  web_search_tool(query="LS전선 매출 추이"): satisfied — "2023-2024 매출 성장률 15%"
  web_search_tool(query="LS전선 경쟁사"): failed
  ```
- 시스템 프롬프트 지침: "DECOMPOSE 시 [EVIDENCE]의 satisfied 데이터를 다시 수집하는 child를 만들지 마라. failed 이력과 동일한 요청을 반복하지 마라."

### 2-2: TaskContext에 evidence 필드
- **파일**: `valuator/core/context.py` — `evidence: list[EvidenceRow]`
- **파일**: `valuator/core/agent/context_builder.py` — evidence_store 조회

---

## Phase 3: 실패 이력 피드백

> task 내 도구 실패 이력 전체를 프롬프트에 노출. `[PREVIOUS_REJECTION]`(마지막 1건)의 보완.

### 3-1: `FailedAttempt` 타입
- **파일**: `valuator/core/types.py` — frozen dataclass: `tool_name`, `args`, `error`, `kind`

### 3-2: Task에 `failed_attempts` 필드
- **파일**: `valuator/core/task.py` — `failed_attempts: list[FailedAttempt]`, `copy_runtime_to()` 반영

### 3-3: 실패 기록
- **파일**: `valuator/core/agent/loop.py`
- `_execute_tool_step()` failure → append, `_effective_decision()` rejection → append

### 3-4: `[FAILED_ATTEMPTS]` 프롬프트 섹션
- **파일**: `valuator/core/planning/prompts.py`
- 최근 8건, tool_name + args 요약 + error + kind

---

## Phase 4: Cross-task 중복 차단

> 실행 시점에서 evidence를 조회하여, 이미 수집된 데이터의 재호출을 차단하는 안전망.
> Phase 2에서 플래너가 자율 판단하지만, 무시할 경우를 대비한 runtime 방어.

### 4-1: `_effective_decision`에서 evidence 조회
- **파일**: `valuator/core/agent/loop.py`
- "satisfied" → reject ("task {task_id}에서 이미 수집됨: {value_summary}")
- "failed"/"empty" → 통과 (재시도 허용)

---

## Phase 5: MCTS 모듈화 (독립)

> Gate+Critic을 토글 가능한 패키지로 분리. MCTS off여도 Phase 1-4는 정상 동작.

### 5-1: `DecompositionGate` Protocol + `PassthroughGate`
- **파일**: `valuator/core/decomposition/protocol.py` 생성

### 5-2: `GateController` → `MCTSGateController` 리네임
- **파일**: `valuator/core/decomposition/controller.py`

### 5-3: Agent에서 gate 선택
- **파일**: `valuator/core/agent/loop.py` — `gate_config.enabled` → MCTS, else → Passthrough

### 5-4: StepPlanner의 static rejection → gate 내부로 이동
- **파일**: `valuator/core/planning/planner.py`

---

## 구현 순서

```
Phase 1 (증거 저장소) ──→ Phase 2 (분해 시점 주입) ──→ Phase 4 (runtime 차단)
                     └──→ Phase 3 (실패 이력)
Phase 5 (MCTS 모듈화) ─── 독립
```

---

## 레이어 정리

플래너 자율 판단이 1차, 기존 장치와 evidence 차단이 2차 안전망.

| 레이어 | 시점 | 주체 | 역할 |
|--------|------|------|------|
| `[EVIDENCE]` in prompt | 분해 시점 | 플래너 (자율) | 수집 현황을 보고 중복 없는 children 구성 |
| `[FAILED_ATTEMPTS]` | 실행 시점 | 플래너 (자율) | task 내 실패 이력 전체를 보고 다른 접근 선택 |
| evidence lookup | 실행 시점 | runtime (강제) | cross-task exact match 중복 차단 |
| `_tool_request_signature` | 실행 시점 | runtime (강제) | task 내 동일 args 즉각 차단 |
| `blocked_tools` | 실행 시점 | runtime (강제) | N회 연속 실패 도구 차단 |
| `[PREVIOUS_REJECTION]` | 실행 시점 | 플래너 (자율) | 결정 구조 위반 피드백 |
| MCTS gate + critic | 분해 시점 | gate (optional) | 통계적/의미적 분해 품질 평가 |

---

## 검증

1. evidence.db에 도구 실행마다 행 생성. web_search는 query별 별도 행.
2. step prompt에 `[EVIDENCE]` 포함 확인. satisfied인 DART를 children에서 제외하는지 E2E.
3. `[FAILED_ATTEMPTS]`에 이전 실패 이력 전체 표시.
4. cross-task 동일 호출 시 reject. 다른 query는 통과.
5. `gate_config.enabled=False` 시 evidence 기반 판단은 유지, gate/critic만 비활성.
6. E2E: 동일 실패 반복 횟수 감소, 중복 API 호출 감소.

---

## 리스크

| 항목 | 리스크 | 대응 |
|------|--------|------|
| 플래너가 `[EVIDENCE]` 무시 | 프롬프트 지침만으로 보장 불가 | Phase 4 runtime 차단이 안전망. MCTS on이면 critic 보강 |
| evidence 목록 길어짐 | 토큰 부담 | satisfied 건수 요약 + truncation priority |
| SQLite sync 블로킹 | event loop | session_store 동일 패턴. 병목 시 aiosqlite |
