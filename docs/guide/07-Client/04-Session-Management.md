# 세션 관리

## 세션의 역할

세션은 클라이언트와 서버 간의 **상태 추적 단위**입니다. 하나의 세션이 저장하는 것:

- 사용자와 어시스턴트 간의 모든 대화 메시지
- 에이전트 실행 로그 및 작업 트리
- 실행 시간, 토큰 사용량, 상태 메타데이터
- 진행 중인 작업 상태

## 세션 생명주기

```
┌─────────────────────────────────────────────────────┐
│ 1. 클라이언트 초기화 (페이지 로드)                  │
│   └─→ getOrCreateChatSessionId()                    │
│       ├─→ sessionStorage에서 기존 ID 확인           │
│       ├─→ 없으면 UUID 생성                          │
│       └─→ sessionStorage에 저장                     │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│ 2. 서버 세션 준비 (첫 API 호출)                     │
│   └─→ POST /api/chat/messages (첫 메시지)          │
│       ├─→ 서버: session_id 기반 세션 객체 생성    │
│       ├─→ 서버: sessions/{session_id}/ 디렉토리 생성 │
│       ├─→ 서버: metadata.json, trace.jsonl 초기화 │
│       └─→ 응답: ChatMessage                        │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│ 3. 활성 상태 (메시지 교환 & 에이전트 실행)          │
│   ├─→ 사용자 메시지 전송                           │
│   ├─→ SSE 스트림으로 진행상황 수신                │
│   ├─→ 에이전트 실행 (작업 분해, 도구 실행)        │
│   └─→ 메시지 수집 (서버: trace.jsonl 기록)        │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│ 4. 세션 유지 (페이지 새로고침)                      │
│   ├─→ sessionStorage의 session_id 복원             │
│   ├─→ GET /api/chat/messages → 이전 메시지 로드   │
│   ├─→ GET /api/chat/agent-status → 실행 상태 확인 │
│   └─→ SSE 스트림 재연결                            │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│ 5. 세션 종료 (사용자 액션)                          │
│   ├─→ 옵션 A: DELETE /api/chat/messages (초기화)   │
│   ├─→ 옵션 B: 브라우저 탭 종료                     │
│   └─→ 옵션 C: sessionStorage 수동 삭제             │
└─────────────────────────────────────────────────────┘
```

## 클라이언트 세션 관리

### 1. Session ID 생성 및 저장

**초기화** (App.tsx 또는 ChatSessionProvider):
```typescript
import { getOrCreateChatSessionId } from './api'

// ChatSessionProvider 내부
const chatSessionIdRef = useRef<string>(getOrCreateChatSessionId())

// api.ts의 구현
export function getOrCreateChatSessionId(): string {
  const existing = window.sessionStorage.getItem(CHAT_SESSION_STORAGE_KEY)?.trim()
  if (existing) return existing
  
  const sessionId = window.crypto.randomUUID()
  window.sessionStorage.setItem(CHAT_SESSION_STORAGE_KEY, sessionId)
  return sessionId
}
```

**저장소**:
- 키: `chat_session_id`
- 값: UUID (RFC 4122)
- 범위: 브라우저 탭 단위 (`sessionStorage`)
- 수명: 탭 종료 시 자동 삭제

### 2. Session ID 전달

**모든 API 요청에 포함**:
```typescript
function chatApiPath(path: string, sessionId: string): string {
  const q = new URLSearchParams({ session_id: sessionId })
  return `${path}?${q.toString()}`
}

// 사용 예
fetch(chatApiPath("/api/chat/messages", sessionId), {
  method: "POST",
  body: JSON.stringify({ text: "..." })
})

// 최종 URL
// /api/chat/messages?session_id=550e8400-e29b-41d4-a716-446655440000
```

**SSE 연결도 포함**:
```typescript
export function chatStreamPath(sessionId: string): string {
  return chatApiPath("/api/chat/stream", sessionId)
}

const es = new EventSource(chatStreamPath(chatSessionId))
// /api/chat/stream?session_id=...
```

### 3. 상태 초기화 및 로드

**페이지 로드 시**:
```typescript
useEffect(() => {
  let cancelled = false
  const chatSessionId = chatSessionIdRef.current
  
  // 이전 메시지 로드
  setLoadingList(true)
  fetchChatMessages(chatSessionId)
    .then((msgs) => {
      if (cancelled) return
      setMessages(msgs)
      setLoadError(null)
    })
    .catch((e: Error) => {
      if (cancelled) return
      setLoadError(e.message)
    })
    .finally(() => {
      if (!cancelled) setLoadingList(false)
    })
  
  // 에이전트 상태 확인
  void fetchAgentRunning(chatSessionId)
    .then((running) => {
      if (!cancelled) setAgentRunning(running)
    })
    .catch(() => { /* ignore */ })
  
  // SSE 스트림 연결
  const es = new EventSource(chatStreamPath(chatSessionId))
  es.onmessage = (ev) => { /* ... */ }
  
  return () => {
    cancelled = true
    es.close()
  }
}, []) // 의존성 배열 비어있음 → 한 번만 실행
```

### 4. 세션 초기화

사용자가 "채팅 초기화" 버튼을 클릭하는 경우:

```typescript
const clearMessages = useCallback(async () => {
  if (pending || loadingList) return
  const confirmed = window.confirm("채팅 세션을 초기화할까요? 기존 메시지는 삭제됩니다.")
  if (!confirmed) return
  
  try {
    // 서버의 세션 삭제
    await clearChatMessages(chatSessionIdRef.current)
    
    // 클라이언트 상태 초기화
    messageIdsRef.current = new Set()
    setMessages([])
    setActiveTaskIds([])
    setTaskDisplayNames(new Map())
    setTaskDescriptions(new Map())
    setAgentRunning(false)
    setLastStepFlow(null)
    
    onMessagesUpdatedRef.current?.()
  } catch (e) {
    console.error(e)
    alert(e instanceof Error ? e.message : "Clear failed")
  }
}, [loadingList, pending])
```

## 서버 세션 관리

### 1. 세션 생성

**첫 요청 시**:
```python
@app.post("/api/chat/messages")
async def post_chat_message(
    session_id: str = Query(...),
    message: ChatMessageRequest = Body(...),
):
    # 세션 객체 생성 또는 로드
    session = session_store.load_or_create(session_id)
    
    # 메시지 저장
    message_obj = ChatMessage(
        id=str(uuid4()),
        role="user",
        text=message.text,
        ts=datetime.now(UTC),
    )
    session.messages.append(message_obj)
    
    # 디렉토리 생성
    session.dir.mkdir(parents=True, exist_ok=True)
    
    # 메타데이터 작성
    session.save_metadata()
    
    # 에이전트 실행 시작 (비동기)
    asyncio.create_task(run_agent(session_id, message.text))
    
    return message_obj
```

### 2. 세션 스토리지

**파일 시스템 구조**:
```
valuator/sessions/
└── S-20260405-104410Z/          # 세션 ID
    ├── metadata.json             # 상태, 시간, 토큰
    ├── trace.jsonl               # 모든 이벤트
    ├── trace_markdown.md         # 사람이 읽기 편한 로그
    └── browse/                   # (선택) 파일 탐색 정보
```

**metadata.json**:
```json
{
  "session_id": "S-20260405-104410Z",
  "created_at": "2026-04-05T10:30:00Z",
  "status": "completed",
  "duration_seconds": 45.3,
  "message_count": 2,
  "llm_usage": {
    "total_input_tokens": 12345,
    "total_output_tokens": 6789
  }
}
```

**trace.jsonl** (줄 단위 JSON):
```
{"timestamp": "2026-04-05T10:30:01Z", "event_type": "user_message", "text": "..."}
{"timestamp": "2026-04-05T10:30:02Z", "event_type": "agent_started"}
{"timestamp": "2026-04-05T10:30:03Z", "event_type": "task_progress", "line": "..."}
{"timestamp": "2026-04-05T10:30:45Z", "event_type": "agent_finished"}
{"timestamp": "2026-04-05T10:30:46Z", "event_type": "assistant_message", "text": "..."}
```

### 3. 세션 로드

```python
# 기존 세션 메시지 조회
@app.get("/api/chat/messages")
async def get_chat_messages(session_id: str = Query(...)):
    session = session_store.load(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"messages": session.messages}
```

### 4. 세션 삭제

```python
# 세션 초기화
@app.delete("/api/chat/messages")
async def delete_chat_messages(session_id: str = Query(...)):
    session = session_store.load(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # 메시지 초기화
    session.messages = []
    
    # 추적 파일 삭제
    if session.dir.exists():
        shutil.rmtree(session.dir)
    
    return {"ok": True}
```

## 상태 추적 흐름

### 클라이언트에서의 상태 추적

```typescript
// ChatSessionContext의 상태들
messages: ChatMessage[]              // 표시할 메시지
pending: boolean                     // 전송 중
loadingList: boolean                 // 로드 중
loadError: string | null             // 로드 오류

agentRunning: boolean                // 에이전트 실행 중
activeTaskIds: string[]              // 현재 작업들
taskDisplayNames: Map                // 작업별 이름
taskDescriptions: Map                // 작업별 설명
lastStepFlow: StepFlowSnapshot       // 최근 진행상황

draftText: string                    // 입력 초안
```

### 상태 변화 시나리오

**시나리오 1: 메시지 전송**
```
초기: messages=[], pending=false
  ↓ 사용자 텍스트 입력
draftText="Apple 수익"
  ↓ 전송 버튼 클릭
pending=true
  ↓ postChatMessage() 호출
(네트워크 중)
  ↓ 응답 수신
pending=false, messages=[...user_msg]
  ↓ SSE에서 agent_started 수신
agentRunning=true
  ↓ 진행상황 이벤트 수신
activeTaskIds=[...], taskDescriptions={...}
  ↓ agent_finished 수신
agentRunning=false, activeTaskIds=[]
  ↓ 최종 답변 수신
messages=[...user_msg, ...assistant_msg]
```

**시나리오 2: 페이지 새로고침**
```
초기: 모든 상태 undefined/empty
  ↓ 마운트 시
getOrCreateChatSessionId() → 기존 ID 복원
fetchChatMessages() 호출
  ↓ 로드 중
loadingList=true, messages=[]
  ↓ 응답 수신
messages=[...이전 메시지들]
loadingList=false
  ↓ fetchAgentRunning() 호출
agentRunning=true/false (확인됨)
  ↓ SSE 재연결
  ↓ 지속적으로 이벤트 수신
```

## 멀티 탭 처리

각 브라우저 탭은 **독립적인 세션 ID**를 가집니다:

```
탭 A: chat_session_id = uuid-1
탭 B: chat_session_id = uuid-2
탭 C: chat_session_id = uuid-1 (탭 A와 동일)
```

**주의사항**:
- 탭 A와 C는 같은 세션을 공유
- 한 탭에서 메시지를 보내면, 다른 탭에서도 SSE를 통해 수신
- 세션 초기화는 모든 탭에 영향

**권장사항**:
- 각 탭을 독립적으로 사용하려면 명시적으로 새 탭 생성
- 같은 분석을 여러 탭에서 추적하려면 session_id 공유 (URL에 포함)

## 오류 복구

### 세션 없음 (404)

```typescript
.catch((e: Error) => {
  if (e.message.includes("Session not found")) {
    // 새 세션 생성
    sessionStorage.removeItem(CHAT_SESSION_STORAGE_KEY)
    window.location.reload()
  }
})
```

### 네트워크 연결 끊김

```typescript
// SSE 자동 재연결
const es = new EventSource(chatStreamPath(sessionId))
es.onerror = (ev) => {
  console.error("SSE connection lost, will retry...")
  // EventSource는 지수 백오프로 자동 재연결 시도
}
```

### 메모리 누수 방지

```typescript
// 언마운트 시 정리
useEffect(() => {
  const es = new EventSource(...)
  
  return () => {
    cancelled = true      // 진행 중인 작업 취소
    es.close()           // SSE 연결 종료
    messageIdsRef.current = null  // 참조 제거
  }
}, [])
```

## 디버깅

### 세션 ID 확인

```javascript
// 브라우저 console
sessionStorage.getItem("chat_session_id")
// "550e8400-e29b-41d4-a716-446655440000"
```

### 서버 세션 파일 확인

```bash
# 세션 디렉토리 목록
ls -la valuator/sessions/

# 특정 세션 메타데이터
cat valuator/sessions/S-20260405-104410Z/metadata.json

# 실시간 로그 확인
tail -f valuator/sessions/S-20260405-104410Z/trace.jsonl
```

### API 요청 로깅

```typescript
// api.ts에 로깅 추가
export async function postChatMessage(
  sessionId: string,
  text: string,
): Promise<ChatMessage> {
  const url = chatApiPath("/api/chat/messages", sessionId)
  console.log(`[API] POST ${url}`, { text })
  
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  })
  
  if (!res.ok) {
    const error = await parseErrorBody(res)
    console.error(`[API] Error: ${error}`)
    throw new Error(error)
  }
  
  const result = await res.json()
  console.log(`[API] Response`, result)
  return result as Promise<ChatMessage>
}
```
