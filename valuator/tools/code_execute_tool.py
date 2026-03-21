"""Code execution tool with subprocess isolation."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from textwrap import dedent

from ..utils.config import config
from .base import ReActBaseTool, ToolResult

_HARNESS = dedent(
    """
    import contextlib
    import io
    import json
    import builtins
    import sys

    ALLOWED_IMPORTS = set(json.loads(sys.argv[2]))
    SOURCE = sys.argv[1]

    def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split('.', 1)[0]
        if root not in ALLOWED_IMPORTS:
            raise ImportError(f"Import blocked: {name}")
        return builtins.__import__(name, globals, locals, fromlist, level)

    SAFE_BUILTINS = {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "filter": filter,
        "float": float,
        "int": int,
        "len": len,
        "list": list,
        "map": map,
        "max": max,
        "min": min,
        "pow": pow,
        "print": print,
        "range": range,
        "repr": repr,
        "reversed": reversed,
        "round": round,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
        "__import__": _safe_import,
    }

    payload = {
        "success": True,
        "output": "",
        "execution_type": "exec",
        "error": "",
    }

    buffer = io.StringIO()
    namespace = {"__builtins__": SAFE_BUILTINS}
    try:
        with contextlib.redirect_stdout(buffer):
            try:
                compiled = compile(SOURCE, "<valuator_code>", "eval")
            except SyntaxError:
                compiled = compile(SOURCE, "<valuator_code>", "exec")
                exec(compiled, namespace, namespace)
                payload["execution_type"] = "exec"
            else:
                result = eval(compiled, namespace, namespace)
                payload["execution_type"] = "eval"
                if result is not None:
                    print(result)
        payload["output"] = buffer.getvalue().strip() or (
            "Expression evaluated successfully (no output)"
            if payload["execution_type"] == "eval"
            else "Code executed successfully (no output)"
        )
    except Exception as exc:
        payload["success"] = False
        payload["execution_type"] = "failed"
        payload["error"] = str(exc)

    print(json.dumps(payload, ensure_ascii=False))
    """
).strip()


class ExecuteCodeTool(ReActBaseTool):
    def __init__(self):
        super().__init__(
            name="code_execute_tool",
            description=(
                "Execute restricted Python code in an isolated subprocess. "
                "Useful for deterministic calculations and small data transforms."
            ),
        )

    async def _execute_impl(
        self, code: str, timeout: int | None = None, language: str | None = None
    ) -> ToolResult:
        timeout_value = self._resolve_timeout(timeout)
        if language and language.lower() != "python":
            return ToolResult(success=False, result=None, error="Only Python is supported")

        normalized_code = self._normalize_code(code)
        if not normalized_code:
            return ToolResult(success=False, result=None, error="'code' is required")

        allowed_imports = self._allowed_imports()
        metadata = self._base_metadata(
            timeout=timeout_value,
            allowed_imports=allowed_imports,
        )

        try:
            completed = self._run_subprocess(
                code=normalized_code,
                timeout=timeout_value,
                allowed_imports=allowed_imports,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                result=self._failed_payload(normalized_code),
                error=f"Code execution timed out after {timeout_value}s",
                metadata=metadata,
            )

        output = _SubprocessOutput.from_completed(completed)
        if not output.stdout:
            return ToolResult(
                success=False,
                result=self._failed_payload(normalized_code),
                error=f"Code execution failed: {output.stderr or 'no output'}",
                metadata=metadata,
            )

        try:
            payload = self._parse_payload(output.stdout)
        except json.JSONDecodeError:
            return ToolResult(
                success=False,
                result=self._failed_payload(normalized_code),
                error=f"Code execution returned invalid payload: {output.stdout[:200]}",
                metadata=metadata,
            )

        if not payload.get("success"):
            return ToolResult(
                success=False,
                result={
                    "output": payload.get("output", ""),
                    "code": normalized_code,
                    "execution_type": "failed",
                },
                error=f"Code execution error: {payload.get('error', 'unknown error')}",
                metadata=metadata,
            )

        return ToolResult(
            success=True,
            result={
                "findings": payload.get("output", ""),
                "output": payload.get("output", ""),
                "code": normalized_code,
                "execution_type": payload.get("execution_type", "exec"),
            },
            metadata=metadata,
        )

    def get_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Execution timeout in seconds",
                        "default": 10,
                    },
                },
                "required": ["code"],
            },
        }

    @staticmethod
    def _normalize_code(code: str) -> str:
        text = (code or "").replace("\\n", "\n").replace("\\t", "\t").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        if text.startswith("python\n"):
            text = text[len("python\n") :]
        return text.strip()

    @staticmethod
    def _resolve_timeout(timeout: int | None) -> int:
        if timeout is None:
            timeout = int(getattr(config, "code_execution_timeout", 10) or 10)
        return max(int(timeout), 1)

    @staticmethod
    def _allowed_imports() -> list[str]:
        imports = getattr(config, "code_execution_allowed_imports", ()) or ()
        return list(imports)

    @staticmethod
    def _build_command(*, code: str, allowed_imports: list[str]) -> list[str]:
        return [
            sys.executable,
            "-I",
            "-S",
            "-c",
            _HARNESS,
            code,
            json.dumps(allowed_imports),
        ]

    def _run_subprocess(
        self,
        *,
        code: str,
        timeout: int,
        allowed_imports: list[str],
    ) -> subprocess.CompletedProcess[str]:
        cmd = self._build_command(code=code, allowed_imports=allowed_imports)
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    @staticmethod
    def _parse_payload(stdout: str) -> dict[str, object]:
        return json.loads(stdout.splitlines()[-1])

    @staticmethod
    def _failed_payload(code: str) -> dict[str, str]:
        return {"output": "", "code": code, "execution_type": "failed"}

    @staticmethod
    def _base_metadata(*, timeout: int, allowed_imports: list[str]) -> dict[str, object]:
        return {
            "timeout": timeout,
            "safe_mode": True,
            "isolation": "subprocess",
            "allowed_imports": allowed_imports,
        }


@dataclass(frozen=True)
class _SubprocessOutput:
    stdout: str
    stderr: str

    @classmethod
    def from_completed(cls, completed: subprocess.CompletedProcess[str]) -> "_SubprocessOutput":
        return cls(
            stdout=(completed.stdout or "").strip(),
            stderr=(completed.stderr or "").strip(),
        )
