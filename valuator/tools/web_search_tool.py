"""Web search tool for AI Agent."""

import asyncio
import os
import re
from typing import Any, Dict

from dotenv import load_dotenv
try:
    from langchain_core.messages import HumanMessage, SystemMessage
except Exception:  # pragma: no cover - optional dependency at runtime
    HumanMessage = None
    SystemMessage = None

try:
    from langchain_perplexity import ChatPerplexity
except Exception:  # pragma: no cover - optional dependency at runtime
    ChatPerplexity = None

from ..utils.config import config
from ..utils.logger import logger
from .base import ToolResult
from .base import ReActBaseTool


class PerplexitySearchTool(ReActBaseTool):
    def __init__(self, usage_writer: Any | None = None):
        super().__init__(
            name="web_search_tool",
            description="Search the web for current information using Perplexity AI. Provides real-time web results with citations.",
        )
        self.usage_writer = usage_writer
        try:
            if ChatPerplexity is None or HumanMessage is None or SystemMessage is None:
                raise ValueError("langchain-perplexity dependency is unavailable")
            api_key = config.perplexity_api_key
            if not api_key:
                load_dotenv(".env")
                api_key = os.getenv("PPLX_API_KEY")
            if not api_key:
                raise ValueError("PPLX_API_KEY not found in config or environment")
            self.chat = ChatPerplexity(
                model="sonar",
                temperature=0.1,
                pplx_api_key=api_key,
            )
            self.available = True
            logger.info("PerplexitySearchTool initialized successfully")
        except Exception as e:
            logger.warning(f"PerplexitySearchTool initialization failed: {e}")
            self.chat = None
            self.available = False

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        self.usage_writer = usage_writer

    async def execute(
        self,
        query: str | None = None,
        queries: list[str] | None = None,
        **kwargs,
    ) -> ToolResult:
        if queries:
            if not all(isinstance(q, str) and q.strip() for q in queries):
                return ToolResult(
                    success=False,
                    result=None,
                    error="queries must be non-empty strings",
                )
            return await self._execute_batch_search(queries)
        if not query:
            return ToolResult(
                success=False, result=None, error="query or queries is required"
            )
        return await self._execute_single_search(query)

    async def _execute_single_search(self, query: str) -> ToolResult:
        if not self.available or not self.chat:
            return ToolResult(
                success=False,
                result=None,
                error="Perplexity API not available. Check PPLX_API_KEY configuration or dependencies.",
            )

        from ..core.llm_usage import start_measurement

        writer = self.usage_writer
        measurement = start_measurement()

        try:
            logger.info(f"Searching web with Perplexity for: {query}")

            response = await self.chat.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "You are a comprehensive search assistant. "
                            "Provide detailed, accurate, and up-to-date information with sources. "
                            "Be thorough and analytical in your responses."
                        )
                    ),
                    HumanMessage(content=query),
                ]
            )
            latency_ms = measurement.latency_seconds()
            answer = response.content
            meta = getattr(response, "response_metadata", {}) or {}
            extra = getattr(response, "additional_kwargs", {}) or {}
            usage_meta = getattr(response, "usage_metadata", {}) or {}
            if hasattr(usage_meta, "model_dump"):
                usage_meta = usage_meta.model_dump()
            if not isinstance(usage_meta, dict):
                usage_meta = {}

            if writer is not None:
                writer.append_call(
                    method="web_search_tool._execute_single_search",
                    model="sonar",
                    usage=usage_meta,
                    latency_ms=latency_ms,
                    started_at=measurement.started_at,
                )

            sources = (
                meta.get("citations")
                or meta.get("sources")
                or extra.get("citations")
                or extra.get("sources")
                or re.findall(r"https?://[^\s)]+", answer)
                or [f"[{n}]" for n in sorted(set(re.findall(r"\[(\d+)\]", answer)))]
            )

            return ToolResult(
                success=True,
                result={
                    "query": query,
                    "summary": answer,
                    "answer": answer,
                    "sources": sources,
                },
                metadata={
                    "search_type": "perplexity_web",
                    "model": "sonar",
                    "usage": usage_meta,
                },
            )
        except Exception as e:
            latency_ms = measurement.latency_seconds()
            if writer is not None:
                writer.append_call(
                    method="web_search_tool._execute_single_search",
                    model="sonar",
                    usage={
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                    latency_ms=latency_ms,
                    started_at=measurement.started_at,
                )
            logger.error(f"Perplexity search failed: {e}")
            return ToolResult(
                success=False, result=None, error=f"Search failed: {str(e)}"
            )

    async def _execute_batch_search(self, queries: list[str]) -> ToolResult:
        if not self.available or not self.chat:
            return ToolResult(
                success=False,
                result=None,
                error="Perplexity API not available. Check PPLX_API_KEY configuration or dependencies.",
            )
        if not queries:
            return ToolResult(
                success=False, result=None, error="queries must be a non-empty list"
            )
        results = await asyncio.gather(
            *(self._execute_single_search(q) for q in queries)
        )
        if any(not r.success for r in results):
            return ToolResult(
                success=False,
                result=[r.model_dump() for r in results],
                error="One or more searches failed",
            )
        return ToolResult(
            success=True,
            result={"results": [r.model_dump() for r in results]},
            metadata={"search_type": "perplexity_web_batch", "count": len(results)},
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query for current web information",
                        },
                        "queries": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Parallel search queries",
                        },
                    },
                    "required": [],
                },
            },
        }
