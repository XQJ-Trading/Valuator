import json

from .gemini3 import Gemini3Client
from .hdps import HDPS


STATE_SYSTEM_PROMPT = (
    "Extract task routing metadata only from the query and tasks. "
    "Output JSON only, no markdown. If unknown, use null."
)

STATE_SCHEMA = {
    "type": "object",
    "properties": {
        "ticker": {"type": ["string", "null"]},
        "company": {"type": ["string", "null"]},
        "year": {"type": ["integer", "null"]},
        "min_year": {"type": ["integer", "null"]},
    },
    "required": ["ticker", "company", "year", "min_year"],
    "additionalProperties": False,
}


class StateManager:
    def __init__(self, hdps: HDPS, client: Gemini3Client | None = None):
        self.hdps = hdps
        self.client = client or Gemini3Client()

    def load(self) -> dict | None:
        path = self.hdps.p("context/state.json")
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if self._valid_state(data) else None

    async def ensure(self, query: str, tasks: list[dict]) -> dict:
        existing = self.load()
        if existing:
            return existing
        prompt = (
            f"User query: {query}\n\n"
            f"Plan tasks: {json.dumps(tasks, ensure_ascii=True)}\n\n"
            "Return JSON with ticker, company, year, min_year."
        )
        raw = await self.client.generate(
            prompt,
            system_prompt=STATE_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=STATE_SCHEMA,
        )
        data = json.loads(self._strip_fence(raw))
        self.hdps.write_json("context/state.json", data)
        return data

    def _valid_state(self, data: dict) -> bool:
        if not isinstance(data, dict):
            return False
        for key in ("ticker", "company", "year", "min_year"):
            if key not in data:
                return False
        return True

    def _strip_fence(self, text: str) -> str:
        if "```" not in text:
            return text.strip()
        parts = text.split("```")
        body = parts[1] if len(parts) > 1 else parts[0]
        body = body.strip()
        if body.lower().startswith("json"):
            body = body[4:].strip()
        return body.strip()
