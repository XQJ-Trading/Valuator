from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .utils.session_trace import utc_isoformat


def create_tool_registry(model: str, usage_writer: Any | None = None):
    from .tools.base import ToolRegistry
    from .tools.code_execute_tool import ExecuteCodeTool
    from .tools.domain_tool import DomainTool
    from .tools.sec_tool import SECTool
    from .tools.web_search_tool import PerplexitySearchTool
    from .tools.yfinance_tool import YFinanceBalanceSheetTool

    registry = ToolRegistry()
    for tool in (
        PerplexitySearchTool(),
        ExecuteCodeTool(),
        YFinanceBalanceSheetTool(),
        SECTool(model=model),
        DomainTool(model=model),
    ):
        registry.register(tool)
    registry.bind_usage_writer(usage_writer)
    return registry


def final_output_text(output: Any) -> str:
    if isinstance(output, str):
        return output.strip()
    if isinstance(output, dict):
        for key in ("markdown", "report", "content"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return json.dumps(output, ensure_ascii=False, indent=2, default=str).strip()


def finalize_trace(
    trace_writer: Any | None,
    *,
    status: str,
    completed_at: datetime | str | None,
    error: str | None = None,
    final_answer: str = "",
    duration: float | None = None,
) -> None:
    if trace_writer is None:
        return
    trace_writer.append_total()
    trace_writer.update_session(
        status=status,
        completed_at=utc_isoformat(completed_at),
        error=error,
        final_answer=final_answer,
        duration=duration,
        llm_usage_summary=trace_writer.usage_summary(),
    )
