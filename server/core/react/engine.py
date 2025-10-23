"""ReAct engine implementation"""

import asyncio
import json
import re
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import yaml

from ..models.gemini import GeminiChatSession, GeminiModel
from ..tools.base import ToolRegistry, ToolResult
from ..utils.logger import logger
from ..utils.react_logger import react_logger
from .prompts import ReActPrompts
from .state import ReActState, ReActStepType


class ReActEngine:
    """ReAct (Reasoning + Acting) engine for autonomous problem solving"""

    def __init__(
        self,
        model: GeminiModel,
        tool_registry: ToolRegistry,
        max_retries: int = None,
        enable_logging: bool = True,
    ):
        """
        Initialize ReAct engine

        Args:
            model: Gemini model instance
            tool_registry: Registry of available tools
            max_retries: Maximum retries for failed actions (uses config if None)
            enable_logging: Whether to enable session logging
        """
        from ..utils.config import config

        self.model = model
        self.tool_registry = tool_registry
        self.max_thought_cycles = config.react_max_thought_cycles
        # Use config values if not explicitly provided
        self.max_steps = self.max_thought_cycles * 4  # Safety net
        self.max_retries = (
            max_retries if max_retries is not None else config.react_max_retries
        )
        self.prompts = ReActPrompts()
        self.enable_logging = enable_logging
        self.current_date = None
        self.api_session: Optional[GeminiChatSession] = None

        logger.info(f"Initialized ReAct engine with {len(tool_registry.tools)} tools")

    async def solve(
        self, query: str, context: Optional[Dict[str, Any]] = None
    ) -> ReActState:
        """
        Solve a problem using ReAct approach

        Args:
            query: Problem to solve
            context: Additional context information

        Returns:
            ReActState with complete solving process
        """
        logger.info(f"Starting ReAct solving: {query[:100]}...")
        self.current_date = datetime.now().strftime("%Y-%m-%d")

        # Start API session
        tools_info = self.tool_registry.list_tools()
        system_prompt = self.prompts.format_system_prompt(tools_info, self.current_date)
        initial_messages = self.model.format_messages(system_prompt, [], "")
        self.api_session = self.model.start_chat_session(initial_messages)

        # Start logging session
        session_id = None
        if self.enable_logging:
            session_id = react_logger.start_session(query)

        # Initialize state
        state = ReActState(
            original_query=query, max_steps=self.max_steps, context=context or {}
        )

        try:
            # Main ReAct loop
            while state.should_continue():
                logger.debug(f"ReAct step {state.current_step + 1}/{state.max_steps}")

                # Check for repetitive patterns before proceeding
                if self._detect_infinite_loop(state):
                    logger.warning(
                        "Detected potential infinite loop - forcing completion"
                    )
                    await self._force_completion(state)
                    break

                # Determine next step type
                next_step_type = self._determine_next_step(state)
                logger.debug(f"Next step type: {next_step_type}")

                if next_step_type == ReActStepType.THOUGHT:
                    await self._thought_step(state)
                elif next_step_type == ReActStepType.ACTION:
                    await self._action_step(state)
                elif next_step_type == ReActStepType.OBSERVATION:
                    await self._observation_step(state)
                elif next_step_type == ReActStepType.FINAL_ANSWER:
                    await self._final_answer_step(state)
                    break

                # Safety check
                if state.current_step >= state.max_steps:
                    logger.warning("Reached maximum steps, forcing completion")
                    await self._force_completion(state)
                    break

            logger.info(f"ReAct solving completed in {state.current_step} steps")

            # End logging session
            if self.enable_logging:
                react_logger.end_session(
                    final_answer=state.final_answer,
                    success=state.is_completed and not state.error,
                )

            return state

        except Exception as e:
            import traceback

            logger.error(f"Error in ReAct solving: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error repr: {repr(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            state.error = str(e)

            # End logging session with error
            if self.enable_logging:
                react_logger.end_session(final_answer=f"Error: {str(e)}", success=False)

            return state

    async def solve_stream(
        self, query: str, context: Optional[Dict[str, Any]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream ReAct solving process step-by-step.

        Yields dict events with keys: type, content, and optional tool/tool_input/tool_output/error/final.
        """
        logger.info(f"[stream] Starting ReAct solving: {query[:100]}...")
        self.current_date = datetime.now().strftime("%Y-%m-%d")

        # Start API session
        tools_info = self.tool_registry.list_tools()
        system_prompt = self.prompts.format_system_prompt(tools_info, self.current_date)
        initial_messages = self.model.format_messages(system_prompt, [], "")
        self.api_session = self.model.start_chat_session(initial_messages)

        # Start logging session
        session_id = None
        if self.enable_logging:
            session_id = react_logger.start_session(query)

        state = ReActState(
            original_query=query, max_steps=self.max_steps, context=context or {}
        )

        try:
            yield {"type": "start", "query": query}

            while state.should_continue():
                if self._detect_infinite_loop(state):
                    logger.warning(
                        "[stream] Detected potential infinite loop - forcing completion"
                    )
                    await self._force_completion(state)
                    break

                next_step_type = self._determine_next_step(state)

                if next_step_type == ReActStepType.THOUGHT:
                    await self._thought_step(state)
                    last = state.get_last_step()
                    yield {"type": "thought", "content": last.content}
                elif next_step_type == ReActStepType.ACTION:
                    await self._action_step(state)
                    last = state.get_last_step()
                    yield {
                        "type": "action",
                        "content": last.content,
                        "tool": last.tool_name,
                        "tool_input": last.tool_input,
                    }
                elif next_step_type == ReActStepType.OBSERVATION:
                    await self._observation_step(state)
                    last = state.get_last_step()

                    # ToolResult를 딕셔너리로 변환
                    tool_result_dict = None
                    if hasattr(last, "tool_result") and last.tool_result:
                        try:
                            if hasattr(last.tool_result, "dict"):
                                # Pydantic 모델인 경우
                                tool_result_dict = last.tool_result.dict()
                            elif hasattr(last.tool_result, "__dict__"):
                                # 일반 객체인 경우
                                tool_result_dict = {
                                    "success": getattr(
                                        last.tool_result, "success", None
                                    ),
                                    "result": getattr(last.tool_result, "result", None),
                                    "error": getattr(last.tool_result, "error", None),
                                    "metadata": getattr(
                                        last.tool_result, "metadata", None
                                    ),
                                }
                            else:
                                tool_result_dict = str(last.tool_result)
                            logger.info(
                                f"[DEBUG] tool_result converted: {type(last.tool_result)} -> {tool_result_dict}"
                            )
                        except Exception as e:
                            logger.error(f"[DEBUG] tool_result conversion failed: {e}")
                            tool_result_dict = {
                                "error": f"Serialization failed: {str(e)}"
                            }

                    yield {
                        "type": "observation",
                        "content": last.content,
                        "tool_output": last.tool_output,
                        "error": last.error,
                        "tool_result": tool_result_dict,
                    }
                elif next_step_type == ReActStepType.FINAL_ANSWER:
                    await self._final_answer_step(state)
                    break

                if state.current_step >= state.max_steps:
                    logger.warning("[stream] Reached maximum steps, forcing completion")
                    await self._force_completion(state)
                    break

            # Final answer event
            yield {
                "type": "final_answer",
                "content": state.final_answer,
                "success": state.is_completed and not state.error,
            }

            if self.enable_logging:
                react_logger.end_session(
                    final_answer=state.final_answer,
                    success=state.is_completed and not state.error,
                )

            yield {"type": "end"}

        except Exception as e:
            import traceback

            logger.error(f"[stream] Error in ReAct solving: {e}")
            logger.error(f"[stream] Traceback: {traceback.format_exc()}")
            state.error = str(e)
            if self.enable_logging:
                react_logger.end_session(final_answer=f"Error: {str(e)}", success=False)
            yield {"type": "error", "message": str(e)}

    def _determine_next_step(self, state: ReActState) -> ReActStepType:
        """Determine what type of step should come next"""
        if not state.steps:
            return ReActStepType.THOUGHT

        last_step = state.get_last_step()

        if last_step.step_type == ReActStepType.THOUGHT:
            return ReActStepType.ACTION
        elif last_step.step_type == ReActStepType.ACTION:
            return ReActStepType.OBSERVATION
        elif last_step.step_type == ReActStepType.OBSERVATION:
            # Check if we should continue or provide final answer
            if self._should_provide_final_answer(state):
                return ReActStepType.FINAL_ANSWER
            else:
                return ReActStepType.THOUGHT
        else:
            return ReActStepType.FINAL_ANSWER

    def _should_provide_final_answer(self, state: ReActState) -> bool:
        """Determine if we have enough information for final answer"""
        # More sophisticated logic for determining completion

        # Check if we've reached maximum reasonable cycles
        thought_steps = len(state.get_steps_by_type(ReActStepType.THOUGHT))
        action_steps = len(state.get_steps_by_type(ReActStepType.ACTION))
        observation_steps = len(state.get_steps_by_type(ReActStepType.OBSERVATION))

        # Prevent infinite loops - max cycles from config
        from ..utils.config import config

        if thought_steps >= config.react_max_thought_cycles:
            return True

        # Only consider completion if we have at least one complete cycle
        if thought_steps < 1 or action_steps < 1 or observation_steps < 1:
            return False

        # Check for repetitive "problem is solved" patterns
        if self._is_repetitive_completion_pattern(state):
            logger.info("Detected repetitive completion pattern - forcing final answer")
            return True

        # Look at recent steps (not just observations) for completion signals
        recent_steps = state.steps[-1:]  # Last 1 step only
        completion_content = []

        for step in recent_steps:
            completion_content.append(step.content.lower())

        all_content = " ".join(completion_content)

        # Check for continuation markers first
        if "<next_task_required/>" in all_content:
            logger.info(
                "Found <next_task_required/> marker - continuing with next step"
            )
            return False

        # Check for explicit completion markers (highest priority)
        explicit_completion_markers = ["<final_answer_ready/>"]

        for marker in explicit_completion_markers:
            if marker in all_content:
                logger.info(
                    f"Found explicit completion marker: {marker} - triggering final answer"
                )
                return True

        # Enhanced completion indicators (fallback)
        strong_completion_indicators = [
            "problem is solved",
            "task is complete",
            "calculation is finished",
            "answer is",
            "final result",
            "completed successfully",
            "all steps are done",
            "process is finished",
            "ready for a new query",
            "awaiting a new task",
            "no further steps",
            "definitively solved",
            "i have confirmed",
            "i have determined",
            "the conclusion",
            "based on the performed",
            "all necessary checks",
            "sufficient information",
        ]

        # Check for strong completion signals
        completion_count = sum(
            1 for indicator in strong_completion_indicators if indicator in all_content
        )

        if completion_count >= 2:  # Multiple completion indicators
            logger.info(
                f"Found {completion_count} completion indicators - triggering final answer"
            )
            return True

        # Look specifically at observations for completion signals
        recent_observations = state.get_steps_by_type(ReActStepType.OBSERVATION)
        if recent_observations:
            last_obs = recent_observations[-1]
            obs_content = last_obs.content.lower()

            # Check for tool execution results that indicate no action was taken
            if (
                "no tool was executed" in obs_content
                and "expected" in obs_content
                and len(recent_observations) >= 3
            ):
                # Multiple consecutive "no tool executed" observations suggest completion
                consecutive_no_tool = 0
                for obs in recent_observations[-3:]:
                    if "no tool was executed" in obs.content.lower():
                        consecutive_no_tool += 1

                if consecutive_no_tool >= 3:
                    logger.info(
                        "Detected multiple consecutive 'no tool executed' - forcing completion"
                    )
                    return True

            # If observation indicates we need more steps, continue
            continue_indicators = [
                "need to",
                "should",
                "next step",
                "continue",
                "more data needed",
                "additional information",
                "further analysis",
                "will check",
                "let me",
                "i will",
            ]

            if any(indicator in obs_content for indicator in continue_indicators):
                return False

        # Default: continue unless we have strong evidence to stop
        return False

    def _is_repetitive_completion_pattern(self, state: ReActState) -> bool:
        """Check if there's a repetitive pattern indicating completion"""
        if len(state.steps) < 6:
            return False

        recent_steps = state.steps[-1:]
        action_contents = []

        for step in recent_steps:
            if step.step_type == ReActStepType.ACTION:
                action_contents.append(step.content.lower())

        if len(action_contents) < 3:
            return False

        # Check if multiple recent actions contain "problem is solved" or similar
        completion_phrases = [
            "problem is solved",
            "task is complete",
            "ready for a new query",
            "no further steps",
            "already provided the final answer",
        ]

        completion_actions = 0
        for content in action_contents:
            if any(phrase in content for phrase in completion_phrases):
                completion_actions += 1

        # If 3 or more of the last actions indicate completion, it's repetitive
        return completion_actions >= 3

    def _detect_infinite_loop(self, state: ReActState) -> bool:
        """Detect if we're in an infinite loop pattern"""
        if len(state.steps) < 8:  # Need at least 8 steps to detect patterns
            return False

        # Check for repetitive content patterns
        recent_steps = state.steps[-8:]
        action_contents = []
        thought_contents = []

        for step in recent_steps:
            if step.step_type == ReActStepType.ACTION:
                action_contents.append(step.content.lower())
            elif step.step_type == ReActStepType.THOUGHT:
                thought_contents.append(step.content.lower())

        # Check for repetitive actions (simplified approach)
        # If we have many actions but they're all very similar, it might be a loop
        if len(action_contents) >= 6:
            # Count how many unique actions we have
            unique_actions = len(set(action_contents))
            # If we have 6+ actions but only 1-2 unique ones, it's likely a loop
            if unique_actions <= 2:
                logger.warning(
                    "Detected repetitive action pattern - too few unique actions"
                )
                return True

        # Check for thoughts that keep mentioning the same completion
        if len(thought_contents) >= 4:
            completion_thoughts = 0
            for content in thought_contents:
                if any(
                    phrase in content
                    for phrase in [
                        "problem has been",
                        "task is complete",
                        "already provided",
                        "no further steps",
                        "solved",
                        "finished",
                    ]
                ):
                    completion_thoughts += 1

            if completion_thoughts >= 3:
                logger.warning("Detected repetitive completion thoughts")
                return True

        return False

    async def _thought_step(self, state: ReActState):
        """Execute thought step"""
        logger.debug("Executing thought step")

        # Create thought prompt
        thought_prompt = self.prompts.format_thought_prompt(
            state, self.max_thought_cycles
        )

        # Generate response
        response = await self.api_session.send_message(thought_prompt)

        # Parse and store thought
        parsed = self.prompts.parse_response(response.content)
        thought_content = parsed.get("thought", response.content.strip())

        state.add_thought(thought_content)

        # Log step with API query
        if self.enable_logging:
            api_query = thought_prompt
            react_logger.log_step(
                "thought",
                thought_content,
                api_query=api_query,
                api_response=response.content,
            )

        logger.debug(f"Thought: {thought_content[:100]}...")

    async def _action_step(self, state: ReActState):
        """Execute action step"""
        logger.debug("Executing action step")

        # Get action prompt with tool details and current time
        tools_info = self.tool_registry.list_tools()
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        action_prompt = self.prompts.format_action_prompt(
            state, tools_info, current_datetime=current_time
        )

        # Generate response
        response = await self.api_session.send_message(action_prompt)

        # Parse action and extract tool usage
        parsed = self.prompts.parse_response(response.content)
        action_content = parsed.get("action", response.content.strip())

        # Extract tool information from action
        try:
            tool_name, tool_input = self._parse_tool_from_action(action_content)
        except Exception as e:
            logger.error(f"Failed to parse action: {e}")
            logger.error(f"Action content: {repr(action_content)}")
            logger.error(f"Raw API response: {repr(response.content)}")
            # Try to extract any useful information before falling back
            tool_name, tool_input = self._fallback_action_parse(action_content)

        state.add_action(
            content=action_content, tool_name=tool_name, tool_input=tool_input or {}
        )

        # Log step with API query
        if self.enable_logging:
            api_query = action_prompt
            react_logger.log_step(
                "action",
                action_content,
                tool_name,
                tool_input,
                api_query=api_query,
                api_response=response.content,
            )

        logger.debug(f"Action: {action_content[:100]}...")
        if tool_name:
            logger.debug(f"Tool: {tool_name}, Input: {tool_input}")

    async def _observation_step(self, state: ReActState):
        """Execute observation step"""
        logger.debug("Executing observation step")

        last_step = state.get_last_step()
        if not last_step or last_step.step_type != ReActStepType.ACTION:
            state.add_observation("No action to observe", error="Invalid state")
            return

        tool_result = None
        error = None

        # Check for special individual searches action
        if (
            last_step.tool_name == "web_search"
            and last_step.tool_input
            and last_step.tool_input.get("action_type") == "individual_searches"
        ):
            logger.info("Handling individual searches action")
            decomposed_queries = last_step.tool_input.get("decomposed_queries", [])
            logger.info(f"Processing {len(decomposed_queries)} individual searches")

            # Add a summary observation for the decomposed query setup
            state.add_observation(
                content=f"Find {len(decomposed_queries)} sub-query",
                tool_output={
                    "action_type": "individual_searches",
                    "queries": decomposed_queries,
                },
                error=None,
                tool_result=ToolResult(
                    success=True,
                    result={
                        "action_type": "individual_searches",
                        "queries": decomposed_queries,
                    },
                    metadata={"decomposed_queries_count": len(decomposed_queries)},
                ),
            )
            return

        # Execute tool if specified
        if last_step.tool_name:
            try:
                tool_result = await self.tool_registry.execute_tool(
                    last_step.tool_name, **(last_step.tool_input or {})
                )

                if not tool_result.success:
                    error = tool_result.error

            except Exception as e:
                error = str(e)
                tool_result = ToolResult(success=False, result=None, error=error)
        else:
            # Check if this was a parsing error or intentional non-tool action
            if "tool" in last_step.content.lower() and "{" in last_step.content:
                # This looks like a tool action that failed to parse
                error = "Failed to parse tool from action - check JSON format"
                tool_result = ToolResult(success=False, result=None, error=error)
            else:
                # This is likely an intentional non-tool action
                logger.debug(f"Non-tool action: {last_step.content}")
                tool_result = None  # No tool result for non-tool actions

        # Generate observation using LLM
        observation_prompt = self.prompts.format_observation_prompt(tool_result)

        # Generate response
        response = await self.api_session.send_message(observation_prompt)

        # Parse observation
        parsed = self.prompts.parse_response(response.content)
        observation_content = parsed.get("observation", response.content.strip())

        state.add_observation(
            content=observation_content,
            tool_output=tool_result.result if tool_result else None,
            error=error,
            tool_result=tool_result,
        )

        # Log step with API query
        if self.enable_logging:
            api_query = observation_prompt
            react_logger.log_step(
                "observation",
                observation_content,
                tool_output=tool_result.result if tool_result else None,
                error=error or "",
                api_query=api_query,
                api_response=response.content,
            )

        logger.debug(f"Observation: {observation_content[:100]}...")

    async def _final_answer_step(self, state: ReActState):
        """Execute final answer step"""
        logger.debug("Executing final answer step")

        # Create final answer prompt
        final_prompt = self.prompts.format_final_answer_prompt(state)

        # Generate response
        response = await self.api_session.send_message(final_prompt)

        # Parse final answer
        parsed = self.prompts.parse_response(response.content)
        final_answer = parsed.get("final_answer", response.content.strip())

        state.set_final_answer(final_answer)

        # Log step with API query
        if self.enable_logging:
            api_query = final_prompt
            react_logger.log_step(
                "final_answer",
                final_answer,
                api_query=api_query,
                api_response=response.content,
            )

        logger.debug(f"Final answer: {final_answer[:100]}...")

    async def _force_completion(self, state: ReActState):
        """Force completion when max steps reached"""
        logger.warning("Forcing completion due to max steps")

        summary = f"""Based on the work done so far, here's what I found:

{state.format_history()}

The analysis reached the maximum number of steps, but I can provide this summary of the findings."""

        state.set_final_answer(summary)

    def _parse_tool_from_action(
        self, action_content: str
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Parse tool name and input from action content - supports Python code blocks, JSON, YAML, and legacy formats"""

        # Clean the action content
        action_content = action_content.strip()

        # Method 0: Check for Python code block (highest priority for code_executor)
        if action_content.startswith("```python"):
            logger.debug("Detected Python code block for code_executor")
            # Extract Python code from markdown block
            code_content = action_content[9:]  # Remove ```python
            if code_content.endswith("```"):
                code_content = code_content[:-3]  # Remove trailing ```
            code_content = code_content.strip()

            # Return code_executor tool with extracted code
            return "code_executor", {"code": code_content}

        # Remove other markdown code blocks if present
        if action_content.startswith("```json"):
            action_content = action_content[7:]  # Remove ```json
        if action_content.startswith("```"):
            action_content = action_content[3:]  # Remove ```
        if action_content.endswith("```"):
            action_content = action_content[:-3]  # Remove trailing ```
        action_content = action_content.strip()

        # Method 1: Try to parse as JSON
        try:
            # Clean up potential formatting issues
            cleaned_content = action_content.replace("\n", " ").replace("\r", " ")
            # Remove extra whitespace
            cleaned_content = " ".join(cleaned_content.split())

            # Try multiple JSON parsing approaches
            data = None

            # Approach 1: Direct parsing
            try:
                data = json.loads(cleaned_content)
            except json.JSONDecodeError:
                # Approach 2: Try to fix common issues
                if cleaned_content.strip().startswith(
                    "{"
                ) and not cleaned_content.strip().endswith("}"):
                    # Incomplete JSON - try to complete it
                    test_content = cleaned_content.strip() + "}"
                    try:
                        data = json.loads(test_content)
                    except:
                        # Try adding closing for nested objects
                        test_content = cleaned_content.strip() + "}}"
                        try:
                            data = json.loads(test_content)
                        except:
                            pass
                elif '"tool"' in cleaned_content and '"parameters"' in cleaned_content:
                    # Try to extract valid JSON from partial content
                    import re

                    match = re.search(
                        r'\{[^}]*"tool"[^}]*"parameters"[^}]*\}', cleaned_content
                    )
                    if match:
                        try:
                            data = json.loads(match.group())
                        except:
                            pass

            if not data:
                # Don't raise exception here, return None instead to trigger fallback
                logger.debug(f"Could not parse JSON from: {cleaned_content}")
                return None, None
            if isinstance(data, dict):
                if "tool" in data:
                    tool_name = data["tool"]
                    tool_input = data.get("parameters", {})
                    return tool_name, tool_input if tool_input else None
                elif "action" in data:
                    # Non-tool action - this is valid, not an error
                    logger.debug(f"Non-tool action detected: {data['action']}")
                    return None, None
                else:
                    # Invalid JSON structure
                    logger.warning(f"Invalid JSON structure: {data}")
                    return None, None
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"JSON parsing failed: {e}")
            logger.debug(f"Original content: {repr(action_content)}")

            # Try to fix common JSON issues
            if action_content.startswith("{") and not action_content.endswith("}"):
                # Incomplete JSON - likely truncated
                logger.warning(f"Incomplete JSON detected: {action_content}")
                # Instead of raising error, try to recover
                try:
                    # Try to find the end of the JSON
                    brace_count = 0
                    end_pos = 0
                    for i, char in enumerate(action_content):
                        if char == "{":
                            brace_count += 1
                        elif char == "}":
                            brace_count -= 1
                            if brace_count == 0:
                                end_pos = i + 1
                                break

                    if end_pos > 0:
                        potential_json = action_content[:end_pos]
                        data = json.loads(potential_json)
                        if isinstance(data, dict) and "tool" in data:
                            tool_name = data["tool"]
                            tool_input = data.get("parameters", {})
                            return tool_name, tool_input if tool_input else None
                except:
                    pass

                # If recovery failed, return None instead of raising error
                logger.warning(
                    "Could not recover from incomplete JSON, skipping action"
                )
                return None, None

            elif '"tool"' in action_content and not action_content.startswith("{"):
                # JSON without proper wrapper - try to extract
                try:
                    # Find the JSON part
                    start = action_content.find("{")
                    if start >= 0:
                        potential_json = action_content[start:]
                        data = json.loads(potential_json)
                        if isinstance(data, dict) and "tool" in data:
                            tool_name = data["tool"]
                            tool_input = data.get("parameters", {})
                            return tool_name, tool_input if tool_input else None
                except:
                    pass

        # Method 2: Try to parse as YAML
        try:
            data = yaml.safe_load(action_content.strip())
            if isinstance(data, dict):
                if "tool" in data:
                    tool_name = data["tool"]
                    tool_input = data.get("parameters", {})
                    return tool_name, tool_input if tool_input else None
                elif "action" in data:
                    return None, None
        except (yaml.YAMLError, ValueError):
            pass

        # Method 3: Look for structured patterns in text
        # Pattern: tool: name\nparameters:\n  key: value
        tool_match = re.search(r"tool:\s*([^\n]+)", action_content, re.IGNORECASE)
        if tool_match:
            tool_name = tool_match.group(1).strip()

            # Try to extract parameters
            tool_input = {}
            params_match = re.search(
                r"parameters:\s*\n((?:\s+[^\n]+\n?)*)", action_content, re.IGNORECASE
            )
            if params_match:
                params_text = params_match.group(1)
                # Try to parse as YAML
                try:
                    tool_input = yaml.safe_load(params_text) or {}
                except:
                    # Parse simple key: value pairs
                    for line in params_text.split("\n"):
                        line = line.strip()
                        if ":" in line:
                            key, value = line.split(":", 1)
                            tool_input[key.strip()] = value.strip().strip("\"'")

            return tool_name, tool_input if tool_input else None

        # Method 4: Legacy patterns (fallback)
        tool_patterns = [
            r"Tool:\s*([^\n]+)",
            r"Use\s+([^\s]+)\s+tool",
            r"Execute\s+([^\s]+)",
            r"Run\s+([^\s]+)",
        ]

        tool_name = None
        for pattern in tool_patterns:
            match = re.search(pattern, action_content, re.IGNORECASE)
            if match:
                tool_name = match.group(1).strip()
                break

        # Try to extract tool input for legacy format
        tool_input = None
        if tool_name:
            input_patterns = [
                r"Input:\s*(\{.*?\})",
                r"Parameters:\s*(\{.*?\})",
                r"Args:\s*(\{.*?\})",
            ]

            for pattern in input_patterns:
                match = re.search(pattern, action_content, re.IGNORECASE | re.DOTALL)
                if match:
                    try:
                        tool_input = json.loads(match.group(1))
                        break  # Success, exit loop
                    except Exception as e1:
                        try:
                            tool_input = eval(match.group(1))  # Fallback eval
                            break  # Success, exit loop
                        except Exception as e2:
                            logger.debug(
                                f"Failed to parse tool input: JSON error: {e1}, Eval error: {e2}"
                            )
                            continue  # Try next pattern

            # Additional pattern for legacy "Input:" without braces
            if not tool_input:
                legacy_input_match = re.search(
                    r"Input:\s*([^{][^\n]*)", action_content, re.IGNORECASE
                )
                if legacy_input_match:
                    input_str = legacy_input_match.group(1).strip()
                    # Try simple key=value parsing
                    if "=" in input_str:
                        parts = input_str.split("=", 1)
                        tool_input = {parts[0].strip(): parts[1].strip().strip("\"'")}

        return tool_name, tool_input

    def _fallback_action_parse(
        self, action_content: str
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Fallback parser for malformed action content"""
        try:
            # Look for common tool names in the content
            tool_names = list(self.tool_registry.tools.keys())
            for tool_name in tool_names:
                if tool_name.lower() in action_content.lower():
                    logger.info(
                        f"Found tool name '{tool_name}' in malformed action, using with empty parameters"
                    )
                    return tool_name, {}

            # If no tools found, treat as non-tool action
            logger.info(
                "No tool detected in malformed action, treating as non-tool action"
            )
            return None, None
        except Exception as e:
            logger.error(f"Fallback parsing also failed: {e}")
            return None, None
