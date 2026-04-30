에이전트 시스템의 심장부라고 할 수 있는 **LLM 모델(Models) 통합 레이어** 설계 문서를 정리해 드립니다. 다양한 모델 제공자를 하나의 인터페이스로 묶고, 사용량 추적과 비용 계산까지 포함하는 구조로 다듬었습니다.

---

# LLM 모델 (Models)

에이전트가 사고하고 결정 내리는 데 필요한 LLM 추론 능력을 추상화한 계층입니다. 다양한 모델 제공자(Provider)를 지원하며, 시스템 내 모든 모듈은 구현체에 관계없이 동일한 인터페이스를 사용합니다.



## 1. 지원 모델 및 제공자

| 제공자 | 주요 모델 (기본값) | 구현 파일 | 특징 |
| :--- | :--- | :--- | :--- |
| **Google** | Gemini 2.0 Flash / Pro | `gemini_direct.py` | 빠른 속도와 긴 컨텍스트 윈도우 |
| **OpenRouter** | Llama 3, Qwen 등 다양함 | `openrouter.py` | 오픈소스 모델 및 저비용 모델 접근 |

---

## 2. LLM 클라이언트 인터페이스 (Protocol)

모든 클라이언트는 아래의 `LLMClient` 프로토콜을 준수해야 합니다.

```python
from typing import Protocol, Any, dict

class LLMClient(Protocol):
    async def generate(
        self,
        system: str,
        user: str,
        max_tokens: int = 8192,
    ) -> str:
        """일반 텍스트 메시지 응답 반환"""
    
    async def generate_json(
        self,
        system: str,
        user: str,
        max_tokens: int = 8192,
    ) -> dict[str, Any]:
        """구조화된 JSON 응답 반환 (의사 결정 및 평가에 사용)"""
```

---

## 3. 주요 구성 요소에서의 활용

### StepPlanner (의사 결정)
LLM의 `generate_json` 기능을 사용하여 에이전트의 다음 행동(`TaskDecision`)을 결정합니다.

```python
class StepPlanner:
    async def decide(self, task: Task, ctx: TaskContext) -> TaskDecision:
        # 프롬프트 생성 및 LLM 호출
        response = await self._llm.generate_json(
            system=prompts.build_system_prompt(ctx),
            user=prompts.build_step_prompt(task, ctx),
            max_tokens=8192,
        )
        # JSON 응답을 객체로 변환
        return parse_decision(response)
```

### DecompositionCritic (분해 검증)
제안된 작업 분해가 적절한지 비판적으로 평가하여 점수를 매깁니다.

---

## 4. 모델 선택 및 팩토리 패턴

`create_llm_client` 함수를 통해 환경 변수나 요청 파라미터에 따라 적절한 클라이언트를 동적으로 생성합니다.

```python
def create_llm_client(llm_backend: str = "google_genai", **kwargs) -> LLMClient:
    if llm_backend == "google_genai":
        return GeminiClient(api_key=os.getenv("GOOGLE_API_KEY"))
    elif llm_backend == "openrouter":
        return OpenRouterClient(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            model=kwargs.get("model", "meta-llama/llama-3-70b-instruct")
        )
    raise ValueError(f"지원하지 않는 백엔드: {llm_backend}")
```

---

## 5. 사용량 추적 및 비용 관리

### LLMUsageWriter
모든 LLM 호출의 토큰 사용량을 기록하여 최종 실행 보고서를 작성합니다.

```python
class LLMUsageWriter:
    def add_usage(self, model: str, input_tokens: int, output_tokens: int):
        self._usage_log.append({
            "model": model,
            "input": input_tokens,
            "output": output_tokens,
            "timestamp": datetime.utcnow().isoformat()
        })

    def get_summary(self):
        # 모델별 총 사용량 및 비용 계산 로직
        pass
```

### 실시간 비용 계산 (2026 기준 예시)
> [!NOTE]
> 아래 가격은 100만(1M) 토큰당 추정 가격($)이며, 시장 상황에 따라 변동될 수 있습니다.

| 모델명 | 입력(Input) | 출력(Output) |
| :--- | :--- | :--- |
| `claude-3-5-sonnet` | \$3.00 | \$15.00 |
| `gemini-2.0-flash` | \$0.10 | \$0.40 |
| `llama-3-70b` (OR) | \$0.60 | \$0.60 |

---

## 6. 에러 처리 및 회복 전략

1.  **지수 백오프 재시도 (Exponential Backoff):** `RateLimitError` 발생 시 대기 시간을 늘려가며 최대 3회 재시도합니다.
2.  **타임아웃 설정:** 응답이 60초 이상 지연될 경우 세션을 보호하기 위해 `asyncio.timeout`을 적용합니다.
3.  **폴백(Fallback) 메커니즘:** (선택 사항) 특정 모델 실패 시 저렴하거나 성능이 유사한 다른 모델로 자동 전환하는 로직을 추가할 수 있습니다.

---

## 7. 새로운 모델 추가 방법

1.  **Protocol 구현:** `LLMClient` 인터페이스를 따르는 새로운 클래스를 생성합니다.
2.  **JSON 파싱 최적화:** 해당 모델이 `JSON Mode`를 지원한다면 이를 활용하고, 지원하지 않는다면 프롬프트 엔지니어링을 통해 JSON 형식을 강제합니다.
3.  **팩토리 등록:** `get_llm_client` 함수에 조건문을 추가하여 시스템에서 호출할 수 있게 합니다.

---