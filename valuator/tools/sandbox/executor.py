from __future__ import annotations

import contextlib
import io
import json
import os
import select
import signal
import time

from .protocol import SandboxRequest, SandboxResponse, dumps_message, loads_response

BASE_SAFE_BUILTINS = {
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
}


def fork_and_execute(
    request: SandboxRequest, preloaded: dict[str, object]
) -> SandboxResponse:
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        _run_child(request, preloaded, write_fd)

    os.close(write_fd)
    deadline = time.monotonic() + request.timeout
    chunks: list[bytes] = []
    status: int | None = None
    try:
        while status is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                os.kill(pid, signal.SIGKILL)
                _, status = os.waitpid(pid, 0)
                return SandboxResponse(
                    success=False,
                    output="",
                    execution_type="failed",
                    error=f"Code execution timed out after {request.timeout}s",
                )

            readable, _, _ = select.select([read_fd], [], [], min(0.05, remaining))
            if readable:
                chunk = os.read(read_fd, 65536)
                if chunk:
                    chunks.append(chunk)

            waited_pid, waited_status = os.waitpid(pid, os.WNOHANG)
            if waited_pid == pid:
                status = waited_status

        while True:
            chunk = os.read(read_fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(read_fd)

    if os.WIFSIGNALED(status):
        signal_number = os.WTERMSIG(status)
        return SandboxResponse(
            success=False,
            output="",
            execution_type="failed",
            error=f"Sandbox child terminated by signal {signal_number}",
        )

    raw = b"".join(chunks).decode("utf-8").strip()
    if not raw:
        return SandboxResponse(
            success=False,
            output="",
            execution_type="failed",
            error="Sandbox child returned no response",
        )

    try:
        return loads_response(raw.splitlines()[-1])
    except json.JSONDecodeError:
        return SandboxResponse(
            success=False,
            output="",
            execution_type="failed",
            error=f"Sandbox child returned invalid payload: {raw[:200]}",
        )


def _run_child(
    request: SandboxRequest,
    preloaded: dict[str, object],
    write_fd: int,
) -> None:
    try:
        response = _execute_request(request, preloaded)
        os.write(write_fd, dumps_message(response).encode("utf-8"))
    finally:
        os.close(write_fd)
        os._exit(0)


def _execute_request(
    request: SandboxRequest,
    preloaded: dict[str, object],
) -> SandboxResponse:
    def _handle_alarm(_signum: int, _frame: object) -> None:
        raise TimeoutError(f"Code execution timed out after {request.timeout}s")

    payload = {
        "success": True,
        "output": "",
        "execution_type": "exec",
        "error": "",
    }
    buffer = io.StringIO()
    namespace = {"__builtins__": _safe_builtins(preloaded), **preloaded}
    previous_handler = signal.signal(signal.SIGALRM, _handle_alarm)
    signal.alarm(request.timeout)
    try:
        with contextlib.redirect_stdout(buffer):
            try:
                compiled = compile(request.code, "<valuator_code>", "eval")
            except SyntaxError:
                compiled = compile(request.code, "<valuator_code>", "exec")
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
        payload["error"] = _format_error(exc, request.code)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)

    return SandboxResponse(
        success=bool(payload["success"]),
        output=str(payload["output"]),
        execution_type=str(payload["execution_type"]),
        error=str(payload["error"]),
    )


def _safe_builtins(preloaded: dict[str, object]) -> dict[str, object]:
    builtins = dict(BASE_SAFE_BUILTINS)
    builtins["__import__"] = _safe_import(preloaded)
    return builtins


def _safe_import(preloaded: dict[str, object]):
    allowed_modules = {
        name: module
        for name, module in preloaded.items()
        if name in {"json", "math", "statistics", "numpy", "pandas", "scipy"}
    }

    def _import(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        del globals, locals, fromlist
        if level != 0:
            raise ImportError("Relative imports are blocked")

        root = name.split(".", 1)[0]
        module = allowed_modules.get(root)
        if module is None:
            raise ImportError(f"Import blocked: {name}")
        return module

    return _import


def _format_error(exc: Exception, source: str) -> str:
    if not isinstance(exc, SyntaxError):
        return str(exc)

    message = exc.msg or str(exc)
    if " (detected at line " in message:
        message = message.split(" (detected at line ", 1)[0]
    if exc.lineno is None:
        return message

    lines = source.splitlines()
    line_text = lines[exc.lineno - 1] if 0 < exc.lineno <= len(lines) else ""
    offset = max((exc.offset or 1) - 1, 0)
    caret_line = " " * offset + "^"
    return (
        f"{message} at line {exc.lineno}\n"
        f"{line_text}\n"
        f"{caret_line}"
    )
