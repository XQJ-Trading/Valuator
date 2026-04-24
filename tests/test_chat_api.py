from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import chat_api
from server import auth as auth_module
from server.main import create_app


class _FakeProcess:
    def __init__(self, release: asyncio.Event) -> None:
        self.stdout = None
        self.stderr = None
        self.returncode: int | None = None
        self._release = release

    async def wait(self) -> int:
        await self._release.wait()
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0
        self._release.set()

    def kill(self) -> None:
        self.returncode = -9
        self._release.set()


@pytest.fixture(autouse=True)
def _reset_chat_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SESSION_DATA_ROOT", str(tmp_path / "session"))
    monkeypatch.setenv("GUIDE_DATA_ROOT", str(tmp_path / "guide"))
    monkeypatch.setattr(auth_module, "_KEY", "")
    monkeypatch.setattr(auth_module, "_SECRET", "")
    auth_module._authenticated_sessions.clear()
    chat_api._subscribers_by_session.clear()
    chat_api._agent_processes.clear()
    chat_api._agent_tasks.clear()
    yield
    for task in list(chat_api._agent_tasks.values()):
        if not task.done():
            task.cancel()
    chat_api._subscribers_by_session.clear()
    chat_api._agent_processes.clear()
    chat_api._agent_tasks.clear()
    auth_module._authenticated_sessions.clear()


def _wait_until(predicate, *, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met before timeout")


def _chat_params(session_id: str) -> dict[str, str]:
    return {"session_id": session_id}


def test_web_search_providers_endpoint_returns_available_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chat_api, "available_web_search_providers", lambda: ["perplexity"])

    with TestClient(create_app()) as client:
        response = client.get("/api/chat/web-search-providers")

    assert response.status_code == 200
    assert response.json() == {
        "available": ["perplexity"],
    }


def test_post_message_passes_web_search_provider_to_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = str(uuid.uuid4())
    commands: list[tuple[object, ...]] = []
    release = asyncio.Event()
    release.set()

    async def _fake_create_subprocess_exec(*args, **kwargs):
        del kwargs
        commands.append(args)
        return _FakeProcess(release)

    monkeypatch.setattr(
        chat_api.asyncio,
        "create_subprocess_exec",
        _fake_create_subprocess_exec,
    )

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/chat/messages",
            params=_chat_params(session_id),
            json={"text": "hello", "web_search_provider": "tavily"},
        )
        assert response.status_code == 200
        _wait_until(lambda: bool(commands))

    assert commands[0][:6] == (
        sys.executable,
        str(chat_api.AGENT_ENTRYPOINT),
        "--query",
        "hello",
        "--web-search-provider",
        "tavily",
    )


def test_post_message_passes_model_and_openrouter_env_to_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = str(uuid.uuid4())
    commands: list[tuple[tuple[object, ...], dict[str, object]]] = []
    release = asyncio.Event()
    release.set()

    async def _fake_create_subprocess_exec(*args, **kwargs):
        commands.append((args, kwargs))
        return _FakeProcess(release)

    monkeypatch.setattr(
        chat_api.asyncio,
        "create_subprocess_exec",
        _fake_create_subprocess_exec,
    )

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/chat/messages",
            params=_chat_params(session_id),
            json={
                "text": "hello",
                "llm_backend": "openrouter",
                "model": "google/gemini-2.5-flash",
                "openrouter_api_key": "or-key",
                "openrouter_base_url": "https://openrouter.ai/api/v1",
            },
        )
        assert response.status_code == 200
        _wait_until(lambda: bool(commands))

    args, kwargs = commands[0]
    assert args[:6] == (
        sys.executable,
        str(chat_api.AGENT_ENTRYPOINT),
        "--query",
        "hello",
        "--model",
        "google/gemini-2.5-flash",
    )
    env = kwargs["env"]
    assert isinstance(env, dict)
    assert env["LLM_BACKEND"] == "openrouter"
    assert env["OPENROUTER_API_KEY"] == "or-key"
    assert env["OPENROUTER_BASE_URL"] == "https://openrouter.ai/api/v1"


def test_post_message_rejects_openrouter_model_without_key() -> None:
    session_id = str(uuid.uuid4())

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/chat/messages",
            params=_chat_params(session_id),
            json={
                "text": "hello",
                "llm_backend": "openrouter",
                "model": "google/gemini-2.5-flash",
            },
        )

    assert response.status_code == 422
    assert "OPENROUTER_API_KEY in the server environment" in response.text


def test_post_message_openrouter_uses_env_key_when_request_omits_openrouter_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = str(uuid.uuid4())
    commands: list[tuple[tuple[object, ...], dict[str, object]]] = []
    release = asyncio.Event()
    release.set()

    async def _fake_create_subprocess_exec(*args, **kwargs):
        commands.append((args, kwargs))
        return _FakeProcess(release)

    monkeypatch.setattr(
        chat_api.asyncio,
        "create_subprocess_exec",
        _fake_create_subprocess_exec,
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-or-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://example.com/v1")

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/chat/messages",
            params=_chat_params(session_id),
            json={
                "text": "hello",
                "llm_backend": "openrouter",
                "model": "google/gemini-2.5-flash",
            },
        )
        assert response.status_code == 200
        _wait_until(lambda: bool(commands))

    _, kwargs = commands[0]
    env = kwargs["env"]
    assert isinstance(env, dict)
    assert env["OPENROUTER_API_KEY"] == "env-or-key"
    assert env["OPENROUTER_BASE_URL"] == "https://example.com/v1"


def test_post_message_forces_google_backend_when_openrouter_not_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = str(uuid.uuid4())
    commands: list[tuple[tuple[object, ...], dict[str, object]]] = []
    release = asyncio.Event()
    release.set()

    async def _fake_create_subprocess_exec(*args, **kwargs):
        commands.append((args, kwargs))
        return _FakeProcess(release)

    monkeypatch.setattr(
        chat_api.asyncio,
        "create_subprocess_exec",
        _fake_create_subprocess_exec,
    )
    monkeypatch.setenv("LLM_BACKEND", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "server-key")

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/chat/messages",
            params=_chat_params(session_id),
            json={
                "text": "hello",
                "llm_backend": "google_genai",
                "model": "gemini-3-flash-preview",
            },
        )
        assert response.status_code == 200
        _wait_until(lambda: bool(commands))

    _, kwargs = commands[0]
    env = kwargs["env"]
    assert isinstance(env, dict)
    assert env["LLM_BACKEND"] == "google_genai"
    assert "OPENROUTER_API_KEY" not in env


def test_post_message_rejects_openrouter_model_for_google_backend() -> None:
    session_id = str(uuid.uuid4())

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/chat/messages",
            params=_chat_params(session_id),
            json={
                "text": "hello",
                "llm_backend": "google_genai",
                "model": "openrouter/auto",
            },
        )

    assert response.status_code == 422
    assert "google_genai backend does not accept provider/model format" in response.text


def test_post_message_rejects_while_starting_and_stop_cancels_pending_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = str(uuid.uuid4())

    async def _slow_create_subprocess_exec(*args, **kwargs):
        del args, kwargs
        await asyncio.sleep(60)
        raise AssertionError("pending run should have been cancelled before spawn")

    monkeypatch.setattr(
        chat_api.asyncio,
        "create_subprocess_exec",
        _slow_create_subprocess_exec,
    )

    with TestClient(create_app()) as client:
        first = client.post(
            "/api/chat/messages",
            params=_chat_params(session_id),
            json={"text": "first message"},
        )
        assert first.status_code == 200
        assert (
            client.get("/api/chat/agent-status", params=_chat_params(session_id)).json()
            == {"running": True}
        )

        second = client.post(
            "/api/chat/messages",
            params=_chat_params(session_id),
            json={"text": "second message"},
        )
        assert second.status_code == 409
        assert second.json() == {"detail": "agent already running"}

        stop = client.post("/api/chat/stop", params=_chat_params(session_id))
        assert stop.status_code == 200
        assert stop.json() == {"ok": True, "stopped": True}

        _wait_until(
            lambda: client.get(
                "/api/chat/agent-status",
                params=_chat_params(session_id),
            ).json()
            == {"running": False}
        )
        messages = client.get(
            "/api/chat/messages",
            params=_chat_params(session_id),
        ).json()["messages"]

    assert [msg["role"] for msg in messages] == ["user", "assistant"]
    assert [msg["text"] for msg in messages] == [
        "first message",
        "세션이 중지되었습니다.",
    ]


def test_sessions_are_isolated_for_messages_status_and_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_session_id = str(uuid.uuid4())
    second_session_id = str(uuid.uuid4())

    async def _slow_create_subprocess_exec(*args, **kwargs):
        del args, kwargs
        await asyncio.sleep(60)
        raise AssertionError("pending run should have been cancelled before spawn")

    monkeypatch.setattr(
        chat_api.asyncio,
        "create_subprocess_exec",
        _slow_create_subprocess_exec,
    )

    with TestClient(create_app()) as client:
        first = client.post(
            "/api/chat/messages",
            params=_chat_params(first_session_id),
            json={"text": "first session"},
        )
        second = client.post(
            "/api/chat/messages",
            params=_chat_params(second_session_id),
            json={"text": "second session"},
        )
        assert first.status_code == 200
        assert second.status_code == 200

        assert (
            client.get(
                "/api/chat/agent-status",
                params=_chat_params(first_session_id),
            ).json()
            == {"running": True}
        )
        assert (
            client.get(
                "/api/chat/agent-status",
                params=_chat_params(second_session_id),
            ).json()
            == {"running": True}
        )

        stop_first = client.post("/api/chat/stop", params=_chat_params(first_session_id))
        assert stop_first.status_code == 200
        assert stop_first.json() == {"ok": True, "stopped": True}

        _wait_until(
            lambda: client.get(
                "/api/chat/agent-status",
                params=_chat_params(first_session_id),
            ).json()
            == {"running": False}
        )
        assert (
            client.get(
                "/api/chat/agent-status",
                params=_chat_params(second_session_id),
            ).json()
            == {"running": True}
        )

        first_messages = client.get(
            "/api/chat/messages",
            params=_chat_params(first_session_id),
        ).json()["messages"]
        second_messages = client.get(
            "/api/chat/messages",
            params=_chat_params(second_session_id),
        ).json()["messages"]

        assert [msg["text"] for msg in first_messages] == [
            "first session",
            "세션이 중지되었습니다.",
        ]
        assert [msg["text"] for msg in second_messages] == ["second session"]

        stop_second = client.post("/api/chat/stop", params=_chat_params(second_session_id))
        assert stop_second.status_code == 200
        assert stop_second.json() == {"ok": True, "stopped": True}
        _wait_until(
            lambda: client.get(
                "/api/chat/agent-status",
                params=_chat_params(second_session_id),
            ).json()
            == {"running": False}
        )


@pytest.mark.asyncio
async def test_run_cleanup_does_not_clear_newer_process_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = str(uuid.uuid4())
    first_release = asyncio.Event()
    second_release = asyncio.Event()
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    processes: list[_FakeProcess] = []

    async def _fake_create_subprocess_exec(*args, **kwargs):
        del args, kwargs
        if not first_started.is_set():
            process = _FakeProcess(first_release)
            processes.append(process)
            first_started.set()
            return process
        process = _FakeProcess(second_release)
        processes.append(process)
        second_started.set()
        return process

    async def _fake_append_and_broadcast_message(
        *, session_id: str, role: str, text: str
    ) -> dict:
        del session_id
        return {"role": role, "text": text}

    async def _fake_broadcast(_session_id: str, _msg: dict) -> None:
        return None

    monkeypatch.setattr(
        chat_api.asyncio,
        "create_subprocess_exec",
        _fake_create_subprocess_exec,
    )
    monkeypatch.setattr(
        chat_api,
        "_append_and_broadcast_message",
        _fake_append_and_broadcast_message,
    )
    monkeypatch.setattr(chat_api, "_broadcast", _fake_broadcast)

    first_task = asyncio.create_task(chat_api._run_agent_for_message(session_id, "first"))
    await first_started.wait()
    assert chat_api._agent_processes[session_id] is processes[0]

    second_task = asyncio.create_task(chat_api._run_agent_for_message(session_id, "second"))
    await second_started.wait()
    assert chat_api._agent_processes[session_id] is processes[1]

    first_release.set()
    await first_task
    assert chat_api._agent_processes[session_id] is processes[1]

    second_release.set()
    await second_task
    assert session_id not in chat_api._agent_processes
