from __future__ import annotations

import pytest

from valuator.tools.code_execute_tool import ExecuteCodeTool


@pytest.mark.asyncio
async def test_code_execute_tool_allows_json_import() -> None:
    tool = ExecuteCodeTool()

    result = await tool.execute(
        code="import json\nprint(json.dumps({'ok': True}, sort_keys=True))"
    )

    assert result.success is True
    assert result.result["output"] == '{"ok": true}'
    assert "json" in result.metadata["allowed_imports"]
