from .hdps import HDPS


class ToolRouter:
    def __init__(self, hdps: HDPS):
        self.hdps = hdps

    def attach_tool_calls(self, plan: dict, state: dict) -> dict:
        ticker = state.get("ticker")
        for task in plan.get("tasks", []):
            sources = task.get("data_sources") or []
            source = sources[0] if sources else None
            if source in {"SEC", "YFINANCE"} and not ticker:
                reason = "missing ticker for data_sources"
                self.hdps.block(reason, ["context/state.json:ticker"])
                raise ValueError(reason)
            task["tool_calls"] = [self._build_call(task, state)]
        return plan

    def _build_call(self, task: dict, state: dict) -> dict:
        source = (task.get("data_sources") or [None])[0]
        if source == "SEC":
            args = {"ticker": state.get("ticker"), "query": self._task_query(task)}
            year = state.get("year")
            if isinstance(year, int):
                args["year"] = year
            return {"name": "sec_tool", "args": args}
        if source == "YFINANCE":
            args = {"ticker": state.get("ticker")}
            min_year = state.get("min_year")
            if isinstance(min_year, int):
                args["min_year"] = min_year
            return {"name": "yfinance_balance_sheet", "args": args}
        if source == "WEB":
            queries = task.get("acceptance") or [task.get("title", "")]
            return {"name": "web_search_tool", "args": {"queries": queries}}
        raise ValueError("unknown data_sources value")

    def _task_query(self, task: dict) -> str:
        parts = [task.get("title", "")]
        parts.extend(task.get("acceptance", []) or [])
        return " | ".join([p for p in parts if p])
