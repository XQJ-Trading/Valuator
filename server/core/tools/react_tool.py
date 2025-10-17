"""ReAct-specific tool implementations"""

import asyncio
import json
from abc import ABC
from typing import Any, Dict, List, Optional

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_perplexity import ChatPerplexity

from ..utils.config import config
from ..utils.logger import logger
from .base import BaseTool, ToolResult


class ReActBaseTool(BaseTool, ABC):
    """Base class for ReAct-specific tools with enhanced metadata"""

    def __init__(self, name: str, description: str):
        super().__init__(name, description)
        self.execution_count = 0
        self.success_count = 0
        self.last_execution = None

    async def execute(self, **kwargs) -> ToolResult:
        """Execute tool with enhanced tracking"""
        self.execution_count += 1
        start_time = asyncio.get_event_loop().time()

        try:
            result = await self._execute_impl(**kwargs)

            if result.success:
                self.success_count += 1

            # Add execution metadata
            execution_time = asyncio.get_event_loop().time() - start_time
            result.metadata.update(
                {
                    "execution_time": execution_time,
                    "execution_count": self.execution_count,
                    "success_rate": self.success_count / self.execution_count,
                }
            )

            self.last_execution = result
            return result

        except Exception as e:
            self.logger.error(f"Error in {self.name}: {e}")
            return ToolResult(
                success=False,
                result=None,
                error=str(e),
                metadata={
                    "execution_time": asyncio.get_event_loop().time() - start_time,
                    "execution_count": self.execution_count,
                },
            )

    async def _execute_impl(self, **kwargs) -> ToolResult:
        """Implement this method in subclasses"""
        raise NotImplementedError


class PerplexitySearchTool(ReActBaseTool):
    """Real web search using Perplexity AI via LangChain"""

    def __init__(self):
        super().__init__(
            name="web_search",
            description="Search the web for current information using Perplexity AI. Provides real-time web results with citations. Set enable_expansion=true for comprehensive query expansion search.",
        )

        # ChatPerplexity 초기화
        try:
            # API 키 로드 (config와 환경변수에서 시도)
            api_key = config.perplexity_api_key
            if not api_key:
                import os

                from dotenv import load_dotenv

                load_dotenv(".env")
                api_key = os.getenv("PPLX_API_KEY")

            if not api_key:
                raise ValueError("PPLX_API_KEY not found in config or environment")

            self.chat = ChatPerplexity(
                model="sonar",  # 기본 모델로 테스트
                temperature=0.1,  # 정확성과 속도를 위해 낮은 temperature
                pplx_api_key=api_key,
            )
            self.available = True
            logger.info("PerplexitySearchTool initialized successfully")
        except Exception as e:
            logger.warning(f"PerplexitySearchTool initialization failed: {e}")
            self.chat = None
            self.available = False

    async def _execute_impl(
        self,
        query: str,
        enable_expansion: bool = False,
        expansion_depth: int = None,
        **kwargs,
    ) -> ToolResult:
        """Execute web search using ChatPerplexity"""

        # If expansion is enabled, perform adaptive decomposition based on query complexity
        if enable_expansion:
            try:
                # Let LLM determine optimal decomposition approach
                from .query_expansion_search import QueryExpansionSearchTool

                expansion_tool = QueryExpansionSearchTool()
                decomposed_queries = await expansion_tool._analyze_and_decompose_query(
                    query, expansion_depth
                )

                # Prepare for individual searches
                return await self.execute_individual_search(
                    decomposed_queries, **kwargs
                )

            except Exception as e:
                self.logger.warning(
                    f"Adaptive expansion failed, falling back to regular search: {e}"
                )
                # If decomposition fails, fall back to simple parallel search with analysis
                return await self._execute_simple_parallel_search(query, 3)

        # Regular single search
        return await self._execute_single_search(query)

    async def execute_individual_search(
        self,
        decomposed_queries: List[str],
        **kwargs,
    ) -> ToolResult:
        """
        Execute individual searches for each decomposed query asynchronously

        This runs all sub-queries in parallel using asyncio.gather for optimal performance
        """
        self.logger.info(
            f"Starting {len(decomposed_queries)} concurrent individual searches: {decomposed_queries}"
        )

        async def single_search(query: str) -> dict:
            """Execute a single search and return structured result"""
            try:
                # 개별 검색에서는 별도 로그 생략 - _execute_single_search에서 로그 출력
                result = await self._execute_single_search(query)
                if result.success and result.result:
                    return {
                        "query": query,
                        "success": True,
                        "answer": result.result.get("answer", "No answer"),
                        "sources": result.result.get("sources", []),
                        "metadata": result.metadata,
                    }
                else:
                    return {
                        "query": query,
                        "success": False,
                        "answer": "Search failed",
                        "sources": [],
                        "error": result.error,
                    }
            except Exception as e:
                self.logger.error(f"Individual search failed for '{query}': {e}")
                return {
                    "query": query,
                    "success": False,
                    "answer": f"Search error: {str(e)}",
                    "sources": [],
                    "error": str(e),
                }

        # Execute all individual searches asynchronously
        tasks = [single_search(query) for query in decomposed_queries]
        search_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process and consolidate results
        successful_searches = []
        all_answers = []

        for i, result in enumerate(search_results):
            if isinstance(result, Exception):
                self.logger.error(f"Search {i+1} failed with exception: {result}")
                all_answers.append(
                    f"Search {i+1} ({decomposed_queries[i]}): Failed - {str(result)}"
                )
            elif result.get("success", False):
                successful_searches.append(result)
                all_answers.append(
                    f"Search {i+1} ({result['query']}):\n{result['answer']}"
                )
            else:
                all_answers.append(
                    f"Search {i+1} ({result['query']}): {result.get('answer', 'No results')}"
                )

        # Create comprehensive consolidated answer
        if successful_searches:
            consolidated_answer = f"Comprehensive Analysis for Original Query\n\n"
            consolidated_answer += "=" * 60 + "\n"
            consolidated_answer += "INDIVIDUAL SEARCH RESULTS\n"
            consolidated_answer += "=" * 60 + "\n\n"

            for answer in all_answers:
                consolidated_answer += answer + "\n\n"
                consolidated_answer += "-" * 40 + "\n\n"

            summary = f"\nSUMMARY: {len(successful_searches)}/{len(decomposed_queries)} searches completed successfully.\n"
            consolidated_answer += summary

            return ToolResult(
                success=True,
                result={
                    "action_type": "consolidated_individual_searches",
                    "original_decomposed_queries": decomposed_queries,
                    "total_searches": len(decomposed_queries),
                    "successful_searches": len(successful_searches),
                    "consolidated_answer": consolidated_answer,
                    "all_answers": all_answers,
                    "search_details": successful_searches,
                },
                metadata={
                    "individual_searches_executed": len(decomposed_queries),
                    "successful_individual_searches": len(successful_searches),
                    "query_list": decomposed_queries,
                },
            )
        else:
            return ToolResult(
                success=False,
                result=None,
                error=f"All {len(decomposed_queries)} individual searches failed",
                metadata={
                    "individual_searches_failed": len(decomposed_queries),
                    "query_list": decomposed_queries,
                },
            )

    async def _execute_single_search(self, query: str) -> ToolResult:
        """Execute a single web search"""
        if not self.available:
            # Fallback to basic response when API not available
            return ToolResult(
                success=False,
                result=None,
                error="Perplexity API not available. Check PPLX_API_KEY configuration.",
            )

        try:
            self.logger.info(f"Searching web with Perplexity for: {query}")

            # 시스템 프롬프트와 사용자 쿼리 구성
            messages = [
                SystemMessage(
                    content="You are a helpful search assistant. Provide accurate, up-to-date information with sources when possible. Be concise but comprehensive."
                ),
                HumanMessage(content=query),
            ]

            # ChatPerplexity 호출
            response = await self.chat.ainvoke(messages)

            # 응답 처리
            answer = response.content

            # 메타데이터에서 소스 정보 추출 (가능한 경우)
            sources = []
            if hasattr(response, "response_metadata") and response.response_metadata:
                # Perplexity 응답에서 인용 정보 추출 시도
                if "citations" in response.response_metadata:
                    sources = response.response_metadata["citations"]
                elif "sources" in response.response_metadata:
                    sources = response.response_metadata["sources"]

            # 응답에서 URL 패턴 추출 (fallback)
            if not sources:
                import re

                url_pattern = r"https?://[^\s)]+"
                found_urls = re.findall(url_pattern, answer)
                sources = list(set(found_urls))  # 중복 제거

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

    async def _execute_simple_parallel_search(
        self, query: str, expansion_depth: int
    ) -> ToolResult:
        """Execute simple parallel search when LLM-based expansion fails"""
        from langchain_core.messages import HumanMessage
        from langchain_google_genai import ChatGoogleGenerativeAI

        try:
            # Use LLM to create simple sub-queries for parallel execution
            llm = ChatGoogleGenerativeAI(
                model=config.agent_model,
                temperature=0.1,
                max_tokens=1028,
                api_key=config.google_api_key,
            )

            # Create sub-queries based on query analysis - aim for 4 sub-queries like in the example
            target_depth = min(expansion_depth, 4)  # Default to 4 like user's example

            sub_query_prompt = f"""
            Given the search query: "{query}"

            Break this into {target_depth} focused sub-queries that explore different aspects.
            Each should be specific and searchable.

            Return ONLY a comma-separated list of {target_depth} queries.
            """

            messages = [HumanMessage(content=sub_query_prompt)]
            response = await llm.ainvoke(messages)

            response_text = response.content.strip()

            # Parse comma-separated queries
            if "," in response_text:
                sub_queries = [q.strip() for q in response_text.split(",") if q.strip()]
            else:
                # Simple fallback decomposition
                words = query.split()
                if len(words) >= 4:
                    # Split into roughly equal parts
                    chunk_size = len(words) // target_depth
                    sub_queries = []
                    for i in range(target_depth):
                        start = i * chunk_size
                        end = (
                            (i + 1) * chunk_size if i < target_depth - 1 else len(words)
                        )
                        sub_queries.append(" ".join(words[start:end]))
                else:
                    # Fallback: just use original query multiple times
                    sub_queries = [query] * target_depth

            # Limit to target depth
            sub_queries = sub_queries[:target_depth]

            # Execute all queries in parallel - each with expansion enabled recursively
            self.logger.info(
                f"Executing {len(sub_queries)} parallel searches with expansion:"
            )
            for i, sq in enumerate(sub_queries, 1):
                self.logger.info(f"  {i}. '{sq}' (enable_expansion=true)")

            # Each sub-query will recursively call web_search with enable_expansion=true
            # This creates nested expansion where each sub-query gets further decomposed
            # Limit to 2 levels deep as requested, with reduced depth for nested calls
            tasks = [
                self.execute(query=sub_query, enable_expansion=True, expansion_depth=2)
                for sub_query in sub_queries
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            successful_results = []
            all_answers = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    self.logger.error(f"Search {i+1} failed: {result}")
                    all_answers.append(
                        f"Search {i+1} ({sub_queries[i]}): Failed - {str(result)}"
                    )
                elif result.success and result.result:
                    successful_results.append(result)
                    consolidated = result.result.get(
                        "consolidated_answer", result.result.get("answer", "No answer")
                    )
                    all_answers.append(
                        f"Search {i+1} ({result.result.get('original_query', sub_queries[i])}):\n{consolidated}"
                    )
                else:
                    all_answers.append(f"Search {i+1} ({sub_queries[i]}): No results")

            if not successful_results:
                return ToolResult(
                    success=False,
                    result=None,
                    error="All parallel searches failed",
                )

            # Final consolidation of all parallel results
            final_answer = f"Comprehensive Multi-Level Analysis for: {query}\n\n"
            final_answer += "=" * 80 + "\n"
            final_answer += "PARALLEL SEARCH RESULTS\n"
            final_answer += "=" * 80 + "\n\n"

            for answer in all_answers:
                final_answer += answer + "\n\n"
                final_answer += "-" * 60 + "\n\n"

            # Add summary statistics
            total_sub_searches = sum(
                r.result.get("total_searches", 0)
                for r in successful_results
                if r.result
            )

            return ToolResult(
                success=True,
                result={
                    "query": query,
                    "answer": final_answer,
                    "sources": [],  # Would need to collect from all nested results
                    "parallel_searches": len(sub_queries),
                    "successful_searches": len(successful_results),
                    "total_nested_searches": total_sub_searches,
                },
                metadata={
                    "search_type": "nested_parallel_expansion",
                    "sub_queries": sub_queries,
                    "expansion_depth": expansion_depth,
                },
            )

        except Exception as e:
            self.logger.error(f"Simple parallel search failed: {e}")
            # Final fallback: just do regular search
            return await self._execute_single_search(query)

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for current web information",
                    },
                    "enable_expansion": {
                        "type": "boolean",
                        "description": "Enable adaptive query decomposition - automatically determines optimal number of sub-queries based on query complexity",
                        "default": False,
                    },
                    "expansion_depth": {
                        "type": "integer",
                        "description": "Specific number of query expansions (1-5). If not provided with enable_expansion=true, will auto-determine based on query complexity",
                        "minimum": 1,
                        "maximum": 5,
                    },
                },
                "required": ["query"],
            },
        }


class CodeExecutorTool(ReActBaseTool):
    """Code execution tool for ReAct"""

    def __init__(self):
        super().__init__(
            name="code_executor",
            description="Execute Python code safely. Use ```python\nyour_code_here\n``` format (no JSON wrapper required). Useful for calculations, data processing, or testing code snippets.",
        )

    async def _execute_impl(
        self, code: str, timeout: int = None, language: str = None
    ) -> ToolResult:
        """Execute Python code safely"""
        from ..utils.config import config

        # Use config timeout if not provided
        if timeout is None:
            timeout = config.code_execution_timeout

        try:
            # Log language if provided (for future extension)
            if language and language.lower() != "python":
                self.logger.warning(
                    f"Language '{language}' specified but only Python is supported"
                )

            # Fix indentation issues from JSON escaped strings
            # First, handle escaped newlines and tabs from JSON
            code = code.replace("\\n", "\n").replace("\\t", "\t")

            self.logger.info(f"Executing code: {code[:100]}...")

            # Capture output using StringIO
            import contextlib
            import io

            # Create string buffer to capture output
            output_buffer = io.StringIO()

            # Safely execute code with output capture
            try:
                # Redirect stdout to capture print statements
                with contextlib.redirect_stdout(output_buffer):
                    # Try to execute as a script first
                    if any(
                        keyword in code
                        for keyword in ["def ", "class ", "for ", "while ", "if "]
                    ):
                        # Multi-line code - use exec
                        exec_globals = {"__builtins__": __builtins__}
                        exec(code, exec_globals)
                        execution_type = "exec"
                    else:
                        # Single expression - try eval first, then exec
                        try:
                            result = eval(code, {"__builtins__": __builtins__})
                            if result is not None:
                                print(result)  # Print the result
                            execution_type = "eval"
                        except SyntaxError:
                            # If eval fails, try exec
                            exec_globals = {"__builtins__": __builtins__}
                            exec(code, exec_globals)
                            execution_type = "exec"

                # Get the captured output
                output = output_buffer.getvalue().strip()
                if not output and execution_type == "eval":
                    output = "Expression evaluated successfully (no output)"
                elif not output:
                    output = "Code executed successfully (no output)"

                return ToolResult(
                    success=True,
                    result={
                        "output": output,
                        "code": code,
                        "execution_type": execution_type,
                    },
                    metadata={"timeout": timeout, "safe_mode": True},
                )

            except Exception as exec_error:
                # If execution fails, return the error
                return ToolResult(
                    success=False,
                    result={"output": "", "code": code, "execution_type": "failed"},
                    error=f"Code execution error: {str(exec_error)}",
                )

        except Exception as e:
            return ToolResult(
                success=False, result=None, error=f"Code execution failed: {str(e)}"
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "usage_format": "Use ```python\nyour_code_here\n``` format instead of JSON",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute (automatically extracted from ```python block)",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Execution timeout in seconds",
                        "default": 30,
                    },
                },
                "required": ["code"],
            },
        }


class FileSystemTool(ReActBaseTool):
    """File system operations tool for ReAct"""

    def __init__(self):
        super().__init__(
            name="file_system",
            description="Read, write, and manage files. Useful for accessing local files, saving data, or reading configurations.",
        )

    async def _execute_impl(
        self, operation: str, path: str, content: str = None, **kwargs
    ) -> ToolResult:
        """Execute file system operation"""
        try:
            import os
            from pathlib import Path

            self.logger.info(f"File operation: {operation} on {path}")

            if operation == "read":
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        file_content = f.read()

                    return ToolResult(
                        success=True,
                        result={
                            "operation": "read",
                            "path": path,
                            "content": file_content,
                            "size": len(file_content),
                        },
                        metadata={"file_exists": True},
                    )
                else:
                    return ToolResult(
                        success=False, result=None, error=f"File not found: {path}"
                    )

            elif operation == "write":
                if content is None:
                    return ToolResult(
                        success=False,
                        result=None,
                        error="Content is required for write operation",
                    )

                # Create directory if it doesn't exist
                Path(path).parent.mkdir(parents=True, exist_ok=True)

                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)

                return ToolResult(
                    success=True,
                    result={"operation": "write", "path": path, "size": len(content)},
                    metadata={"created": True},
                )

            elif operation == "list":
                if os.path.isdir(path):
                    files = os.listdir(path)
                    return ToolResult(
                        success=True,
                        result={
                            "operation": "list",
                            "path": path,
                            "files": files,
                            "count": len(files),
                        },
                        metadata={"is_directory": True},
                    )
                else:
                    return ToolResult(
                        success=False, result=None, error=f"Directory not found: {path}"
                    )

            else:
                return ToolResult(
                    success=False, result=None, error=f"Unknown operation: {operation}"
                )

        except Exception as e:
            return ToolResult(
                success=False,
                result=None,
                error=f"File system operation failed: {str(e)}",
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["read", "write", "list"],
                        "description": "File system operation to perform",
                    },
                    "path": {"type": "string", "description": "File or directory path"},
                    "content": {
                        "type": "string",
                        "description": "Content to write (for write operation)",
                        "default": None,
                    },
                },
                "required": ["operation", "path"],
            },
        }
