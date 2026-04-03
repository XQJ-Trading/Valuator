from __future__ import annotations

import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SandboxRequest:
    code: str
    timeout: int


@dataclass(frozen=True)
class SandboxResponse:
    success: bool
    output: str
    execution_type: str
    error: str


@dataclass(frozen=True)
class ReadySignal:
    ready: bool
    preloaded: tuple[str, ...] = ()


def dumps_message(
    message: SandboxRequest | SandboxResponse | ReadySignal,
) -> str:
    return json.dumps(asdict(message), ensure_ascii=False) + "\n"


def loads_request(line: str) -> SandboxRequest:
    payload = json.loads(line)
    return SandboxRequest(
        code=str(payload["code"]),
        timeout=int(payload["timeout"]),
    )


def loads_response(line: str) -> SandboxResponse:
    payload = json.loads(line)
    return SandboxResponse(
        success=bool(payload["success"]),
        output=str(payload.get("output", "")),
        execution_type=str(payload.get("execution_type", "failed")),
        error=str(payload.get("error", "")),
    )


def loads_ready_signal(line: str) -> ReadySignal:
    payload = json.loads(line)
    preloaded = payload.get("preloaded", ())
    return ReadySignal(
        ready=bool(payload.get("ready", False)),
        preloaded=tuple(str(item) for item in preloaded),
    )
