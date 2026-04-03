from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from ..core.types import ToolResult
from ..utils.logger import logger


class BaseTool(ABC):
    """Base class for all tools"""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.logger = logger.getChild(f"tool.{name}")

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        pass

    def get_info(self) -> Dict[str, Any]:
        from .specs import TOOL_SPECS

        if self.name in TOOL_SPECS:
            schema = TOOL_SPECS[self.name].to_llm_schema(self.description)
        else:
            schema = {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            }
        return {
            "name": self.name,
            "description": self.description,
            "schema": schema,
        }

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        _ = usage_writer

    def close(self) -> None:
        pass


class ReActBaseTool(BaseTool, ABC):
    def __init__(self, name: str, description: str):
        super().__init__(name, description)

    async def execute(self, **kwargs) -> ToolResult:
        loop = asyncio.get_event_loop()
        start_time = loop.time()

        try:
            result = await self._execute_impl(**kwargs)
            result.metadata.update({"execution_time": loop.time() - start_time})
            return result
        except Exception as e:
            self.logger.error(f"Error in {self.name}: {e}")
            return ToolResult(
                success=False,
                result=None,
                error=str(e),
                metadata={"execution_time": loop.time() - start_time},
            )

    async def _execute_impl(self, **kwargs) -> ToolResult:
        raise NotImplementedError


class ToolRegistry:
    """Registry for managing tools"""

    def __init__(self):
        self.tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        """Register a tool"""
        self.tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")

    def get_tool(self, tool_name: str) -> Optional[BaseTool]:
        """Get a tool by name"""
        return self.tools.get(tool_name)

    def list_tools(self) -> List[Dict[str, Any]]:
        """List all registered tools"""
        return [tool.get_info() for tool in self.tools.values()]

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        for tool in self.tools.values():
            tool.bind_usage_writer(usage_writer)

    def close(self) -> None:
        for tool in self.tools.values():
            tool.close()

    async def execute_tool(self, tool_name: str, **kwargs) -> ToolResult:
        """Execute a tool"""
        tool = self.get_tool(tool_name)
        if not tool:
            return ToolResult(
                success=False, result=None, error=f"Tool '{tool_name}' not found"
            )

        try:
            result = await tool.execute(**kwargs)
            logger.debug(f"Executed tool '{tool_name}': success={result.success}")
            return result

        except Exception as e:
            logger.error(f"Error executing tool '{tool_name}': {e}")
            return ToolResult(success=False, result=None, error=str(e))
