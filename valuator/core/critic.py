import json
import re

from .gemini3 import Gemini3Client
from .hdps import HDPS


SYSTEM_PROMPT = "You are a strict critic. Verdict must be PASS, REJECT, or BLOCKING."
ALLOWED_VERDICTS = {"PASS", "REJECT", "BLOCKING"}


class Critic:
    def __init__(self, hdps: HDPS | None = None, model: str | None = None):
        self.hdps = hdps or HDPS()
        self.client = Gemini3Client(model=model)

    async def review_task_outputs(self, task_id: str) -> dict:
        if not task_id:
            raise ValueError("task_id is required")
        plan = self.hdps.read_json("plan/active/decomposition.json")
        task = next((t for t in plan.get("tasks", []) if t.get("id") == task_id), None)
        if not task:
            raise ValueError(f"unknown task_id: {task_id}")
        if not (task.get("acceptance") or []):
            return await self.review(task_id, "PASS")
        artifacts = self._load_artifacts(task_id)
        if not artifacts:
            return await self.review(
                task_id, "BLOCKING", required_fixes=["missing artifacts"]
            )
        payload = json.dumps(task, ensure_ascii=True)
        prompt = (
            f"Review rules:\n{self._rules()}\n\n"
            f"Task:\n{payload}\n\n"
            f"Artifacts:\n{artifacts}\n\n"
            "Return JSON with keys: verdict, findings, required_fixes. No markdown."
        )
        data = await self._judge(prompt)
        return await self.review(
            task_id,
            data["verdict"],
            data.get("findings"),
            data.get("required_fixes"),
        )

    async def review_global(self, query: str, plan: dict, reports: list[dict]) -> dict:
        if not query:
            raise ValueError("query is required")
        blocking = [r for r in reports if r.get("verdict") == "BLOCKING"]
        if blocking:
            fixes = [f"{r.get('task_id')}: BLOCKING" for r in blocking]
            return {
                "task_id": "GLOBAL",
                "verdict": "BLOCKING",
                "findings": [],
                "required_fixes": fixes,
            }
        prompt = (
            f"Review rules:\n{self._rules()}\n\n"
            f"User query:\n{query}\n\n"
            f"Plan:\n{json.dumps(plan, ensure_ascii=True)}\n\n"
            f"Task reports:\n{json.dumps(reports, ensure_ascii=True)}\n\n"
            "Judge if top-level tasks cover the query and decomposition can be improved. "
            "Return JSON with keys: verdict, findings, required_fixes. No markdown."
        )
        data = await self._judge(prompt)
        return {
            "task_id": "GLOBAL",
            "verdict": data["verdict"],
            "findings": data.get("findings") or [],
            "required_fixes": data.get("required_fixes") or [],
        }

    async def review(
        self,
        task_id: str,
        verdict: str,
        findings: list[dict] | None = None,
        required_fixes: list[str] | None = None,
    ) -> dict:
        if not task_id:
            raise ValueError("task_id is required")
        verdict = verdict.upper()
        if verdict not in ALLOWED_VERDICTS:
            raise ValueError("verdict must be PASS, REJECT, or BLOCKING")
        self.hdps.set_status("Critic", "CRITIQUE_START", "CRITIQUING", task_id)
        report = {
            "task_id": task_id,
            "ts": self.hdps.now(),
            "verdict": verdict,
            "findings": findings or [],
            "required_fixes": required_fixes or [],
        }
        path = self.hdps.p(f"critique/reports/{task_id}.json")
        if path.exists():
            raise FileExistsError(f"report already exists for {task_id}")
        self.hdps.write_json(f"critique/reports/{task_id}.json", report)
        return report

    async def _judge(self, prompt: str) -> dict:
        raw = await self.client.generate(
            prompt,
            system_prompt=SYSTEM_PROMPT,
            response_mime_type="application/json",
        )
        data = self._parse_json_response(raw)
        if isinstance(data, str):
            data = self._parse_json_response(data)
        if isinstance(data, list):
            data = next(
                (item for item in data if isinstance(item, dict) and "verdict" in item),
                None,
            ) or next((item for item in data if isinstance(item, dict)), None)
        if not isinstance(data, dict):
            raise ValueError("critic response must be an object")
        verdict = (data.get("verdict") or "").upper()
        if verdict not in ALLOWED_VERDICTS:
            raise ValueError(f"invalid verdict: {verdict}")
        data["verdict"] = verdict
        return data

    def _rules(self) -> str:
        path = self.hdps.p("critique/review_rules.md")
        return path.read_text(encoding="utf-8").strip() if path.exists() else ""

    def _load_artifacts(self, task_id: str) -> str:
        out_dir = self.hdps.p(f"execution/outputs/{task_id}")
        if not out_dir.exists():
            return ""
        manifest = out_dir / "artifact_manifest.json"
        if manifest.exists():
            items = (
                self.hdps.read_json(
                    f"execution/outputs/{task_id}/artifact_manifest.json"
                ).get("artifacts")
                or []
            )
            paths = [
                out_dir / item["artifact"] for item in items if item.get("artifact")
            ]
        else:
            paths = [p for p in out_dir.iterdir() if p.is_file()]
        blocks = []
        for path in paths:
            if path.name == "artifact_manifest.json":
                continue
            content = path.read_text(encoding="utf-8").strip()
            if content:
                blocks.append(f"[{path.name}]\n{content[:4000]}")
        return "\n\n".join(blocks)

    def _parse_json_response(self, raw: str) -> dict | list | str:
        body = self._strip_fences(raw)
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            data = self._recover_json(body)
            if data is None:
                preview = raw.strip().replace("\n", " ")
                if len(preview) > 160:
                    preview = f"{preview[:160]}..."
                raise ValueError(f"invalid JSON response: {preview}") from exc
            return data

    def _strip_fences(self, text: str) -> str:
        content = text.strip()
        if "```" in content:
            parts = content.split("```")
            content = parts[1] if len(parts) > 1 else parts[0]
        content = content.strip()
        return re.sub(r"^json\\s*", "", content, flags=re.IGNORECASE)

    def _recover_json(self, text: str) -> dict | list | str | None:
        body = text.lstrip()
        decoder = json.JSONDecoder()
        try:
            data, _ = decoder.raw_decode(body)
            return data
        except json.JSONDecodeError:
            return None
