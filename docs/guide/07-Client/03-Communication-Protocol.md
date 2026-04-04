# Client-Server 통신 프로토콜

## 개요

클라이언트와 서버는 **HTTP + Server-Sent Events (SSE)**로 통신합니다.

| 통신 방식 | 용도 | 특성 |
|---------|------|------|
| **REST API (HTTP)** | 명령형 작업 (메시지 전송, 상태 조회) | Request-Response, 일회성 |
| **SSE (EventSource)** | 실시간 이벤트 스트림 | 단방향, 서버 → 클라이언트, 지속 연결 |

## REST API 엔드포인트

### 1. 메시지 관리

#### `POST /api/chat/messages`

사용자 메시지를 전송하고 에이전트 실행을 트리거합니다.

**요청**:
```http
POST /api/chat/messages?session_id=uuid
Content-Type: application/json

{
  "text": "Apple의 2024년 수익 분석"
}
```

**응답** (200 OK):
```json
{
  "id": "msg-123456",
  "role": "user",
  "text": "Apple의 2024년 수익 분석",
  "ts": "2026-04-05T10:30:45.123Z"
}
```

**에러** (400/500):
```json
{
  "detail": "Invalid session_id"
}
```

**클라이언트 코드**:
```typescript
export async function postChatMessage(
  sessionId: string,
  text: string,
): Promise<ChatMessage> {
  const res = await fetch(chatApiPath("/api/chat/messages", sessionId), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  return res.json() as Promise<ChatMessage>
}
```

#### `GET /api/chat/messages`

현재 세션의 모든 메시지를 조회합니다.

**요청**:
```http
GET /api/chat/messages?session_id=uuid
```

**응답** (200 OK):
```json
{
  "messages": [
    {
      "id": "msg-1",
      "role": "user",
      "text": "Apple 수익",
      "ts": "2026-04-05T10:30:45.123Z"
    },
    {
      "id": "msg-2",
      "role": "assistant",
      "text": "Apple의 2024년 총 매출은...",
      "ts": "2026-04-05T10:35:12.456Z"
    }
  ]
}
```

**클라이언트 코드**:
```typescript
export async function fetchChatMessages(sessionId: string): Promise<ChatMessage[]> {
  const res = await fetch(chatApiPath("/api/chat/messages", sessionId))
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const data = (await res.json()) as { messages: ChatMessage[] }
  return data.messages
}
```

#### `DELETE /api/chat/messages`

세션의 모든 메시지를 삭제하고 초기화합니다.

**요청**:
```http
DELETE /api/chat/messages?session_id=uuid
```

**응답** (204 No Content):
```
(empty)
```

**클라이언트 코드**:
```typescript
export async function clearChatMessages(sessionId: string): Promise<void> {
  const res = await fetch(chatApiPath("/api/chat/messages", sessionId), {
    method: "DELETE",
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
}
```

### 2. 에이전트 제어

#### `POST /api/chat/stop`

실행 중인 에이전트를 중단합니다.

**요청**:
```http
POST /api/chat/stop?session_id=uuid
```

**응답** (200 OK):
```json
{
  "ok": true,
  "stopped": true
}
```

**클라이언트 코드**:
```typescript
export async function postChatStop(
  sessionId: string,
): Promise<{ ok: boolean; stopped: boolean }> {
  const res = await fetch(chatApiPath("/api/chat/stop", sessionId), {
    method: "POST",
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  return res.json() as Promise<{ ok: boolean; stopped: boolean }>
}
```

#### `GET /api/chat/agent-status`

에이전트 실행 상태를 확인합니다.

**요청**:
```http
GET /api/chat/agent-status?session_id=uuid
```

**응답** (200 OK):
```json
{
  "running": false
}
```

**클라이언트 코드**:
```typescript
export async function fetchAgentRunning(sessionId: string): Promise<boolean> {
  const res = await fetch(chatApiPath("/api/chat/agent-status", sessionId))
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const data = (await res.json()) as { running?: boolean }
  return Boolean(data.running)
}
```

## Server-Sent Events (SSE) 스트림

### 개요

클라이언트가 서버의 이벤트 스트림을 구독합니다. 연결이 유지되는 동안 서버는 실시간으로 이벤트를 푸시합니다.

**사용 방식**:
```typescript
// api.ts
export function chatStreamPath(sessionId: string): string {
  return chatApiPath("/api/chat/stream", sessionId)
}

// ChatSessionContext.tsx
const es = new EventSource(chatStreamPath(chatSessionId))
es.onmessage = (ev) => {
  const payload = JSON.parse(ev.data)
  // 이벤트 처리
}
```

### 이벤트 타입

#### 1. `ChatMessage` (메시지)

사용자 또는 어시스턴트의 메시지입니다.

```json
{
  "id": "msg-123",
  "role": "user",
  "text": "메시지 본문",
  "ts": "2026-04-05T10:30:45.123Z"
}
```

또는

```json
{
  "id": "msg-456",
  "role": "assistant",
  "text": "응답 내용",
  "ts": "2026-04-05T10:35:12.456Z"
}
```

**처리**:
```typescript
const msg = payload as ChatMessage
if (typeof msg.id === "string" && (msg.role === "user" || msg.role === "assistant")) {
  if (!messageIdsRef.current.has(msg.id)) {
    messageIdsRef.current.add(msg.id)
    setMessages(prev => [...prev, msg])
  }
}
```

#### 2. `agent_started` (에이전트 시작)

에이전트 루프가 시작되었습니다.

```json
{
  "type": "agent_started"
}
```

**처리**:
```typescript
if (typed.type === "agent_started") {
  setAgentRunning(true)
  setLastStepFlow(null)
}
```

#### 3. `agent_finished` (에이전트 완료)

에이전트 루프가 완료되었습니다.

```json
{
  "type": "agent_finished"
}
```

**처리**:
```typescript
if (typed.type === "agent_finished") {
  setAgentRunning(false)
  setLastStepFlow(null)
  onBrowseOutlineRefreshRef.current?.()  // 콜백 호출
}
```

#### 4. `task_progress` (작업 진행상황)

에이전트가 작업을 진행 중입니다.

```json
{
  "type": "task_progress",
  "line": "g0/l1 [task-1.0] Analyzing revenue trends"
}
```

**포맷**: `g{globalSeq}/l{localStep} [{taskId}] {description}`

**파싱**:
```typescript
if (typed.type === "task_progress") {
  const raw = (payload as { line: string }).line
  const item = parseProgressLine(raw)
  
  if (item.kind === "step") {
    // g0/l1 형식의 진행상황
    setTaskDescriptions(prev => 
      new Map(prev).set(item.taskId, item.description)
    )
    setTaskDisplayNames(prev => 
      new Map(prev).set(item.taskId, item.taskName || item.taskId)
    )
    setActiveTaskIds(prev =>
      prev.includes(item.taskId) ? prev : [...prev, item.taskId]
    )
  } else if (item.kind === "done" || item.kind === "failed") {
    // 작업 완료 또는 실패
    setActiveTaskIds(prev => prev.filter(id => id !== item.taskId))
  }
}
```

#### 5. `reset` (세션 리셋)

세션이 초기화되었습니다. 클라이언트는 모든 상태를 리셋합니다.

```json
{
  "type": "reset",
  "ts": "2026-04-05T10:40:00.000Z"
}
```

**처리**:
```typescript
if (isChatResetEvent(payload as ChatMessage | ChatResetEvent)) {
  messageIdsRef.current = new Set()
  setMessages([])
  setActiveTaskIds([])
  setTaskDisplayNames(new Map())
  setTaskDescriptions(new Map())
  setAgentRunning(false)
  setLastStepFlow(null)
  onMessagesUpdatedRef.current?.()
  onBrowseOutlineRefreshRef.current?.()
}
```

## 요청/응답 순서 (시나리오)

### 시나리오 1: 사용자 질의 → 에이전트 실행 → 완료

```
시간
│
├─ T0: 사용자 입력
│   └─→ POST /api/chat/messages {"text": "..."}
│       ← 200 ChatMessage { role: "user", ... }
│
├─ T1: 에이전트 백그라운드 시작
│   (SSE 이벤트만 수신, REST 호출 X)
│
├─ T2-T5: SSE 스트림
│   ← { type: "agent_started" }
│   ← { type: "task_progress", line: "g0/l1 [task-1.0] ..." }
│   ← { type: "task_progress", line: "g1/l1 [task-1.1] ..." }
│   ← { type: "task_progress", line: "g0/l2 [task-1.0] ..." }
│   ← { type: "task_progress", line: "done [task-1.1]" }
│   ← { type: "agent_finished" }
│   ← ChatMessage { role: "assistant", text: "...", ... }
│
└─ T6: 완료
    클라이언트: messages 업데이트, UI 렌더링
```

### 시나리오 2: 사용자 중단

```
│
├─ T0-T3: 에이전트 실행 중
│
├─ T3.5: 사용자 "중단" 클릭
│   └─→ POST /api/chat/stop
│       ← 200 { ok: true, stopped: true }
│
├─ T4: SSE 이벤트
│   ← { type: "agent_finished" }
│   (또는 ChatMessage with "Interrupted" 메시지)
│
└─ T5: 완료
    클라이언트: agentRunning = false
```

## 에러 처리

### HTTP 에러

**400 Bad Request** (잘못된 요청):
```json
{
  "detail": "Invalid input"
}
```

**404 Not Found** (세션 없음):
```json
{
  "detail": "Session not found"
}
```

**500 Internal Server Error**:
```json
{
  "detail": "Internal server error"
}
```

**클라이언트 처리**:
```typescript
async function parseErrorBody(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as {
      error?: string
      detail?: string | Array<{ msg?: string }>
    }
    if (body.error) return body.error
    if (typeof body.detail === "string") return body.detail
    if (Array.isArray(body.detail)) {
      const first = body.detail.find(entry => typeof entry?.msg === "string")
      if (first?.msg) return first.msg
    }
    return `request ${res.status}`
  } catch {
    return `request ${res.status}`
  }
}
```

### SSE 연결 오류

```typescript
es.onerror = (ev) => {
  console.error("SSE connection error", ev)
  // EventSource는 자동 재연결 시도
}
```

## 세션 ID 관리

### 생성
```typescript
function getOrCreateChatSessionId(): string {
  const existing = window.sessionStorage.getItem("chat_session_id")?.trim()
  if (existing) return existing
  
  const sessionId = window.crypto.randomUUID()
  window.sessionStorage.setItem("chat_session_id", sessionId)
  return sessionId
}
```

### 전달
```typescript
function chatApiPath(path: string, sessionId: string): string {
  const q = new URLSearchParams({ session_id: sessionId })
  return `${path}?${q.toString()}`
}

// 모든 API 호출에 적용
fetch(chatApiPath("/api/chat/messages", sessionId), ...)
```

### 저장소
- **클라이언트**: `sessionStorage["chat_session_id"]`
- **서버**: `sessions/{session_id}/` 디렉토리 (파일 시스템)

## 타입 정의

### ChatMessage
```typescript
interface ChatMessage {
  id: string              // 고유 메시지 ID
  role: "user" | "assistant"
  text: string            // 메시지 본문
  ts: string              // ISO 8601 타임스탐프
}
```

### StepFlowSnapshot
```typescript
type StepFlowSnapshot = {
  taskId: string          // 예: "task-1.0"
  taskName?: string       // 예: "Analyze Revenue"
  globalSeq?: number      // 전체 진행 순서 (g)
  localStep?: number      // 해당 작업 내 단계 (l)
  description: string     // 현재 작업 설명
}
```

## 성능 및 최적화

### 1. 메시지 배치
- 클라이언트는 개별 메시지를 수신할 때마다 처리
- 대용량 응답은 여러 이벤트로 분산 전송

### 2. 중복 제거
```typescript
const messageIdsRef = useRef<Set<string>>(new Set())
if (messageIdsRef.current.has(msg.id)) return  // 중복 무시
messageIdsRef.current.add(msg.id)
```

### 3. 연결 유지
- SSE는 자동으로 재연결 시도 (지수 백오프)
- 클라이언트는 주기적으로 `fetchAgentRunning()` 호출으로 상태 확인

### 4. CORS
서버의 CORS 설정:
```python
allow_origins=["localhost:5173", "localhost:3000"]
allow_methods=["GET", "POST", "DELETE", "PUT"]
allow_headers=["*"]
allow_credentials=True
```

## 디버깅 팁

### 브라우저 DevTools

**Network 탭**:
- `/api/chat/messages` (REST) 요청 확인
- `/api/chat/stream` (SSE) 연결 상태 확인

**Console**:
```javascript
// 현재 세션 ID 확인
sessionStorage.getItem("chat_session_id")

// SSE 수신 메시지 로깅
fetch("/api/chat/stream?session_id=...", {
  credentials: "include"
}).then(r => {
  const reader = r.body.getReader()
  const decoder = new TextDecoder()
  while (true) {
    const {value, done} = await reader.read()
    if (done) break
    console.log(decoder.decode(value))
  }
})
```

**Application 탭**:
- Session Storage에서 `chat_session_id` 확인

### curl로 API 테스트

```bash
# 메시지 목록 조회
curl http://localhost:8000/api/chat/messages?session_id=test-session

# 메시지 전송
curl -X POST http://localhost:8000/api/chat/messages?session_id=test-session \
  -H "Content-Type: application/json" \
  -d '{"text": "test"}'

# SSE 스트림 구독 (실시간 출력)
curl -N http://localhost:8000/api/chat/stream?session_id=test-session
```
