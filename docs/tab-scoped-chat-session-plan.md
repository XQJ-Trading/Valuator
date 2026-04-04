# 탭 단위 채팅 세션 전환 플랜

## 1. 문제 정의

현재 채팅 세션은 브라우저 탭 단위가 아니라 서버 전역 단위다.

- 모든 탭이 같은 `/api/chat/*` 엔드포인트를 공유한다.
- 메시지 저장 파일이 `_chat/messages.json` 하나로 고정돼 있다.
- 실행 상태도 `_agent_task`, `_agent_process`, `_subscribers` 전역 변수 1세트로 유지된다.

이 구조에서는 아래 문제가 생긴다.

- 여러 탭을 띄우면 서로 같은 채팅을 본다.
- 한 탭의 `stop`/`clear`가 다른 탭에도 영향을 준다.
- 사용자는 새 탭이 독립 작업 공간인지 공유 작업 공간인지 예측하기 어렵다.

## 2. 목표 동작

목표는 "탭 단위 독립 세션 + 같은 탭 새로고침 시 유지"다.

- 같은 탭에서 새로고침하면 같은 채팅 세션을 계속 사용한다.
- 새 탭을 열면 새 채팅 세션을 만든다.
- 다른 탭의 메시지/실행 상태/중지는 서로 영향을 주지 않는다.
- 서버 재시작 전까지는 세션 상태를 복구할 수 있다.

## 3. 비목표

이번 변경에서 바로 해결하지 않는 범위:

- 사용자 로그인 단위 세션 공유
- 여러 기기 간 세션 동기화
- 세션 공유 링크
- 세션 간 메시지 병합

## 4. 세션 모델

세션 식별자는 `chat_session_id`로 통일한다.

- 생성 위치: 클라이언트
- 저장 위치: `sessionStorage`
- 사용 범위: 현재 브라우저 탭
- 수명: 탭이 살아 있는 동안 유지, 새로고침 시 유지

이 선택의 의미:

- `sessionStorage`는 새로고침 후에도 유지된다.
- `sessionStorage`는 탭 간 공유되지 않는다.
- `localStorage`를 쓰지 않으므로 멀티탭 충돌을 피할 수 있다.

## 5. 설계 원칙

- 세션 경계는 HTTP/SSE boundary에서 한 번만 결정한다.
- 서버 내부 로직은 `chat_session_id`가 이미 유효하다고 가정한다.
- `messages`, `agent-status`, `stop`, `clear`, `stream`은 반드시 같은 세션 키를 사용해야 한다.
- 채팅 저장과 실행 상태는 같은 세션 키를 기준으로 묶어야 한다.

## 6. 프론트엔드 변경 계획

### 6-1. 세션 ID 생성/보관

`client`에서 앱 시작 시 `chat_session_id`를 읽는다.

- `sessionStorage.getItem("chat_session_id")`
- 없으면 `crypto.randomUUID()`로 생성
- 생성한 값을 `sessionStorage.setItem(...)`에 저장

이 로직은 앱 전체에서 단일 source of truth여야 한다.

### 6-2. API 요청에 세션 ID 포함

아래 요청은 모두 같은 `chat_session_id`를 전달해야 한다.

- `GET /api/chat/messages`
- `POST /api/chat/messages`
- `DELETE /api/chat/messages`
- `GET /api/chat/agent-status`
- `POST /api/chat/stop`
- `GET /api/chat/stream`

전달 방식 후보:

1. query parameter
- 장점: SSE에 바로 붙이기 쉽다.
- 단점: URL에 식별자가 노출된다.

2. custom header
- 장점: API 형태가 깔끔하다.
- 단점: 브라우저 `EventSource`는 커스텀 헤더를 직접 보내기 어렵다.

현재 구조에서는 query parameter가 가장 단순하다.

권장:

- HTTP: `?session_id=...`
- SSE: `/api/chat/stream?session_id=...`

### 6-3. 클라이언트 상태 초기화 규칙

탭 내부 상태는 세션 ID와 함께 묶어서 생각해야 한다.

- 세션 ID가 바뀌면 메시지/실행 상태/outline refresh tick을 새 세션 기준으로 초기화
- 일반 새로고침에서는 같은 세션 ID를 그대로 사용하므로 복구만 수행

## 7. 백엔드 변경 계획

### 7-1. 세션 ID를 boundary에 추가

`server/chat_api.py`의 모든 엔드포인트가 `session_id`를 받도록 바꾼다.

예시:

- `GET /api/chat/messages?session_id=...`
- `POST /api/chat/messages?session_id=...`
- `POST /api/chat/stop?session_id=...`
- `GET /api/chat/stream?session_id=...`

입력 검증은 boundary에서만 한다.

- 빈 값 금지
- 허용 가능한 문자열 형식만 통과
- 파일 경로로 직접 사용하지 않도록 path-safe 변환 필요

### 7-2. 전역 단일 상태를 세션별 상태로 변경

현재:

- `_agent_task: Task | None`
- `_agent_process: Process | None`
- `_subscribers: list[Queue]`

변경 후:

- `_agent_tasks: dict[str, Task[None]]`
- `_agent_processes: dict[str, Process]`
- `_subscribers_by_session: dict[str, list[Queue[dict]]]`

핵심은 세션마다 아래가 독립적이어야 한다는 점이다.

- 실행 중 여부
- stop 대상 프로세스
- SSE 구독자 목록

### 7-3. 메시지 저장 경로 분리

현재는 `_chat/messages.json` 한 파일이다.

변경 후보:

1. `_chat/<session_id>/messages.json`
2. `_chat/sessions/<session_id>.json`

권장:

`_chat/<session_id>/messages.json`

이유:

- 세션별 부가 메타데이터 파일을 나중에 두기 쉽다.
- 디렉터리 단위 삭제가 단순하다.

### 7-4. 세션별 헬퍼로 묶을 최소 책임

과한 추상화는 피하고 아래 정도만 분리한다.

- `session_id -> chat file path`
- `session_id -> subscriber list`
- `session_id -> active task/process`

목표는 main flow를 짧게 유지하는 것이지, 범용 세션 프레임워크를 만드는 것이 아니다.

## 8. API 계약 변경안

### `GET /api/chat/messages`

- 입력: `session_id`
- 출력: 해당 세션의 메시지 목록

### `POST /api/chat/messages`

- 입력: `session_id`, `text`
- 동작: 해당 세션에만 user message append, 해당 세션에만 agent run 시작
- 동시성: 같은 `session_id`에서만 1개 run 허용

### `POST /api/chat/stop`

- 입력: `session_id`
- 동작: 해당 세션의 run만 중지

### `DELETE /api/chat/messages`

- 입력: `session_id`
- 동작: 해당 세션의 run 중지 후 해당 세션 메시지만 초기화

### `GET /api/chat/agent-status`

- 입력: `session_id`
- 출력: 해당 세션 실행 중 여부

### `GET /api/chat/stream`

- 입력: `session_id`
- 동작: 해당 세션의 SSE 이벤트만 구독

## 9. 동시성/정합성 고려사항

- 서로 다른 세션은 동시에 실행 가능해야 한다.
- 같은 세션에서는 여전히 한 번에 하나의 run만 허용한다.
- cleanup은 세션 단위 소유권 검사 후 수행해야 한다.
- 오래된 run이 같은 세션의 더 새로운 handle을 지우면 안 된다.
- 다른 세션의 handle을 건드릴 가능성은 구조적으로 없어야 한다.

## 10. 새로고침 복구 시나리오

### 기대 흐름

1. 탭이 처음 열리면 `chat_session_id` 생성
2. 새로고침 시 같은 `chat_session_id`를 다시 읽음
3. 클라이언트가 같은 `session_id`로 `/messages`, `/agent-status`, `/stream` 재연결
4. 기존 메시지와 실행 상태가 복구됨

### 경계 사례

- 서버 재시작 시 메모리 상태는 사라질 수 있다.
- 이 경우 메시지 파일은 남아도 실행 중 상태는 복구되지 않을 수 있다.
- 필요하면 나중에 세션 메타데이터 파일을 둬서 "마지막 known state"를 표시할 수 있다.

## 11. 정리 정책

탭 단위 세션을 도입하면 세션 수가 늘어난다. 정리 정책이 필요하다.

최소 정책:

- 오래된 세션 메시지 디렉터리를 주기적으로 삭제
- 기준: 마지막 수정 시각 기준 N일 보관

확장 가능 정책:

- `last_accessed_at` 메타데이터 유지
- 세션 개수 상한
- 수동 세션 삭제 UI

초기 구현에서는 "파일 수정 시각 기준 TTL 삭제" 정도면 충분하다.

## 12. 테스트 계획

### 서버 테스트

- 서로 다른 `session_id`로 보낸 메시지가 섞이지 않는지
- `session_a` 실행 중 `session_b`는 새 메시지를 정상 수락하는지
- `stop(session_a)`가 `session_b`에 영향이 없는지
- `clear(session_a)`가 `session_b` 메시지를 지우지 않는지
- 같은 `session_id` 새로고침 시 `agent-status`가 복구되는지

### 클라이언트 테스트

- 새로고침 시 같은 `chat_session_id`를 재사용하는지
- 새 탭에서는 새 `chat_session_id`가 생기는지
- SSE가 현재 탭 세션 이벤트만 반영하는지

### 수동 확인 시나리오

1. 탭 A에서 질문 전송
2. 탭 A 새로고침
3. 진행 중 상태와 메시지 복구 확인
4. 탭 B 새로 열기
5. 탭 B가 빈 세션으로 시작하는지 확인
6. 탭 B에서 질문 전송
7. 탭 A/B 메시지와 stop 버튼 영향 범위가 분리됐는지 확인

## 13. 구현 순서

### 1단계: 세션 ID plumbing

- 프론트에서 `chat_session_id` 생성 및 `sessionStorage` 저장
- 모든 chat API/SSE에 `session_id` 전달

### 2단계: 서버 세션 분리

- `session_id`별 메시지 저장 경로 분리
- `session_id`별 task/process/subscriber 분리

### 3단계: 회귀 테스트 보강

- 멀티세션 독립성 테스트 추가
- 새로고침 복구 테스트 추가

### 4단계: 운영 정리

- TTL 기반 세션 정리 정책 추가
- 필요하면 세션 메타데이터 저장 도입

## 14. 권장 구현 범위

첫 PR은 아래만 포함하는 것이 적절하다.

- `sessionStorage` 기반 `chat_session_id`
- query parameter 기반 chat API/SSE 세션 전달
- 서버의 세션별 메시지/실행 상태 분리
- 멀티세션 회귀 테스트

첫 PR에서 제외해도 되는 것:

- 공유 링크
- URL 동기화
- 세션 목록 UI
- 세션 정리 백그라운드 잡

## 15. 결정 사항 요약

- 현재 구조: 서버 전역 공유 채팅 세션
- 목표 구조: 탭 단위 독립 채팅 세션
- 같은 탭 새로고침: 유지
- 새 탭 열기: 새 세션
- 세션 키 저장소: `sessionStorage`
- API 식별자: `chat_session_id`
- 초기 전달 방식: query parameter
