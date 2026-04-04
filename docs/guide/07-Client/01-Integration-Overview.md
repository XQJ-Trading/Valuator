# Client ↔ Server 통합 개요

## 시스템 아키텍처

Valuator는 **프론트엔드 클라이언트(React)**와 **백엔드 서버(FastAPI)**로 구성된 분산 시스템입니다.

```
┌──────────────────────────────────┐
│      React Client (SPA)           │
│  localhost:5173                   │
│                                   │
│  - User Query Input               │
│  - Real-time Task Visualization   │
│  - Message History Display        │
└────────────┬──────────────────────┘
             │
       (HTTP + SSE)
             │
┌────────────▼──────────────────────┐
│     FastAPI Server                │
│  localhost:8000                   │
│                                   │
│  - Agent Execution Engine         │
│  - Session State Management       │
│  - Event Broadcasting             │
└──────────────────────────────────┘
```

## 통신 흐름

### 1️⃣ 사용자 질의 입력

**클라이언트 액션**:
```typescript
// ChatSessionContext.sendMessage()
await postChatMessage(sessionId, "Apple 수익 분석")
```

**HTTP 요청**:
```
POST /api/chat/messages?session_id=...
Content-Type: application/json

{ "text": "Apple 수익 분석" }
```

**서버 처리**:
- 메시지 저장
- 에이전트 실행 시작 (비동기)
- 즉시 응답 (클라이언트 차단 X)

**응답**:
```json
{
  "id": "msg-uuid",
  "role": "user",
  "text": "Apple 수익 분석",
  "ts": "2026-04-05T10:30:00Z"
}
```

### 2️⃣ 에이전트 실행 (백그라운드)

**서버 내부 흐름**:
1. Task 생성 및 스케줄러에 등록
2. Agent Loop 시작
3. 각 단계마다 `TaskProgress` 이벤트 발행
4. 도구 실행 및 LLM 호출
5. 완료 또는 실패

### 3️⃣ 실시간 진행상황 스트리밍

**클라이언트 수신** (SSE EventSource):
```typescript
const es = new EventSource(chatStreamPath(sessionId))
es.onmessage = (ev) => {
  const payload = JSON.parse(ev.data)
  // 메시지 타입별 처리
}
```

**서버 발행 이벤트**:

| 이벤트 타입 | 설명 | 예시 |
|-----------|------|------|
| `ChatMessage` | 사용자/어시스턴트 메시지 | `{ role: "assistant", text: "..." }` |
| `agent_started` | 에이전트 시작 | `{ type: "agent_started" }` |
| `agent_finished` | 에이전트 완료 | `{ type: "agent_finished" }` |
| `task_progress` | 작업 진행상황 | `{ type: "task_progress", line: "g0/l1 [task1] ..." }` |
| `reset` | 세션 리셋 | `{ type: "reset" }` |

**클라이언트 상태 업데이트**:
```typescript
// 진행상황 파싱 → TaskFlowSnapshot 생성
const snapshot = parseProgressLine("g0/l1 [task-1.0] Analyzing revenue...")
// ChatSessionContext의 activeTaskIds, taskDisplayNames 업데이트
setActiveTaskIds(prev => [...prev, snapshot.taskId])
```

### 4️⃣ 최종 결과 수신

**시나리오 1: 에이전트 완료**
- SSE에서 `agent_finished` 이벤트 수신
- 서버가 최종 답변을 포함한 `ChatMessage` 발행
- 클라이언트 messages 배열에 추가 및 UI 렌더링

**시나리오 2: 사용자 중단**
```typescript
// 클라이언트
await postChatStop(sessionId)

// 서버
POST /api/chat/stop?session_id=...
// → 에이전트 루프 중단
// → agent_finished 이벤트 발행
```

## Session ID 기반 상태 추적

### 클라이언트 측
```typescript
// 초기화
const sessionId = getOrCreateChatSessionId() // sessionStorage 활용
// 또는
const sessionId = window.crypto.randomUUID()

// 모든 API 요청에 포함
fetch(`/api/chat/messages?session_id=${sessionId}`, ...)
```

### 서버 측
```python
# 요청 매핑
session_id = request.query_params.get("session_id")

# 세션 상태 로드
session = session_store.load(session_id)  # 또는 신규 생성

# 상태 유지
session.messages.append(new_message)
session_store.save(session)
```

## 데이터 플로우 (메시지 관점)

```
User Input
  ↓
ChatSessionContext.sendMessage(text)
  ├─→ POST /api/chat/messages (user message)
  │   └─→ Server: Session에 메시지 저장
  │   └─→ Trigger Agent Loop (백그라운드)
  │
  └─→ Response: ChatMessage { id, role, text, ts }
      └─→ setMessages(prev => [...prev, msg])

[Agent Execution in Background]
  ├─→ Task Decomposition
  │   └─→ SSE: task_progress events
  │       └─→ parseProgressLine() → StepFlowSnapshot
  │       └─→ setTaskDescriptions, setTaskDisplayNames
  │
  ├─→ Tool Execution
  │   └─→ SSE: task_progress events (step 증가)
  │
  └─→ Completion
      ├─→ SSE: agent_finished
      ├─→ SSE: ChatMessage { role: "assistant", text: result }
      └─→ setMessages(prev => [...prev, result_msg])
```

## 핵심 인터페이스

### 세션 관리

```typescript
// api.ts
export function getOrCreateChatSessionId(): string
export async function fetchChatMessages(sessionId: string): Promise<ChatMessage[]>
export async function postChatMessage(sessionId: string, text: string): Promise<ChatMessage>
export async function clearChatMessages(sessionId: string): Promise<void>
export async function postChatStop(sessionId: string): Promise<{ ok: boolean }>
export async function fetchAgentRunning(sessionId: string): Promise<boolean>
export function chatStreamPath(sessionId: string): string
```

### 상태 관리

```typescript
// ChatSessionContext.tsx
export type ChatSessionContextValue = {
  messages: ChatMessage[]           // 모든 메시지 (사용자 + 어시스턴트)
  pending: boolean                  // 메시지 전송 중
  agentRunning: boolean             // 에이전트 실행 중
  activeTaskIds: string[]           // 현재 실행 중인 작업 ID들
  taskDisplayNames: Map<string, string>  // 작업별 이름
  taskDescriptions: Map<string, string>  // 작업별 설명
  lastStepFlow: StepFlowSnapshot | null  // 마지막 진행상황
  
  sendMessage: (text?: string) => Promise<void>
  clearMessages: () => Promise<void>
  stopAgent: () => Promise<void>
}
```

## 오류 처리

### 네트워크 오류

```typescript
// api.ts - parseErrorBody()
// - HTTP 실패 응답 파싱
// - { error, detail } 필드 추출
// - 사용자 알림 (alert)

async function parseErrorBody(res: Response): Promise<string> {
  const body = await res.json()
  if (body.error) return body.error
  if (typeof body.detail === "string") return body.detail
  return `request ${res.status}`
}
```

### 세션 불일치

서버는 세션 ID가 없거나 잘못되면:
```json
{ "detail": "Session not found" }
```

클라이언트는:
```typescript
.catch((e: Error) => {
  setLoadError(e.message)
  // → UI에 "Session not found" 표시
})
```

## 성능 고려사항

### 1. SSE 연결 유지
- EventSource는 서버의 Keep-Alive와 독립적
- 브라우저는 자동으로 재연결 시도
- 서버는 주기적 ping 이벤트 권장 (선택사항)

### 2. 메시지 중복 방지
```typescript
const messageIdsRef = useRef<Set<string>>(new Set())
if (messageIdsRef.current.has(msg.id)) return
setMessages(prev => [...prev, msg])
messageIdsRef.current.add(msg.id)
```

### 3. 대용량 응답
- 서버는 응답을 스트리밍 또는 청크 단위로 전송
- 클라이언트는 메시지별로 처리 (한 번에 모든 메시지 로드 X)

## CORS 설정

서버의 `main.py`:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["localhost:5173", "localhost:3000", ...],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

프로덕션 배포 시 `allow_origins`을 명시적으로 제한해야 합니다.
