# OpenRouter 통합 — 구현 스펙

## 1. 목표

에이전트 LLM 경로에 OpenRouter를 대안 백엔드로 추가한다.
경계(팩토리)에서 백엔드를 결정하고, 내부는 Protocol만 참조한다.

**범위**: 에이전트 본체 LLM 호출만. 웹 검색(Perplexity Sonar)은 대상이 아니다.

---

## 2. 현재 GeminiClient 의존 지점

`GeminiClient`를 직접 생성하는 곳 — 이 지점들이 팩토리로 교체되어야 한다.

| 위치 | 용도 | 사용 메서드 |
|------|------|------------|
| `server/main.py:92` | QueryAnalyzer | `generate_json` |
| `server/main.py:500` | Agent 본체 | `generate`, `generate_json` |
| `scripts/run_recursive_agent_query.py:118` | QueryAnalyzer (CLI) | `generate_json` |
| `scripts/run_recursive_agent_query.py:292` | Agent 본체 (CLI) | `generate`, `generate_json` |
| `valuator/tools/domain_tool.py:17` | DomainTool 내부 | `generate` |
| `valuator/tools/sec_tool.py:203` | SECTool 내부 | `generate`, `generate_json` |
| `server/services/task_rewrite/llm_client.py:47` | TaskRewrite | `generate` |
| `domain/query_analysis.py:567` | QueryAnalyzer fallback | `generate_json` |

---

## 3. LlmClient Protocol

`GeminiClient`의 실사용 메서드에서 추출한 최소 계약.

```python
# valuator/models/protocol.py

from __future__ import annotations
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class LlmClient(Protocol):
    model: str

    def bind_usage_writer(self, usage_writer: Any | None) -> None: ...

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        response_mime_type: str | None = None,
        response_json_schema: dict[str, Any] | None = None,
        trace_method: str = "llm.generate",
        max_output_tokens: int | None = None,
    ) -> str: ...

    async def generate_json(
        self,
        *,
        prompt: str,
        system_prompt: str = "",
        response_json_schema: dict[str, Any],
        trace_method: str,
        max_response_chars: int | None = None,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]: ...
```

**GeminiClient**는 이미 이 시그니처를 만족한다 — 수정 불필요.

---

## 4. OpenRouterClient 구현

```python
# valuator/models/openrouter.py

from __future__ import annotations
import asyncio, json
from typing import Any
from openai import AsyncOpenAI
from ..utils.config import config
from ..core.llm_usage import Measurement

class OpenRouterClient:
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        usage_writer: Any | None = None,
        retry_count: int | None = None,
        retry_base_delay: float | None = None,
    ):
        self.model = model or config.agent_model
        self.usage_writer = usage_writer
        self._retry_count = retry_count if retry_count is not None else config.agent_llm_retry_count
        self._retry_base_delay = retry_base_delay if retry_base_delay is not None else config.agent_llm_retry_base_delay
        self._client = AsyncOpenAI(
            api_key=api_key or config.openrouter_api_key,
            base_url=base_url or config.openrouter_base_url,
        )

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        self.usage_writer = usage_writer

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        response_mime_type: str | None = None,
        response_json_schema: dict[str, Any] | None = None,
        trace_method: str = "openrouter.generate",
        max_output_tokens: int | None = None,
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if max_output_tokens is not None:
            kwargs["max_tokens"] = max_output_tokens
        if response_json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": response_json_schema,
                },
            }
        elif response_mime_type == "application/json":
            kwargs["response_format"] = {"type": "json_object"}

        writer = self.usage_writer

        for attempt in range(self._retry_count + 1):
            measurement = Measurement.start()
            try:
                response = await self._client.chat.completions.create(**kwargs)
                latency_seconds = measurement.latency_seconds()

                text = (response.choices[0].message.content or "").strip()
                if not text:
                    raise ValueError("Empty response from OpenRouter")

                usage = None
                if response.usage:
                    usage = {
                        "prompt_tokens": response.usage.prompt_tokens or 0,
                        "completion_tokens": response.usage.completion_tokens or 0,
                        "total_tokens": response.usage.total_tokens or 0,
                    }

                if writer is not None:
                    writer.append_call(
                        method=trace_method,
                        model=self.model,
                        usage=usage,
                        latency_seconds=latency_seconds,
                        started_at=measurement.started_at,
                    )
                return text

            except Exception as exc:
                if writer is not None:
                    retry_suffix = f".retry{attempt}" if attempt < self._retry_count else ""
                    writer.append_call(
                        method=f"{trace_method}.error{retry_suffix}",
                        model=self.model,
                        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                        latency_seconds=measurement.latency_seconds(),
                        started_at=measurement.started_at,
                    )
                if attempt >= self._retry_count:
                    raise
                await asyncio.sleep(self._retry_base_delay * (2 ** attempt))

    async def generate_json(
        self,
        *,
        prompt: str,
        system_prompt: str = "",
        response_json_schema: dict[str, Any],
        trace_method: str,
        max_response_chars: int | None = None,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        raw = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            response_mime_type="application/json",
            response_json_schema=response_json_schema,
            trace_method=trace_method,
            max_output_tokens=max_output_tokens,
        )
        if max_response_chars is not None and len(raw) > max_response_chars:
            raise ValueError(
                f"{trace_method} returned oversized JSON ({len(raw)} chars > {max_response_chars})"
            )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            decoder = json.JSONDecoder()
            data = None
            for index, char in enumerate(raw):
                if char != "{":
                    continue
                try:
                    candidate, _ = decoder.raw_decode(raw[index:])
                except json.JSONDecodeError:
                    continue
                if isinstance(candidate, dict):
                    data = candidate
                    break
            if data is None:
                raise ValueError(f"{trace_method} returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{trace_method} expected JSON object")
        return data
```

---

## 5. 팩토리 함수

```python
# valuator/models/factory.py

from __future__ import annotations
from typing import Any
from ..utils.config import config

def create_llm_client(
    model: str | None = None,
    usage_writer: Any | None = None,
) -> Any:  # returns LlmClient
    backend = config.llm_backend
    resolved_model = model or config.agent_model

    if backend == "openrouter":
        from .openrouter import OpenRouterClient
        return OpenRouterClient(
            model=resolved_model,
            usage_writer=usage_writer,
        )

    from .gemini_direct import GeminiClient
    return GeminiClient(
        model=resolved_model,
        usage_writer=usage_writer,
    )
```

---

## 6. Config 변경

`valuator/utils/config.py`에 추가할 필드:

```python
# Config dataclass에 추가
llm_backend: str              # "google_genai" | "openrouter"
openrouter_api_key: str | None
openrouter_base_url: str

# load_config()에 추가
llm_backend=read_env("LLM_BACKEND", "google_genai") or "google_genai",
openrouter_api_key=read_env("OPENROUTER_API_KEY"),
openrouter_base_url=read_env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1") or "https://openrouter.ai/api/v1",
```

`MODEL_ALIASES`에 OpenRouter 슬러그 매핑 추가:

```python
MODEL_ALIASES = {
    # 기존 Gemini
    "gemini-2.5-flash": "gemini-3-flash-preview",
    "gemini-flash-latest": "gemini-3-flash-preview",
    "gemini-2.5-pro": "gemini-3-pro-preview",
    "gemini-pro-latest": "gemini-3-pro-preview",
    # OpenRouter — canonical은 OR 슬러그 그대로 사용
    # (OR 백엔드에서는 alias 변환을 건너뛰거나, OR 슬러그를 canonical로 등록)
}
```

`PRICING`에 OR 모델 추가:

```python
LLMUsage.PRICING = {
    "gemini-3-flash-preview": (0.50, 3.00, 0.0),
    "gemini-3-pro-preview": (2.00, 12.00, 0.0),
    "sonar": (1.00, 1.00, 0.005),
    # OpenRouter 경유 — OR 마진 포함 단가로 갱신
    "google/gemini-2.5-flash": (0.50, 3.00, 0.0),  # 예시, 실제 단가 확인 필요
}
```

---

## 7. 경계 교체 지점 (diff 개요)

### 7.1 `server/main.py`

```diff
- from valuator.models.gemini_direct import GeminiClient, ensure_supported_google_genai_runtime
+ from valuator.models.factory import create_llm_client

  # build_query_analysis 내부
- analyzer=QueryAnalyzer(client=GeminiClient(model=model)),
+ analyzer=QueryAnalyzer(client=create_llm_client(model=model)),

  # run_agent 내부
- llm_client=GeminiClient(
-     model=record.model,
-     usage_writer=usage_writer,
- ),
+ llm_client=create_llm_client(
+     model=record.model,
+     usage_writer=usage_writer,
+ ),
```

### 7.2 `scripts/run_recursive_agent_query.py`

동일 패턴. `GeminiClient(...)` → `create_llm_client(...)`.

### 7.3 `valuator/tools/domain_tool.py`

```diff
  def __init__(self, usage_writer=None, model=None):
-     from ..models.gemini_direct import GeminiClient as RuntimeGeminiClient
-     self.client = RuntimeGeminiClient(model or config.agent_model, usage_writer=usage_writer)
+     from ..models.factory import create_llm_client
+     self.client = create_llm_client(model=model, usage_writer=usage_writer)
```

### 7.4 `valuator/tools/sec_tool.py`

동일 패턴.

### 7.5 `server/services/task_rewrite/llm_client.py`

```diff
- from valuator.models.gemini_direct import GeminiClient
+ from valuator.models.factory import create_llm_client

  # _get_model 내부
- self._model_cache[cache_key] = GeminiClient(model=model_name, api_key=self.api_key)
+ self._model_cache[cache_key] = create_llm_client(model=model_name)
```

### 7.6 `domain/query_analysis.py`

```diff
- from valuator.models.gemini_direct import GeminiClient as RuntimeGeminiClient
- client = RuntimeGeminiClient(config.agent_model)
+ from valuator.models.factory import create_llm_client
+ client = create_llm_client()
```

---

## 8. 의존성

`requirements.txt`에 추가:

```
openai>=1.0.0
```

`openai` SDK는 OpenRouter뿐 아니라 OpenAI 호환 엔드포인트 전반에 사용 가능.
`LLM_BACKEND=google_genai`(기본값)이면 import되지 않으므로 런타임 영향 없음.

---

## 9. 테스트 계획

### 9.1 단위 테스트

| 대상 | 검증 |
|------|------|
| `OpenRouterClient.generate` | 응답 텍스트 추출, usage 매핑, 빈 응답 시 ValueError |
| `OpenRouterClient.generate_json` | JSON 파싱, oversized 거부, 스키마 위반 복구 시도 |
| `create_llm_client` | `LLM_BACKEND` 값에 따라 올바른 클래스 반환 |
| `LlmClient` Protocol | `GeminiClient`, `OpenRouterClient` 모두 `isinstance(client, LlmClient)` 통과 |

### 9.2 평가 프레임워크

POC의 목적은 "전환할 가치가 있는가"를 수치로 판단하는 것이다.
대표 쿼리 **5개**(한국어 2, 영어 2, 혼합 1)를 고정하고, 동일 쿼리를 두 백엔드로 실행한다.

```bash
# Gemini 직접 (baseline)
LLM_BACKEND=google_genai python scripts/run_recursive_agent_query.py --query "..."

# OpenRouter 경유
LLM_BACKEND=openrouter OPENROUTER_API_KEY=... AGENT_MODEL=google/gemini-2.5-flash \
  python scripts/run_recursive_agent_query.py --query "..."
```

#### 측정 항목

| 질문 | 데이터 소스 | 측정 방법 | 통과 기준 |
|------|------------|-----------|-----------|
| **현재 비용 구조는?** | `llm_usage.jsonl` TOTAL 행 | 모델별 `cost_usd` 합산. sonar vs agent LLM 비중 분리 (`method` 필드에서 `web_search_tool` 필터) | baseline 확보 (통과/실패 없음) |
| **실제로 싸지는가?** | 양쪽 `llm_usage.jsonl` | 동일 쿼리의 `prompt_tokens` × 모델 단가로 견적표 작성. OR 마진 포함 실단가 사용 | OR 경유 비용 ≤ Gemini 직접 비용 × 1.1 (10% 이내) |
| **JSON 스키마를 지키는가?** | `method` 필드 `.error` / `.retry` 접미사 | `step_planner`, `decomposition_critic`, `query_analysis` 3경로의 1차 성공률 (retry 없이 유효 JSON 반환 비율) | 1차 성공률 ≥ 90% (Gemini baseline 대비 -5%p 이내) |
| **느려지지 않는가?** | `latency_ms` 필드 | 쿼리당 전체 `latency_ms` 합산의 p50, p95 | p95 ≤ Gemini baseline p95 × 1.5 |
| **재시도가 늘지 않는가?** | `method` 필드 `.retry` 카운트 | 전체 호출 대비 retry 비율 | retry율 ≤ 10% |

#### 견적표 포맷

각 쿼리에 대해 아래 형태로 산출:

```
Query: "삼성전자 2024년 실적 분석"
Backend: google_genai → gemini-3-flash-preview
  Agent LLM:  prompt 12,340 tok × $0.50/1M + completion 3,210 tok × $3.00/1M = $0.0158
  Sonar:      prompt 8,100 tok × $1.00/1M + completion 2,400 tok × $1.00/1M + $0.005/req × 4 = $0.0305
  Total: $0.0463

Backend: openrouter → google/gemini-2.5-flash
  Agent LLM:  prompt 12,340 tok × $0.50/1M + completion 3,210 tok × $3.00/1M = $0.0158
  Sonar:      (동일 — 검색 경로 불변)
  Total: $0.0463
  차이: +0.0% (OR 마진 포함 시 재계산)
```

#### 판단 기준

| 결과 | 행동 |
|------|------|
| 5개 항목 모두 통과 | 구현 진행 (§10 단계 6~8) |
| 비용만 미통과 (OR이 비쌈) | OR 불채택. Flash 하향 또는 현행 유지 |
| JSON 스키마 미통과 | 해당 모델 불채택. 다른 OR 모델로 재측정 또는 불채택 |
| 지연/재시도 미통과 | OR 리전/모델 변경 후 재측정 1회. 재실패 시 불채택 |

---

## 10. 실행 순서

| 단계 | 작업 | 산출물 |
|------|------|--------|
| 1 | `Config`에 `llm_backend`, `openrouter_*` 필드 추가 | `config.py` 변경 |
| 2 | `LlmClient` Protocol 정의 | `valuator/models/protocol.py` |
| 3 | `OpenRouterClient` 구현 | `valuator/models/openrouter.py` |
| 4 | `create_llm_client` 팩토리 | `valuator/models/factory.py` |
| 5 | 단위 테스트 | `tests/test_openrouter_client.py`, `tests/test_llm_factory.py` |
| 6 | §7 경계 교체 (8개 지점) | diff 적용 |
| 7 | `PRICING` 매핑 갱신 | `llm_usage.py` |
| 8 | 통합 테스트 (baseline vs OR) | 비교 리포트 |

단계 1-5는 `LLM_BACKEND=google_genai`(기본값)에서 기존 동작에 영향 없음.
단계 6부터 팩토리 경유로 전환되나, 기본값이 Gemini이므로 회귀 없음.

---

## 11. 리스크

| ID | 리스크 | 영향 | 완화 |
|----|--------|------|------|
| R1 | OR 모델의 JSON 스키마 불이행 → planner/critic 실패 | 높음 | POC에서 위반율 측정 후 결정 |
| R2 | PRICING 키 불일치 → 비용 추적 0 | 중간 | OR 슬러그를 PRICING에 명시 등록 |
| R3 | OR 장애 시 전체 중단 | 중간 | 기본값이 Gemini — OR 장애 시 env만 변경 |
| R4 | 지연 증가 (한국 ↔ OR 리전) | 중간 | POC에서 p95 측정 |
