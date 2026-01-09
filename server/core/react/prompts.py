"""ReAct prompt templates"""

from typing import Any, Dict, List, Optional

from .state import ReActState, ReActStepType


class ReActPrompts:
    """ReAct prompt template manager"""

    SYSTEM_PROMPT = """You are a highly intelligent AI assistant that solves complex problems step-by-step using the ReAct (Reasoning + Acting) framework. Your goal is to provide accurate, efficient, and reliable solutions.

**ReAct Framework:**
You will proceed in a loop of Thought -> Action -> Observation.
1.  **Thought**: Analyze the problem, history, and previous observation to form a plan for the next action.
2.  **Action**: Execute a single, specific action. This MUST be a tool call in the specified JSON format.
3.  **Observation**: I will provide the result of your action.

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

RUNTIME DATA (apply after the rules above):
-   Available Tools:\n{available_tools}
-   Today's Date: {current_date}
{system_context}
"""

    PLANNING_PROMPT = """Create a concise, context-grounded execution plan before the ReAct cycle begins.{system_context_block}
-  Use the query and the runtime/system context already provided in the system message; reference relevant items by name instead of pasting them.
-  Make Step 1 a `context_tool` call to load valuation instructions. Describe the call in words only (do NOT output JSON or a tool call). State what you'll do with that context and the immediate next action after loading it.
-  Flag assumptions or missing data to validate early.
-  Keep it executable and brief; no code or JSON.

Today's Date: {current_date}

**Available Tools:**
{tools_section}

Return the plan followed by a short "Risks/Assumptions:" list.
**Query:** {query}
"""

    THOUGHT_PROMPT = """Follow the rules, then review the latest observation and plan the next move.{plan_block}
-  Provide ONLY your thought process. Do not include the action itself.
-  Describe intended tools in words only.
-  If ready to answer, output `<final_answer_ready/>` only.
-  Review the observation and include a **Review Point** section:
   - Alignment: {{full | partial | none}} relative to expected outcomes.
   - Gaps: Enumerate all missing, incorrect, or incomplete expected items.
-  For each planned step, verify which context item (or system context) justifies it; if missing, quickly scan context to add the needed evidence or flag the gap.
-  If context_tool was used, reference only the relevant parts from previous observations' tool_output rather than repeating the full context.
-  Draft checklist: Step → evidence source (context/system) → status (found/missing). Keep it tight.

**Original Query:** {original_query}

Progress: {thought_steps}/{max_thought_cycles} thought cycles used.

**Thought:**"""

    ACTION_PROMPT = """Execute ONE tool action after reviewing the prior thought.

**Response Requirements:**
-   **For code_executor**: You MUST respond with ```python\nyour_code_here\n``` format ONLY
-   **For all other tools**: You MUST respond with a single, complete, and **valid JSON object**
-   **If you are ready to provide the final answer**: Respond with `{{"tool": "final_answer", "parameters": {{}}}}`
-   Refer to the system prompt for the exact format and rules

Current Time: {current_datetime}

**Action:**"""

    OBSERVATION_PROMPT = """Summarize the tool result only.

**Tool Execution Result**
- Success: {success}
- Output: {output}
- Error: {error}

**Observation:**"""

    FINAL_ANSWER_PROMPT = """Write only the final answer.

Follow all instructions and constraints specified in the prompt/context exactly.
- Ensure hierarchical representation: sections → structures → entity-level elements.

Preserve all fields, values, and entity units exactly as produced.
Do not summarize, infer missing values, aggregate, correct, or omit any items.
Ensure units are consistent across the entire output.

Represent top-level objects or arrays as Markdown tables.
- Use keys as columns and one object per row.

**Original Query:** {original_query}

**Final Answer:**"""

    @classmethod
    def format_system_prompt(
        cls,
        available_tools: List[Dict[str, Any]],
        current_date: str,
        system_context: Optional[str] = None,
    ) -> str:
        """Format the system prompt with available tools"""
        tools_desc = "\n".join(cls._format_tool_entry(tool) for tool in available_tools)
        if not tools_desc:
            tools_desc = "- (no tools registered)"

        context_section = ""
        if system_context:
            safe_context = str(system_context).replace("{", "{{").replace("}", "}}")
            context_section = (
                "\n\nADDITIONAL CONTEXT (apply alongside the rules above):\n"
                f"{safe_context}\n"
            )
        return cls.SYSTEM_PROMPT.format(
            available_tools=tools_desc,
            current_date=current_date,
            system_context=context_section,
        )

    @classmethod
    def format_thought_prompt(
        cls,
        state: ReActState,
        max_thought_cycles: int,
    ) -> str:
        """Format prompt for thought step"""
        thought_steps = len(state.get_steps_by_type(ReActStepType.THOUGHT))
        plan_block = ""
        if state.plan:
            plan_block = (
                "\n\nCurrent plan (adjust if it no longer fits):\n" + state.plan
            )

        return cls.THOUGHT_PROMPT.format(
            original_query=state.original_query,
            thought_steps=thought_steps,
            max_thought_cycles=max_thought_cycles,
            plan_block=plan_block,
        )

    @classmethod
    def format_action_prompt(
        cls,
        current_datetime: str = None,
    ) -> str:
        """Format prompt for action step"""
        from datetime import datetime

        if current_datetime is None:
            current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return cls.ACTION_PROMPT.format(
            current_datetime=current_datetime,
        )

    @classmethod
    def format_observation_prompt(
        cls,
        tool_result: Any = None,
        success: bool = False,
        output: str = "",
        error: str = "",
    ) -> str:
        """Format prompt for observation step"""
        if tool_result:
            success = tool_result.success if hasattr(tool_result, "success") else False
            if hasattr(tool_result, "result") and tool_result.result:
                output = str(tool_result.result)
            else:
                output = "No output"
            if hasattr(tool_result, "error") and tool_result.error:
                error = tool_result.error
            else:
                error = "None"
            return cls.OBSERVATION_PROMPT.format(
                success=success,
                output=output,
                error=error,
            )

        output = "No tool executed"
        error = "None"

        return cls.OBSERVATION_PROMPT.format(
            success=success,
            output=output,
            error=error,
        )

    @classmethod
    def format_final_answer_prompt(cls, state: ReActState) -> str:
        """Format prompt for final answer"""
        return cls.FINAL_ANSWER_PROMPT.format(original_query=state.original_query)

    @classmethod
    def _format_tool_entry(cls, tool: Dict[str, Any]) -> str:
        """Render tool name, description, and parameter hints for the LLM."""
        name = tool.get("name", "(unknown)")
        desc = " ".join(str(tool.get("description", "")).split())
        params = cls._build_param_summary(tool.get("schema"))
        suffix = f" | params: {params}" if params else ""
        return f"- {name}: {desc}{suffix}"

    @classmethod
    def _build_param_summary(cls, schema: Optional[Dict[str, Any]]) -> str:
        """Summarize tool parameters from heterogeneous schema shapes."""
        params_schema = cls._extract_params_schema(schema)
        if not params_schema:
            return ""

        props = params_schema.get("properties")
        if not isinstance(props, dict) or not props:
            return ""

        required = set(params_schema.get("required") or [])
        summaries: List[str] = []

        for key, prop in props.items():
            summary = cls._summarize_property(key, prop, key in required)
            if summary:
                summaries.append(summary)

        return "; ".join(summaries)

    @staticmethod
    def _extract_params_schema(
        schema: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Locate the parameters schema regardless of nesting shape."""
        if not isinstance(schema, dict):
            return None

        function_block = schema.get("function")
        if isinstance(function_block, dict):
            params = function_block.get("parameters")
            if isinstance(params, dict):
                return params

        params = schema.get("parameters")
        return params if isinstance(params, dict) else None

    @staticmethod
    def _summarize_property(name: str, prop: Any, is_required: bool) -> Optional[str]:
        """Create a single property summary line."""
        if not isinstance(prop, dict):
            return None

        type_name = prop.get("type") or "any"
        flags = []
        if is_required:
            flags.append("required")
        if prop.get("default") is not None:
            flags.append(f"default={prop['default']}")

        meta = ", ".join([type_name] + flags) if flags else type_name
        desc = " ".join(str(prop.get("description", "")).split()).strip()
        return f"{name} [{meta}]" + (f": {desc}" if desc else "")

    @classmethod
    def get_step_prompt(
        cls,
        step_type: ReActStepType,
        state: ReActState,
        tool_result: Any = None,
        max_thought_cycles: int = 10,
    ) -> str:
        """Get prompt for specific step type"""
        if step_type == ReActStepType.THOUGHT:
            return cls.format_thought_prompt(state, max_thought_cycles)
        elif step_type == ReActStepType.ACTION:
            return cls.format_action_prompt()
        elif step_type == ReActStepType.OBSERVATION:
            return cls.format_observation_prompt(tool_result)
        elif step_type == ReActStepType.FINAL_ANSWER:
            return cls.format_final_answer_prompt(state)
        else:
            raise ValueError(f"Unknown step type: {step_type}")

    @staticmethod
    def _strip_leading_role_label(content: str) -> str:
        import re

        pattern = re.compile(
            r"^\s*(?:[-*>]\s*)?(?:\*{1,2}|__)?\s*"
            r"(Thought|Action|Observation|Final\s+Answer)"
            r"\s*:?\s*(?:\*{1,2}|__)?\s*",
            re.IGNORECASE,
        )
        match = pattern.match(content)
        if match:
            return content[match.end() :].lstrip()
        return content

    @classmethod
    def parse_response(cls, response: str) -> Dict[str, str]:
        """Parse ReAct response - handles both JSON and text responses"""
        import json

        # Clean up the response
        content = cls._strip_leading_role_label(response.strip())

        # Try to parse as JSON first (for action steps)
        if content.startswith("{") and content.endswith("}"):
            try:
                parsed_json = json.loads(content)
            except json.JSONDecodeError:
                parsed_json = None

            if isinstance(parsed_json, dict):
                if "action" in parsed_json:
                    return {
                        "thought": parsed_json.get("action", content),
                        "action": content,
                        "observation": parsed_json.get("action", content),
                        "final_answer": parsed_json.get("action", content),
                    }
                if "tool" in parsed_json:
                    return {
                        "thought": content,
                        "action": content,
                        "observation": content,
                        "final_answer": content,
                    }

        # Remove common prefixes if they exist
        prefixes_to_remove = [
            "Thought:",
            "Action:",
            "Observation:",
            "Final Answer:",
            "Your response should start with your analysis of the situation:",
            "Your action:",
            "Your observation:",
            "Your final answer:",
        ]

        for prefix in prefixes_to_remove:
            if content.startswith(prefix):
                content = content[len(prefix) :].strip()
                break

        # Return a dict with the content for all possible types
        return {
            "thought": content,
            "action": content,
            "observation": content,
            "final_answer": content,
        }

    @classmethod
    def format_planning_prompt(
        cls,
        query: str,
        available_tools: List[Dict[str, Any]],
        system_context: Optional[str] = None,
        current_date: Optional[str] = None,
    ) -> str:
        """Format upfront planning prompt with context awareness"""
        tools_section = "\n".join(
            cls._format_tool_entry(tool) for tool in available_tools
        )
        if not tools_section:
            tools_section = "- (no tools registered)"

        system_context_block = ""
        if system_context:
            system_context_block = "\n\nSystem Context:\n" + str(system_context).strip()

        return cls.PLANNING_PROMPT.format(
            query=query,
            tools_section=tools_section,
            current_date=current_date or "",
            system_context_block=system_context_block,
        )
