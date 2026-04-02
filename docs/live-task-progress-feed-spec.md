# 기능 명세서: 실시간 작업 진행 피드 (Live Task Progress Feed)

---

## 1. 배경 및 목적

### 문제
에이전트 실행 중 클라이언트는 최종 결과가 올 때까지 완전히 블랙박스 상태.
수 분간 아무런 피드백이 없어서 실행 중인지조차 알 수 없음.

### 근본 원인
`scripts/run_recursive_agent_query.py`의 `on_event` 콜백이 이미 아래 같은 라인을 stdout에 실시간 출력하고 있음:
```
[step] root.0.1 g5 l1 재무 안정성 분석
[decision] root.0.1 EXECUTE
[tool] root.0.1 domain_tool {...}
[done] root.0.1
[failed] root.0.2 [Errno 32] Broken pipe
```
하지만 `server/chat_api.py`의 `_pipe_process_stream`은 이 라인들을 `sys.stdout`(서버 콘솔)에 찍기만 하고 클라이언트에는 전달하지 않음.

### 목적
- 실행 중 어떤 태스크가 돌고 있는지 태스크 이름(한국어 description)으로 실시간 표시
- `root.1.1` 같은 내부 ID는 노출하지 않음
- 완료/실패한 태스크는 즉시 목록에서 제거해 "지금 실행 중"인 것만 보여줌

---

## 2. 이벤트 라인 포맷 (기존 출력 그대로)

| prefix | 예시 | 의미 |
|--------|------|------|
| `[step]` | `[step] root.0.1 g5 l1 재무 안정성 분석` | 태스크 스텝 시작. description 포함 |
| `[decision]` | `[decision] root.0.1 EXECUTE` | LLM 결정 완료 |
| `[tool]` | `[tool] root.0.1 domain_tool {...}` | 툴 실행 |
| `[done]` | `[done] root.0.1` | 태스크 완료 |
| `[failed]` | `[failed] root.0.2 에러 메시지` | 태스크 실패 |

**스크립트 변경 없음** — `render_event()`가 이미 올바른 포맷을 출력하고 있으므로 `scripts/run_recursive_agent_query.py`는 건드리지 않는다.

---

## 3. SSE 이벤트 명세

### 신규 이벤트 타입: `task_progress`

기존 `/api/chat/stream` SSE 채널에 새 이벤트 타입을 추가한다. 별도 엔드포인트 없음.

```
data: {"type": "task_progress", "line": "[step] root.0.1 g5 l1 재무 안정성 분석"}\n\n
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `type` | `"task_progress"` | 이벤트 구분자 |
| `line` | `string` | `render_event()`가 출력한 원본 라인 (trailing newline 제거) |

### 기존 이벤트 타입 (변경 없음)

| type | 설명 |
|------|------|
| `(없음, 기존 ChatMessage 구조)` | 최종 채팅 메시지 |
| `"reset"` | 채팅 초기화 이벤트 |

---

## 4. 서버 변경 명세 — `server/chat_api.py`

### 4-1. `_pipe_process_stream` 시그니처 변경

**변경 전:**
```python
async def _pipe_process_stream(
    stream: asyncio.StreamReader | None,
    target,
    *,
    prefix: str,
) -> str:
```

**변경 후:**
```python
from collections.abc import Callable, Coroutine
from typing import Any

async def _pipe_process_stream(
    stream: asyncio.StreamReader | None,
    target,
    *,
    prefix: str,
    on_line: Callable[[str], Coroutine[Any, Any, None]] | None = None,
) -> str:
```

**변경 내용:** 루프 내 `target.flush()` 호출 직후에 아래 블록 추가:
```python
if on_line is not None:
    await on_line(text)
```

기존 반환값, 동작, 에러 처리 모두 그대로 유지.

### 4-2. `_run_agent_for_message` 내부 콜백 추가

`_PROGRESS_PREFIXES` 상수와 `_on_stdout_line` 코루틴을 함수 최상단에 정의:

```python
_PROGRESS_PREFIXES = ("[step]", "[decision]", "[tool]", "[done]", "[failed]")

async def _on_stdout_line(line: str) -> None:
    stripped = line.rstrip("\n")
    if stripped.startswith(_PROGRESS_PREFIXES):
        await _broadcast({"type": "task_progress", "line": stripped})
```

`stdout_task` 생성 시 `on_line=_on_stdout_line` 전달:
```python
stdout_task = asyncio.create_task(
    _pipe_process_stream(
        process.stdout, sys.stdout,
        prefix="[chat-agent] ",
        on_line=_on_stdout_line,   # 추가
    )
)
```

`stderr_task`는 변경 없음.

---

## 5. 클라이언트 변경 명세 — `client/src/components/AgentChatPanel.tsx`

### 5-1. 타입 추가 (파일 상단)

```ts
interface ProgressItem {
  kind: "step" | "done" | "failed" | "other";
  taskId: string;
  description: string;
}
```

### 5-2. 파싱 헬퍼 (컴포넌트 바깥)

```ts
function parseProgressLine(line: string): ProgressItem {
  const parts = line.split(" ");
  const raw = parts[0] ?? "";
  const kind = (raw.startsWith("[") && raw.endsWith("]")
    ? raw.slice(1, -1)
    : "other") as ProgressItem["kind"];
  const taskId = parts[1] ?? "";
  // [step] 포맷: "[step] {taskId} g{N} l{N} {description...}"
  // g/l 토큰은 없을 수도 있음 — /^[gl]\d+$/ 로 판별해 건너뜀
  let descStart = 2;
  if (kind === "step") {
    while (descStart < parts.length && /^[gl]\d+$/.test(parts[descStart])) {
      descStart++;
    }
  }
  const description = parts.slice(descStart).join(" ").trim();
  return { kind, taskId, description };
}
```

### 5-3. 상태 추가

```ts
// taskId → 가장 최근 description 캐시
const [taskDescriptions, setTaskDescriptions] = useState<Map<string, string>>(new Map());
// 현재 실행 중인 taskId 목록 (순서 보존)
const [activeTaskIds, setActiveTaskIds] = useState<string[]>([]);
```

### 5-4. SSE 핸들러 확장

기존 `es.onmessage` 내부에서 `isChatResetEvent` 분기 이후, ChatMessage 처리 이전에 삽입:

```ts
if ((payload as { type?: string }).type === "task_progress") {
  const raw = (payload as unknown as { line: string }).line;
  const item = parseProgressLine(raw);
  if (item.kind === "step") {
    if (item.description) {
      setTaskDescriptions(prev => new Map(prev).set(item.taskId, item.description));
    }
    setActiveTaskIds(prev =>
      prev.includes(item.taskId) ? prev : [...prev, item.taskId]
    );
  } else if (item.kind === "done" || item.kind === "failed") {
    setActiveTaskIds(prev => prev.filter(id => id !== item.taskId));
    onMessagesUpdated?.();  // TaskTreeOutline 새로고침 트리거
  }
  return;
}
```

### 5-5. 완료 후 클리어 (effect 아님)

`pending`은 `postChatMessage()` 요청 구간만 가리키므로, 에이전트 실행 전체와 무관하게 곧바로 `false`가 된다. 그래서 **`pending`으로 `activeTaskIds`를 비우면 안 된다** (비우는 순간이 에이전트 시작 직후가 되어 피드가 사라짐).

대신 다음에서 전체 클리어한다.

- **SSE로 `ChatMessage`가 도착했을 때 `role === "assistant"`** — 최종 답·에러 메시지 브로드캐스트 시 에이전트 실행이 끝난 것으로 본다.
- **`reset` 이벤트** — `setMessages([])`와 함께 `setActiveTaskIds([])`.

예시:

```ts
if (isChatResetEvent(payload)) {
  setMessages([]);
  setActiveTaskIds([]);
  // ...
  return;
}
// ... task_progress ...
const msg: ChatMessage = payload;
if (messageIdsRef.current.has(msg.id)) return;
setMessages((prev) => [...prev, msg]);
if (msg.role === "assistant") {
  setActiveTaskIds([]);
}
```

`taskDescriptions`는 표시용 캐시로 두고, 필요 시 어시스턴트 수신 시점에 비우는 것은 구현 선택 사항이다.

### 5-6. 피드 렌더링 위치

`.chat` 영역과 `.inputBar` 사이에 삽입:

```tsx
{activeTaskIds.length > 0 && (
  <div className={styles.progressFeed}>
    {activeTaskIds.map(id => (
      <div key={id} className={styles.progressItem}>
        <span className={styles.progressSpinner} aria-hidden="true" />
        <span className={styles.progressName}>
          {taskDescriptions.get(id) ?? id}
        </span>
      </div>
    ))}
  </div>
)}
```

피드 표시는 `activeTaskIds.length > 0`만 보면 된다. `pending`과 연동하지 않는다.

---

## 6. 스타일 명세 — `client/src/components/AgentChatPanel.module.css`

기존 `.inputBar` 규칙 앞에 추가:

```css
/* ── Progress Feed ─────────────────────────────── */
.progressFeed {
  flex-shrink: 0;
  padding: 5px 10px;
  border-top: 1px solid var(--border);
  background: var(--bg-tertiary);
  display: flex;
  flex-direction: column;
  gap: 3px;
  max-height: 96px;   /* 최대 ~6줄 */
  overflow-y: auto;
}

.progressItem {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-secondary);
  min-height: 16px;
}

.progressSpinner {
  flex-shrink: 0;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  border: 1.5px solid var(--text-secondary);
  border-top-color: transparent;
  animation: progressSpin 0.75s linear infinite;
}

@keyframes progressSpin {
  to { transform: rotate(360deg); }
}

.progressName {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
```

---

## 7. 데이터 흐름 다이어그램

```
agent subprocess
  └─ render_event() → stdout 라인 emit
        │
        ▼
server: _pipe_process_stream (readline loop)
  └─ on_line(text)
        └─ startswith([step]/[done]/…) → _broadcast({type:"task_progress", line})
                │
                ▼ SSE: /api/chat/stream
client: EventSource.onmessage
  └─ type === "task_progress"
        ├─ kind=step  → activeTaskIds에 추가, description 캐시
        └─ kind=done/failed → activeTaskIds에서 제거, onMessagesUpdated 호출
                │
                ▼
  AgentChatPanel 피드 영역
    [spinner] 재무 안정성 분석
    [spinner] 성장 촉매 분석
```

---

## 8. 엣지 케이스

| 케이스 | 처리 |
|--------|------|
| `[step]` 라인에 description이 없음 | `description`이 빈 문자열 → `activeTaskIds`에 추가하되 표시는 taskId fallback |
| 같은 taskId의 `[step]`이 여러 번 (retry) | `taskDescriptions`를 덮어쓰고, `activeTaskIds`는 중복 추가 안 함 |
| `[done]` 없이 프로세스 종료 | 서버는 실패 시에도 assistant 메시지를 보내므로, 그 SSE 수신 시 `activeTaskIds` 클리어. 메시지 없이 끊기면 줄이 남을 수 있음 (허용) |
| SSE 연결 끊김 후 재연결 | EventSource 자동 재연결, 재연결 전 이벤트는 누락됨 (허용) |
| 여러 브라우저 탭 동시 접속 | `_subscribers` 브로드캐스트로 모든 탭에 동일하게 전달 |

---

## 9. 검증 시나리오

1. **기본 동작**: 질문 전송 → 수 초 내 progressFeed 영역 출현 → spinner + 한국어 태스크명 표시
2. **완료 동작**: 태스크 완료 시 해당 row 즉시 사라짐
3. **최종 완료**: 에이전트 응답 수신 → progressFeed 전체 사라짐
4. **실패 동작**: 태스크 실패 시 해당 row 사라짐 (에러 메시지는 description 영역에 표시하지 않음, 기존 에러 처리 유지)
5. **TaskTree 갱신**: `[done]` 이벤트마다 `onMessagesUpdated` 호출 → TaskTreeOutline이 `task_tree.md` 재로드
6. **description 없는 라인**: taskId(`root.0.1` 형태) fallback 표시

---

## 10. 변경 파일 요약

| 파일 | 변경 종류 |
|------|---------|
| `server/chat_api.py` | 수정 (약 +10줄) |
| `client/src/components/AgentChatPanel.tsx` | 수정 (약 +35줄) |
| `client/src/components/AgentChatPanel.module.css` | 수정 (약 +25줄) |
| `scripts/run_recursive_agent_query.py` | **변경 없음** |
