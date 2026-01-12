"""Base tool implementation for AI Agent"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..utils.logger import logger


class ToolResult(BaseModel):
    """Result from tool execution"""

    success: bool = Field(..., description="Whether the tool execution was successful")
    result: Any = Field(..., description="Tool execution result")
    error: Optional[str] = Field(None, description="Error message if execution failed")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


@dataclass
class ObservationData:
    data: Any
    observation: Optional[str] = None
    error: Optional[str] = None
    store_output: bool = True
    store_result: bool = True
    skip_llm: bool = False
    log_query: Optional[str] = None
    log_response: Optional[str] = None


class BaseTool(ABC):
    """Base class for all tools"""

    def __init__(self, name: str, description: str):
        """
        Initialize tool

        Args:
            name: Tool name
            description: Tool description
        """
        self.name = name
        self.description = description
        self.logger = logger.getChild(f"tool.{name}")

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """
        Execute the tool

        Args:
            **kwargs: Tool-specific parameters

        Returns:
            ToolResult object
        """
        pass

    @abstractmethod
    def get_schema(self) -> Dict[str, Any]:
        """
        Get tool schema for function calling

        Returns:
            Tool schema dictionary
        """
        pass

    def validate_parameters(self, **kwargs) -> bool:
        """
        Validate tool parameters

        Args:
            **kwargs: Parameters to validate

        Returns:
            True if valid, False otherwise
        """
        return True

    def get_info(self) -> Dict[str, Any]:
        """Get tool information"""
        return {
            "name": self.name,
            "description": self.description,
            "schema": self.get_schema(),
        }


class ToolRegistry:
    """Registry for managing tools"""

    def __init__(self):
        self.tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        """Register a tool"""
        self.tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")

    def unregister(self, tool_name: str):
        """Unregister a tool"""
        if tool_name in self.tools:
            del self.tools[tool_name]
            logger.info(f"Unregistered tool: {tool_name}")

    def get_tool(self, tool_name: str) -> Optional[BaseTool]:
        """Get a tool by name"""
        return self.tools.get(tool_name)

    def list_tools(self) -> List[Dict[str, Any]]:
        """List all registered tools"""
        return [tool.get_info() for tool in self.tools.values()]

    async def execute_tool(self, tool_name: str, **kwargs) -> ToolResult:
        """Execute a tool"""
        tool = self.get_tool(tool_name)
        if not tool:
            return ToolResult(
                success=False, result=None, error=f"Tool '{tool_name}' not found"
            )

        try:
            if not tool.validate_parameters(**kwargs):
                return ToolResult(
                    success=False,
                    result=None,
                    error=f"Invalid parameters for tool '{tool_name}'",
                )

            result = await tool.execute(**kwargs)
            logger.debug(f"Executed tool '{tool_name}': success={result.success}")
            return result

        except Exception as e:
            logger.error(f"Error executing tool '{tool_name}': {e}")
            return ToolResult(success=False, result=None, error=str(e))
