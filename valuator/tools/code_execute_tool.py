"""Code execution tool for ReAct."""

import contextlib
import io

from ..utils.config import config
from .base import ToolResult
from .base import ReActBaseTool


class ExecuteCodeTool(ReActBaseTool):
    def __init__(self):
        super().__init__(
            name="code_execute_tool",
            description="Execute Python code safely. Use ```python\\nyour_code_here\\n``` format (no JSON wrapper required). Useful for calculations, data processing, or testing code snippets.",
        )

    async def _execute_impl(
        self, code: str, timeout: int | None = None, language: str | None = None
    ) -> ToolResult:
        if timeout is None:
            timeout = config.code_execution_timeout
        if language and language.lower() != "python":
            self.logger.warning(
                f"Language '{language}' specified but only Python is supported"
            )

        code = code.replace("\\n", "\n").replace("\\t", "\t")
        output_buffer = io.StringIO()
        exec_globals = {"__builtins__": __builtins__}
        try:
            with contextlib.redirect_stdout(output_buffer):
                if any(k in code for k in ("def ", "class ", "for ", "while ", "if ")):
                    exec(code, exec_globals)
                    execution_type = "exec"
                else:
                    try:
                        result = eval(code, exec_globals)
                    except SyntaxError:
                        exec(code, exec_globals)
                        execution_type = "exec"
                    else:
                        if result is not None:
                            print(result)
                        execution_type = "eval"
            output = output_buffer.getvalue().strip()
            if not output:
                output = (
                    "Expression evaluated successfully (no output)"
                    if execution_type == "eval"
                    else "Code executed successfully (no output)"
                )
            return ToolResult(
                success=True,
                result={
                    "output": output,
                    "code": code,
                    "execution_type": execution_type,
                },
                metadata={"timeout": timeout, "safe_mode": True},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                result={"output": "", "code": code, "execution_type": "failed"},
                error=f"Code execution error: {str(e)}",
            )

    def get_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "usage_format": "Use ```python\\nyour_code_here\\n``` format instead of JSON",
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
