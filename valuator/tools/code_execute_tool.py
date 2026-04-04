"""Code execution tool with a persistent fork-based sandbox server."""

from __future__ import annotations

import asyncio
import select
import subprocess
import sys
import threading
import time

from ..utils.config import config
from .base import ReActBaseTool, ToolResult
from .sandbox.protocol import (
    SandboxRequest,
    SandboxResponse,
    dumps_message,
    loads_ready_signal,
    loads_response,
)

SANDBOX_STARTUP_TIMEOUT_SECONDS = 10.0


class ExecuteCodeTool(ReActBaseTool):
    def __init__(self):
        super().__init__(
            name="code_execute_tool",
            description=(
                "Execute restricted Python code in an isolated subprocess. "
                "Useful for deterministic calculations and small data transforms."
            ),
        )
        self._client: _SandboxClient | None = None
        self._client_lock = threading.Lock()

    async def _execute_impl(
        self, code: str, timeout: int | None = None, language: str | None = None
    ) -> ToolResult:
        timeout_value = self._resolve_timeout(timeout)
        if language and language.lower() != "python":
            return ToolResult(
                success=False, result=None, error="Only Python is supported"
            )

        normalized_code = self._normalize_code(code)
        if not normalized_code:
            return ToolResult(success=False, result=None, error="'code' is required")

        metadata = self._base_metadata(timeout=timeout_value)
        request = SandboxRequest(code=normalized_code, timeout=timeout_value)

        try:
            response = await asyncio.to_thread(self._execute_request, request)
        except _SandboxClientError as exc:
            return ToolResult(
                success=False,
                result=self._failed_payload(normalized_code),
                error=f"Code execution failed: {exc}",
                metadata=metadata,
            )

        return self._response_to_tool_result(response, normalized_code, metadata)

    def close(self) -> None:
        self._reset_client()

    def warm_up(self) -> None:
        self._ensure_client()

    def _execute_request(self, request: SandboxRequest) -> SandboxResponse:
        client = self._ensure_client()
        try:
            return client.execute(request)
        except _SandboxClientError as exc:
            if exc.request_sent:
                raise
            self._reset_client()
            return self._ensure_client().execute(request)

    def _ensure_client(self) -> "_SandboxClient":
        with self._client_lock:
            if self._client is not None and self._client.alive:
                return self._client

            if self._client is not None:
                self._client.close()

            client = _SandboxClient()
            client.spawn()
            self._client = client
            return client

    def _reset_client(self) -> None:
        with self._client_lock:
            if self._client is not None:
                self._client.close()
                self._client = None

    @staticmethod
    def _normalize_code(code: str) -> str:
        text = (code or "").strip()
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
            timeout = int(getattr(config, "code_execution_timeout", 3) or 3)
        return max(int(timeout), 1)

    @staticmethod
    def _response_to_tool_result(
        response: SandboxResponse,
        code: str,
        metadata: dict[str, object],
    ) -> ToolResult:
        if not response.success:
            error = response.error or "unknown error"
            if error.startswith("Code execution timed out after "):
                message = error
            else:
                message = f"Code execution error: {error}"
            return ToolResult(
                success=False,
                result={
                    "output": response.output,
                    "code": code,
                    "execution_type": "failed",
                },
                error=message,
                metadata=metadata,
            )

        return ToolResult(
            success=True,
            result={
                "findings": response.output,
                "output": response.output,
                "code": code,
                "execution_type": response.execution_type,
            },
            metadata=metadata,
        )

    @staticmethod
    def _failed_payload(code: str) -> dict[str, str]:
        return {"output": "", "code": code, "execution_type": "failed"}

    @staticmethod
    def _base_metadata(*, timeout: int) -> dict[str, object]:
        return {
            "timeout": timeout,
            "safe_mode": True,
            "isolation": "fork_server",
        }


class _SandboxClient:
    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def spawn(self) -> None:
        if self.alive:
            return

        self.close()
        self.process = subprocess.Popen(
            [sys.executable, "-m", "valuator.tools.sandbox.server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        try:
            line = self._read_ready_line(SANDBOX_STARTUP_TIMEOUT_SECONDS)
            if not line:
                raise _SandboxClientError(self._startup_error())

            signal = loads_ready_signal(line)
            if not signal.ready:
                raise _SandboxClientError("sandbox server did not become ready")
        except Exception:
            self.close()
            raise

    def execute(self, request: SandboxRequest) -> SandboxResponse:
        with self._lock:
            if not self.alive or self.process is None:
                raise _SandboxClientError(
                    "sandbox server is not running",
                    request_sent=False,
                )

            stdin = self.process.stdin
            stdout = self.process.stdout
            if stdin is None or stdout is None:
                raise _SandboxClientError(
                    "sandbox server pipes are unavailable",
                    request_sent=False,
                )

            try:
                stdin.write(dumps_message(request))
                stdin.flush()
            except BrokenPipeError as exc:
                raise _SandboxClientError(
                    "sandbox server stdin is closed",
                    request_sent=False,
                ) from exc

            line = stdout.readline()
            if not line:
                raise _SandboxClientError(
                    "sandbox server disconnected",
                    request_sent=True,
                )

            try:
                return loads_response(line)
            except Exception as exc:
                raise _SandboxClientError(
                    f"sandbox server returned invalid response: {line[:200]}",
                    request_sent=True,
                ) from exc

    def close(self) -> None:
        if self.process is None:
            return

        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)

        for stream_name in ("stdin", "stdout", "stderr"):
            stream = getattr(self.process, stream_name)
            if stream is not None:
                stream.close()

        self.process = None

    def _startup_error(self) -> str:
        if self.process is None:
            return "sandbox server failed to start"
        stderr = ""
        if self.process.stderr is not None:
            stderr = self.process.stderr.read().strip()
        return stderr or "sandbox server exited before ready signal"

    def _read_ready_line(self, timeout_seconds: float) -> str:
        if self.process is None or self.process.stdout is None:
            raise _SandboxClientError("sandbox server stdout is unavailable")

        stdout = self.process.stdout
        deadline = time.monotonic() + timeout_seconds
        while True:
            if self.process.poll() is not None:
                return ""

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _SandboxClientError(
                    f"sandbox server startup timed out after {timeout_seconds:.0f}s"
                )

            readable, _, _ = select.select(
                [stdout.fileno()],
                [],
                [],
                min(0.05, remaining),
            )
            if readable:
                return stdout.readline()


class _SandboxClientError(RuntimeError):
    def __init__(self, message: str, *, request_sent: bool = False):
        super().__init__(message)
        self.request_sent = request_sent
