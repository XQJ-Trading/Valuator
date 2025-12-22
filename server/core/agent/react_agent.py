"""AI Agent with integrated ReAct capabilities"""

from typing import Any, AsyncGenerator, Dict, List, Optional

from ..models.gemini import GeminiModel
from ..react.engine import ReActEngine
from ..tools.base import ToolRegistry
from ..tools.react_tool import CodeExecutorTool, FileSystemTool, PerplexitySearchTool
from ..tools.sec_tool import SECTool
from ..tools.yfinance_tool import YFinanceBalanceSheetTool
from ..utils.config import config
from ..utils.logger import logger


class AIAgent:
    """Main AI Agent class with integrated ReAct capabilities"""

    def __init__(
        self,
        model_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        thinking_level: Optional[str] = None,
    ):
        """
        Initialize AI Agent with ReAct capabilities

        Args:
            model_name: Name of the Gemini model to use
            system_prompt: System prompt for the agent
            thinking_level: Thinking level for Gemini 3.0 ('high', 'low', or None)
        """
        self.model_name = model_name or config.agent_model
        self.system_prompt = system_prompt or self._get_default_system_prompt()
        self.model = GeminiModel(self.model_name, thinking_level=thinking_level)

        # Initialize ReAct components
        self._initialize_react_components()

        logger.info(
            f"Initialized AI Agent with ReAct capabilities: {config.agent_name} v{config.agent_version}"
        )
        logger.debug(f"Using model: {self.model_name}")

    def _initialize_react_components(self):
        """Initialize ReAct-specific components"""
        # Initialize tool registry
        self.tool_registry = ToolRegistry()

        # Register default tools
        self.tool_registry.register(PerplexitySearchTool())
        self.tool_registry.register(CodeExecutorTool())
        self.tool_registry.register(FileSystemTool())
        self.tool_registry.register(YFinanceBalanceSheetTool())
        self.tool_registry.register(SECTool())

        # Initialize ReAct engine
        self.react_engine = ReActEngine(
            model=self.model, tool_registry=self.tool_registry
        )

        logger.info(
            f"ReAct components initialized with {len(self.tool_registry.tools)} tools"
        )

    def _get_default_system_prompt(self) -> str:
        """Get default system prompt with ReAct capabilities"""
        return """You are a helpful AI assistant powered by Google's Gemini model with ReAct (Reasoning + Acting) capabilities.
You are designed to be helpful, harmless, and honest. You can engage in conversations,
answer questions, help with tasks, and provide information on a wide variety of topics.

You are enhanced with ReAct capabilities, which means you can:

1. **Think step by step** - Break down complex problems into manageable parts
2. **Use tools actively** - Execute calculations, search information, run code, and access files
3. **Learn from experience** - Build on past solving patterns and successful approaches
4. **Adapt your approach** - Modify your strategy based on intermediate results

When faced with problems, you will:
- **Analyze** the situation thoroughly (Thought)
- **Take specific actions** using available tools (Action)
- **Observe and evaluate** the results (Observation)
- **Continue iterating** until you reach a complete solution

Key guidelines:
- Be concise but comprehensive in your responses
- If you're unsure about something, say so rather than guessing
- Be respectful and professional in all interactions
- Use clear and easy-to-understand language
- When appropriate, provide examples or explanations to help users understand concepts better"""

    async def solve_stream(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream ReAct solution events.

        Yields dict events where 'type' can be 'start' | 'thought' | 'action' | 'observation' | 'final_answer' | 'error' | 'end'.
        """
        async for event in self.react_engine.solve_stream(query, context or {}):
            yield event

    async def chat(
        self,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Chat interface that uses ReAct for problem solving

        Args:
            message: User message
            metadata: Additional metadata

        Returns:
            Agent response
        """
        try:
            # Use ReAct engine for all interactions
            result = await self.solve(message, metadata)
            return result["response"]
        except Exception as e:
            logger.error(f"Error in chat: {e}")
            error_msg = "I apologize, but I encountered an error while processing your request. Please try again."
            return error_msg

    async def chat_stream(
        self,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Chat interface with streaming using ReAct

        Args:
            message: User message
            metadata: Additional metadata

        Yields:
            Response chunks as they are generated
        """
        try:
            # Stream through ReAct engine
            async for event in self.solve_stream(message, metadata):
                if event["type"] == "final_answer":
                    yield event["content"]
                # For compatibility, we can also yield intermediate steps as text
                elif event["type"] in ["thought", "action", "observation"]:
                    yield f"[{event['type'].upper()}] {event['content']}\n\n"
        except Exception as e:
            logger.error(f"Error in chat_stream: {e}")
            error_msg = "I apologize, but I encountered an error while processing your request. Please try again."
            yield error_msg

    def register_tool(self, tool):
        """Register a new tool"""
        if hasattr(self, "tool_registry"):
            self.tool_registry.register(tool)
            logger.info(f"Registered tool: {tool.name}")
        else:
            logger.warning("Tool registry not available")

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """Get list of available tools"""
        if hasattr(self, "tool_registry"):
            return self.tool_registry.list_tools()
        return []

    def set_system_prompt(self, prompt: str):
        """Update the system prompt"""
        self.system_prompt = prompt
        logger.info("Updated system prompt")

    def is_ready(self) -> bool:
        """Check if agent is ready to process requests"""
        model_ready = self.model is not None
        prompt_ready = self.system_prompt is not None
        engine_ready = hasattr(self, "react_engine") and self.react_engine is not None
        return model_ready and prompt_ready and engine_ready


# Alias for backward compatibility
ReActGeminiAgent = AIAgent
