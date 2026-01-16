"""Web search tool for AI Agent."""

import asyncio
import os
import re
from typing import Any, Dict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_perplexity import ChatPerplexity

from ..utils.config import config
from ..utils.logger import logger
from .base import ToolResult
from .base import ReActBaseTool


class PerplexitySearchTool(ReActBaseTool):
    def __init__(self):
        super().__init__(
            name="web_search_tool",
            description="Search the web for current information using Perplexity AI. Provides real-time web results with citations.",
        )
        try:
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

        try:
            logger.info(f"Searching web with Perplexity for: {query}")

            response = await self.chat.ainvoke(
                [
                    SystemMessage(
                        content="You are a comprehensive search assistant. Provide detailed, accurate, and up-to-date information with sources. Be thorough and analytical in your responses."
                    ),
                    HumanMessage(content=query),
                ]
            )
            answer = response.content
            meta = getattr(response, "response_metadata", {}) or {}
            extra = getattr(response, "additional_kwargs", {}) or {}
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
                result={"query": query, "answer": answer, "sources": sources},
                metadata={
                    "search_type": "perplexity_web",
                    "model": "sonar",
                    "usage": getattr(response, "usage_metadata", {}),
                },
            )
        except Exception as e:
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
        results = await asyncio.gather(*(self._execute_single_search(q) for q in queries))
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
