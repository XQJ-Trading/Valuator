Plan: WebSearchTool Adapter Pattern + Tavily + UI Select

## 용어 (헷갈리지 않게)

- LLM이 고르는 **도구 이름(`tool_name`)** 은 항상 **`web_search_tool`** 이다. Perplexity/Tavily 중 무엇을 쓰는지는 **도구가 바뀌는 것이 아니라**, 같은 도구에 주입되는 **검색 백엔드(Provider) 어댑터**만 바뀐다.
- 채팅/API에서 쓰는 필드 **`web_search_provider`** 는 위 어댑터 선택이며, **`tool_name` 과 별개**다.
- **허용 값:** `perplexity` | `tavily` (소문자, 환경 변수 `WEB_SEARCH_PROVIDER` 과 동일한 식별자).

## 런타임 주입 (한 줄)

- **`create_tool_registry` 시점에 `PerplexityProvider` 와 `TavilyProvider` 중 하나만 만들어 `WebSearchTool` 에 주입한다.** 레지스트리에는 웹 검색 도구가 하나뿐이며, 런타임에 프로바이더 인스턴스는 하나만 존재한다.

## UI (A) — 사용 불가 옵션 비활성화

- 클라이언트가 선택한 provider에 해당 **API 키가 없거나** 초기화에 실패하면 해당 Provider는 `available=False` 가 된다.
- **옵션 비활성화**를 하려면 서버가 **“현재 사용 가능한 provider” 목록**(예: `perplexity` 키 있음 / `tavily` 키 있음)을 API로 내려주고, 프론트는 목록에 없는 값은 `<select>` 에서 빼거나 `disabled` 처리한다. (목록을 안 내리면 사용자가 비활성 provider를 고른 뒤 에이전트에서 도구 실패로 끝날 수 있다.)

---

Context

web_search_tool에 Perplexity가 하드코딩되어 있다. Tavily를 추가하면서 adapter pattern으로 프로바이더를 갈아끼울 수 있게 한다.

핵심 설계 문제 두 가지:

search_mode: "web" | "academic" | "sec"는 Perplexity 고유 개념 — Provider Protocol에 그대로 노출하면 추상화가 Perplexity에 종속된다. → 도메인 중립 intent "general" | "deep" | "financial"로 재정의하고, 각 Provider가 자기 API에 맞게 매핑.
Provider __init__의 반복 패턴 — 의존성 import 체크 + API key 체크 + available 플래그 세팅이 동일 구조. → 베이스 클래스로 추출.

## Tavily 공식 문서 (원문)

- **REST Search 엔드포인트·요청/응답 스키마:** [Tavily Search — API Reference](https://docs.tavily.com/documentation/api-reference/endpoint/search)
- **Python `AsyncTavilyClient.search` 파라미터·응답 키:** [SDK Reference (Python)](https://docs.tavily.com/sdk/python/reference)

아래 표·설명은 위 문서 기준이다. SDK 버전에 따라 일부 파라미터 이름/지원 여부가 다를 수 있으니, 설치한 `tavily-python` 의 실제 시그니처를 한 번 확인하는 것이 좋다.

### `client.search(...)` — 조정용 파라미터 (공식 요약)

| 파라미터 | 타입 (공식) | 기본값 (공식) | 조정 시 메모 |
| --- | --- | --- | --- |
| `query` | `str` | (필수) | — |
| `topic` | `"general"` \| `"news"` \| `"finance"` | `"general"` | Valuator에서는 intent→topic 매핑으로 덮어씀. **기본 코퍼스를 finance로 둘 때** `general` intent → `topic="finance"`. |
| `search_depth` | REST: `advanced` \| `basic` \| `fast` \| `ultra-fast` / SDK 문서 표: `basic` \| `advanced` | `basic` | **크레딧:** 공식 REST 설명상 `basic`·`fast`·`ultra-fast`는 1 credit, `advanced`는 2 credit (문서 [Search depth](https://docs.tavily.com/documentation/best-practices/best-practices-search) 참고). |
| `max_results` | `int` | `5` | **0–20** (공식). |
| `chunks_per_source` | `int` | `3` | **1–3**. `search_depth`가 `advanced`일 때만 의미 있음 (청크당 최대 500자). |
| `include_answer` | `bool` \| `"basic"` \| `"advanced"` | `False` | `True`/`basic`은 짧은 답, **`advanced`**는 더 긴 답. |
| `include_usage` | `bool` | `False` | **`True`로 두면 응답에 `usage`(예: `credits`) 포함** — `usage_meta`에 그대로 넣기 좋음. |
| `time_range` | `day`/`week`/`month`/`year` 또는 `d`/`w`/`m`/`y` | — | 최신성 필터. |
| `start_date` / `end_date` | `YYYY-MM-DD` | — | 기간 필터. |
| `include_raw_content` | `bool` \| `"markdown"` \| `"text"` | `False` | 지연·페이로드 증가. |
| `include_domains` / `exclude_domains` | `list[str]` | `[]` | 각각 최대 300 / 150 도메인 (REST 스키마). |
| `country` | `str` | — | **topic이 `general`일 때만** 사용 가능 (SDK 문서). |
| `timeout` | `float` | `60` | API 요청 타임아웃(초). |
| `auto_parameters` | `bool` | `False` | 켜면 쿼리 의도에 따라 파라미터 자동 설정. **`include_answer`·`include_raw_content`·`max_results`는 항상 수동**(SDK 문서). `search_depth`가 자동으로 advanced가 되면 **2 credit** 될 수 있음 — 비용 민감하면 명시적으로 `search_depth="basic"` 유지. |
| `exact_match` | `bool` | `False` | 쿼리에 따옴표로 구문 고정. |

### 응답 JSON — `usage_meta`에 옮기면 좋은 키 (공식)

| 키 | 설명 |
| --- | --- |
| `query` | 실행된 검색어 |
| `response_time` | float, 초 단위 |
| `answer` | `include_answer` 켰을 때만 |
| `results[]` | `title`, `url`, `content`, `score`, (옵션) `raw_content`, `favicon`, `images` 등 |
| `usage` | **`include_usage=True`일 때** — 문서 예: `{ "credits": 1 }` 형태의 **크레딧 사용량** |
| `request_id` | 지원/디버깅용 ID |

구현 시: **`usage_meta` = 요청에 실제로 넣은 인자(dict) + 응답의 `response_time`, `request_id`, `usage`(있으면)** 를 합치면, 나중에 대시보드/과금 추적에 재사용하기 쉽다.

## Tavily `usage_meta` 와 비용 (구체화)

- Tavily Search 응답은 **OpenAI 스타일 `prompt_tokens` / `completion_tokens` 를 주지 않는다.** 그래서 `TokenUsage.from_raw(result.usage_meta)` 는 대개 **0**이 된다. 이는 버그가 아니라 **API 형태 차이**다.
- **크레딧·요금:** 공식 응답 필드 **`usage`**(예: `credits`)는 요청에 **`include_usage=True`** 를 줄 때 포함된다 ([API Reference — `include_usage`](https://docs.tavily.com/documentation/api-reference/endpoint/search)). 이 dict 전체를 `usage_meta["usage"]` 또는 평탄화해 넣으면 된다.
- **`search_depth`와 크레딧:** REST 문서에 따르면 `basic`/`fast`/`ultra-fast`는 1 credit, `advanced`는 2 credit (동일 문서 Search depth 섹션). Valuator의 `MODEL_PRICES["tavily"]` 는 **토큰이 아니라 호출당·크레딧 단가**에 맞춰 조정하거나, 트레이스에는 **`usage.credits`** 를 우선 표시하는 편이 정확하다.
- **비용 집계(앱 내부):** `valuator/utils/llm_usage.py` 의 `ModelPrice(..., request_usd_per_call=...)` 는 **대략치**로 두고, **실제 청구는 Tavily 대시보드 + `usage` 필드**를 기준으로 맞춘다.
- Perplexity 쪽은 LangChain `usage_metadata` 가 오면 토큰 기반으로 채워질 수 있음 — **두 Provider의 usage 형태가 다르다**는 점을 트레이스/요약 UI에서 구분할 수 있게 한다.

### Perplexity 쪽 (163–179행 근처) — Tavily와 무관

해당 블록은 **LangChain `ChatPerplexity` / `AIMessage`** 의 `response_metadata`, `additional_kwargs`, `usage_metadata`, 인용 추출 로직이다. Tavily REST/SDK 응답 형식과는 다르다. Perplexity 전용으로 유지한다.

search_intent 매핑

도메인 중립 intent를 정의하고, 각 Provider가 자기 API 파라미터로 매핑:

| search_intent | 의미 | Perplexity 매핑 | Tavily 매핑 |
| --- | --- | --- | --- |
| "general" | 일반 웹 검색 | search_mode="web" | **topic="finance", depth="basic" (Tavily 기본 코퍼스: finance)** |
| "deep" | 학술/심층 검색 | search_mode="academic" | topic="general", depth="advanced" |
| "financial" | 금융/공시 특화 | search_mode="sec" | topic="finance", depth="advanced" |

**제품 결정:** Tavily는 기본적으로 **finance 토픽을 기본값**으로 쓴다. 그래서 `search_intent="general"` 이라도 Tavily 경로에서는 `topic="finance"` 로 검색한다(깊이는 `basic`). `deep` 만 `topic="general"` 로 넓게 잡는다.

영향 범위 — search_intent 리네임은 LLM이 호출하는 tool spec (specs.py), 프롬프트 (prompts.py), 기존 테스트까지 전파된다.

### 브로커 리서치 제외 — RAG 검색 경로(구현됨)

- `valuator/tools/web_search_tool.py`의 `_effective_search_query_for_rag`가 Perplexity(및 추후 Tavily) 호출 직전에 `RAG_SOURCE_POLICY_MARKER` 문구를 붙인다. 플래너와 무관하게 **웹 검색 자체 RAG**에 적용된다.
- 끄기: `WEB_SEARCH_RAG_EXCLUDE_BROKER_RESEARCH=0` → `config.web_search_rag_exclude_broker_research=False`.
- 이미 쿼리에 `[valuator_rag_source_policy]`가 있으면 중복하지 않는다. 트레이스에는 `metadata.effective_query`로 실제 전송 문자열을 남긴다.

---

1. 신규: valuator/tools/web_search_providers.py

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from ..utils.logger import logger

SearchIntent = Literal["general", "deep", "financial"]


@dataclass(frozen=True)
class WebSearchResult:
    answer: str
    sources: list[str]
    usage_meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class WebSearchProvider(Protocol):
    name: str
    model_name: str
    available: bool

    async def search(
        self, query: str, *, intent: SearchIntent,
    ) -> WebSearchResult: ...


class _BaseProvider:
    """Provider __init__ 공통 패턴: API key 조회 → 클라이언트 생성 → available 세팅."""

    name: str
    model_name: str
    _api_key_env: str  # 서브클래스가 선언 — config attribute 이름 (e.g. "perplexity_api_key")
    available: bool = False

    def _init_client(self, api_key: str) -> Any:
        """서브클래스가 구현. api_key는 검증 완료 상태. 성공 시 client 반환, 실패 시 예외."""
        raise NotImplementedError

    def __init__(self) -> None:
        from ..utils.config import config

        try:
            api_key = getattr(config, self._api_key_env, None)
            if not api_key:
                raise ValueError(f"{self._api_key_env} not found in config")
            self._client = self._init_client(api_key)
            self.available = True
            logger.info("%s initialized", self.__class__.__name__)
        except Exception as e:
            logger.warning("%s init failed: %s", self.__class__.__name__, e)
            self._client = None
            self.available = False


class PerplexityProvider(_BaseProvider):
    name = "perplexity"
    model_name = "sonar"
    _api_key_env = "perplexity_api_key"

    _INTENT_TO_MODE: dict[str, str] = {
        "general": "web",
        "deep": "academic",
        "financial": "sec",
    }

    def _init_client(self, api_key: str) -> Any:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_perplexity import ChatPerplexity

        self._HumanMessage = HumanMessage
        self._SystemMessage = SystemMessage
        return ChatPerplexity(model="sonar", temperature=0.1, pplx_api_key=api_key)

    async def search(
        self, query: str, *, intent: SearchIntent,
    ) -> WebSearchResult:
        mode = self._INTENT_TO_MODE[intent]
        response = await self._client.ainvoke(
            [
                self._SystemMessage(
                    content=(
                        "You are a comprehensive search assistant. "
                        "Provide detailed, accurate, and up-to-date information with sources. "
                        "Be thorough and analytical in your responses. "
                        "Write the full answer in Korean (한국어), including headings and explanations; "
                        "keep proper nouns, tickers, and direct quotes in their original form when needed."
                    )
                ),
                self._HumanMessage(content=query),
            ],
            extra_body={"web_search_options": {"search_mode": mode}},
        )

        answer = response.content
        meta = getattr(response, "response_metadata", {}) or {}
        extra = getattr(response, "additional_kwargs", {}) or {}
        usage_meta = getattr(response, "usage_metadata", {}) or {}
        if hasattr(usage_meta, "model_dump"):
            usage_meta = usage_meta.model_dump()
        if not isinstance(usage_meta, dict):
            usage_meta = {}

        sources = (
            meta.get("citations")
            or meta.get("sources")
            or extra.get("citations")
            or extra.get("sources")
            or re.findall(r"https?://[^\s)]+", answer)
            or [f"[{n}]" for n in sorted(set(re.findall(r"\[(\d+)\]", answer)))]
        )
        return WebSearchResult(answer=answer, sources=sources, usage_meta=usage_meta)


class TavilyProvider(_BaseProvider):
    """Tavily Async SDK. 파라미터 의미·기본값은 공식 문서를 기준으로 조정한다.
    https://docs.tavily.com/sdk/python/reference
    https://docs.tavily.com/documentation/api-reference/endpoint/search
    """

    name = "tavily"
    model_name = "tavily"
    _api_key_env = "tavily_api_key"

    # intent → (topic, search_depth). topic 기본을 finance로 쓰려면 general 행을 ("finance", "basic") 로 유지.
    _INTENT_MAP: dict[str, tuple[str, str]] = {
        "general": ("finance", "basic"),
        "deep": ("general", "advanced"),
        "financial": ("finance", "advanced"),
    }

    # --- 아래만 바꿔서 튜닝 (문서의 Default/제한과 맞출 것) ---
    _max_results: int = 5  # 공식: 0–20, default 5
    _include_answer: str | bool = "advanced"  # False | True | "basic" | "advanced"
    _include_usage: bool = True  # True 시 응답에 usage(크레딧) 포함 — usage_meta에 복사
    _chunks_per_source: int = 3  # 공식: 1–3, search_depth advanced 일 때만 적용
    _timeout: float = 60.0  # 공식 SDK default 60
    # 선택 — 기본은 미전달(SDK 기본값). 값을 주면 search() kwargs에 합친다.
    _time_range: str | None = None  # "day"|"week"|"month"|"year" 또는 "d"|"w"|"m"|"y"
    _start_date: str | None = None  # YYYY-MM-DD
    _end_date: str | None = None  # YYYY-MM-DD
    _include_raw_content: bool | str | None = None  # None이면 kwargs 생략. True|"markdown"|"text"
    _include_domains: tuple[str, ...] = ()  # 최대 300 (REST)
    _exclude_domains: tuple[str, ...] = ()  # 최대 150 (REST)
    _country: str | None = None  # SDK: topic이 general일 때만 의미 있음

    def _init_client(self, api_key: str) -> Any:
        from tavily import AsyncTavilyClient

        return AsyncTavilyClient(api_key=api_key)

    async def search(
        self, query: str, *, intent: SearchIntent,
    ) -> WebSearchResult:
        topic, depth = self._INTENT_MAP[intent]
        kwargs: dict[str, Any] = {
            "query": query,
            "topic": topic,
            "search_depth": depth,
            "max_results": self._max_results,
            "include_answer": self._include_answer,
            "include_usage": self._include_usage,
            "timeout": self._timeout,
        }
        if depth == "advanced":
            kwargs["chunks_per_source"] = self._chunks_per_source

        if self._time_range is not None:
            kwargs["time_range"] = self._time_range
        if self._start_date is not None:
            kwargs["start_date"] = self._start_date
        if self._end_date is not None:
            kwargs["end_date"] = self._end_date
        if self._include_raw_content is not None:
            kwargs["include_raw_content"] = self._include_raw_content
        if self._include_domains:
            kwargs["include_domains"] = list(self._include_domains)
        if self._exclude_domains:
            kwargs["exclude_domains"] = list(self._exclude_domains)
        if self._country is not None:
            kwargs["country"] = self._country

        response = await self._client.search(**kwargs)

        results = response.get("results", [])
        answer = response.get("answer", "")
        if not answer:
            answer = "\n\n".join(
                r.get("content", "") for r in results if r.get("content")
            )
        sources = [r["url"] for r in results if r.get("url")]

        usage_meta: dict[str, Any] = {
            "provider": "tavily",
            "request": {k: v for k, v in kwargs.items() if k != "query"},
        }
        for key in ("response_time", "request_id", "usage", "query"):
            if key in response:
                usage_meta[key] = response[key]

        return WebSearchResult(answer=answer, sources=sources, usage_meta=usage_meta)
```

설계 결정:

_BaseProvider.__init__이 _api_key_env로 config에서 API key를 읽고 _init_client(api_key) 호출 → 성공/실패에 따라 available 세팅. 서브클래스는 _api_key_env 선언 + _init_client(api_key)에서 의존성 import + 클라이언트 생성만 담당.
API key 조회/검증, available 플래그 관리, 로깅이 모두 _BaseProvider에 집중. 서브클래스에 boilerplate 없음.
의존성 import를 모듈 레벨 try/except가 아닌 _init_client() 내부에서 수행 — import 실패도 자연스럽게 available=False 처리.
SearchIntent 타입으로 Provider-agnostic intent 정의. Perplexity는 _INTENT_TO_MODE, Tavily는 _INTENT_MAP으로 각자 매핑.

---

2. 수정: valuator/tools/web_search_tool.py — 전체 교체

```python
"""Web search tool for AI Agent."""

from __future__ import annotations

import asyncio
from typing import Any

from ..utils.config import config
from ..utils.llm_usage import TokenUsage
from ..utils.logger import logger
from ..utils.time_utils import Measurement
from .base import ReActBaseTool, ToolResult
from .web_search_providers import SearchIntent, WebSearchProvider

_VALID_INTENTS: set[str] = {"general", "deep", "financial"}


class WebSearchTool(ReActBaseTool):
    def __init__(self, provider: WebSearchProvider, usage_writer: Any | None = None):
        super().__init__(
            name="web_search_tool",
            description=(
                "Search the web for current information. "
                "Provides real-time web results with citations."
            ),
        )
        self.provider = provider
        self.usage_writer = usage_writer
        self.available = provider.available

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        self.usage_writer = usage_writer

    async def execute(
        self,
        query: str | None = None,
        queries: list[str] | None = None,
        search_intent: str | None = None,
        **_kwargs,
    ) -> ToolResult:
        intent = (search_intent or "general").strip().lower()
        if intent not in _VALID_INTENTS:
            return ToolResult(
                success=False,
                result=None,
                error=f"search_intent must be one of: {', '.join(sorted(_VALID_INTENTS))}",
            )
        if queries:
            return await self._batch(queries, intent=intent)
        if not query:
            return ToolResult(
                success=False, result=None, error="query or queries is required"
            )
        return await self._single(query, intent=intent)

    async def _single(self, query: str, *, intent: SearchIntent) -> ToolResult:
        if not self.available:
            return ToolResult(
                success=False, result=None,
                error=f"{self.provider.name} provider not available.",
            )
        provider = self.provider
        writer = self.usage_writer
        max_retries = max(int(config.web_search_retry_count), 0)
        base_delay = float(config.web_search_retry_base_delay)

        for attempt in range(max_retries + 1):
            measurement = Measurement.start()
            try:
                logger.info(
                    "Searching with %s: %s (intent=%s)",
                    provider.name, query, intent,
                )
                result = await provider.search(query, intent=intent)
                latency = measurement.latency_seconds()
                if writer is not None:
                    writer.append_call(
                        method="web_search_tool._single",
                        model=provider.model_name,
                        usage=TokenUsage.from_raw(result.usage_meta),
                        latency_seconds=latency,
                        started_at=measurement.started_at,
                    )
                return ToolResult(
                    success=True,
                    result={
                        "query": query,
                        "findings": result.answer,
                        "sources": result.sources,
                    },
                    metadata={
                        "search_type": f"{provider.name}_web",
                        "model": provider.model_name,
                        "search_intent": intent,
                        "usage": result.usage_meta,
                    },
                )
            except Exception as e:
                latency = measurement.latency_seconds()
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "%s attempt %d failed (%s), retrying in %ss",
                        provider.name, attempt + 1, e, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                if writer is not None:
                    writer.append_call(
                        method="web_search_tool._single.error",
                        model=provider.model_name,
                        usage=TokenUsage(),
                        latency_seconds=latency,
                        started_at=measurement.started_at,
                    )
                logger.error("%s search failed: %s", provider.name, e)
                return ToolResult(
                    success=False, result=None, error=f"Search failed: {e}"
                )

    async def _batch(self, queries: list[str], *, intent: SearchIntent) -> ToolResult:
        if not self.available:
            return ToolResult(
                success=False, result=None,
                error=f"{self.provider.name} provider not available.",
            )
        results = await asyncio.gather(
            *(self._single(q, intent=intent) for q in queries)
        )
        if any(not r.success for r in results):
            return ToolResult(
                success=False,
                result=[r.model_dump() for r in results],
                error="One or more searches failed",
            )
        rows = [r.model_dump() for r in results]
        parts = []
        for row in rows:
            payload = row.get("result")
            if isinstance(payload, dict):
                findings = payload.get("findings", "")
                if isinstance(findings, str) and findings.strip():
                    parts.append(findings.strip())
        findings_text = "\n\n".join(parts) or f"batch search completed: {len(rows)} queries"
        return ToolResult(
            success=True,
            result={"findings": findings_text, "results": rows},
            metadata={
                "search_type": f"{self.provider.name}_web_batch",
                "count": len(results),
                "search_intent": intent,
            },
        )


# backward compat alias
PerplexitySearchTool = WebSearchTool
```

---

3. 수정: valuator/tools/specs.py

search_mode → search_intent, choices 변경, 프롬프트 description 변경.

L100-105: _select_choice fallback 조건도 web_search_tool + search_intent로 변경:

```python
if (
    selected is None
    and self.name == "web_search_tool"
    and key == "search_intent"
):
    selected = "general"
```

---

4. 수정: valuator/core/planning/prompts.py

L102: search_mode='sec' → search_intent='financial'

---

5–13. (config, llm_usage, runtime, __init__, CLI, chat_api, client, requirements, tests)

구현 순서·검증은 기존 플랜과 동일. API/클라이언트 계약:

- **Body:** `web_search_provider`: `""` | `perplexity` | `tavily`
- **빈 값:** 서버 기본 `WEB_SEARCH_PROVIDER` 사용
- **서버가 내려줄 수 있는 것 (UI A):** 예: `GET /api/chat/web-search-providers` → `{ "available": ["perplexity", "tavily"] }` (키·초기화 성공 여부 반영)

검증

pip install tavily-python + ruff check . + ruff format .
python -m pytest tests/test_web_search_tool.py tests/test_step_planner.py
CLI: python scripts/run_recursive_agent_query.py --query "삼성전자 분석" --web-search-provider tavily
E2E: dev server → chat UI select → tavily 선택 → 메시지 전송 → 서버 로그에 TavilyProvider 확인
