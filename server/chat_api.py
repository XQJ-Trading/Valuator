from __future__ import annotations

import asyncio
import json
import signal
import sys
import uuid
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from valuator.tools.web_search_providers import available_web_search_providers
from valuator.utils.config import WEB_SEARCH_PROVIDER_NAMES
from valuator.utils.time_utils import kst_isoformat

from .auth import register_session
from .session_viewer_api import session_data_root

router = APIRouter(prefix="/api/chat", tags=["chat"])

CHAT_REL = Path("_chat")
AGENT_ENTRYPOINT = (
    Path(__file__).resolve().parents[1] / "scripts" / "run_recursive_agent_query.py"
)
MAX_TEXT_LEN = 100_000

_lock = asyncio.Lock()
_subscribers_by_session: dict[str, list[asyncio.Queue[dict]]] = {}
_agent_processes: dict[str, asyncio.subprocess.Process] = {}
_agent_tasks: dict[str, asyncio.Task[None]] = {}
_agent_lock = asyncio.Lock()


def _kst_now_iso() -> str:
    return kst_isoformat()


def _chat_file(session_id: str) -> Path:
    return session_data_root() / CHAT_REL / session_id / "messages.json"


def _load_messages(session_id: str) -> list[dict]:
    path = _chat_file(session_id)
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        return []
    return data


def _save_messages(session_id: str, messages: list[dict]) -> None:
    path = _chat_file(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(messages, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def _broadcast(session_id: str, msg: dict) -> None:
    for q in list(_subscribers_by_session.get(session_id, [])):
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


async def _append_and_broadcast_message(*, session_id: str, role: str, text: str) -> dict:
    msg = {
        "id": str(uuid.uuid4()),
        "role": role,
        "text": text,
        "ts": _kst_now_iso(),
    }
    async with _lock:
        messages = _load_messages(session_id)
        messages.append(msg)
        _save_messages(session_id, messages)
    await _broadcast(session_id, msg)
    return msg


async def _clear_and_broadcast_reset(session_id: str) -> dict:
    event = {"type": "reset", "ts": _kst_now_iso()}
    async with _lock:
        _save_messages(session_id, [])
    await _broadcast(session_id, event)
    return event


async def _run_agent_for_message(
    session_id: str,
    text: str,
    web_search_provider: str | None = None,
) -> None:
    process: asyncio.subprocess.Process | None = None

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
            await _broadcast(session_id, {"type": "task_progress", "line": stripped})

    await _broadcast(session_id, {"type": "agent_started", "ts": _kst_now_iso()})
    try:
        command = [
            sys.executable,
            str(AGENT_ENTRYPOINT),
            "--query",
            text,
        ]
        if web_search_provider:
            command.extend(["--web-search-provider", web_search_provider])
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        async with _agent_lock:
            _agent_processes[session_id] = process
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
                        session_id=session_id,
                        role="assistant",
                        text="세션이 중지되었습니다.",
                    )
                    return
            error_text = _extract_error_text(stderr_text)
            if "QueryAnalysisPayload" in error_text:
                error_text = "질문 분석에 실패했습니다. 티커/기업명과 분석 목적을 조금 더 구체적으로 적어주세요."
            await _append_and_broadcast_message(
                session_id=session_id,
                role="assistant",
                text=error_text,
            )
            return

        final_text = _extract_final_text(stdout_text)
        if not final_text:
            await _append_and_broadcast_message(
                session_id=session_id,
                role="assistant",
                text="Agent run completed, but no final output was produced.",
            )
            return
        await _append_and_broadcast_message(
            session_id=session_id,
            role="assistant",
            text=final_text,
        )
    except asyncio.CancelledError:
        if process is None:
            await _append_and_broadcast_message(
                session_id=session_id,
                role="assistant",
                text="세션이 중지되었습니다.",
            )
        raise
    except Exception as exc:
        await _append_and_broadcast_message(
            session_id=session_id,
            role="assistant",
            text=f"에이전트 실행 중 오류가 발생했습니다: {exc}",
        )
    finally:
        current_task = asyncio.current_task()
        async with _agent_lock:
            if _agent_processes.get(session_id) is process:
                _agent_processes.pop(session_id, None)
            if current_task is not None and _agent_tasks.get(session_id) is current_task:
                _agent_tasks.pop(session_id, None)
        await _broadcast(session_id, {"type": "agent_finished", "ts": _kst_now_iso()})


class PostChatMessageRequest(BaseModel):
    text: str
    web_search_provider: str | None = None

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("text required")
        if len(stripped) > MAX_TEXT_LEN:
            raise ValueError("text too long")
        return stripped

    @field_validator("web_search_provider")
    @classmethod
    def validate_web_search_provider(cls, value: str | None) -> str | None:
        if value is None:
            return None
        selected = value.strip().lower()
        if not selected:
            return None
        if selected not in WEB_SEARCH_PROVIDER_NAMES:
            allowed = ", ".join(WEB_SEARCH_PROVIDER_NAMES)
            raise ValueError(f"web_search_provider must be one of: {allowed}")
        return selected


@router.get("/messages")
async def get_messages(session_id: uuid.UUID):
    session_key = str(session_id)
    async with _lock:
        messages = _load_messages(session_key)
    return {"messages": messages}


@router.post("/messages")
async def post_message(body: PostChatMessageRequest, session_id: uuid.UUID):
    session_key = str(session_id)
    async with _agent_lock:
        if session_key in _agent_tasks and not _agent_tasks[session_key].done():
            raise HTTPException(status_code=409, detail="agent already running")
        msg = await _append_and_broadcast_message(
            session_id=session_key,
            role="user",
            text=body.text,
        )
        _agent_tasks[session_key] = asyncio.create_task(
            _run_agent_for_message(
                session_key,
                body.text,
                body.web_search_provider,
            )
        )
    return msg


@router.get("/web-search-providers")
async def get_web_search_providers() -> dict[str, object]:
    return {
        "available": available_web_search_providers(),
    }


async def _stop_running_agent(session_id: str) -> bool:
    async with _agent_lock:
        task = _agent_tasks.get(session_id)
        proc = _agent_processes.get(session_id)
    if task is None or task.done():
        return False
    if proc is None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return True
    if proc.returncode is not None:
        return False
    proc.terminate()
    try:
        await asyncio.wait_for(task, timeout=8.0)
    except TimeoutError:
        proc.kill()
        try:
            await asyncio.wait_for(task, timeout=4.0)
        except (TimeoutError, ProcessLookupError, asyncio.CancelledError):
            pass
    except (ProcessLookupError, asyncio.CancelledError):
        pass
    return True


@router.delete("/messages")
async def clear_messages(session_id: uuid.UUID):
    session_key = str(session_id)
    await _stop_running_agent(session_key)
    event = await _clear_and_broadcast_reset(session_key)
    return {"ok": True, **event}


@router.get("/agent-status")
async def agent_status(session_id: uuid.UUID):
    session_key = str(session_id)
    async with _agent_lock:
        task = _agent_tasks.get(session_key)
    running = task is not None and not task.done()
    return {"running": running}


@router.post("/stop")
async def stop_agent(session_id: uuid.UUID):
    stopped = await _stop_running_agent(str(session_id))
    return {"ok": True, "stopped": stopped}


@router.get("/stream")
async def stream(session_id: uuid.UUID):
    session_key = str(session_id)

    async def event_gen():
        queue: asyncio.Queue[dict] = asyncio.Queue()
        _subscribers_by_session.setdefault(session_key, []).append(queue)
        try:
            yield ": connected\n\n"
            while True:
                msg = await queue.get()
                data = json.dumps(msg, ensure_ascii=False)
                yield f"data: {data}\n\n"
        finally:
            try:
                subscribers = _subscribers_by_session.get(session_key)
                if subscribers is not None:
                    subscribers.remove(queue)
                    if not subscribers:
                        _subscribers_by_session.pop(session_key, None)
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


@router.post("/authenticate")
async def authenticate_session(session_id: uuid.UUID) -> dict:
    """Authenticate a session_id for SSE/stream access using key+secret in headers."""
    register_session(str(session_id))
    return {"ok": True}
