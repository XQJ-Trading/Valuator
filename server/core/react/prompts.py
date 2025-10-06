"""ReAct prompt templates"""

from typing import List, Dict, Any, Optional
from .state import ReActState, ReActStep, ReActStepType


class ReActPrompts:
    """ReAct prompt template manager"""
    
    SYSTEM_PROMPT = """You are a highly intelligent AI assistant that solves complex problems step-by-step using the ReAct (Reasoning + Acting) framework. Your goal is to provide accurate, efficient, and reliable solutions.

Today's Date: {current_date}. Use this for any date-related tasks.

**ReAct Framework:**
You will proceed in a loop of Thought -> Action -> Observation.
1.  **Thought**: Analyze the problem, history, and previous observation to form a plan for the next action.
2.  **Action**: Execute a single, specific action. This MUST be a tool call in the specified JSON format.
3.  **Observation**: I will provide the result of your action. You will then start the next cycle with a new Thought.

**Available Tools:**
You have access to the following tools. Use them when necessary.
{available_tools}

**CRITICAL Response Format:**
You MUST follow these rules for every response.
-   **For Tool Actions**: 
    -   **Code Execution ONLY**: Use ```python\nyour_code_here\n``` format (no JSON wrapper)
    -   **All Other Tools**: Your response MUST be ONLY a single, valid JSON object
        -   Format: `{{"tool": "tool_name", "parameters": {{"param_name": "param_value"}}}}`
        -   Do NOT include any text, explanations, or markdown before or after the JSON
        -   Ensure all strings in JSON are enclosed in double quotes
-   **For Thoughts, Observations, and Final Answer**: Respond in plain text. Do NOT use JSON.

**General Guidelines:**
-   Be methodical. Analyze the results of each action before planning the next one.
-   If a tool fails, analyze the error and try a different approach. Do not repeat the same failed action.
-   Break down complex problems into smaller, manageable steps.
-   Strive to solve the problem in the fewest steps possible.
"""

    THOUGHT_PROMPT = """**Original Query:** {original_query}

**Task:**
1.  Analyze the original query and formulate a concise plan for your next immediate action.
2.  Provide ONLY your thought process. Do not include the action itself.

You have completed {thought_steps}/{max_thought_cycles} thought cycles. Use the remaining cycles effectively.

**Thought:**"""

    ACTION_PROMPT = """**Current Time:** {current_datetime}

**Task:**
Based on your last thought, execute ONE tool action.

**Response Requirements:**
-   **For code_executor**: You MUST respond with ```python\nyour_code_here\n``` format ONLY
-   **For all other tools**: You MUST respond with a single, complete, and valid JSON object
-   Refer to the system prompt for the exact format and rules
-   Do NOT add any extra text or explanations

**Action:**"""

    OBSERVATION_PROMPT = """**Tool Execution Result:**
-   Success: {success}
-   Output: {output}
-   Error: {error}

**Task:**
1.  Analyze the result of the action.
2.  Determine if the problem is solved or what the next logical step should be.

**Completion Markers (use at the end of your observation):**
-   `<next_task_required/>`: If more steps are needed to solve the problem.
-   `<final_answer_ready/>`: If you have successfully solved the problem and verified the answer.

**Observation:**"""

    FINAL_ANSWER_PROMPT = """**Original Query:** {original_query}

**Task:**
Provide the final, comprehensive answer to the original query.

**Final Answer:**"""
    
    @classmethod
    def format_system_prompt(cls, available_tools: List[Dict[str, Any]], current_date: str) -> str:
        """Format the system prompt with available tools"""
        tools_desc = "\n".join([
            f"- {tool['name']}: {tool['description']}"
            for tool in available_tools
        ])
        return cls.SYSTEM_PROMPT.format(
            available_tools=tools_desc, 
            current_date=current_date
        )
    
    @classmethod
    def format_thought_prompt(cls, state: ReActState, max_thought_cycles: int) -> str:
        """Format prompt for thought step"""
        thought_steps = len(state.get_steps_by_type(ReActStepType.THOUGHT))

        return cls.THOUGHT_PROMPT.format(
            original_query=state.original_query,
            thought_steps=thought_steps,
            max_thought_cycles=max_thought_cycles,
        )
    
    @classmethod
    def format_action_prompt(cls, state: ReActState, available_tools: List[Dict[str, Any]] = None, current_datetime: str = None) -> str:
        """Format prompt for action step"""
        from datetime import datetime
        if current_datetime is None:
            current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return cls.ACTION_PROMPT.format(current_datetime=current_datetime)
    
    @classmethod
    def format_observation_prompt(cls, tool_result: Any = None, success: bool = False, 
                                 output: str = "", error: str = "") -> str:
        """Format prompt for observation step"""
        if tool_result:
            success = tool_result.success if hasattr(tool_result, 'success') else False
            output = str(tool_result.result) if hasattr(tool_result, 'result') and tool_result.result else "No output"
            error = tool_result.error if hasattr(tool_result, 'error') and tool_result.error else "None"
        else:
            success = success
            output = output or "No tool executed"
            error = error or "None"
        
        return cls.OBSERVATION_PROMPT.format(
            success=success,
            output=output,
            error=error
        )
    
    @classmethod
    def format_final_answer_prompt(cls, state: ReActState) -> str:
        """Format prompt for final answer"""
        return cls.FINAL_ANSWER_PROMPT.format(
            original_query=state.original_query
        )
    
    @staticmethod
    def _format_context(context: Dict[str, Any]) -> str:
        """Format context information"""
        if not context:
            return "No additional context available."
        
        formatted = []
        for key, value in context.items():
            formatted.append(f"{key}: {value}")
        
        return "\n".join(formatted)
    
    @staticmethod
    def _format_history(steps: List[ReActStep]) -> str:
        """Format step history"""
        if not steps:
            return "No previous steps."
        
        formatted = []
        for i, step in enumerate(steps, 1):
            if step.step_type == ReActStepType.THOUGHT:
                formatted.append(f"Thought {i}: {step.content}")
            elif step.step_type == ReActStepType.ACTION:
                action_text = f"Action {i}: {step.content}"
                if step.tool_name:
                    action_text += f" (Tool: {step.tool_name})"
                formatted.append(action_text)
            elif step.step_type == ReActStepType.OBSERVATION:
                obs_text = f"Observation {i}: {step.content}"
                if step.error:
                    obs_text += f" (Error: {step.error})"
                formatted.append(obs_text)
        
        return "\n".join(formatted)
    
    @classmethod
    def get_step_prompt(cls, step_type: ReActStepType, state: ReActState,
                       tool_result: Any = None, available_tools: List[Dict[str, Any]] = None,
                       max_thought_cycles: int = 10) -> str:
        """Get prompt for specific step type"""
        if step_type == ReActStepType.THOUGHT:
            return cls.format_thought_prompt(state, max_thought_cycles)
        elif step_type == ReActStepType.ACTION:
            return cls.format_action_prompt(state, available_tools)
        elif step_type == ReActStepType.OBSERVATION:
            return cls.format_observation_prompt(tool_result)
        elif step_type == ReActStepType.FINAL_ANSWER:
            return cls.format_final_answer_prompt(state)
        else:
            raise ValueError(f"Unknown step type: {step_type}")
    
    @classmethod
    def parse_response(cls, response: str) -> Dict[str, str]:
        """Parse ReAct response - handles both JSON and text responses"""
        import json
        
        # Clean up the response
        content = response.strip()
        
        # Try to parse as JSON first (for action steps)
        if content.startswith('{') and content.endswith('}'):
            try:
                parsed_json = json.loads(content)
                if isinstance(parsed_json, dict):
                    # If it's a valid JSON dict, extract the appropriate field
                    if "action" in parsed_json:
                        # For thought steps, we want the content of the action field
                        # For action steps, we want the entire JSON string
                        return {
                            "thought": parsed_json.get("action", content),  # Extract action content for thought
                            "action": content,  # Keep entire JSON for action parsing
                            "observation": parsed_json.get("action", content),
                            "final_answer": parsed_json.get("action", content)
                        }
                    elif "tool" in parsed_json:
                        # It's a tool action, return the entire JSON as action content
                        return {
                            "thought": content,
                            "action": content,
                            "observation": content,
                            "final_answer": content
                        }
            except json.JSONDecodeError:
                # If JSON parsing fails, fall through to text processing
                pass
        
        # Remove common prefixes if they exist
        prefixes_to_remove = [
            "Thought:", "Action:", "Observation:", "Final Answer:",
            "Your response should start with your analysis of the situation:",
            "Your action:", "Your observation:", "Your final answer:"
        ]
        
        for prefix in prefixes_to_remove:
            if content.startswith(prefix):
                content = content[len(prefix):].strip()
                break
        
        # Return a dict with the content for all possible types
        return {
            "thought": content,
            "action": content, 
            "observation": content,
            "final_answer": content
        }
