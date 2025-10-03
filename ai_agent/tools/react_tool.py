"""ReAct-specific tool implementations"""

import asyncio
import json
import httpx
from typing import Dict, Any, Optional, List
from abc import ABC

from langchain_perplexity import ChatPerplexity
from langchain_core.messages import HumanMessage, SystemMessage

from .base import BaseTool, ToolResult
from ..utils.config import config
from ..utils.logger import logger


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
            description="Search the web for current information using Perplexity AI. Provides real-time web results with citations.",
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
                temperature=0.2,  # 정확성을 위해 낮은 temperature
                pplx_api_key=api_key,
            )
            self.available = True
            logger.info("PerplexitySearchTool initialized successfully")
        except Exception as e:
            logger.warning(f"PerplexitySearchTool initialization failed: {e}")
            self.chat = None
            self.available = False

    async def _execute_impl(self, query: str) -> ToolResult:
        """Execute web search using ChatPerplexity"""

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
                    }
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
        from ai_agent.utils.config import config

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
            import io
            import sys
            import contextlib

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
