"""Tool package.

Keep this module lightweight: avoid importing heavy optional dependencies at import time.
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "ExecuteCodeTool",
    "OpenDartFinancialTool",
    "WebSearchTool",
    "SECTool",
    "YFinanceBalanceSheetTool",
    "TOOL_SPECS",
    "ToolSpec",
    "get_tool_spec",
]

_LAZY_EXPORTS = {
    "ExecuteCodeTool": (".code_execute_tool", "ExecuteCodeTool"),
    "OpenDartFinancialTool": (".opendart_financial_tool", "OpenDartFinancialTool"),
    "WebSearchTool": (".web_search_tool", "WebSearchTool"),
    "SECTool": (".sec_tool", "SECTool"),
    "YFinanceBalanceSheetTool": (".yfinance_tool", "YFinanceBalanceSheetTool"),
    "TOOL_SPECS": (".specs", "TOOL_SPECS"),
    "ToolSpec": (".specs", "ToolSpec"),
    "get_tool_spec": (".specs", "get_tool_spec"),
}


def __getattr__(name: str):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _LAZY_EXPORTS[name]
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
