# AI Agent Tools

이 폴더에는 AI Agent를 위한 다양한 도구(tool)들이 구현되어 있습니다. ReAct 아키텍처를 기반으로 하며, 에이전트가 다양한 작업을 수행할 수 있도록 돕습니다.

## 📋 목차

- [React Tool 소개](#react-tool-소개)
- [기본 구조](#기본-구조)
- [사용 가능한 도구들](#사용-가능한-도구들)
- [신규 도구 추가 방법](#신규-도구-추가-방법)
- [베스트 프랙티스](#베스트-프랙티스)

## React Tool 소개

React Tool은 **ReAct (Reasoning + Acting)** 아키텍처를 기반으로 하는 AI 에이전트 도구 시스템입니다. 이 시스템은 다음을 특징으로 합니다:

### 주요 특징

- **비동기 실행**: 모든 도구가 `async/await` 기반으로 구현되어 있어 효율적인 비동기 작업 처리
- **타입 안정성**: Pydantic 기반의 타입 검증으로 안정적인 데이터 처리
- **실행 추적**: 도구 실행 횟수, 성공률, 실행 시간 등의 메타데이터 자동 수집
- **에러 처리**: 강력한 에러 처리와 로깅 시스템
- **확장성**: 모듈화된 구조로 새로운 도구를 쉽게 추가 가능

### ReAct 아키텍처

ReAct는 다음의 순환 구조로 동작합니다:
1. **Reasoning**: 현재 상황을 분석하고 다음 행동을 계획
2. **Acting**: 계획된 행동을 도구를 통해 실행
3. **Observing**: 실행 결과를 관찰하고 다음 단계 계획

## 기본 구조

### BaseTool 클래스

모든 도구의 기본이 되는 추상 클래스입니다:

```python
class BaseTool(ABC):
    def __init__(self, name: str, description: str)
    async def execute(self, **kwargs) -> ToolResult
    def get_schema(self) -> Dict[str, Any]
```

### ToolResult 클래스

도구 실행 결과를 담는 표준화된 응답 형식:

```python
class ToolResult(BaseModel):
    success: bool              # 실행 성공 여부
    result: Any               # 실행 결과
    error: Optional[str]      # 에러 메시지 (실패 시)
    metadata: Dict[str, Any]  # 추가 메타데이터
```

### ReActBaseTool 클래스

ReAct 특화 기능이 추가된 기본 클래스:

- 실행 카운트 및 성공률 추적
- 실행 시간 측정
- 향상된 메타데이터 수집

## 사용 가능한 도구들

### 1. PerplexitySearchTool

**목적**: 실시간 웹 검색 및 정보 수집

**주요 기능**:
- Perplexity AI를 통한 실시간 웹 검색
- 인용 정보와 출처 제공
- 다양한 언어 지원

**사용 예시**:
```python
tool = PerplexitySearchTool()
result = await tool.execute(query="Python async programming")
```

**특징**:
- `sonar` 모델 사용으로 정확도 높음
- 자동 인용 정보 추출
- API 키 기반 인증

### 2. CodeExecutorTool

**목적**: 안전한 Python 코드 실행

**주요 기능**:
- 코드 실행 및 결과 반환
- 타임아웃 설정
- 표준 출력/에러 캡처
- 안전한 실행 환경

**사용 예시**:
```python
tool = CodeExecutorTool()
result = await tool.execute(code="print('Hello, World!')")
```

**특징**:
- `exec()`와 `eval()`을 활용한 동적 코드 실행
- JSON 이스케이프 처리
- 안전한 빌트인 환경

### 3. FileSystemTool

**목적**: 파일 시스템 조작

**주요 기능**:
- 파일 읽기/쓰기
- 디렉토리 목록 조회
- 경로 검증 및 디렉토리 생성

**사용 예시**:
```python
tool = FileSystemTool()
result = await tool.execute(operation="read", path="config.txt")
```

**특징**:
- UTF-8 인코딩 지원
- 자동 디렉토리 생성
- 파일 크기 정보 제공

### 4. WebSearchTool

**목적**: Google Custom Search API를 통한 웹 검색

**주요 기능**:
- Google Custom Search API 연동
- 결과 수 제한 및 언어 설정
- 구조화된 검색 결과 반환

**특징**:
- Google Custom Search API 필요
- JSON 형식 결과 반환
- 검색 시간 및 총 결과 수 정보 제공

## 신규 도구 추가 방법

새로운 도구를 추가하려면 다음 단계를 따르세요:

### 1단계: 기본 구조 구현

```python
from .base import BaseTool, ToolResult

class MyNewTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="my_tool",
            description="나만의 도구에 대한 설명"
        )

    async def execute(self, **kwargs) -> ToolResult:
        # 도구 실행 로직 구현
        pass

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    # 파라미터 정의
                },
                "required": ["필수_파라미터"]
            }
        }
```

### 2단계: ReActBaseTool 상속 (권장)

더 나은 추적 기능을 위해 ReActBaseTool을 상속하세요:

```python
from .react_tool import ReActBaseTool

class MyNewTool(ReActBaseTool):
    def __init__(self):
        super().__init__(
            name="my_tool",
            description="나만의 도구에 대한 설명"
        )

    async def _execute_impl(self, **kwargs) -> ToolResult:
        # 실제 실행 로직 구현
        pass
```

### 3단계: 도구 등록

새로운 도구를 사용하려면 `tools/__init__.py`에 등록하세요:

```python
from .my_tool import MyNewTool

__all__ = ["BaseTool", "ToolResult", "WebSearchTool", "MyNewTool"]
```

### 4단계: 도구 사용

```python
from .tools import MyNewTool

tool = MyNewTool()
result = await tool.execute(param1="value1", param2="value2")
```

## 베스트 프랙티스

### 1. 에러 처리

```python
try:
    # 도구 실행 로직
    pass
except Exception as e:
    return ToolResult(
        success=False,
        result=None,
        error=f"도구 실행 중 오류: {str(e)}"
    )
```

### 2. 로깅

```python
self.logger.info(f"도구 실행 시작: {param}")
self.logger.error(f"도구 실행 실패: {error}")
```

### 3. 파라미터 검증

```python
def validate_parameters(self, **kwargs) -> bool:
    if not kwargs.get("required_param"):
        return False
    return True
```

### 4. 메타데이터 활용

```python
return ToolResult(
    success=True,
    result=execution_result,
    metadata={
        "execution_time": measured_time,
        "data_size": len(result),
        "custom_info": "추가 정보"
    }
)
```

### 5. 비동기 처리

```python
async def _execute_impl(self, **kwargs) -> ToolResult:
    # 비동기 API 호출 등
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()
    return ToolResult(success=True, result=data)
```

## 추가 리소스

- [ReAct 논문](https://arxiv.org/abs/2210.03629)
- [LangChain Tool 개발 가이드](https://python.langchain.com/docs/modules/tools/)
- [Pydantic 모델링 가이드](https://pydantic-docs.helpmanual.io/)

---

이 문서는 지속적으로 업데이트됩니다. 새로운 도구가 추가되거나 기존 도구가 개선될 때마다 내용을 갱신해주세요.
