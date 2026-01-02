"""ReAct engine implementation"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import yaml
from langchain_core.messages import AIMessage, HumanMessage

from ..models.gemini import GeminiChatSession, GeminiModel
from ..tools.base import ObservationData, ToolRegistry, ToolResult
from ..utils.logger import logger
from ..utils.react_logger import react_logger
from .prompts import ReActPrompts
from .state import ReActState, ReActStepType


@dataclass
class ObservationPayload:
    content: str
    tool_output: Any = None
    error: Optional[str] = None
    tool_result: Optional[ToolResult] = None
    store_output: bool = True
    store_result: bool = True
    log_query: str = ""
    log_response: str = ""

    def to_state_args(self) -> Tuple[str, Any, Optional[str], Optional[ToolResult]]:
        stored_output = self.tool_output if self.store_output else None
        stored_result = self.tool_result if self.store_result else None
        return self.content, stored_output, self.error, stored_result

    def to_stream(self, serializer) -> Dict[str, Any]:
        return {
            "content": self.content,
            "tool_output": self.tool_output,
            "error": self.error,
            "tool_result": serializer(self.tool_result),
        }


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
        self.max_steps = self.max_thought_cycles * 4
        self.max_retries = (
            max_retries if max_retries is not None else config.react_max_retries
        )
        self.prompts = ReActPrompts()
        self.enable_logging = enable_logging
        self.current_date = None
        self.api_session: Optional[GeminiChatSession] = None

        logger.info(f"Initialized ReAct engine with {len(tool_registry.tools)} tools")

    async def solve_stream(
        self, query: str, context: Optional[Dict[str, Any]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream ReAct solving process step-by-step.

        Yields dict events with keys: type, content, and optional tool/tool_input/tool_output/error/final.
        """
        logger.info(f"[stream] Starting ReAct solving: {query[:100]}...")
        self.current_date = datetime.now().strftime("%Y-%m-%d")

        tools_info = self.tool_registry.list_tools()
        context = context or {}

        system_context = context.get("system_context")
        system_prompt = context.get("system_prompt_override")
        if system_prompt is not None:
            system_prompt = str(system_prompt)
        elif context.get("skip_default_prompt"):
            system_prompt = str(system_context).strip() if system_context else ""
            if not system_prompt:
                system_prompt = "You are an assistant. Use the provided tools and context if present."
        else:
            system_prompt = self.prompts.format_system_prompt(
                tools_info,
                self.current_date,
                system_context=system_context,
            )
        initial_messages = self.model.format_messages(system_prompt, [], "")
        self.api_session = self.model.start_chat_session(initial_messages)

        if self.enable_logging:
            react_logger.start_session(query, context=context)

        state = ReActState(
            original_query=query, max_steps=self.max_steps, context=context
        )

        try:
            yield {"type": "start", "query": query}

            plan = await self._planning_step(
                state=state,
                query=query,
                available_tools=tools_info,
                system_context=system_context,
            )
            if plan:
                yield {
                    "type": "thought",
                    "content": plan,
                    "metadata": {"stage": "plan"},
                }

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
                    observation = await self._observation_step(state)
                    yield {
                        "type": "observation",
                        **observation.to_stream(self._tool_result_to_dict),
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
            if self._should_provide_final_answer(state):
                return ReActStepType.FINAL_ANSWER
            return ReActStepType.THOUGHT
        else:
            return ReActStepType.FINAL_ANSWER

    def _should_provide_final_answer(self, state: ReActState) -> bool:
        """Determine if we have enough information for final answer"""
        from ..utils.config import config

        thought_steps = len(state.get_steps_by_type(ReActStepType.THOUGHT))
        if thought_steps >= config.react_max_thought_cycles:
            return True

        action_steps = len(state.get_steps_by_type(ReActStepType.ACTION))
        observation_steps = len(state.get_steps_by_type(ReActStepType.OBSERVATION))
        if thought_steps < 1 or action_steps < 1 or observation_steps < 1:
            return False

        if state.steps:
            last_content = state.steps[-1].content.lower()
            if "<next_task_required/>" in last_content:
                return False
            if "<final_answer_ready/>" in last_content:
                logger.info(
                    "Found explicit completion marker - triggering final answer"
                )
                return True

        return False

    def _detect_infinite_loop(self, state: ReActState) -> bool:
        """Detect if we're in an infinite loop pattern"""
        if len(state.steps) < 8:
            return False

        recent_steps = state.steps[-8:]
        action_contents = []
        thought_contents = []

        for step in recent_steps:
            if step.step_type == ReActStepType.ACTION:
                action_contents.append(step.content.lower())
            elif step.step_type == ReActStepType.THOUGHT:
                thought_contents.append(step.content.lower())

        if len(action_contents) >= 6:
            unique_actions = len(set(action_contents))
            if unique_actions <= 2:
                logger.warning(
                    "Detected repetitive action pattern - too few unique actions"
                )
                return True

        if len(thought_contents) >= 4:
            completion_phrases = [
                "problem has been",
                "task is complete",
                "already provided",
                "no further steps",
                "solved",
                "finished",
            ]
            completion_thoughts = sum(
                1
                for content in thought_contents
                if any(phrase in content for phrase in completion_phrases)
            )

            if completion_thoughts >= 3:
                logger.warning("Detected repetitive completion thoughts")
                return True

        return False

    async def _planning_step(
        self,
        state: ReActState,
        query: str,
        available_tools: List[Dict[str, Any]],
        system_context: Optional[str] = None,
    ) -> Optional[str]:
        """Run an upfront planning pass using context"""
        logger.debug("Executing planning step")

        planning_prompt = self.prompts.format_planning_prompt(
            query=query,
            available_tools=available_tools,
            system_context=system_context,
            current_date=self.current_date,
        )

        response = await self.api_session.send_message(planning_prompt)
        plan_text = self._strip_trailing_tool_call(response.content.strip())
        try:
            if not plan_text:
                return None
            state.set_plan(plan_text)
            if self.enable_logging:
                react_logger.log_step(
                    "plan",
                    plan_text,
                    api_query=planning_prompt,
                    api_response=response.content,
                )
            logger.debug("Planning complete")
            return plan_text
        finally:
            self._prune_planning_history()

    async def _thought_step(self, state: ReActState):
        """Execute thought step"""
        logger.debug("Executing thought step")

        thought_prompt = self.prompts.format_thought_prompt(
            state, self.max_thought_cycles
        )
        response = await self.api_session.send_message(thought_prompt)
        parsed = self.prompts.parse_response(response.content)
        thought_content = parsed.get("thought", response.content.strip())

        state.add_thought(thought_content)

        if self.enable_logging:
            react_logger.log_step(
                "thought",
                thought_content,
                api_query=thought_prompt,
                api_response=response.content,
            )

        logger.debug(f"Thought: {thought_content[:100]}...")

    async def _action_step(self, state: ReActState):
        """Execute action step"""
        logger.debug("Executing action step")

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        action_prompt = self.prompts.format_action_prompt(
            state, current_datetime=current_time
        )
        response = await self.api_session.send_message(action_prompt)
        parsed = self.prompts.parse_response(response.content)
        action_content = parsed.get("action", response.content.strip())

        try:
            tool_name, tool_input = self._parse_tool_from_action(action_content)
        except Exception as e:
            logger.error(f"Failed to parse action: {e}")
            logger.error(f"Action content: {repr(action_content)}")
            logger.error(f"Raw API response: {repr(response.content)}")
            tool_name, tool_input = self._fallback_action_parse(action_content)

        state.add_action(
            content=action_content, tool_name=tool_name, tool_input=tool_input or {}
        )

        if self.enable_logging:
            react_logger.log_step(
                "action",
                action_content,
                tool_name,
                tool_input,
                api_query=action_prompt,
                api_response=response.content,
            )

        logger.debug(f"Action: {action_content[:100]}...")
        if tool_name:
            logger.debug(f"Tool: {tool_name}, Input: {tool_input}")

    async def _observation_step(self, state: ReActState) -> ObservationPayload:
        logger.debug("Executing observation step")

        last_step = state.get_last_step()
        if not last_step or last_step.step_type != ReActStepType.ACTION:
            raise RuntimeError("Observation step requires a preceding action")

        if not last_step.tool_name:
            if "tool" in last_step.content.lower() and "{" in last_step.content:
                tool_result = ToolResult(
                    success=False,
                    result=None,
                    error="Failed to parse tool from action - check JSON format",
                )
                payload = await self._llm_observation(tool_result)
            else:
                payload = ObservationPayload(
                    content="Non-tool action.",
                    tool_output=None,
                    error=None,
                    tool_result=None,
                    store_output=False,
                    store_result=False,
                )
            self._record_observation(state, payload)
            return payload

        tool_result = await self.tool_registry.execute_tool(
            last_step.tool_name, **(last_step.tool_input or {})
        )

        obs_data = self._extract_observation_data(tool_result.result)
        if obs_data and obs_data.skip_llm:
            payload = self._observation_from_data(obs_data, tool_result)
        elif obs_data:
            llm_input = ToolResult(
                success=tool_result.success,
                result=obs_data.data,
                error=obs_data.error or tool_result.error,
                metadata=tool_result.metadata,
            )
            llm_payload = await self._llm_observation(llm_input)
            payload = ObservationPayload(
                content=llm_payload.content,
                tool_output=obs_data.data,
                error=obs_data.error or llm_payload.error,
                tool_result=tool_result if obs_data.store_result else None,
                store_output=obs_data.store_output,
                store_result=obs_data.store_result,
                log_query=obs_data.log_query or llm_payload.log_query,
                log_response=obs_data.log_response or llm_payload.log_response,
            )
        else:
            payload = await self._llm_observation(tool_result)

        self._record_observation(state, payload)
        return payload

    async def _llm_observation(self, tool_result: ToolResult) -> ObservationPayload:
        prompt = self.prompts.format_observation_prompt(tool_result)
        response = await self.api_session.send_message(prompt)
        parsed = self.prompts.parse_response(response.content)
        content = parsed.get("observation", response.content.strip())

        return ObservationPayload(
            content=content,
            tool_output=tool_result.result,
            error=tool_result.error,
            tool_result=tool_result,
            store_output=True,
            store_result=True,
            log_query=prompt,
            log_response=response.content,
        )

    def _observation_from_data(
        self, obs_data: ObservationData, tool_result: ToolResult
    ) -> ObservationPayload:
        return ObservationPayload(
            content=obs_data.observation or "Tool completed",
            tool_output=obs_data.data,
            error=obs_data.error or tool_result.error,
            tool_result=tool_result if obs_data.store_result else None,
            store_output=obs_data.store_output,
            store_result=obs_data.store_result,
            log_query=obs_data.log_query or "",
            log_response=obs_data.log_response or "",
        )

    def _record_observation(self, state: ReActState, payload: ObservationPayload):
        content, tool_output, error, tool_result = payload.to_state_args()

        state.add_observation(
            content=content,
            tool_output=tool_output,
            error=error,
            tool_result=tool_result,
        )

        if not self.enable_logging:
            return

        react_logger.log_step(
            "observation",
            payload.content,
            tool_output=payload.tool_output,
            error=payload.error or "",
            api_query=payload.log_query or "",
            api_response=payload.log_response or "",
        )

        logger.debug(f"Observation: {payload.content[:100]}...")

    async def _final_answer_step(self, state: ReActState):
        """Execute final answer step"""
        logger.debug("Executing final answer step")

        final_prompt = self.prompts.format_final_answer_prompt(state)
        response = await self.api_session.send_message(final_prompt)
        parsed = self.prompts.parse_response(response.content)
        final_answer = parsed.get("final_answer", response.content.strip())

        state.set_final_answer(final_answer)

        if self.enable_logging:
            react_logger.log_step(
                "final_answer",
                final_answer,
                api_query=final_prompt,
                api_response=response.content,
            )

        logger.debug(f"Final answer: {final_answer[:100]}...")

    def _strip_trailing_tool_call(self, text: str) -> str:
        stripped = text.strip()
        if not stripped:
            return stripped
        fenced_match = re.search(
            r"```(?:json)?\s*([\s\S]*?)\s*```\s*$", stripped
        )
        if fenced_match and '"tool"' in fenced_match.group(1):
            return stripped[:fenced_match.start()].rstrip()
        last_brace = stripped.rfind("{")
        if last_brace != -1 and '"tool"' in stripped[last_brace:]:
            return stripped[:last_brace].rstrip()
        return stripped

    def _prune_planning_history(self) -> None:
        if not self.api_session:
            return
        history = self.api_session.history
        if history and isinstance(history[-1], AIMessage):
            history.pop()
        if history and isinstance(history[-1], HumanMessage):
            history.pop()

    def _tool_result_to_dict(
        self, tool_result: Optional[ToolResult]
    ) -> Optional[Dict[str, Any]]:
        if tool_result is None:
            return None

        return {
            "success": tool_result.success,
            "result": tool_result.result,
            "error": tool_result.error,
            "metadata": tool_result.metadata,
        }

    def _extract_observation_data(self, result: Any) -> Optional[ObservationData]:
        if isinstance(result, ObservationData):
            return result
        return None

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

        action_content = action_content.strip()

        if action_content.startswith("```python"):
            logger.debug("Detected Python code block for code_executor")
            code_content = action_content[9:]
            if code_content.endswith("```"):
                code_content = code_content[:-3]
            code_content = code_content.strip()
            return "code_executor", {"code": code_content}

        if action_content.startswith("```json"):
            action_content = action_content[7:]
        if action_content.startswith("```"):
            action_content = action_content[3:]
        if action_content.endswith("```"):
            action_content = action_content[:-3]
        action_content = action_content.strip()

        try:
            cleaned_content = action_content.replace("\n", " ").replace("\r", " ")
            cleaned_content = " ".join(cleaned_content.split())

            data = None
            try:
                data = json.loads(cleaned_content)
            except json.JSONDecodeError:
                if cleaned_content.strip().startswith(
                    "{"
                ) and not cleaned_content.strip().endswith("}"):
                    test_content = cleaned_content.strip() + "}"
                    try:
                        data = json.loads(test_content)
                    except json.JSONDecodeError:
                        test_content = cleaned_content.strip() + "}}"
                        try:
                            data = json.loads(test_content)
                        except json.JSONDecodeError:
                            pass
                elif '"tool"' in cleaned_content and '"parameters"' in cleaned_content:
                    match = re.search(
                        r'\{[^}]*"tool"[^}]*"parameters"[^}]*\}', cleaned_content
                    )
                    if match:
                        try:
                            data = json.loads(match.group())
                        except json.JSONDecodeError:
                            pass

            if not data:
                logger.debug(f"Could not parse JSON from: {cleaned_content}")
                return None, None
            if isinstance(data, dict):
                if "tool" in data:
                    tool_name = data["tool"]
                    tool_input = data.get("parameters", {})
                    return tool_name, tool_input if tool_input else None
                elif "action" in data:
                    logger.debug(f"Non-tool action detected: {data['action']}")
                    return None, None
                else:
                    logger.warning(f"Invalid JSON structure: {data}")
                    return None, None
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"JSON parsing failed: {e}")
            logger.debug(f"Original content: {repr(action_content)}")

            if action_content.startswith("{") and not action_content.endswith("}"):
                logger.warning(f"Incomplete JSON detected: {action_content}")
                try:
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
                except Exception:
                    pass

                logger.warning(
                    "Could not recover from incomplete JSON, skipping action"
                )
                return None, None

            elif '"tool"' in action_content and not action_content.startswith("{"):
                try:
                    start = action_content.find("{")
                    if start >= 0:
                        potential_json = action_content[start:]
                        data = json.loads(potential_json)
                        if isinstance(data, dict) and "tool" in data:
                            tool_name = data["tool"]
                            tool_input = data.get("parameters", {})
                            return tool_name, tool_input if tool_input else None
                except Exception:
                    pass

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

        tool_match = re.search(r"tool:\s*([^\n]+)", action_content, re.IGNORECASE)
        if tool_match:
            tool_name = tool_match.group(1).strip()
            tool_input = {}
            params_match = re.search(
                r"parameters:\s*\n((?:\s+[^\n]+\n?)*)", action_content, re.IGNORECASE
            )
            if params_match:
                params_text = params_match.group(1)
                try:
                    tool_input = yaml.safe_load(params_text) or {}
                except yaml.YAMLError:
                    for line in params_text.split("\n"):
                        line = line.strip()
                        if ":" in line:
                            key, value = line.split(":", 1)
                            tool_input[key.strip()] = value.strip().strip("\"'")

            return tool_name, tool_input if tool_input else None

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
                        break
                    except Exception as e1:
                        try:
                            tool_input = eval(match.group(1))
                            break
                        except Exception as e2:
                            logger.debug(
                                f"Failed to parse tool input: JSON error: {e1}, Eval error: {e2}"
                            )
                            continue

            if not tool_input:
                legacy_input_match = re.search(
                    r"Input:\s*([^{][^\n]*)", action_content, re.IGNORECASE
                )
                if legacy_input_match:
                    input_str = legacy_input_match.group(1).strip()
                    if "=" in input_str:
                        parts = input_str.split("=", 1)
                        tool_input = {parts[0].strip(): parts[1].strip().strip("\"'")}

        return tool_name, tool_input

    def _fallback_action_parse(
        self, action_content: str
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Fallback parser for malformed action content"""
        try:
            tool_names = list(self.tool_registry.tools.keys())
            for tool_name in tool_names:
                if tool_name.lower() in action_content.lower():
                    logger.info(
                        f"Found tool name '{tool_name}' in malformed action, using with empty parameters"
                    )
                    return tool_name, {}

            logger.info(
                "No tool detected in malformed action, treating as non-tool action"
            )
            return None, None
        except Exception as e:
            logger.error(f"Fallback parsing also failed: {e}")
            return None, None
