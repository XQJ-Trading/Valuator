import json
from pathlib import Path

from .hdps import HDPS
from ..tools.base import ObservationData, ToolResult


class Executor:
    def __init__(self, hdps: HDPS | None = None):
        self.hdps = hdps or HDPS()

    def _run_log_path(self, ts: str) -> str:
        date = ts.split("T", 1)[0].replace("-", "")
        return f"execution/run_logs/{date}.ndjson"

    def _log(self, entry: dict) -> None:
        ts = entry.get("ts") or self.hdps.now()
        entry["ts"] = ts
        self.hdps.append_ndjson(self._run_log_path(ts), entry)

    def _serialize(self, content):
        if isinstance(content, (dict, list)):
            return json.dumps(content, indent=2, ensure_ascii=True) + "\n"
        return str(content)

    def _write_outputs(self, task_id: str, artifacts: list[dict]) -> dict:
        out_dir = self.hdps.p(f"execution/outputs/{task_id}")
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = out_dir / "artifact_manifest.json"
        if manifest_path.exists():
            raise FileExistsError(f"artifact_manifest already exists for {task_id}")
        manifest = {"task_id": task_id, "created_at": self.hdps.now(), "artifacts": []}
        for artifact in artifacts:
            name = artifact.get("name")
            content = artifact.get("content")
            source = artifact.get("source_path")
            if not name or content is None or not source:
                raise ValueError("artifact requires name, content, source_path")
            dest = out_dir / name
            self.hdps.write_atomic(dest, self._serialize(content))
            manifest["artifacts"].append(
                {
                    "source_path": source,
                    "artifact": str(dest.relative_to(out_dir)),
                    "type": artifact.get("type"),
                }
            )
        self.hdps.write_json(f"execution/outputs/{task_id}/artifact_manifest.json", manifest)
        return manifest

    def execute_task(self, task_id: str, artifacts: list[dict]) -> dict:
        if not task_id:
            raise ValueError("task_id is required")
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError("artifacts must be a non-empty list")
        plan = self.hdps.read_json("plan/active/decomposition.json")
        task = next((task for task in plan.get("tasks", []) if task["id"] == task_id), None)
        if not task:
            raise ValueError(f"unknown task_id: {task_id}")
        self.hdps.set_status("Executor", "EXECUTION_START", "EXECUTING", task_id)
        allowed = {item.get("path") for item in task.get("outputs", []) if item.get("path")}
        for artifact in artifacts:
            name = artifact.get("name")
            source = artifact.get("source_path")
            if allowed and source not in allowed:
                raise ValueError(f"source_path not in task outputs: {source}")
        manifest = self._write_outputs(task_id, artifacts)
        self._log(
            {
                "task_id": task_id,
                "actor": "Executor",
                "action": "write_output",
                "tool": "executor",
                "input": {"artifacts": [a["name"] for a in artifacts]},
                "result": "success",
            }
        )
        return manifest

    def ask_question(self, task_id: str, question: str) -> str:
        if not task_id:
            raise ValueError("task_id is required")
        if not question or not question.strip():
            raise ValueError("question is required")
        ts = self.hdps.now()
        qid = self.hdps.create_question(ts, task_id, question)
        self._log(
            {
                "task_id": task_id,
                "actor": "Executor",
                "action": "ask_question",
                "tool": "executor",
                "input": {"question_id": qid},
                "result": "blocked",
            }
        )
        return qid

    async def run_tool(
        self,
        task_id: str,
        tool_name: str,
        tool_input: dict,
        output_path: str,
    ) -> dict:
        if not task_id:
            raise ValueError("task_id is required")
        if not tool_name:
            raise ValueError("tool_name is required")
        if not isinstance(tool_input, dict):
            raise ValueError("tool_input must be a dict")
        if not output_path:
            raise ValueError("output_path is required")
        plan = self.hdps.read_json("plan/active/decomposition.json")
        task = next((task for task in plan.get("tasks", []) if task["id"] == task_id), None)
        if not task:
            raise ValueError(f"unknown task_id: {task_id}")
        allowed = {item.get("path") for item in task.get("outputs", []) if item.get("path")}
        if allowed and output_path not in allowed:
            raise ValueError(f"output_path not in task outputs: {output_path}")
        self.hdps.set_status("Executor", "EXECUTION_START", "EXECUTING", task_id)
        tool = self._build_tool(tool_name)
        self._log(
            {
                "task_id": task_id,
                "actor": "Executor",
                "action": "run_tool",
                "tool": tool.name,
                "input": tool_input,
                "result": "started",
            }
        )
        result = await tool.execute(**tool_input)
        if not isinstance(result, ToolResult):
            raise ValueError("tool must return ToolResult")
        if not result.success:
            self._log(
                {
                    "task_id": task_id,
                    "actor": "Executor",
                    "action": "run_tool",
                    "tool": tool.name,
                    "input": tool_input,
                    "result": "failed",
                    "error": result.error,
                }
            )
            raise ValueError(result.error or "tool failed")
        payload = result.result
        if isinstance(payload, ObservationData):
            payload = payload.data
        artifact_name = Path(output_path).name or f"{tool.name}_result.json"
        manifest = self._write_outputs(
            task_id,
            [
                {
                    "name": artifact_name,
                    "content": payload,
                    "source_path": output_path,
                    "type": "tool_result",
                }
            ],
        )
        self._log(
            {
                "task_id": task_id,
                "actor": "Executor",
                "action": "run_tool",
                "tool": tool.name,
                "input": tool_input,
                "result": "success",
            }
        )
        return {"manifest": manifest, "tool_result": result.model_dump()}

    def _build_tool(self, tool_name: str):
        if tool_name == "code_execute_tool":
            from ..tools.code_execute_tool import ExecuteCodeTool

            return ExecuteCodeTool()
        if tool_name == "web_search_tool":
            from ..tools.web_search_tool import PerplexitySearchTool

            return PerplexitySearchTool()
        if tool_name == "yfinance_balance_sheet":
            from ..tools.yfinance_tool import YFinanceBalanceSheetTool

            return YFinanceBalanceSheetTool()
        if tool_name == "sec_tool":
            from ..tools.sec_tool import SECTool

            return SECTool()
        raise ValueError(f"unknown tool: {tool_name}")
