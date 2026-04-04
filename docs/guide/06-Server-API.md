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

| 메서드 | 엔드포인트 | 설명 |
| :--- | :--- | :--- |
| `POST` | `/api/chat` | 신규 분석 요청 및 에이전트 실행 |
| `GET` | `/api/sessions/{id}` | 특정 세션의 요약 및 전체 이벤트 로그 조회 |
| `GET` | `/api/sessions/{id}/tree` | 작업을 트리 구조(부모-자식)로 시각화하여 반환 |
| `GET` | `/api/health` | 서버 상태 확인 |

---

## 3. 상세 엔드포인트 명세

### [POST] 분석 요청 (`/api/chat`)
사용자의 질의를 받아 에이전트를 가동합니다.

**Request Body**
```json
{
  "query": "Apple의 2024 회계연도 수익 분석",
  "model": "claude",
  "session_id": null 
}
```

**Response**
```json
{
  "status": "completed",
  "output": "Apple의 2024년 총 매출은...",
  "session_id": "S-20260405-104410Z",
  "duration": 45.3,
  "llm_usage": {
    "total_input_tokens": 12345,
    "total_output_tokens": 6789
  }
}
```

---

## 4. 내부 실행 흐름 (Request Lifecycle)

하나의 `/api/chat` 요청이 들어오면 서버 내부에서는 다음 과정을 거칩니다.



1.  **세션 준비:** 전달된 `session_id`가 없으면 신규 ID를 생성하고 디렉토리를 확보합니다.
2.  **환경 구성:** 요청된 모델에 맞춰 `ToolRegistry`와 `LLMClient`를 인스턴스화합니다.
3.  **에이전트 주입:** `Scheduler`, `SharedState`, `TraceWriter`를 에이전트에 주입합니다. 이때 `on_event` 콜백을 통해 이벤트를 실시간으로 기록합니다.
4.  **실행 (`Agent.run`):** 비동기 루프가 완료될 때까지 대기합니다.
5.  **사후 처리:** 실행 시간, 토큰 사용량, 최종 답변을 `metadata.json`에 업데이트하고 클라이언트에 응답합니다.

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

### Python (httpx 사용)
```python
import httpx

async def run_analysis():
    async with httpx.AsyncClient() as client:
        # 1. 분석 시작
        res = await client.post("http://localhost:8000/api/chat", json={
            "query": "Apple 수익 확인",
            "model": "gemini"
        })
        session_id = res.json()["session_id"]
        
        # 2. 진행 상태/로그 확인
        log_res = await client.get(f"http://localhost:8000/api/sessions/{session_id}")
        for step in log_res.json()["steps"]:
            print(f"[{step['timestamp']}] {step['event']}")
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