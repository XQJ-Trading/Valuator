# AI Agent (Gemini + ReAct)

LangChain과 Google Gemini를 사용한 경량 AI Agent. ReAct 루프, 스트리밍, FastAPI 서버, Vue 프런트엔드를 포함합니다.

### 📁 디렉토리 구조 (Valuator/)

```
Valuator/
├── ai_agent/
│   ├── agent/           # core.py, react_agent.py
│   ├── models/          # gemini.py
│   ├── react/           # engine.py, prompts.py, state.py
│   ├── tools/           # base.py, react_tool.py, web_search.py
│   ├── utils/           # config.py, logger.py, react_logger.py
│   └── examples/        # chat_demo.py, tool_demo.py, react_demo.py
├── server/
│   └── main.py          # FastAPI 엔드포인트
├── frontend-vue/        # Vue 3 + Vite 앱
├── requirements.txt
├── README.md
└── logs/                # 실행 로그 (선택)
```

### 🛠 설치

```bash
cd Valuator
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

`.env` 파일(Valuator/.env)에 최소 다음 값을 설정하세요:

```bash
GOOGLE_API_KEY=your_google_api_key
# 선택: LANGCHAIN_TRACING_V2=true, LANGCHAIN_PROJECT=ai-agent-project, LOG_LEVEL=INFO
```

기본 모델은 `gemini-2.0-flash-exp` 입니다 (`ai_agent/utils/config.py`).

### ▶ 실행

- Backend (FastAPI)
```bash
uvicorn server.main:app --reload
```
- Health: `GET http://127.0.0.1:8000/health`

- Frontend (Vue)
```bash
cd frontend-vue
npm install
npm run dev
```

### 🔌 API (요약)

**Chat API:**
- `POST /api/v1/chat` → { query: string, use_react?: bool }
- `POST /api/v1/chat/stream` → SSE 스트리밍
- `GET  /api/v1/chat/stream?query=...&use_react=bool` → SSE 스트리밍

**History API:**
- `GET /api/v1/history?limit=10&offset=0` → 세션 목록
- `GET /api/v1/history/{session_id}` → 세션 상세
- `GET /api/v1/history/{session_id}/stream` → 세션 재생 (SSE)
- `GET /api/v1/history/search?q=검색어` → 세션 검색
- `DELETE /api/v1/history/{session_id}` → 세션 삭제

> 전략 패턴으로 파일 IO ↔ MongoDB 전환 가능 (`.env`에서 `MONGODB_ENABLED` 설정)

### 💡 사용 예시 (비동기)

```python
import asyncio
from ai_agent.agent.react_agent import ReActGeminiAgent

async def main():
    agent = ReActGeminiAgent()
    print(await agent.chat_enhanced("안녕하세요?"))

asyncio.run(main())
```

### 참고
- 필수 키: `GOOGLE_API_KEY`
- 프런트 CORS: 5173/3000 허용 (`server/main.py`)
- 제공 도구: `react_tool`, `web_search` (계산기/메모리 모듈은 포함되지 않음)

### 라이선스
MIT
