# Plan: browse/ 디렉토리 — LLM 생성 task_name 기반 요약 트리

## Context

현재 `tasks/` 디렉토리는 `root`, `root.0`, `root.0.0` 등 기계적 ID로 명명된다. 파일 시스템 탐색만으로는 태스크 내용을 파악할 수 없다. 기존 `tasks/` 구조는 유지하고, 세션 완료 후 `browse/` 디렉토리에 LLM이 생성한 `task_name` 기반 트리를 만들어 사람이 읽을 수 있는 뷰를 제공한다.

## 목표 구조 (현재 로그 기반 예시)

```
logs/CLI-20260327-132030843112Z/
├── tasks/                                    # 기존 그대로 유지
│   └── root/
│       ├── root.0/ ...
│       └── ...
│
└── browse/                                   # 새로 생성
    └── 이란미국_전쟁_시나리오_분석/
        ├── README.md                         # task_id/state/task_type/description
        ├── report.md
        ├── final.md
        ├── 군사적긴장_대리전_현황/
        │   ├── README.md
        │   ├── task.md
        │   ├── result.md
        │   ├── 최신군사충돌_조사/
        │   │   ├── README.md
        │   │   ├── 월별충돌_타임라인/
        │   │   ├── 전투지역_피해집계/
        │   │   └── 호르무즈_대리세력개입/
        │   ├── 후티_헤즈볼라_미군충돌/
        │   └── 양국_공식입장_비교/
        ├── 호르무즈봉쇄_유가_공급망/
        │   ├── 봉쇄시나리오_유가예측/
        │   │   ├── 봉쇄시나리오_확률추정/
        │   │   └── 공급차질_유가상단/
        │   └── 운임상승_공급망지연/
        │       ├── 해상운임_물류지연/
        │       ├── 에너지산업_파급효과/
        │       └── 제조업_재고비용_생산차질/
        ├── 방산에너지금융_과거사례/
        │   ├── 걸프전_이라크전_주가반응/
        │   │   ├── 걸프전_수익률변동성/
        │   │   ├── 이라크전_솔레이마니/
        │   │   └── SP500_섹터별수익률/
        │   └── 최근중동충돌_자산변동성/
        │       ├── 하마스이란_자산군수익률/
        │       │   ├── 일별종가수집/
        │       │   └── 수익률변동성_계산/
        │       └── ETF자금흐름_세이프헤이븐/
        └── 미국정치_중동개입영향/
```

## 구현

### Step 1: `task_name` 필드를 LLM 스키마에 추가

decomposition 시 LLM이 `description`과 함께 `task_name`(30자 이내, 파일시스템 안전)을 생성하도록 한다.

**`valuator/core/step_planner.py`**
- `TASK_NAME_MAX_CHARS = 30`
- `_TaskSpecPayload`에 `task_name: str` 필드 추가
- `_system_prompt()`에 task_name 생성 가이드:
  - "task_name은 description 전체의 핵심 개념을 압축한 이름이다. 앞부분만 잘라내지 말고, 전체 의미를 보존하여 요약하라."
  - 예시: description='호르무즈 해협 봉쇄 시나리오별 확률 추정 및 유가 상한선 예측' → task_name='봉쇄확률_유가상한_예측' (O), '봉쇄시나리오_확률' (X, 뒷부분 누락)

**`valuator/core/types.py`**
- `TaskSpec`에 `task_name: str = ""` 필드 추가

### Step 2: `Task` 모델에 `task_name` 전달

**`valuator/core/task.py`**
- `Task.__init__`에 `task_name: str = ""` 파라미터 추가, `self.task_name = task_name`

**`valuator/core/scheduler.py:189-223` (`_create_children`)**
- `AtomicTask()`/`ComplexTask()` 생성 시 `task_name=spec.task_name` 전달

### Step 3: `task_name`을 task.json에 저장

**`valuator/session_store.py:445-475` (`_write_task_tree`)**
- task.json payload에 `"task_name": task.task_name` 추가

**`valuator/utils/session_trace.py:540-576` (`_ensure_task_dir`)**
- 초기 task.json에도 `task_name` 필드 포함

### Step 4: `build_browse_tree()` 함수 — 세션 완료 후 browse/ 생성

**`valuator/session_store.py`에 추가**

```python
def build_browse_tree(self) -> None:
    """tasks/ 구조를 읽어 browse/ markdown-first 트리를 생성한다."""
    browse_dir = self.session_dir / "browse"
    tasks_dir = self.session_dir / "tasks"
    # 1. tasks/ 아래 모든 task.json을 재귀 순회
    # 2. 각 task의 task_name으로 디렉토리 생성
    # 3. README.md 작성: task_id/state/task_type/description
    # 4. task.md/result.md/report.md/final.md 등 markdown 산출물 복사
    # 4. 동일 부모 아래 task_name 충돌 시 _2, _3 suffix
```

- `browse/`는 JSON 뷰가 아니라 markdown-first 사람용 뷰로 생성
- `task.json`, `info.json`, `steps.jsonl`, `llm_calls/`, `*.meta.json`, `ledger.json`, `result.json`은 browse에 복사하지 않음
- child task dir(`root.0.0` 등)는 raw copy하지 않고, `task_name` 기반 하위 디렉토리로 재귀 재구성
- symlink 사용하지 않음 — browse/는 자체 완결

### Step 5: 세션 종료 시 호출

**`scripts/run_recursive_agent_query.py:297-316`**
- `session_store.sync_task_tree(root_task)` 직후에 `session_store.build_browse_tree()` 호출

## root task의 task_name

root task는 LLM decomposition이 아닌 직접 생성(`server/main.py:452`)이므로, `build_browse_tree()`에서 root의 description을 기반으로 slug를 생성한다. 별도의 `_to_slug()` fallback 함수가 필요하다 (task_name이 비어있는 경우 사용).

## 수정 대상 파일

| 파일 | 변경 |
|------|------|
| `valuator/core/types.py` | `TaskSpec.task_name` 추가 |
| `valuator/core/task.py` | `Task.__init__` `task_name` 파라미터 |
| `valuator/core/step_planner.py` | `_TaskSpecPayload.task_name`, 프롬프트 가이드 |
| `valuator/core/scheduler.py` | `_create_children()`에서 task_name 전달 |
| `valuator/session_store.py` | task.json에 task_name 저장, `build_browse_tree()` |
| `valuator/utils/session_trace.py` | 초기 task.json에 task_name |
| `scripts/run_recursive_agent_query.py` | 세션 종료 시 `build_browse_tree()` 호출 |

## 검증

1. `python -m pytest tests/` — 기존 테스트 통과
2. 쿼리 실행 후 `find logs/*/browse -type d` 로 요약명 디렉토리 확인
3. `cat logs/*/browse/*/README.md` 로 task_id 매핑 확인
4. 기존 `tasks/` 구조 무변경 확인
