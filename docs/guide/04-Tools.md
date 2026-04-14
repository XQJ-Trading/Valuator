# 도구 시스템 (Tools)

작업(Task)이 외부 정보를 수집하거나 복잡한 계산을 수행하기 위해 사용하는 핵심 수단입니다.

## 1. 도구 목록 개요

| 도구 | 용도 | 입력 (Schema) | 출력 |
| :--- | :--- | :--- | :--- |
| **WebSearchTool** | 실시간 웹 검색 | `query: str`, `search_intent: str` | 검색 결과 텍스트 |
| **YFinanceBalanceSheetTool** | 기업 재무 데이터 조회 | `ticker: str` | 잔액표(JSON) |
| **SECTool** | 미국 증시 공시 문서 조회 | `ticker: str`, `form_type: str` | 10-K, 8-K 등 원문 |
| **ExecuteCodeTool** | 파이썬 코드 실행 | `code: str` | 실행 결과 (Stdout) |

---

## 2. 도구 인터페이스 정의

모든 도구는 공통된 인터페이스를 따르며, LLM이 이해할 수 있는 JSON 스키마를 제공해야 합니다.

### Tool 기본 클래스
```python
from abc import ABC, abstractmethod
from typing import Any

class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """도구의 고유 식별자 (예: 'web_search')"""
    
    @property
    @abstractmethod
    def description(self) -> str:
        """LLM이 도구의 용도를 이해하기 위한 설명"""
    
    @abstractmethod
    def get_spec(self) -> ToolSpec:
        """LLM 호출에 필요한 JSON Schema 반환"""
    
    @abstractmethod
    async def execute(self, **kwargs) -> Any:
        """도구의 실제 비즈니스 로직 실행"""
```

### 구현 예시: WebSearchTool
```python
class WebSearchTool(Tool):
    @property
    def name(self) -> str:
        return "web_search_tool"
    
    def get_spec(self) -> ToolSpec:
        return ToolSpec(
            name="web_search_tool",
            description="검색 쿼리로 최신 웹 정보를 검색합니다.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "검색어"},
                    "search_intent": {
                        "type": "string",
                        "enum": ["general", "deep", "financial"],
                    },
                },
                "required": ["query"],
            },
        )
    
    async def execute(self, query: str, search_intent: str = "general") -> str:
        response = await self.provider.search(query, intent=search_intent)
        return response.text
```

---

## 3. 도구 등록 및 관리 (Registry)

시스템 시작 시 사용할 도구들을 등록하고 관리하는 중앙 레지스트리입니다.

### 도구 등록 프로세스 (`runtime.py`)
```python
def create_tool_registry(model: str, usage_writer=None):
    registry = ToolRegistry()
    
    # 특수 초기화가 필요한 도구 인스턴스 생성
    code_tool = ExecuteCodeTool()
    code_tool.warm_up()  # 샌드박스 환경 사전 준비
    
    # 레지스트리에 도구 일괄 등록
    tools_to_register = [
        WebSearchTool(provider=create_web_search_provider()),
        code_tool,
        YFinanceBalanceSheetTool(),
        SECTool(model=model),
    ]
    
    for tool in tools_to_register:
        registry.register(tool)
    
    registry.bind_usage_writer(usage_writer)
    return registry
```

---

## 4. 실행 및 예외 처리

에이전트는 레지스트리를 통해 도구를 실행하며, 타임아웃과 실패에 대한 방어 로직을 가집니다.

### 도구 실행 흐름
1. **도구 조회:** `tool_request.tool_name`으로 등록된 인스턴스를 찾음.
2. **비동기 실행:** `asyncio.wait_for`를 사용하여 도구별 타임아웃 강제.
3. **결과 처리:** 성공 시 결과 반환, 실패 시 에러 로그 기록 및 재시도 방지.

### 실패 방지 로직 (Anti-Loop)
동일한 인자로 반복해서 실패하는 것을 막기 위해 실행 전 시그니처를 확인합니다.
```python
# Task 상태 관리 예시
signature = _generate_signature(tool_name, args)

if signature in task.failed_tool_request_signatures:
    # 이전에 실패했던 동일 요청은 즉시 차단
    return Error("Same request failed previously.")

if task.tool_failure_counts[tool_name] > MAX_FAILURES:
    task.blocked_tools.add(tool_name) # 해당 도구 전체 차단
```

---

## 5. 특수 도구: ExecuteCodeTool (Sandbox)

보안과 격리를 위해 코드는 별도의 샌드박스 프로세스에서 실행됩니다.

* **보안 프로토콜:**
    1.  실행 코드를 JSON으로 직렬화하여 전달.
    2.  독립된 서브프로세스에서 코드 실행.
    3.  결과(Stdout/Stderr) 수신 후 프로세스 자원 회수.
    4.  **타임아웃(기본 30초)** 초과 시 강제 종료.

---

## 6. 새 도구 추가 가이드

1.  **클래스 구현:** `Tool` 추상 클래스를 상속받아 `name`, `get_spec`, `execute` 구현.
2.  **레지스트리 등록:** `runtime.py`의 `create_tool_registry` 함수 내 목록에 추가.
3.  **LLM 연동:** 별도의 작업 없이도 `StepPlanner`가 자동으로 새로운 `ToolSpec`을 인식하여 프롬프트에 포함함.

> [!TIP]
> **Tool Hint 활용**
> 특정 작업에서 LLM이 헤맬 경우 `TaskSpec`에 `tool_hint="web_search"`와 같이 특정 도구 사용을 권장할 수 있습니다.

---

## 7. 도구별 권장 타임아웃

| 도구 이름 | 권장 타임아웃 |
| :--- | :--- |
| `web_search` | 15초 |
| `code_execute` | 30초 |
| `yfinance` | 10초 |
| `sec_tool` | 30초 |
