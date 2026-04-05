# 클라이언트 (Client)

Valuator 클라이언트는 React 기반의 SPA(Single Page Application)로, 서버의 분석 엔진과 REST API + SSE(Server-Sent Events)를 통해 실시간으로 통신합니다.

## 📚 목차

- [통합 개요](01-Integration-Overview.md) — Client와 Server의 상호작용
- [클라이언트 아키텍처](02-Client-Architecture.md) — 컴포넌트 구조 및 상태 관리
- [통신 프로토콜](03-Communication-Protocol.md) — REST API와 SSE 스트림
- [세션 관리](04-Session-Management.md) — 세션 생명주기 및 상태 추적

## 🎯 빠른 개요

```
┌─────────────────────────────────────────────────────────────┐
│                    React Client (SPA)                        │
│  - UI Components: ChatPanel, TaskTree, FileExplorer         │
│  - State: ChatSessionContext (messages, agent status)       │
│  - API Layer: api.ts (REST + SSE)                          │
└──────────────────┬──────────────────────────────────────────┘
                   │
         ┌─────────┴─────────┐
         ▼                   ▼
   REST API              SSE Stream
(POST /api/chat)    (EventSource)
         │                   │
         └─────────┬─────────┘
                   ▼
         ┌─────────────────────┐
         │  FastAPI Server     │
         │  - Session Store    │
         │  - Agent Executor   │
         │  - Event Broker     │
         └─────────────────────┘
```

## 📁 클라이언트 디렉토리 구조

```
client/src/
├── App.tsx                      # 메인 앱 컴포넌트
├── ChatSessionContext.tsx       # 채팅 세션 상태 관리
├── api.ts                       # REST API + SSE 인터페이스
├── components/
│   ├── AgentChatPanel.tsx       # 채팅 UI 메인
│   ├── TaskTreeOutline.tsx      # 작업 트리 시각화
│   ├── ActivitySidebar.tsx      # 활동 로그 사이드바
│   ├── ChatEditor.tsx           # 메시지 입력 에디터
│   └── ContentView.tsx          # 파일/세션 내용 뷰
├── chatProgressParse.ts         # 에이전트 진행상황 파싱
├── taskTreeParse.ts             # 작업 트리 구조 파싱
└── agentConfigStorage.ts        # 에이전트 설정 저장
```

## 🔑 핵심 개념

### 1. Session ID
- 클라이언트가 생성하는 고유 식별자
- 브라우저 `sessionStorage`에 저장
- 모든 API 요청의 `session_id` 파라미터로 전달
- 서버가 상태(메시지, 실행 로그)를 추적할 때 사용

### 2. ChatSessionContext
- React Context API를 통한 전역 상태 관리
- 채팅 메시지, 에이전트 실행 상태, 작업 정보 저장
- SSE 스트림과의 통합 (실시간 메시지 수신)

### 3. API 계층 (api.ts)
- **REST**: 메시지 전송 (`POST /api/chat/messages`), 상태 조회
- **SSE**: 실시간 진행상황 수신 (`/api/chat/stream`)

### 4. 작업 시각화
- 서버의 Task/AtomicTask 트리 구조를 클라이언트에서 시각화
- 진행 중인 작업의 이름, 단계(globalSeq/localStep) 표시

## 🚀 개발 시작

```bash
# 클라이언트 실행
cd client
npm install
npm run dev

# 브라우저 (기본 localhost:5173)
http://localhost:5173

# 서버는 별도 터미널에서
cd ..
uvicorn server.main:app --reload --port 8000
```

> [!TIP]
> **개발 팁**
> - DevTools의 Network 탭에서 SSE 스트림 실시간 확인: `/api/chat/stream?session_id=...`
> - 채팅 세션 ID: F12 → Application → Session Storage → `chat_session_id`
> - 메시지 추적: ChatSessionContext의 `messages`, `activeTaskIds` 상태 확인
