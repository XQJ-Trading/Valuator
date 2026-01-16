## 0. 목적과 설계 철학
HDPS는 단일 에이전트 운영 시스템이며, 모든 판단/결과/맥락은 파일 시스템에만 존재한다.
런타임 메모리는 캐시일 뿐 “상태”가 아니다. 상태는 오직 파일만이 진실 원천이다.
작업은 Top‑down 분해, 결과는 Bottom‑up 검증/승격된다.

## 1. HDPS Laws
Law 1. File is State: 파일에 기록되지 않은 정보는 존재하지 않는다.
Law 2. Immutable Execution: 계획/실행/검수 기록은 덮어쓰지 않는다. 변경은 Append / Archive / New Snapshot만 허용.
Law 3. Role Isolation: Planner/Executor/Critic는 명확히 분리된다.
Law 4. Validated Knowledge Only: Critic 통과(PASS) 산출물만 Knowledge로 승격.

## 2. 디렉토리 구조
/project
 └─ /sessions
     └─ S-YYYYMMDD-HHMMSSZ/
         ├─ status.json
         ├─ /plan
         │   ├─ goal.md
         │   ├─ active/
         │   │   ├─ decomposition.json
         │   │   ├─ metadata.json
         │   │   └─ status_log.ndjson
         │   ├─ archive/
         │   │   └─ snapshot_{timestamp}_{reason}/
         │   └─ change_log.md
         ├─ /context
         │   ├─ index.json
         │   ├─ state.json
         │   └─ sources/
         ├─ /execution
         │   ├─ run_logs/
         │   ├─ outputs/
         │   └─ questions/
         ├─ /critique
         │   ├─ review_rules.md
         │   └─ reports/
         ├─ /input
         │   ├─ user_input.md
         │   └─ system_prompt.md
         ├─ /output
         │   ├─ final.md
         │   ├─ artifacts/
         │   └─ summary.json
         ├─ verdict.md
         └─ pointers.json

### 2.1 기존 디렉토리와의 관계
구분	성격
/sessions/<session_id>/plan, context, execution, critique, status.json	시스템 내부 상태 (Source of Truth)
/sessions/<session_id>/input, output, verdict, pointers	입력 → 출력 관점의 결과 뷰

각 세션은 내부 상태와 출력 뷰를 함께 포함한다.  
세션 밖에 별도의 전역 상태 디렉토리는 두지 않는다.

## 3. ID/시간 규칙
Task ID: T-0001 (4자리 고정)  
Session ID: S-YYYYMMDD-HHMMSSZ  
Timestamp: ISO‑8601 UTC (2026-01-12T14:30:00Z)  
모든 파일명에 UTC 사용.

## 4. 상태 모델
status.json은 “현재 포인터”만 기록한다. 덮어쓰기는 허용되는 유일한 예외 포인터 파일이다.  
모든 상태 변경 이력은 /sessions/<session_id>/plan/active/status_log.ndjson에 append-only로 기록한다.

status.json 예시:
{
  "system_status": "EXECUTING",
  "plan_major_version": 2,
  "plan_revision": 7,
  "current_task_id": "T-0007",
  "blocked_count": 1,
  "last_event_id": "EV-20260112T143000Z-0009"
}

status_log.ndjson 이벤트 예시:
{"event_id":"EV-20260112T143000Z-0009","ts":"2026-01-12T14:30:00Z","actor":"Planner","type":"PLAN_REVISION_BUMP","detail":{"from":6,"to":7,"reason":"T-0007 failed 3 times"}}

### 4.1 Startup Checklist (Every Request)
- Read /sessions/<session_id>/status.json
- Read /sessions/<session_id>/plan/active/decomposition.json
- Read /sessions/<session_id>/plan/active/metadata.json
- Read tail of /sessions/<session_id>/plan/active/status_log.ndjson
- Read /sessions/<session_id>/critique/review_rules.md if it exists

If any required file is missing:
- Create a question in /sessions/<session_id>/execution/questions (Q-YYYYMMDD-####.json)
- Set system_status=BLOCKED in /sessions/<session_id>/status.json and increment blocked_count
- Append a SYSTEM_BLOCKED event to /sessions/<session_id>/plan/active/status_log.ndjson

## 5. Role Isolation (쓰기 권한 규칙)
SESSION_ROOT=/sessions/<session_id>

Planner: SESSION_ROOT/plan/**, SESSION_ROOT/execution/questions/** 읽기/쓰기, SESSION_ROOT/context/index.json 읽기만.  
Executor: SESSION_ROOT/execution/run_logs/**, SESSION_ROOT/execution/outputs/**, SESSION_ROOT/execution/questions/** 쓰기, SESSION_ROOT/plan/** 읽기만.  
Critic: SESSION_ROOT/critique/** 쓰기, SESSION_ROOT/execution/outputs/** 읽기, SESSION_ROOT/context/index.json 쓰기(승격 시만).

시스템 제어자는 role 간 허용된 파일만 접근 가능하도록 강제한다.

## 6. Plan 영역 명세
목적: “무엇을 할지(WHAT)”만 기록.  
구현/도구/코드 금지.  
경로는 SESSION_ROOT 기준이다.

Top-down 분해 원칙:
- task는 level과 parent_id를 포함한다.
- level 1은 상위 목표(phase)이며 parent_id는 null.
- level 2+는 상위 task를 parent_id로 참조하고, parent가 먼저 등장한다.
- task는 data_sources를 포함하며 값은 {SEC, YFINANCE, WEB, SYNTHESIS} 중 하나다.
- data_sources는 정확히 1개만 허용하며, SYNTHESIS는 실행/수집이 아닌 통합 작업이다.
- data_sources 기반 tool_calls를 생성하며 실행 단계는 이를 그대로 수행한다.

goal.md 예시:
프로젝트 목표: HDPS 기반 단일 에이전트 시스템 구축

decomposition.json 스키마:
{
  "major_version": 2,
  "revision": 7,
  "tasks": [
    {
      "id": "T-0007",
      "title": "Planner/Executor/ Critic 분리 파일 I/O 정의",
      "level": 1,
      "parent_id": null,
      "data_sources": ["SYNTHESIS"],
      "deps": ["T-0001","T-0004"],
      "outputs": [
        {"path": "/execution/outputs/T-0007/role_io_spec.md", "type": "spec"},
        {"path": "/execution/outputs/T-0007/review_rules.md", "type": "spec"}
      ],
      "tool_calls": [],
      "acceptance": [
        "role별 쓰기 권한 정의됨",
        "검수 규칙이 명시됨"
      ]
    }
  ]
}

metadata.json 스키마:
{
  "major_version": 2,
  "revision": 7,
  "modification_type": "MINOR",
  "trigger": "T-0007 failed 3 times",
  "last_modified": "2026-01-12T14:30:00Z"
}

change_log.md: append-only 텍스트 로그.

tool_calls 규칙:
- tool_calls는 [{ "name": "<tool_name>", "args": { ... } }] 형식이다.
- SYNTHESIS는 tool_calls가 비어있어야 한다.

## 7. Execution 영역 명세
목적: 실제 수행 기록과 산출물 저장.  
run_logs/ (NDJSON, append-only, SESSION_ROOT/execution/run_logs/)

{"ts":"2026-01-12T14:31:00Z","task_id":"T-0007","actor":"Executor","action":"run_tool","tool":"file_system","input":{"path":"/plan/active/decomposition.json"},"result":"success"}

outputs/  
산출물은 task ID 기준 디렉토리로 격리.  
SESSION_ROOT/execution/outputs/T-0007/...  
실제 코드/문서 결과는 복제본 또는 스냅샷으로 저장.  
원본 경로는 artifact_manifest.json에 기록.

questions/  
Executor가 의사결정 불가 시 질문 등록.
{
  "id": "Q-20260112-0003",
  "task_id": "T-0007",
  "ts": "2026-01-12T14:35:00Z",
  "question": "role별 파일 권한을 OS 수준으로 강제할지?",
  "status": "OPEN"
}

## 8. Critique 영역 명세
목적: 결과물의 품질/유효성 판정.

review_rules.md: 프로젝트 전역 검수 기준.

reports/ 스키마:
{
  "task_id": "T-0007",
  "ts": "2026-01-12T15:00:00Z",
  "verdict": "PASS",
  "findings": [
    {"severity":"HIGH","detail":"role write scope 명시됨"}
  ],
  "required_fixes": []
}

## 9. Context 영역 명세
목적: PASS된 지식만 저장.

index.json 스키마:
{
  "knowledge": [
    {
      "id": "K-0009",
      "source_task_id": "T-0007",
      "artifact_path": "/sessions/<session_id>/execution/outputs/T-0007/role_io_spec.md",
      "status": "ACTIVE",
      "created_at": "2026-01-12T15:05:00Z",
      "invalidated_by": null
    }
  ]
}

state.json 스키마 (routing metadata):
{
  "ticker": "AVGO",
  "company": "Broadcom",
  "year": 2024,
  "min_year": 2019
}

state.json은 Planner가 query와 tasks를 기반으로 추론해 생성한다.

## 10. Sessions 영역 명세 (Session Root)
Session은 다음을 고정한 단위다.
- User Input (원문)
- System Prompt / Operational Mode
- 해당 입력으로 촉발된 HDPS 실행 결과물

Session = f(input, prompt)

세션은 내부 상태와 출력 뷰를 모두 포함한다.

/sessions/S-YYYYMMDD-HHMMSSZ/
 ├─ input/
 │   ├─ user_input.md          # 유저 쿼리 원문
 │   └─ system_prompt.md       # 해당 세션에서 사용된 시스템/운영 프롬프트
 │
 ├─ output/
 │   ├─ final.md               # 유저에게 반환된 최종 응답
 │   ├─ artifacts/             # 유저가 소비할 수 있는 산출물
 │   │   ├─ api_spec.yaml
 │   │   ├─ auth_module.py
 │   │   └─ ...
 │   └─ summary.json           # 출력 메타데이터
 │
 ├─ verdict.md                 # Critic의 최종 판정 요약
 └─ pointers.json              # 내부 HDPS 구조와의 연결 포인터

pointers.json 예시:
{
  "status": "/sessions/<session_id>/status.json",
  "plan": "/sessions/<session_id>/plan/active/decomposition.json",
  "critique_report": "/sessions/<session_id>/critique/reports/T-0007.json",
  "context_index": "/sessions/<session_id>/context/index.json"
}

## 11. Replanning 규칙
상황	처리
단순 구현 오류	Executor 재시도 (run_logs에 실패 누적)
논리적 불가능	major_version++, /sessions/<session_id>/plan/archive/snapshot_* 생성

## 12. 복구/부팅 절차
/sessions/<session_id>/status.json 로딩 → 현재 포인터 확인  
/sessions/<session_id>/plan/active/status_log.ndjson에서 마지막 event 복구  
/sessions/<session_id>/execution/run_logs에서 current_task 수행 상태 확인  
/sessions/<session_id>/critique/reports 존재 여부로 PASS/FAIL 판정  
필요 시 /sessions/<session_id>/plan/archive로 rollback 또는 replanning 수행

## 13. 불변성/원자성 규칙
모든 append-only 로그는 NDJSON으로만 기록.  
파일 쓰기는 temp 파일 → rename으로 원자성 확보.  
변경 금지 파일: /sessions/<session_id>/plan/active/*, /sessions/<session_id>/execution/run_logs/*, /sessions/<session_id>/critique/reports/* (append‑only 예외 제외).

## 14. 최소 실행 흐름
Session root 생성 → input/system_prompt 기록  
Planner: goal.md, decomposition.json, metadata.json 생성  
Executor: task 수행 → run_logs, outputs 기록  
Critic: review_rules.md 기준으로 reports/* 생성  
PASS 시 Context 승격: index.json 업데이트  
output/final.md + summary.json 기록  
status_log.ndjson + status.json 갱신
