# 서버 API (Server API)

Valuator 서버는 에이전트 루프를 구동하고, 모든 분석 과정을 세션 단위로 기록하여 클라이언트에게 RESTful 인터페이스를 제공합니다.

## 1. 프로젝트 아키텍처

서버 코드는 기능에 따라 엔드포인트가 분리되어 있으며, 세션 데이터를 파일 시스템에 유지합니다.

```text
server/
├── main.py                 # FastAPI 앱 초기화 및 미들웨어 설정
├── chat_api.py            # 핵심 분석 (/api/chat) 엔드포인트
├── session_viewer_api.py  # 세션 및 로그 조회 API
└── session_store.py       # 세션 객체 및 파일 입출력 관리
```

---

## 2. API 엔드포인트 개요

### Chat API (`/api/chat` 프리픽스)

| 메서드 | 엔드포인트 | 설명 |
| :--- | :--- | :--- |
| `POST` | `/api/chat/authenticate` | 세션 인증 (SSE 연결 전 필수) |
| `POST` | `/api/chat/messages` | 메시지 전송 (분석 요청) |
| `GET` | `/api/chat/messages` | 메시지 히스토리 조회 |
| `DELETE` | `/api/chat/messages` | 메시지 초기화 |
| `GET` | `/api/chat/stream` | SSE 스트림 (실시간 진행 상태) |
| `GET` | `/api/chat/agent-status` | 에이전트 상태 조회 |
| `POST` | `/api/chat/stop` | 에이전트 실행 중단 |
| `GET` | `/api/chat/web-search-providers` | 사용 가능한 웹 검색 제공자 목록 |

### Session Viewer API

| 메서드 | 엔드포인트 | 설명 |
| :--- | :--- | :--- |
| `GET` | `/api/session/default-explore` | 최신 세션 정보 조회 |
| `GET` | `/api/session/browse-outline` | 세션 작업 트리 구조 |
| `GET` | `/api/tree` | 파일 시스템 트리 |
| `GET` | `/api/file` | 파일 조회 |
| `PUT` | `/api/file` | 파일 저장 |

### File System API (`/api/fs` 프리픽스)

| 메서드 | 엔드포인트 | 설명 |
| :--- | :--- | :--- |
| `POST` | `/api/fs/create` | 파일/폴더 생성 |
| `POST` | `/api/fs/rename` | 파일/폴더 이름 변경 |
| `POST` | `/api/fs/delete` | 파일/폴더 삭제 |
| `POST` | `/api/fs/move` | 파일/폴더 이동 |
| `POST` | `/api/fs/copy` | 파일/폴더 복사 |

### Utility

| 메서드 | 엔드포인트 | 설명 |
| :--- | :--- | :--- |
| `GET` | `/api/search` | 파일 검색 |
| `GET` | `/health` | 서버 상태 확인 |

---

## 3. 상세 엔드포인트 명세

### Chat API

#### [POST] 세션 인증 (`/api/chat/authenticate`)
SSE 연결을 위한 세션 인증. 모든 SSE 스트림 호출 전에 먼저 호출해야 합니다.

**Request Body**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Response**
```json
{
  "authenticated": true,
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "expires_at": "2026-04-21T12:00:00Z"
}
```

---

#### [POST] 메시지 전송 (`/api/chat/messages`)
사용자의 질의를 전송하여 에이전트 실행을 시작합니다.

**Request Body**
```json
{
  "message": "Apple의 2024 회계연도 수익 분석",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "llm_backend": "google_genai",
  "model": "gemini-2.0-flash",
  "web_search_provider": "google",
  "openrouter_api_key": null
}
```

**Response** (비동기 실행, 즉시 반환)
```json
{
  "message_id": "msg-001",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "submitted"
}
```

**옵션 설명:**
- `llm_backend`: "google_genai" (기본) 또는 "openrouter"
- `web_search_provider`: "google" (기본) 또는 다른 제공자
- `model`: LLM 모델명 (llm_backend에 따라 다름)

---

#### [GET] 메시지 히스토리 (`/api/chat/messages`)

**Query Parameters**
```
session_id=550e8400-e29b-41d4-a716-446655440000
```

**Response**
```json
{
  "messages": [
    {
      "id": "msg-001",
      "role": "user",
      "content": "Apple의 2024 회계연도 수익 분석",
      "timestamp": "2026-04-21T10:00:00Z"
    },
    {
      "id": "msg-002",
      "role": "assistant",
      "content": "분석을 시작하겠습니다...",
      "timestamp": "2026-04-21T10:00:05Z"
    }
  ]
}
```

---

#### [GET] SSE 스트림 (`/api/chat/stream`)
실시간 진행 상태를 Server-Sent Events로 수신합니다.

**Query Parameters**
```
session_id=550e8400-e29b-41d4-a716-446655440000
```

**Response** (스트림)
```
event: progress
data: {"type": "step", "message": "계획 중: Revenue 분석..."}

event: progress
data: {"type": "done", "task_id": "root-c1", "output": "$195B"}

event: complete
data: {"final_output": "분석 완료: ..."}
```

**메시지 타입:**
- `step`: 단계 진행 정보
- `done`: 작업 완료
- `failed`: 작업 실패
- `complete`: 전체 완료

---

#### [GET] 에이전트 상태 (`/api/chat/agent-status`)

**Query Parameters**
```
session_id=550e8400-e29b-41d4-a716-446655440000
```

**Response**
```json
{
  "status": "running",
  "active_task": {
    "id": "root-c1",
    "name": "Revenue Analysis",
    "phase": "COLLECT",
    "progress": 0.6
  },
  "elapsed_seconds": 12.5
}
```

---

#### [POST] 에이전트 중단 (`/api/chat/stop`)

**Request Body**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Response**
```json
{
  "stopped": true,
  "reason": "User requested"
}
```

---

#### [GET] 웹 검색 제공자 (`/api/chat/web-search-providers`)

**Response**
```json
{
  "providers": [
    {"id": "google", "name": "Google Search", "available": true},
    {"id": "bing", "name": "Bing Search", "available": false}
  ]
}
```

---

### Session Viewer API

#### [GET] 최신 세션 (`/api/session/default-explore`)

**Response**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "created_at": "2026-04-21T10:00:00Z",
  "status": "completed",
  "final_output": "분석 결과: ..."
}
```

---

#### [GET] 작업 트리 (`/api/session/browse-outline`)

**Query Parameters**
```
session_id=550e8400-e29b-41d4-a716-446655440000
```

**Response**
```json
{
  "root": {
    "id": "root",
    "name": "Apple Stock Analysis",
    "phase": "SYNTHESIZE",
    "children": [
      {
        "id": "root-c1",
        "name": "Revenue Analysis",
        "phase": "DONE",
        "children": []
      },
      {
        "id": "root-c2",
        "name": "PE Ratio Analysis",
        "phase": "DONE",
        "children": []
      }
    ]
  }
}
```

---

### File System API

#### [GET] 파일 시스템 트리 (`/api/tree`)

**Query Parameters**
```
session_id=550e8400-e29b-41d4-a716-446655440000
path=/results
```

**Response**
```json
{
  "type": "directory",
  "name": "results",
  "path": "/results",
  "children": [
    {"type": "file", "name": "analysis.md", "path": "/results/analysis.md"},
    {"type": "directory", "name": "logs", "path": "/results/logs"}
  ]
}
```

---

#### [GET] 파일 조회 (`/api/file`)

**Query Parameters**
```
session_id=550e8400-e29b-41d4-a716-446655440000
path=/results/analysis.md
```

**Response**
```json
{
  "path": "/results/analysis.md",
  "content": "# Apple 분석\n\n## 수익...",
  "mime_type": "text/markdown"
}
```

---

#### [PUT] 파일 저장 (`/api/file`)

**Request Body**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "path": "/results/custom.md",
  "content": "# 커스텀 분석\n..."
}
```

---

#### [POST] 파일 시스템 작업 (`/api/fs/*`)

**Create File/Directory** (`/api/fs/create`)
```json
{
  "session_id": "...",
  "path": "/results/new_folder",
  "type": "directory"
}
```

**Rename** (`/api/fs/rename`)
```json
{
  "session_id": "...",
  "path": "/results/old_name.md",
  "new_name": "new_name.md"
}
```

---

### 검색 API

#### [GET] 파일 검색 (`/api/search`)

**Query Parameters**
```
session_id=550e8400-e29b-41d4-a716-446655440000
q=수익
```

**Response**
```json
{
  "results": [
    {"path": "/results/analysis.md", "matches": 3},
    {"path": "/results/logs/trace.log", "matches": 1}
  ]
}
```

---

## 4. 내부 실행 흐름 (Request Lifecycle)

### 전체 시나리오

```
클라이언트
  ├─ [1] POST /api/chat/authenticate (session_id)
  │   └─ 서버: 세션 등록 및 인증 토큰 발급
  │
  ├─ [2] POST /api/chat/messages (query, llm_backend, model)
  │   └─ 서버: 에이전트 비동기 시작
  │
  ├─ [3] GET /api/chat/stream (session_id) - SSE 연결 유지
  │   └─ 서버: 실시간 진행 상황 스트리밍
  │
  └─ [4] GET /api/chat/agent-status (세션_id) - 폴링
      └─ 서버: 현재 상태 응답
```

### 상세 단계

1.  **세션 인증** (`/api/chat/authenticate`):
    - 클라이언트가 session_id를 전송
    - 서버가 세션 인증 정보를 저장 (24시간 TTL)
    - X-Auth-Key/Secret 헤더 발급

2.  **메시지 전송** (`/api/chat/messages` POST):
    - 세션 검증 및 메시지 저장
    - 요청된 모델에 맞춰 `ToolRegistry`와 `LLMClient` 인스턴스화
    - **비동기 백그라운드 작업으로 에이전트 시작**
    - 메시지 ID 즉시 반환 (완료 대기 안 함)

3.  **에이전트 실행** (백그라운드):
    - `Scheduler`, `TraceWriter`를 에이전트에 주입
    - `Agent.run()` 비동기 루프 실행
    - 각 이벤트마다 `on_event` 콜백으로 SSE 스트림에 발행

4.  **SSE 스트리밍** (`/api/chat/stream` GET):
    - 클라이언트가 SSE 연결 유지
    - 서버가 실시간으로 진행 상황 전송
    - 최종 완료 또는 실패 이벤트 전송

5.  **상태 폴링** (`/api/chat/agent-status` GET):
    - 현재 활성 작업, 경과 시간, 토큰 사용량 등 조회
    - 클라이언트가 주기적으로 호출

6.  **종료**:
    - 에이전트 완료 후 최종 output을 메시지 저장소에 기록
    - `metadata.json`에 실행 시간, 토큰 사용량 업데이트
    - 세션 상태를 "completed" 또는 "failed"로 변경

---

## 5. 세션 및 로그 관리 (Persistence)

모든 분석 세션은 고유 디렉토리에 저장되어 서버 재시작 후에도 조회가 가능합니다.

### 디렉토리 구조
```text
valuator/sessions/
└── S-20260405-104410Z/       # 세션 고유 ID
    ├── metadata.json         # 상태, 시간, 토큰 사용량 등 요약
    ├── trace.jsonl           # 모든 AgentEvent의 순차적 기록
    └── trace_markdown.md     # 사람이 읽기 편하도록 렌더링된 로그
```

### 세션 데이터 객체 (`Session`)
```python
class Session:
    def __init__(self, id: str, dir: Path, trace_writer):
        self.id = id
        self.dir = dir
        self.trace_writer = trace_writer # JSONL 기록 담당
        self.created_at = datetime.now(UTC)
        self.status = "in_progress"
```

---

## 6. 클라이언트 사용 예시

### Python (httpx + SSE 사용)
```python
import httpx
import asyncio
import uuid

async def run_analysis():
    base_url = "http://localhost:8000"
    
    # 1. 세션 생성 및 인증
    session_id = str(uuid.uuid4())
    auth_res = await client.post(
        f"{base_url}/api/chat/authenticate",
        json={"session_id": session_id}
    )
    print(f"인증 완료: {auth_res.json()}")
    
    # 2. 분석 요청 (비동기)
    message_res = await client.post(
        f"{base_url}/api/chat/messages",
        json={
            "message": "Apple의 2024 회계연도 수익 분석",
            "session_id": session_id,
            "llm_backend": "google_genai",
            "model": "gemini-2.0-flash",
            "web_search_provider": "google"
        }
    )
    msg_id = message_res.json()["message_id"]
    print(f"분석 시작: {msg_id}")
    
    # 3. SSE 스트림으로 실시간 진행 상황 수신
    async with client.stream(
        "GET",
        f"{base_url}/api/chat/stream",
        params={"session_id": session_id}
    ) as response:
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                event = line.replace("data:", "").strip()
                print(f"진행: {event}")
    
    # 4. 최종 메시지 조회
    messages_res = await client.get(
        f"{base_url}/api/chat/messages",
        params={"session_id": session_id}
    )
    messages = messages_res.json()["messages"]
    for msg in messages:
        print(f"[{msg['role']}] {msg['content']}")
```

### TypeScript (Node.js)
```typescript
async function runAnalysis() {
    const sessionId = crypto.randomUUID();
    const baseUrl = "http://localhost:8000";
    
    // 1. 인증
    const authRes = await fetch(`${baseUrl}/api/chat/authenticate`, {
        method: "POST",
        body: JSON.stringify({ session_id: sessionId })
    });
    
    // 2. 분석 시작
    const msgRes = await fetch(`${baseUrl}/api/chat/messages`, {
        method: "POST",
        body: JSON.stringify({
            message: "Apple 수익 분석",
            session_id: sessionId,
            llm_backend: "google_genai"
        })
    });
    
    // 3. SSE 스트림 구독
    const eventSource = new EventSource(
        `${baseUrl}/api/chat/stream?session_id=${sessionId}`
    );
    
    eventSource.addEventListener("progress", (e) => {
        console.log("진행:", JSON.parse(e.data));
    });
    
    eventSource.addEventListener("complete", () => {
        eventSource.close();
    });
}
```

---

## 7. 서버 실행 및 설정

### CORS 설정
프론트엔드(React/Vue 등)와의 통신을 위해 `main.py`에서 허용된 오리진(Origin)을 관리합니다. 기본적으로 `localhost:5173` 및 `3000` 포트가 개방되어 있습니다.

### 실행 명령
```bash
# Valuator 루트 디렉토리에서 실행
uvicorn server.main:app --reload --port 8000
```

> [!TIP]
> **디버깅 모드**
> 실시간 로그 출력을 확인하려면 `--log-level debug` 옵션을 추가하세요. 세션 로그는 `valuator/sessions/` 디렉토리에서 실시간으로 생성되는 `.jsonl` 파일을 통해 `tail -f`로 관찰할 수도 있습니다.

---
**업데이트 확인:** 이 문서는 2026년 4월 기준 API 명세를 바탕으로 작성되었습니다. 모델 가격이나 엔드포인트 변경 시 업데이트가 필요합니다.