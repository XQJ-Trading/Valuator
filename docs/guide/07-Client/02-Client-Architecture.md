# 클라이언트 아키텍처

## 레이어 구조

```
┌─────────────────────────────────────────────────┐
│         UI Layer (React Components)             │
│  - AgentChatPanel.tsx (메인 채팅 UI)            │
│  - TaskTreeOutline.tsx (작업 트리)              │
│  - ActivitySidebar.tsx (활동 로그)              │
│  - ChatEditor.tsx (입력 에디터)                 │
│  - ContentView.tsx (결과 표시)                  │
└────────────────┬────────────────────────────────┘
                 │ (useContext)
┌────────────────▼────────────────────────────────┐
│     State Management Layer                      │
│  - ChatSessionContext.tsx                       │
│  - ChatSessionContextValue (전역 상태)          │
└────────────────┬────────────────────────────────┘
                 │ (async functions)
┌────────────────▼────────────────────────────────┐
│         API Layer (api.ts)                      │
│  - REST API calls (fetch)                       │
│  - EventSource (SSE stream)                     │
│  - Error parsing & handling                     │
└────────────────┬────────────────────────────────┘
                 │ (HTTP)
┌────────────────▼────────────────────────────────┐
│         FastAPI Server (localhost:8000)         │
└─────────────────────────────────────────────────┘
```

## 상태 관리 (ChatSessionContext)

### 주요 상태

```typescript
type ChatSessionContextValue = {
  // 메시지 상태
  messages: ChatMessage[]                    // 모든 대화 메시지
  draftText: string                          // 입력 에디터의 임시 텍스트
  
  // 실행 상태
  pending: boolean                           // 메시지 전송 중
  loadingList: boolean                       // 초기 메시지 로드 중
  loadError: string | null                   // 로드 오류
  
  // 에이전트 상태
  agentRunning: boolean                      // 에이전트 실행 중
  activeTaskIds: string[]                    // 현재 진행 중인 작업들
  taskDisplayNames: Map<string, string>      // 작업별 표시 이름
  taskDescriptions: Map<string, string>      // 작업별 상세 설명
  lastStepFlow: StepFlowSnapshot | null      // 최근 단계 정보
  
  // 메서드들
  sendMessage: (textOverride?: string) => Promise<void>
  clearMessages: () => Promise<void>
  stopAgent: () => Promise<void>
  setDraftText: (s: string) => void
}
```

### 상태 흐름

```
초기화
  ├─→ sessionStorage에서 또는 신규 생성 (sessionId)
  ├─→ fetchChatMessages(sessionId) → messages 로드
  ├─→ fetchAgentRunning(sessionId) → agentRunning 확인
  ├─→ EventSource(chatStreamPath(sessionId)) 연결
  │
사용자 메시지 전송
  ├─→ sendMessage() 호출
  ├─→ pending = true
  ├─→ postChatMessage(sessionId, text)
  ├─→ 응답: ChatMessage 수신
  ├─→ messages에 추가
  ├─→ pending = false
  │
SSE 이벤트 수신
  ├─→ ChatMessage 수신 → messages에 추가
  ├─→ agent_started → agentRunning = true
  ├─→ task_progress → 파싱 후 activeTaskIds, taskDisplayNames 업데이트
  ├─→ agent_finished → agentRunning = false, activeTaskIds 초기화
  ├─→ reset → 모든 상태 초기화
  │
사용자 액션 (중단, 초기화)
  └─→ stopAgent() / clearMessages()
      └─→ 서버에 요청
      └─→ 로컬 상태 업데이트
```

## 주요 컴포넌트

### 1. AgentChatPanel.tsx (메인 UI)

**역할**: 전체 채팅 인터페이스 구성
- 메시지 리스트 표시
- 작업 트리 시각화
- 입력 에디터
- 상태 표시

**Props**: 없음 (전부 Context 사용)

**Hook**:
```typescript
const {
  messages,
  pending,
  agentRunning,
  activeTaskIds,
  sendMessage,
  clearMessages,
  stopAgent,
  draftText,
  setDraftText,
} = useChatSession()
```

### 2. ChatEditor.tsx (입력)

**역할**: 메시지 입력 및 전송

**기능**:
- 텍스트 입력 (multiline)
- Enter/Shift+Enter 처리
- 자동완성 (멘션)
- 전송 버튼

**Hook**:
```typescript
const { draftText, setDraftText, pending, sendMessage } = useChatSession()

// 사용자 입력
onChange={(e) => setDraftText(e.target.value)}

// 전송
onSubmit={() => sendMessage()}
```

### 3. TaskTreeOutline.tsx (작업 트리)

**역할**: 에이전트 실행 중인 작업들을 트리 구조로 시각화

**입력**:
```typescript
interface TaskTreeOutlineProps {
  taskId: string
  displayName: string
  description: string
  isActive: boolean
}
```

**데이터 소스**:
```typescript
const { activeTaskIds, taskDisplayNames, taskDescriptions } = useChatSession()

activeTaskIds.forEach(id => (
  <TaskTreeOutline
    taskId={id}
    displayName={taskDisplayNames.get(id) || id}
    description={taskDescriptions.get(id) || ""}
    isActive={true}
  />
))
```

### 4. ActivitySidebar.tsx (로그)

**역할**: 실행 로그, 세션 정보 표시

**표시 내용**:
- 메시지 개수
- 에이전트 실행 상태
- 활성 작업 수
- 마지막 진행상황 (lastStepFlow)

### 5. ContentView.tsx (결과)

**역할**: 메시지 또는 파일 내용 렌더링

**기능**:
- Markdown 렌더링
- JSON 트리 뷰
- Raw 텍스트 표시
- 파일 내용 표시

## 유틸리티 모듈

### chatProgressParse.ts

**목적**: SSE의 `task_progress` 이벤트 라인 파싱

**입력 예시**:
```
"g0/l1 [task-1.0] Analyzing revenue trends"
```

**파싱 결과**:
```typescript
interface StepFlowSnapshot {
  taskId: string         // "task-1.0"
  taskName?: string      // 작업 이름
  globalSeq?: number     // 0 (전체 진행 순서)
  localStep?: number     // 1 (해당 작업 내 단계)
  description: string    // "Analyzing revenue trends"
}
```

**사용**:
```typescript
const item = parseProgressLine(line)
if (item.kind === "step") {
  setTaskDescriptions(prev => 
    new Map(prev).set(item.taskId, item.description)
  )
}
```

### taskTreeParse.ts

**목적**: 작업 트리 구조 파싱 및 변환

**입력**: 서버의 Task 트리 구조
**출력**: UI 렌더링용 트리 노드

### agentConfigStorage.ts

**목적**: 에이전트 설정 로컬 스토리지

**기능**:
- 모델 선택 저장
- 도구 활성화 여부 저장
- 사용자 선호도 저장

**사용**:
```typescript
const config = loadAgentConfig()
saveAgentConfig(config)
```

## 컴포넌트 상호작용 다이어그램

```
┌──────────────────────────────────────┐
│      App.tsx (Main)                  │
│  - ChatSessionProvider 감싸기        │
│  - 레이아웃 정의                     │
└────────┬─────────────────────────────┘
         │
         ├─→ ┌──────────────────────┐
         │   │ AgentChatPanel       │
         │   └────┬─────────────────┘
         │        │
         │        ├─→ TaskTreeOutline (시각화)
         │        ├─→ ChatEditor (입력)
         │        ├─→ MessageList (메시지)
         │        └─→ ContentView (결과)
         │
         └─→ ┌──────────────────────┐
             │ ActivitySidebar      │
             │ (로그, 상태 표시)    │
             └──────────────────────┘

모든 컴포넌트는 useChatSession() 훅으로 상태 접근
```

## 데이터 흐름 예시: 사용자 질의 → 답변

```
1. ChatEditor에서 텍스트 입력
   └─→ setDraftText("Apple 수익 분석")

2. "전송" 버튼 클릭
   └─→ sendMessage()
       ├─→ pending = true
       └─→ postChatMessage(sessionId, "Apple 수익 분석")

3. 서버 응답: ChatMessage { id, role: "user", text, ts }
   └─→ messages.push(msg)
   └─→ setDraftText("")
   └─→ pending = false
   └─→ draftText 입력 필드 초기화

4. 서버가 에이전트 시작 (백그라운드)
   └─→ SSE: { type: "agent_started" }
       └─→ agentRunning = true

5. 에이전트 실행 중 진행상황 스트리밍
   └─→ SSE: { type: "task_progress", line: "g0/l1 [task-1.0] ..." }
       ├─→ parseProgressLine() 파싱
       ├─→ taskDescriptions.set("task-1.0", "...")
       └─→ activeTaskIds.push("task-1.0")

6. TaskTreeOutline이 activeTaskIds 변경 감지
   └─→ 트리 UI 업데이트 (작업 표시, 진행도)

7. 에이전트 완료
   └─→ SSE: { type: "agent_finished" }
       └─→ agentRunning = false
       └─→ activeTaskIds = []

8. 최종 답변 수신
   └─→ SSE: { id, role: "assistant", text: "Apple의 2024년 수익은...", ts }
       └─→ messages.push(final_msg)
       └─→ ContentView가 답변 렌더링

9. 사용자가 답변 확인
```

## 에러 처리 흐름

```
API 호출 실패
  ├─→ res.ok === false
  ├─→ parseErrorBody(res) → 에러 메시지 추출
  ├─→ Error 인스턴스로 throw
  │
catch 블록
  ├─→ alert(e.message) → 사용자 알림
  └─→ 상태 복구 (pending = false 등)
  
예시:
try {
  const msg = await postChatMessage(sessionId, text)
  setMessages(prev => [...prev, msg])
} catch (e) {
  alert(e instanceof Error ? e.message : "Send failed")
} finally {
  setPending(false)
}
```

## 성능 최적화

### 1. 메모이제이션 (useMemo)
```typescript
const value = useMemo<ChatSessionContextValue>(
  () => ({ messages, agentRunning, ... }),
  [messages, agentRunning, ...]  // dependencies
)
// → Context 값 변경 없으면 자식 컴포넌트 리렌더링 X
```

### 2. 중복 메시지 방지
```typescript
const messageIdsRef = useRef<Set<string>>(new Set())
if (messageIdsRef.current.has(msg.id)) return
setMessages(prev => [...prev, msg])
messageIdsRef.current.add(msg.id)
```

### 3. EventSource 정리
```typescript
return () => {
  cancelled = true
  es.close()  // 언마운트 시 연결 종료
}
```

## 테스트 가이드

### Unit Test: API 모듈
```typescript
// api.ts 함수들
jest.mock('fetch')
test('postChatMessage sends correct payload', () => {
  await postChatMessage(sessionId, "test")
  expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining('/api/chat/messages'),
    expect.objectContaining({ method: 'POST' })
  )
})
```

### Integration Test: ChatSessionContext
```typescript
// 렌더링 테스트
const wrapper = ({ children }) => (
  <ChatSessionProvider>{children}</ChatSessionProvider>
)
const { result } = renderHook(() => useChatSession(), { wrapper })

// 메시지 전송 시뮬레이션
await act(async () => {
  await result.current.sendMessage("test")
})
expect(result.current.messages).toHaveLength(1)
```

### E2E Test: 전체 흐름
```typescript
// Playwright
await page.goto('http://localhost:5173')
await page.fill('[data-testid="chat-input"]', 'Apple revenue')
await page.click('[data-testid="send-button"]')
await page.waitForSelector('[data-testid="assistant-message"]')
// 메시지가 화면에 표시되었는지 확인
```
