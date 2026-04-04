from __future__ import annotations

import signal

import pytest

from valuator.tools.code_execute_tool import (
    ExecuteCodeTool,
    _SandboxClientError,
)
from valuator.tools.sandbox.protocol import SandboxRequest, SandboxResponse


@pytest.fixture
def tool() -> ExecuteCodeTool:
    instance = ExecuteCodeTool()
    yield instance
    instance.close()


@pytest.mark.asyncio
async def test_code_execute_tool_uses_preloaded_json(tool: ExecuteCodeTool) -> None:
    result = await tool.execute(code="print(json.dumps({'ok': True}, sort_keys=True))")

    assert result.success is True
    assert result.result["output"] == '{"ok": true}'
    assert result.metadata["isolation"] == "fork_server"


@pytest.mark.asyncio
async def test_code_execute_tool_allows_standard_import_syntax(
    tool: ExecuteCodeTool,
) -> None:
    result = await tool.execute(
        code=(
            "import json\n"
            "import numpy as np\n"
            "import pandas as pd\n"
            "print(json.dumps({"
            "'mean': float(np.mean([1, 2, 3])), "
            "'rows': int(pd.DataFrame({'a': [1, 2]}).shape[0])"
            "}, sort_keys=True))"
        )
    )

    assert result.success is True
    assert result.result["output"] == '{"mean": 2.0, "rows": 2}'


@pytest.mark.asyncio
async def test_code_execute_tool_allows_numpy_alias(tool: ExecuteCodeTool) -> None:
    result = await tool.execute(
        code=(
            "print(json.dumps({"
            "'mean': float(np.mean([1, 2, 3])), "
            "'std': round(float(np.std([1, 2, 3])), 5)"
            "}, sort_keys=True))"
        )
    )

    assert result.success is True
    assert result.result["output"] == '{"mean": 2.0, "std": 0.8165}'


@pytest.mark.asyncio
async def test_code_execute_tool_allows_pandas_alias(tool: ExecuteCodeTool) -> None:
    result = await tool.execute(
        code=(
            "df = pd.DataFrame({'a': [1, 2, 3]})\n"
            "print(float(df.describe().loc['mean', 'a']))"
        )
    )

    assert result.success is True
    assert result.result["output"] == "2.0"


@pytest.mark.asyncio
async def test_code_execute_tool_times_out(tool: ExecuteCodeTool) -> None:
    result = await tool.execute(code="while True:\n    pass", timeout=1)

    assert result.success is False
    assert result.error == "Code execution timed out after 1s"


@pytest.mark.asyncio
async def test_code_execute_tool_blocks_imports(tool: ExecuteCodeTool) -> None:
    result = await tool.execute(code="import os\nprint(os.getcwd())")

    assert result.success is False
    assert "Import blocked: os" in (result.error or "")


@pytest.mark.asyncio
async def test_code_execute_tool_reports_syntax_error_context(
    tool: ExecuteCodeTool,
) -> None:
    result = await tool.execute(code='print("ok")\ntext = "unterminated\nprint(text)')

    assert result.success is False
    assert "unterminated string literal at line 2" in (result.error or "")
    assert 'text = "unterminated' in (result.error or "")
    assert "^" in (result.error or "")


@pytest.mark.asyncio
async def test_code_execute_tool_preserves_escaped_newlines_in_strings(
    tool: ExecuteCodeTool,
) -> None:
    result = await tool.execute(code='print("alpha\\nbeta")')

    assert result.success is True
    assert result.result["output"] == "alpha\nbeta"


@pytest.mark.asyncio
async def test_code_execute_tool_restarts_server_after_crash(
    tool: ExecuteCodeTool,
) -> None:
    first = await tool.execute(code="print(1)")

    assert first.success is True
    assert tool._client is not None
    assert tool._client.process is not None

    tool._client.process.send_signal(signal.SIGKILL)
    tool._client.process.wait(timeout=5)

    second = await tool.execute(code="print(2)")

    assert second.success is True
    assert second.result["output"] == "2"


@pytest.mark.asyncio
async def test_code_execute_tool_does_not_retry_after_request_may_have_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = ExecuteCodeTool()

    class FailingClient:
        alive = True

        def __init__(self) -> None:
            self.calls = 0

        def execute(self, request: SandboxRequest) -> SandboxResponse:
            self.calls += 1
            raise _SandboxClientError("sandbox server disconnected", request_sent=True)

        def close(self) -> None:
            return None

    client = FailingClient()
    reset_calls: list[bool] = []
    monkeypatch.setattr(tool, "_ensure_client", lambda: client)
    monkeypatch.setattr(tool, "_reset_client", lambda: reset_calls.append(True))

    result = await tool.execute(code="print(1)")

    assert result.success is False
    assert client.calls == 1
    assert reset_calls == []


@pytest.mark.asyncio
async def test_code_execute_tool_retries_only_when_request_was_not_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = ExecuteCodeTool()

    class FailingClient:
        alive = True

        def __init__(self) -> None:
            self.calls = 0

        def execute(self, request: SandboxRequest) -> SandboxResponse:
            self.calls += 1
            raise _SandboxClientError("sandbox server stdin is closed", request_sent=False)

        def close(self) -> None:
            return None

    class SucceedingClient:
        alive = True

        def __init__(self) -> None:
            self.calls = 0

        def execute(self, request: SandboxRequest) -> SandboxResponse:
            self.calls += 1
            return SandboxResponse(
                success=True,
                output="ok",
                execution_type="exec",
                error="",
            )

        def close(self) -> None:
            return None

    failing_client = FailingClient()
    succeeding_client = SucceedingClient()
    clients = iter((failing_client, succeeding_client))
    reset_calls: list[bool] = []
    monkeypatch.setattr(tool, "_ensure_client", lambda: next(clients))
    monkeypatch.setattr(tool, "_reset_client", lambda: reset_calls.append(True))

    result = await tool.execute(code="print(1)")

    assert result.success is True
    assert result.result["output"] == "ok"
    assert failing_client.calls == 1
    assert succeeding_client.calls == 1
    assert reset_calls == [True]
