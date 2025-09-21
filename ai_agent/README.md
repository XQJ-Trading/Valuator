# AI Agent - Gemini 2.5 Pro

LangChain과 Google의 Gemini 2.5 Pro를 활용한 AI Agent 구현입니다.

## 🚀 주요 기능

- **Gemini 2.5 Pro 통합**: LangChain을 통한 안정적인 Gemini 모델 사용
- **대화 메모리 관리**: 컨텍스트 유지를 위한 대화 기록 관리
- **도구 시스템**: 계산기, 날씨, 웹 검색 등 다양한 도구 지원
- **스트리밍 응답**: 실시간 응답 스트리밍
- **비동기 처리**: asyncio 기반의 비동기 처리
- **설정 관리**: 환경 변수를 통한 유연한 설정

## 📁 프로젝트 구조

```
ai-agent/
├── __init__.py
├── agent/
│   ├── __init__.py
│   └── core.py              # 핵심 Agent 클래스
├── models/
│   ├── __init__.py
│   └── gemini.py            # Gemini 모델 통합
├── memory/
│   ├── __init__.py
│   └── conversation.py      # 대화 메모리 관리
├── tools/
│   ├── __init__.py
│   ├── base.py              # 기본 도구 클래스
│   └── web_search.py        # 웹 검색 도구
├── utils/
│   ├── __init__.py
│   ├── config.py            # 설정 관리
│   └── logger.py            # 로깅
└── examples/
    ├── __init__.py
    ├── chat_demo.py         # 채팅 데모
    └── tool_demo.py         # 도구 데모
```

## 🛠️ 설치 및 설정

### 1. 의존성 설치

```bash
# 가상환경 활성화
source venv/bin/activate

# 의존성 설치 (이미 완료됨)
pip install -r requirements.txt
```

### 2. API 키 설정

`.env` 파일을 생성하고 Google API 키를 설정하세요:

```bash
# .env.example을 복사하여 .env 파일 생성
cp .env.example .env

# .env 파일 편집하여 실제 API 키 입력
# GOOGLE_API_KEY=your_actual_google_api_key_here
```

**⚠️ 보안 주의사항:**
- `.env` 파일은 Git에 커밋되지 않습니다
- 실제 API 키는 `.env` 파일에만 저장하세요

### 3. 실행

```bash
python main.py
```

## 📖 사용법

### 기본 사용법

```python
import asyncio
from ai_agent import GeminiAgent

async def main():
    # Agent 초기화
    agent = GeminiAgent()
    
    # 채팅
    response = await agent.chat("안녕하세요!")
    print(response)
    
    # 스트리밍 응답
    async for chunk in agent.chat_stream("파이썬에 대해 설명해주세요"):
        print(chunk, end="", flush=True)

asyncio.run(main())
```

### 도구 사용

```python
from ai_agent.tools import ToolRegistry
from ai_agent.tools.react_tool import CodeExecutorTool

async def main():
    # 도구 등록
    registry = ToolRegistry()
    code_executor = CodeExecutorTool()
    registry.register(code_executor)
    
    # 코드 실행
    result = await registry.execute_tool("code_executor", code="print(2 + 3 * 4)")
    print(f"결과: {result.result}")

asyncio.run(main())
```

## 🔧 설정 옵션

### 환경 변수

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `GOOGLE_API_KEY` | Google API 키 | 필수 |
| `AGENT_MODEL` | 사용할 모델명 | `gemini-2.0-flash-exp` |
| `TEMPERATURE` | 창의성 수준 | `0.7` |
| `MAX_TOKENS` | 최대 토큰 수 | `2048` |
| `MAX_MEMORY_SIZE` | 최대 메모리 크기 | `100` |

### 모델 설정

```python
from ai_agent.utils.config import config

# 설정 확인
print(config.get_model_info())

# 시스템 프롬프트 설정
agent.set_system_prompt("당신은 전문적인 코딩 어시스턴트입니다.")
```

## 🧪 데모 실행

### 1. 채팅 데모

```bash
python -m ai_agent.examples.chat_demo
```

### 2. 도구 데모

```bash
python -m ai_agent.examples.tool_demo
```

## 🔍 주요 클래스

### GeminiAgent

메인 Agent 클래스로 다음 기능을 제공합니다:

- `chat(message)`: 일반 채팅
- `chat_stream(message)`: 스트리밍 채팅
- `clear_conversation()`: 대화 기록 삭제
- `get_status()`: Agent 상태 확인

### ConversationMemory

대화 메모리 관리를 담당합니다:

- `add_user_message(content)`: 사용자 메시지 추가
- `add_assistant_message(content)`: AI 응답 추가
- `get_recent_history(limit)`: 최근 대화 기록 조회
- `clear_all()`: 모든 기록 삭제

### BaseTool

모든 도구의 기본 클래스:

- `execute(**kwargs)`: 도구 실행
- `get_schema()`: 도구 스키마 반환
- `validate_parameters(**kwargs)`: 매개변수 검증

## 🚨 주의사항

1. **API 키 보안**: Google API 키를 안전하게 관리하세요
2. **토큰 제한**: 모델의 토큰 제한을 고려하여 메모리 크기를 조정하세요
3. **비동기 처리**: 모든 메서드는 비동기이므로 `await`를 사용하세요
4. **에러 처리**: 네트워크 오류나 API 제한에 대한 예외 처리를 구현하세요

## 🔄 확장 방법

### 새로운 도구 추가

```python
from ai_agent.tools.base import BaseTool, ToolResult

class CustomTool(BaseTool):
    def __init__(self):
        super().__init__("custom_tool", "Custom tool description")
    
    async def execute(self, **kwargs) -> ToolResult:
        # 도구 로직 구현
        return ToolResult(success=True, result="Custom result")
    
    def get_schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {...}
            }
        }
```

### 커스텀 메모리 구현

```python
from ai_agent.memory.conversation import ConversationMemory

class CustomMemory(ConversationMemory):
    def __init__(self):
        super().__init__()
        # 커스텀 로직 추가
    
    def custom_method(self):
        # 커스텀 메서드 구현
        pass
```

## 📝 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다.

## 🤝 기여

버그 리포트, 기능 요청, 풀 리퀘스트를 환영합니다!

---

**Gemini AI Agent** - LangChain과 Gemini 2.5 Pro를 활용한 강력한 AI Agent
