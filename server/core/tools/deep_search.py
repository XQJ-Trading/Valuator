"""
Query Expansion Search Tool - 단편적인 쿼리를 다각도로 검색

Pipeline:
1. Query Rewrite: 유저의 context를 구체화
2. Query Decomposition: 구체화된 쿼리를 서브쿼리로 분해 (LLM이 개수 자율 결정)
3. Parallel Search: 각 쿼리를 병렬로 검색
4. Result Synthesis: 검색 결과를 분석하고 하나의 답변으로 합성
"""

import json
import re
import asyncio
import os
from typing import Any, Dict, List
from dotenv import load_dotenv

from langchain_core.messages import HumanMessage, SystemMessage

from ..models.gemini_direct import GeminiDirectModel
from ..utils.config import config
from ..utils.logger import logger
from .base import BaseTool, ToolResult
from .react_tool import PerplexitySearchTool


class QueryRewriter:
    """단편적인 유저 쿼리를 구체화하는 클래스."""

    REWRITE_PROMPT = """
    Analyze and rewrite the following search query to be more specific and comprehensive:

    Original Query: "{query}"

    Your task:
    1. IDENTIFY what the user is really looking for
    2. ADD relevant context and specificity
    3. MAINTAIN the core intent while making it more searchable
    4. CONSIDER time sensitivity (if asking for current/latest information, make it explicit)

    Guidelines:
    - Make the query more concrete and specific
    - Add relevant temporal context (e.g., "latest", "current", "as of 2024")
    - Include important details that would help get better search results
    - Keep it as a single, cohesive query (not multiple questions)

    Return ONLY the rewritten query - no explanation or additional text.
    """

    def __init__(self, llm_config: Dict[str, Any]):
        load_dotenv(".env")
        api_key = (
            llm_config.get("api_key")
            or config.google_api_key
            or os.getenv("GOOGLE_API_KEY")
        )

        if not api_key:
            logger.warning(
                "Google API key not found for QueryRewriter. Will use original queries."
            )
            self.llm = None
            self.available = False
        else:
            try:
                # Always use direct API
                self.llm = GeminiDirectModel(
                    model=llm_config.get("model", config.agent_model),
                    google_api_key=api_key,
                    temperature=0.1,
                    max_output_tokens=500,
                    thinking_level=None,  # Deep search uses default (no thinking level)
                    streaming=False,
                )
                logger.info("QueryRewriter initialized with Direct API")
                self.available = True
            except Exception as e:
                logger.warning(f"Failed to initialize QueryRewriter: {e}")
                self.llm = None
                self.available = False

    async def rewrite(self, query: str) -> str:
        """쿼리를 구체화하여 재작성합니다."""
        if not self.available or not self.llm:
            logger.info("LLM not available for rewrite, using original query")
            return query

        try:
            messages = [
                SystemMessage(
                    content="You are an expert at understanding user intent and rewriting queries for better search results."
                ),
                HumanMessage(content=self.REWRITE_PROMPT.format(query=query)),
            ]

            response = await self.llm.ainvoke(messages)
            rewritten = response.content.strip()

            if rewritten and len(rewritten) > 5:
                logger.info(f"Query rewritten: '{query}' -> '{rewritten}'")
                return rewritten

            return query

        except Exception as e:
            logger.warning(f"Query rewrite failed: {e}, using original")
            return query


class QueryDecomposer:
    """구체화된 쿼리를 서브쿼리로 분해하는 클래스."""

    DECOMPOSITION_PROMPT = """
    Break down this query into 3-4 DISTINCT search queries that explore DIFFERENT PERSPECTIVES:

    "{query}"

    Create queries that are:
    - DIFFERENT from each other (avoid similar wording)
    - Cover different angles: current state, causes, impacts, trends, solutions, statistics
    - Short and specific

    Examples for "Tesla stock analysis":
    - "Tesla stock technical analysis" (technical perspective)
    - "Tesla stock analyst opinions" (expert perspective)
    - "Tesla stock market sentiment" (market perspective)
    - "Tesla stock regulatory issues" (regulatory perspective)

    Return ONLY a JSON array: ["query 1", "query 2", ...]
    """

    def __init__(self, llm_config: Dict[str, Any]):
        load_dotenv(".env")
        api_key = (
            llm_config.get("api_key")
            or config.google_api_key
            or os.getenv("GOOGLE_API_KEY")
        )

        if not api_key:
            logger.warning(
                "Google API key not found for QueryDecomposer. Will use simple decomposition."
            )
            self.llm = None
            self.available = False
        else:
            try:
                # Always use direct API
                self.llm = GeminiDirectModel(
                    model=llm_config.get("model", config.agent_model),
                    google_api_key=api_key,
                    temperature=0.1,
                    max_output_tokens=600,
                    thinking_level=None,  # Deep search uses default (no thinking level)
                    streaming=False,
                )
                logger.info("QueryDecomposer initialized with Direct API")
                self.available = True
            except Exception as e:
                logger.warning(f"Failed to initialize QueryDecomposer: {e}")
                self.llm = None
                self.available = False

    async def decompose(self, query: str) -> List[str]:
        """쿼리를 서브쿼리로 분해합니다."""
        if not self.available or not self.llm:
            logger.info("LLM not available, using original query only")
            return [query]

        try:
            messages = [
                SystemMessage(
                    content="You are an expert at breaking down complex queries into focused sub-queries."
                ),
                HumanMessage(content=self.DECOMPOSITION_PROMPT.format(query=query)),
            ]

            response = await self.llm.ainvoke(messages)
            sub_queries = self._parse_response(response.content)

            if sub_queries and len(sub_queries) >= 2:
                logger.info(
                    f"Query decomposed into {len(sub_queries)} sub-queries: {sub_queries}"
                )
                return sub_queries
            return [query]

        except Exception as e:
            logger.warning(f"Decomposition failed: {e}, using original query")
            return [query]

    def _parse_response(self, response_text: str) -> List[str]:
        """LLM 응답에서 JSON 배열을 파싱합니다."""
        response_text = response_text.strip()

        if response_text.startswith("```"):
            # Extract content between ```json and ```
            match = re.search(
                r"```(?:json)?\s*\n?(.*?)\n?```", response_text, re.DOTALL
            )
            if match:
                response_text = match.group(1).strip()
            else:
                # Fallback: remove ``` markers
                response_text = re.sub(r"```(?:json)?\n?", "", response_text).strip()

        # Handle incomplete JSON responses (common issue)
        if response_text.startswith("```json") and not response_text.endswith("```"):
            # Try to find the end of the JSON content
            lines = response_text.split("\n")
            json_lines = []
            in_json = False
            for line in lines:
                if line.strip() == "```json":
                    in_json = True
                    continue
                elif line.strip() == "```" and in_json:
                    break
                elif in_json:
                    json_lines.append(line)
            if json_lines:
                response_text = "\n".join(json_lines).strip()

        # Handle truncated JSON responses (try to complete them)
        if response_text.startswith("[") and not response_text.endswith("]"):
            # Try to find the last complete element and close the array
            lines = response_text.split("\n")
            complete_lines = []
            for line in lines:
                line = line.strip()
                if line and '"' in line:
                    # Clean up the line and add it
                    cleaned_line = line.rstrip(",").strip()
                    if cleaned_line.startswith('"') and cleaned_line.endswith('"'):
                        complete_lines.append(cleaned_line)
                    elif cleaned_line.startswith('"'):
                        # Try to complete the string
                        complete_lines.append(cleaned_line + '"')
            if complete_lines:
                # Try to create a valid JSON array
                response_text = "[" + ",".join(complete_lines) + "]"

        # Additional fallback: try to extract queries from incomplete JSON
        if response_text.startswith("```json") and "[" in response_text:
            # Try to extract array content even if incomplete
            array_start = response_text.find("[")
            if array_start != -1:
                array_content = response_text[array_start:]
                # Try to find quoted strings in the array content
                quoted_strings = re.findall(r'"([^"]+)"', array_content)
                if len(quoted_strings) >= 2:
                    return quoted_strings[:6]

        try:
            # Try to parse as JSON array
            if response_text.startswith("[") and response_text.endswith("]"):
                queries = json.loads(response_text)
                if isinstance(queries, list):
                    valid = []
                    seen = set()
                    for q in queries:
                        if isinstance(q, str) and q.strip() and q.lower() not in seen:
                            valid.append(q.strip())
                            seen.add(q.lower())
                    return valid[:6] if valid else []

            # Try to parse as JSON object with array
            elif response_text.startswith("{") and response_text.endswith("}"):
                data = json.loads(response_text)
                if isinstance(data, dict):
                    # Look for common keys that might contain queries
                    for key in [
                        "queries",
                        "sub_queries",
                        "questions",
                        "search_queries",
                        "items",
                    ]:
                        if key in data and isinstance(data[key], list):
                            queries = data[key]
                            valid = []
                            seen = set()
                            for q in queries:
                                if (
                                    isinstance(q, str)
                                    and q.strip()
                                    and q.lower() not in seen
                                ):
                                    valid.append(q.strip())
                                    seen.add(q.lower())
                            return valid[:6] if valid else []
        except json.JSONDecodeError:
            pass

        # Try to extract queries from numbered lists
        numbered_pattern = (
            r"(?:\d+\.?\s*|\-\s*|\*\s*)(.+?)(?=\n\d+\.?\s*|\n\-\s*|\n\*\s*|$)"
        )
        numbered_matches = re.findall(
            numbered_pattern, response_text, re.MULTILINE | re.DOTALL
        )
        if len(numbered_matches) >= 2:
            valid = []
            seen = set()
            for match in numbered_matches:
                query = match.strip()
                if query and query.lower() not in seen:
                    valid.append(query)
                    seen.add(query.lower())
            return valid[:6] if valid else []

        # Try to extract quoted strings
        quoted = re.findall(r'"([^"]+)"', response_text)
        if len(quoted) >= 2:
            return list(dict.fromkeys(quoted))[:6]

        # Try to extract from lines that look like queries
        lines = [line.strip() for line in response_text.split("\n") if line.strip()]
        valid_lines = []
        seen = set()
        for line in lines:
            if (
                len(line) > 10
                and line.lower() not in seen
                and not line.startswith(("Query:", "Sub-query:", "Question:"))
            ):
                valid_lines.append(line)
                seen.add(line.lower())
        if len(valid_lines) >= 2:
            return valid_lines[:6]

        # Final fallback: try to extract any quoted strings from the response
        quoted_strings = re.findall(r'"([^"]{20,})"', response_text)
        if len(quoted_strings) >= 2:
            return quoted_strings[:6]

        return []


class ParallelSearchExecutor:
    """여러 검색 쿼리를 병렬로 실행하는 클래스."""

    def __init__(self, search_tool: BaseTool):
        self.search_tool = search_tool

    async def execute_parallel(self, queries: List[str]) -> List[Dict[str, Any]]:
        """여러 쿼리를 병렬로 검색합니다."""
        logger.info(f"Executing parallel search for {len(queries)} queries")

        async def _search(query: str) -> Dict[str, Any]:
            try:
                result = await self.search_tool.execute(query=query)
                return {
                    "query": query,
                    "success": result.success,
                    "result": result.result,
                    "error": result.error,
                }
            except Exception as e:
                logger.error(f"Search failed for '{query}': {e}")
                return {
                    "query": query,
                    "success": False,
                    "result": None,
                    "error": str(e),
                }

        results = await asyncio.gather(
            *[_search(q) for q in queries], return_exceptions=True
        )

        processed = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed.append(
                    {
                        "query": queries[i],
                        "success": False,
                        "result": None,
                        "error": str(result),
                    }
                )
            else:
                processed.append(result)

        success_count = sum(1 for r in processed if r["success"])
        logger.info(
            f"Parallel search completed: {success_count}/{len(queries)} successful"
        )

        return processed


class SearchResultSynthesizer:
    """여러 검색 결과를 분석하고 하나의 종합 답변으로 합성하는 클래스."""

    SYNTHESIS_PROMPT = """
    Synthesize the following search results into a comprehensive answer for: "{original_query}"

    Search Results:
    {results}

    Create a detailed, well-structured answer that:
    1. Combines ALL unique information from each source without losing important details
    2. Preserves specific numbers, statistics, dates, and concrete data points
    3. Identifies and highlights key insights and patterns
    4. Notes any contradictions or different perspectives between sources
    5. Provides a complete picture by connecting information from different angles
    6. Maintains accuracy with source attribution
    7. Adds analytical depth by comparing and contrasting findings
    8. Includes all relevant quotes, findings, and evidence from the sources

    CRITICAL: Do not summarize or truncate important information. Include all specific details, numbers, and concrete findings that were discovered in the search results.

    Make the answer significantly more comprehensive than any single source.
    Be thorough and detailed, preserving the full depth of information gathered.
    """

    def __init__(self, llm_config: Dict[str, Any]):
        load_dotenv(".env")
        api_key = (
            llm_config.get("api_key")
            or config.google_api_key
            or os.getenv("GOOGLE_API_KEY")
        )

        if not api_key:
            logger.warning(
                "Google API key not found for SearchResultSynthesizer. Will use basic synthesis."
            )
            self.llm = None
            self.available = False
        else:
            try:
                # Always use direct API
                self.llm = GeminiDirectModel(
                    model=llm_config.get("model", config.agent_model),
                    google_api_key=api_key,
                    temperature=0.1,
                    max_output_tokens=1500,
                    thinking_level=None,  # Deep search uses default (no thinking level)
                    streaming=False,
                )
                logger.info("SearchResultSynthesizer initialized with Direct API")
                self.available = True
            except Exception as e:
                logger.warning(f"Failed to initialize SearchResultSynthesizer: {e}")
                self.llm = None
                self.available = False

    async def synthesize(
        self, original_query: str, search_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """여러 검색 결과를 종합하여 최종 답변을 생성합니다."""
        successful = [r for r in search_results if r["success"] and r.get("result")]

        if not successful:
            return {
                "original_query": original_query,
                "answer": "검색 결과를 찾을 수 없습니다.",
                "sources": [],
                "search_count": len(search_results),
                "success_count": 0,
            }

        if self.available and self.llm:
            try:
                answer = await self._synthesize_with_llm(original_query, successful)
            except Exception as e:
                logger.warning(f"LLM synthesis failed: {e}")
                answer = self._basic_synthesis(successful)
        else:
            answer = self._basic_synthesis(successful)

        all_sources = self._collect_sources(successful)

        return {
            "original_query": original_query,
            "answer": answer,
            "sources": all_sources,
            "search_count": len(search_results),
            "success_count": len(successful),
            "sub_queries": [r["query"] for r in successful],
        }

    async def _synthesize_with_llm(
        self, query: str, results: List[Dict[str, Any]]
    ) -> str:
        """LLM을 사용하여 결과를 종합합니다."""
        results_text = self._format_results(results)

        messages = [
            SystemMessage(
                content="You are an expert at synthesizing information from multiple sources."
            ),
            HumanMessage(
                content=self.SYNTHESIS_PROMPT.format(
                    original_query=query, results=results_text
                )
            ),
        ]

        response = await self.llm.ainvoke(messages)
        return response.content.strip()

    def _basic_synthesis(self, results: List[Dict[str, Any]]) -> str:
        """LLM 없이 기본적인 결과 통합"""
        if not results:
            return "검색 결과가 없습니다."

        # 모든 성공한 결과 수집
        successful_results = [r for r in results if r["success"] and r.get("result")]

        if not successful_results:
            return "검색에 실패했습니다."

        # 각 결과의 핵심 정보 추출
        synthesis_parts = []

        for i, r in enumerate(successful_results, 1):
            answer = r["result"].get("answer", "")
            query = r.get("query", f"검색 {i}")

            if answer:
                # 더 긴 텍스트 허용 (2000자로 증가)
                truncated = answer[:2000] + ("..." if len(answer) > 2000 else "")
                synthesis_parts.append(f"**{query}**:\n{truncated}")

        if synthesis_parts:
            return f"다음은 {len(successful_results)}개의 검색 결과를 종합한 정보입니다:\n\n" + "\n\n".join(
                synthesis_parts
            )
        else:
            return "결과를 통합할 수 없습니다."

    def _format_results(self, results: List[Dict[str, Any]]) -> str:
        """검색 결과를 텍스트로 포맷팅합니다."""
        formatted = []
        for i, r in enumerate(results, 1):
            answer = r["result"].get("answer", "") if r["result"] else ""
            # 길이 제한을 3000자로 늘리고, 중요한 정보 보존
            if len(answer) > 3000:
                # 문장 단위로 자르기 (더 많은 문장 허용)
                sentences = answer.split(". ")
                truncated = ". ".join(sentences[:15]) + (
                    "..." if len(sentences) > 15 else ""
                )
                formatted.append(f"[{i}] {r['query']}\n{truncated}")
            else:
                formatted.append(f"[{i}] {r['query']}\n{answer}")
        return "\n\n".join(formatted)

    def _collect_sources(self, results: List[Dict[str, Any]]) -> List[str]:
        """모든 검색 결과에서 소스를 수집합니다."""
        all_sources = []
        for r in results:
            if r["result"] and r["result"].get("sources"):
                all_sources.extend(r["result"]["sources"])
        return list(dict.fromkeys(all_sources))[:10]


class DeepSearchTool(BaseTool):
    """
    Deep Search Tool

    단편적인 쿼리를 다각도로 검색하여 종합적인 정보를 제공합니다.

    Pipeline:
    1. Query Rewrite: 쿼리 구체화
    2. Query Decomposition: 서브쿼리로 분해 (LLM이 개수 자율 결정)
    3. Parallel Search: 병렬 검색 실행
    4. Result Synthesis: 결과 합성

    Components:
    - QueryRewriter: 쿼리를 구체화
    - QueryDecomposer: 사람처럼 간결한 쿼리로 분해
    - ParallelSearchExecutor: 병렬 검색 실행
    - SearchResultSynthesizer: 결과를 하나의 답변으로 합성
    """

    def __init__(self):
        super().__init__(
            name="deep_search",
            description="Deep web search that analyzes queries from multiple angles. Rewrites and decomposes queries to gather comprehensive information from various perspectives.",
        )

        load_dotenv(".env")
        api_key = config.google_api_key or os.getenv("GOOGLE_API_KEY")

        llm_config = {
            "model": config.agent_model,
            "api_key": api_key,
        }

        self.rewriter = QueryRewriter(llm_config)
        self.decomposer = QueryDecomposer(llm_config)
        self.executor = ParallelSearchExecutor(PerplexitySearchTool())
        self.synthesizer = SearchResultSynthesizer(llm_config)

        logger.info("DeepSearchTool initialized")

    async def execute(self, query: str, **kwargs) -> ToolResult:
        """Deep Search 파이프라인을 실행합니다."""
        try:
            logger.info(f"Deep Search started: '{query}'")

            rewritten_query = await self.rewriter.rewrite(query)
            sub_queries = await self.decomposer.decompose(rewritten_query)
            search_results = await self.executor.execute_parallel(sub_queries)
            final_result = await self.synthesizer.synthesize(query, search_results)

            logger.info(
                f"Deep Search completed: {final_result['success_count']}/{final_result['search_count']} successful"
            )

            return ToolResult(
                success=True,
                result=final_result,
                metadata={
                    "pipeline": "rewrite -> decompose -> parallel_search -> synthesize",
                    "rewritten_query": rewritten_query,
                    "sub_queries": sub_queries,
                },
            )

        except Exception as e:
            logger.error(f"Deep Search failed: {e}")
            return ToolResult(
                success=False,
                result=None,
                error=f"Deep search failed: {str(e)}",
            )

    def get_schema(self) -> Dict[str, Any]:
        """Function calling을 위한 툴 스키마"""
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
                            "description": "Search query to analyze and search from multiple angles for comprehensive results",
                        },
                    },
                    "required": ["query"],
                },
            },
        }
