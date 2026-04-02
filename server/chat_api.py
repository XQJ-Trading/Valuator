from __future__ import annotations

import asyncio
import json
import signal
import sys
import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from .session_viewer_api import session_data_root

router = APIRouter(prefix="/api/chat", tags=["chat"])

CHAT_REL = Path("_chat") / "messages.json"
AGENT_ENTRYPOINT = (
    Path(__file__).resolve().parents[1] / "scripts" / "run_recursive_agent_query.py"
)
MAX_TEXT_LEN = 100_000

_lock = asyncio.Lock()
_subscribers: list[asyncio.Queue[dict]] = []
_agent_process: asyncio.subprocess.Process | None = None
_agent_lock = asyncio.Lock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _chat_file() -> Path:
    return session_data_root() / CHAT_REL


def _load_messages() -> list[dict]:
    path = _chat_file()
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        return []
    return data


def _save_messages(messages: list[dict]) -> None:
    path = _chat_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(messages, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def _broadcast(msg: dict) -> None:
    for q in list(_subscribers):
        q.put_nowait(msg)


async def _pipe_process_stream(
    stream: asyncio.StreamReader | None,
    target,
    *,
    prefix: str,
    on_line: Callable[[str], Coroutine[Any, Any, None]] | None = None,
) -> str:
    if stream is None:
        return ""
    chunks: list[str] = []
    while True:
        line = await stream.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="replace")
        chunks.append(text)
        target.write(f"{prefix}{text}")
        target.flush()
        if on_line is not None:
            await on_line(text)
    return "".join(chunks)


def _extract_final_text(stdout_text: str) -> str:
    marker = "\n[final]\n"
    if marker in stdout_text:
        return stdout_text.split(marker, maxsplit=1)[1].strip()
    return stdout_text.strip()


def _extract_error_text(stderr_text: str) -> str:
    lines = [line.strip() for line in stderr_text.splitlines() if line.strip()]
    if not lines:
        return "Agent execution failed."
    for line in reversed(lines):
        if line.startswith("error:"):
            return line.removeprefix("error:").strip() or "Agent execution failed."
    return lines[-1]


async def _append_and_broadcast_message(*, role: str, text: str) -> dict:
    msg = {
        "id": str(uuid.uuid4()),
        "role": role,
        "text": text,
        "ts": _utc_now_iso(),
    }
    async with _lock:
        messages = _load_messages()
        messages.append(msg)
        _save_messages(messages)
    await _broadcast(msg)
    return msg


async def _clear_and_broadcast_reset() -> dict:
    event = {"type": "reset", "ts": _utc_now_iso()}
    async with _lock:
        _save_messages([])
    await _broadcast(event)
    return event


async def _run_agent_for_message(text: str) -> None:
    global _agent_process

    _PROGRESS_PREFIXES = (
        "[step]",
        "[decision]",
        "[tool]",
        "[done]",
        "[failed]",
        "[decomposed]",
        "[step_invalid]",
        "[conflict]",
    )

    async def _on_stdout_line(line: str) -> None:
        stripped = line.rstrip("\n")
        if stripped.startswith(_PROGRESS_PREFIXES):
            await _broadcast({"type": "task_progress", "line": stripped})

    await _broadcast({"type": "agent_started", "ts": _utc_now_iso()})
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(AGENT_ENTRYPOINT),
            "--query",
            text,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        async with _agent_lock:
            _agent_process = process
        stdout_task = asyncio.create_task(
            _pipe_process_stream(
                process.stdout,
                sys.stdout,
                prefix="[chat-agent] ",
                on_line=_on_stdout_line,
            )
        )
        stderr_task = asyncio.create_task(
            _pipe_process_stream(process.stderr, sys.stderr, prefix="[chat-agent] ")
        )
        await process.wait()
        stdout_text, stderr_text = await asyncio.gather(stdout_task, stderr_task)
        stderr_text = stderr_text.strip()

        if process.returncode != 0:
            rc = process.returncode
            if isinstance(rc, int) and rc < 0:
                sig = -rc
                if sig in (signal.SIGTERM, signal.SIGINT, signal.SIGKILL):
                    await _append_and_broadcast_message(
                        role="assistant",
                        text="세션이 중지되었습니다.",
                    )
                    return
            error_text = _extract_error_text(stderr_text)
            if "QueryAnalysisPayload" in error_text:
                error_text = "질문 분석에 실패했습니다. 티커/기업명과 분석 목적을 조금 더 구체적으로 적어주세요."
            await _append_and_broadcast_message(role="assistant", text=error_text)
            return

        final_text = _extract_final_text(stdout_text)
        if not final_text:
            await _append_and_broadcast_message(
                role="assistant",
                text="Agent run completed, but no final output was produced.",
            )
            return
        await _append_and_broadcast_message(role="assistant", text=final_text)
    except Exception as exc:
        await _append_and_broadcast_message(
            role="assistant",
            text=f"에이전트 실행 중 오류가 발생했습니다: {exc}",
        )
    finally:
        async with _agent_lock:
            _agent_process = None
        await _broadcast({"type": "agent_finished", "ts": _utc_now_iso()})


class PostChatMessageRequest(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("text required")
        if len(stripped) > MAX_TEXT_LEN:
            raise ValueError("text too long")
        return stripped


@router.get("/messages")
async def get_messages():
    async with _lock:
        messages = _load_messages()
    return {"messages": messages}


@router.post("/messages")
async def post_message(body: PostChatMessageRequest):
    msg = await _append_and_broadcast_message(role="user", text=body.text)
    asyncio.create_task(_run_agent_for_message(body.text))
    return msg


async def _stop_running_agent() -> bool:
    async with _agent_lock:
        proc = _agent_process
    if proc is None or proc.returncode is not None:
        return False
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=8.0)
    except TimeoutError:
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=4.0)
        except (TimeoutError, ProcessLookupError):
            pass
    except ProcessLookupError:
        pass
    return True


@router.delete("/messages")
async def clear_messages():
    await _stop_running_agent()
    event = await _clear_and_broadcast_reset()
    return {"ok": True, **event}


@router.get("/agent-status")
async def agent_status():
    async with _agent_lock:
        proc = _agent_process
    running = proc is not None and proc.returncode is None
    return {"running": running}


@router.post("/stop")
async def stop_agent():
    stopped = await _stop_running_agent()
    return {"ok": True, "stopped": stopped}


@router.get("/stream")
async def stream():
    async def event_gen():
        queue: asyncio.Queue[dict] = asyncio.Queue()
        _subscribers.append(queue)
        try:
            yield ": connected\n\n"
            while True:
                msg = await queue.get()
                data = json.dumps(msg, ensure_ascii=False)
                yield f"data: {data}\n\n"
        finally:
            try:
                _subscribers.remove(queue)
            except ValueError:
                pass

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
