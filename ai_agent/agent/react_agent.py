"""ReAct-enabled AI Agent"""

import asyncio
from typing import Dict, Any, Optional, List, AsyncGenerator

from .core import GeminiAgent
from ..react.engine import ReActEngine
from ..tools.base import ToolRegistry
from ..tools.react_tool import PerplexitySearchTool, CodeExecutorTool, FileSystemTool
from ..tools.yfinance_tool import YFinanceBalanceSheetTool
from ..utils.logger import logger


class ReActGeminiAgent(GeminiAgent):
    """Gemini Agent enhanced with ReAct capabilities"""

    def __init__(
        self,
        model_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        enable_react: bool = True,
    ):
        """
        Initialize ReAct-enabled Gemini Agent

        Args:
            model_name: Name of the Gemini model to use
            system_prompt: System prompt for the agent
            enable_react: Whether to enable ReAct capabilities
        """
        from ..utils.config import config

        super().__init__(model_name, system_prompt)

        self.enable_react = enable_react

        # Initialize ReAct components
        if self.enable_react:
            self._initialize_react_components()

        logger.info(
            f"Initialized ReAct Gemini Agent (ReAct: {'enabled' if enable_react else 'disabled'})"
        )

    def _initialize_react_components(self):
        """Initialize ReAct-specific components"""
        # Initialize tool registry
        self.tool_registry = ToolRegistry()

        # Register default tools
        self.tool_registry.register(PerplexitySearchTool())
        self.tool_registry.register(CodeExecutorTool())
        self.tool_registry.register(FileSystemTool())
        self.tool_registry.register(YFinanceBalanceSheetTool())

        # Initialize ReAct engine
        self.react_engine = ReActEngine(
            model=self.model, tool_registry=self.tool_registry
        )

        logger.info(
            f"ReAct components initialized with {len(self.tool_registry.tools)} tools"
        )

    def _get_default_system_prompt(self) -> str:
        """Get enhanced system prompt for ReAct capabilities"""
        base_prompt = super()._get_default_system_prompt()

        if not hasattr(self, "enable_react") or not self.enable_react:
            return base_prompt

        react_prompt = """

You are enhanced with ReAct (Reasoning + Acting) capabilities, which means you can:

1. **Think step by step** - Break down complex problems into manageable parts
2. **Use tools actively** - Execute calculations, search information, run code, and access files
3. **Learn from experience** - Build on past solving patterns and successful approaches
4. **Adapt your approach** - Modify your strategy based on intermediate results

When faced with complex problems, you will:
- **Analyze** the situation thoroughly (Thought)
- **Take specific actions** using available tools (Action)  
- **Observe and evaluate** the results (Observation)
- **Continue iterating** until you reach a complete solution

This makes you capable of solving problems that require multiple steps, external information, or computational work."""

        return base_prompt + react_prompt

    async def solve_with_react(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        force_react: bool = False,
    ) -> Dict[str, Any]:
        """
        Solve a problem using ReAct approach

        Args:
            query: Problem to solve
            context: Additional context information
            force_react: Force ReAct even for simple queries

        Returns:
            Dictionary with solution results and metadata
        """
        if not self.enable_react:
            # Fall back to regular chat
            response = await self.chat(query)
            return {
                "mode": "chat",
                "response": response,
                "react_state": None,
                "reasoning_steps": 0,
            }

        # Check if ReAct is needed
        if not force_react and not self._should_use_react(query):
            # Use regular chat for simple queries
            response = await self.chat(query)
            return {
                "mode": "chat",
                "response": response,
                "react_state": None,
                "reasoning_steps": 0,
            }

        # Use ReAct for complex problems
        logger.info(f"Using ReAct to solve: {query[:100]}...")

        # Solve using ReAct
        react_state = await self.react_engine.solve(query, context or {})

        # Prepare response
        if react_state.is_completed and not react_state.error:
            response = react_state.final_answer
        else:
            response = f"I encountered difficulties solving this problem. {react_state.error or 'The process was incomplete.'}"

        return {
            "mode": "react",
            "response": response,
            "react_state": react_state,
            "reasoning_steps": len(react_state.steps),
            "tools_used": list(
                set(s.tool_name for s in react_state.steps if s.tool_name)
            ),
            "success": react_state.is_completed and not react_state.error,
        }

    async def solve_with_react_stream(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        force_react: bool = True,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream ReAct solution events.

        Yields dict events where 'type' can be 'start' | 'thought' | 'action' | 'observation' | 'final_answer' | 'error' | 'end'.
        """
        if not self.enable_react:
            # Fall back to plain streaming chat
            async for chunk in self.chat_stream(query):
                yield {"type": "token", "content": chunk}
            yield {"type": "end"}
            return

        # If auto-detection says it's simple and not forced, stream plain chat
        if not force_react and not self._should_use_react(query):
            async for chunk in self.chat_stream(query):
                yield {"type": "token", "content": chunk}
            yield {"type": "end"}
            return

        async for event in self.react_engine.solve_stream(query, context or {}):
            yield event

    async def chat_enhanced(
        self,
        message: str,
        use_react: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Enhanced chat that automatically decides between regular chat and ReAct

        Args:
            message: User message
            use_react: Force ReAct usage (None = auto-decide)
            metadata: Additional metadata

        Returns:
            Agent response
        """
        # Auto-decide or use specified mode
        should_use_react = (
            use_react if use_react is not None else self._should_use_react(message)
        )

        if should_use_react and self.enable_react:
            result = await self.solve_with_react(message, metadata)
            return result["response"]
        else:
            # Use regular chat
            return await self.chat(message, metadata)

    def _should_use_react(self, query: str) -> bool:
        """Determine if ReAct should be used for this query"""
        # Keywords that suggest complex problem-solving
        react_keywords = [
            # Calculation and analysis
            "calculate",
            "compute",
            "solve",
            "analyze",
            "compare",
            "evaluate",
            # Research and information gathering
            "research",
            "find out",
            "investigate",
            "look up",
            "search for",
            # Code and technical tasks
            "code",
            "program",
            "script",
            "function",
            "algorithm",
            "debug",
            # Multi-step processes
            "step by step",
            "plan",
            "strategy",
            "approach",
            "process",
            # File operations
            "file",
            "save",
            "read",
            "write",
            "create document",
            # Complex reasoning
            "explain why",
            "how does",
            "what if",
            "pros and cons",
        ]

        query_lower = query.lower()

        # Check for multiple conditions that suggest complexity
        complexity_indicators = 0

        # Keyword matching
        if any(keyword in query_lower for keyword in react_keywords):
            complexity_indicators += 1

        # Question complexity (multiple questions)
        if query_lower.count("?") > 1:
            complexity_indicators += 1

        # Length and complexity
        if len(query.split()) > 15:
            complexity_indicators += 1

        # Numbers suggesting calculations
        import re

        if re.search(r"\d+", query):
            complexity_indicators += 1

        # Multiple tasks (indicated by "and", "then", "also")
        multi_task_words = ["and then", "also", "additionally", "furthermore", "next"]
        if any(word in query_lower for word in multi_task_words):
            complexity_indicators += 1

        # Use ReAct if we have threshold or more complexity indicators
        from ai_agent.utils.config import config

        return complexity_indicators >= config.react_complexity_threshold

    def register_tool(self, tool):
        """Register a new tool for ReAct"""
        if self.enable_react and hasattr(self, "tool_registry"):
            self.tool_registry.register(tool)
            logger.info(f"Registered tool: {tool.name}")
        else:
            logger.warning("ReAct not enabled or tool registry not available")

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """Get list of available tools"""
        if self.enable_react and hasattr(self, "tool_registry"):
            return self.tool_registry.list_tools()
        return []

    def get_enhanced_status(self) -> Dict[str, Any]:
        """Get enhanced agent status including ReAct info"""
        base_status = self.get_status()

        if self.enable_react:
            base_status.update(
                {
                    "react_enabled": True,
                    "available_tools": (
                        len(self.tool_registry.tools)
                        if hasattr(self, "tool_registry")
                        else 0
                    ),
                }
            )
        else:
            base_status["react_enabled"] = False

        return base_status

    async def demonstrate_react(self, problem: str = None) -> Dict[str, Any]:
        """Demonstrate ReAct capabilities with a sample problem"""
        if not self.enable_react:
            return {"error": "ReAct not enabled"}

        demo_problem = (
            problem
            or "Calculate the compound interest on $1000 at 5% annual rate for 3 years and explain what this means for an investor"
        )

        print(f"🧠 Demonstrating ReAct with problem: {demo_problem}")

        result = await self.solve_with_react(demo_problem, force_react=True)

        return {
            "demo_problem": demo_problem,
            "result": result,
            "demonstration": "ReAct process completed - check the reasoning steps above",
        }
