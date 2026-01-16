import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "status.json",
    "plan/active/decomposition.json",
    "plan/active/metadata.json",
    "plan/active/status_log.ndjson",
)


class HDPS:
    def __init__(self, root: Path = ROOT, session_id: str | None = None):
        self.session_id = session_id
        if session_id:
            root = root / "sessions" / session_id
        self.root = root
        self._lock = threading.RLock()

    def p(self, rel: str) -> Path:
        return self.root / rel.lstrip("/")

    def now(self) -> str:
        return (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def new_session_id(self, ts: str | None = None) -> str:
        ts = ts or self.now()
        date, time = ts.split("T", 1)
        time = time.replace("Z", "").replace(":", "")
        return f"S-{date.replace('-', '')}-{time}Z"

    def event_id(self, ts: str, seq: int) -> str:
        compact = ts.replace("-", "").replace(":", "")
        return f"EV-{compact}-{seq:04d}"

    def write_atomic(self, path: Path, content: str) -> None:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)

    def append_atomic(self, path: Path, line: str) -> None:
        with self._lock:
            existing = ""
            if path.exists():
                existing = path.read_text(encoding="utf-8")
                if existing and not existing.endswith("\n"):
                    existing += "\n"
            self.write_atomic(path, existing + line)

    def read_json(self, rel: str) -> dict:
        return json.loads(self.p(rel).read_text(encoding="utf-8"))

    def write_json(self, rel: str, data: dict) -> None:
        self.write_atomic(
            self.p(rel), json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        )

    def append_ndjson(self, rel: str, data: dict) -> None:
        line = json.dumps(data, ensure_ascii=False) + "\n"
        self.append_atomic(self.p(rel), line)

    def bootstrap(self, goal: str | None = None) -> list[str]:
        ts = self.now()
        created = []
        dirs = [
            self.p("plan/active"),
            self.p("plan/archive"),
            self.p("context/sources"),
            self.p("execution/run_logs"),
            self.p("execution/outputs"),
            self.p("execution/questions"),
            self.p("critique/reports"),
        ]
        if not self.session_id:
            dirs.append(self.p("sessions"))
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
        goal_path = self.p("plan/goal.md")
        if not goal_path.exists():
            goal_text = goal or (
                "Project goal: HDPS-based single-agent system for quant company analysis\n"
            )
            self.write_atomic(goal_path, goal_text)
            created.append("plan/goal.md")
        if not self.p("plan/active/decomposition.json").exists():
            self.write_json(
                "plan/active/decomposition.json",
                {"major_version": 1, "revision": 0, "tasks": []},
            )
            created.append("plan/active/decomposition.json")
        if not self.p("plan/active/metadata.json").exists():
            self.write_json(
                "plan/active/metadata.json",
                {
                    "major_version": 1,
                    "revision": 0,
                    "modification_type": "MAJOR",
                    "trigger": "bootstrap",
                    "last_modified": ts,
                },
            )
            created.append("plan/active/metadata.json")
        event_id = None
        if not self.p("plan/active/status_log.ndjson").exists():
            event_id = self.event_id(ts, 1)
            self.append_ndjson(
                "plan/active/status_log.ndjson",
                {
                    "event_id": event_id,
                    "ts": ts,
                    "actor": "Planner",
                    "type": "SYSTEM_INIT",
                    "detail": {
                        "status": "PLANNING",
                        "plan_major_version": 1,
                        "plan_revision": 0,
                        "reason": "bootstrap",
                    },
                },
            )
            created.append("plan/active/status_log.ndjson")
        if not self.p("status.json").exists():
            self.write_json(
                "status.json",
                {
                    "system_status": "PLANNING",
                    "plan_major_version": 1,
                    "plan_revision": 0,
                    "current_task_id": None,
                    "blocked_count": 0,
                    "last_event_id": event_id,
                },
            )
            created.append("status.json")
        if not self.p("plan/change_log.md").exists():
            self.append_atomic(
                self.p("plan/change_log.md"),
                f"{ts} INIT: bootstrap scaffold\n",
            )
            created.append("plan/change_log.md")
        if not self.p("critique/review_rules.md").exists():
            self.write_atomic(
                self.p("critique/review_rules.md"),
                "# Review Rules\n\n- Enforce HDPS laws and role isolation.\n",
            )
            created.append("critique/review_rules.md")
        if not self.p("context/index.json").exists():
            self.write_json("context/index.json", {"knowledge": []})
            created.append("context/index.json")
        return created

    def missing_required(self) -> list[str]:
        return [r for r in REQUIRED if not self.p(r).exists()]

    def set_status(
        self, actor: str, event_type: str, system_status: str, task_id: str
    ) -> None:
        ts = self.now()
        status = self.read_json("status.json")
        status_log = self.p("plan/active/status_log.ndjson")
        event_id = self.next_event_id(ts, status_log)
        self.append_ndjson(
            "plan/active/status_log.ndjson",
            {
                "event_id": event_id,
                "ts": ts,
                "actor": actor,
                "type": event_type,
                "detail": {"system_status": system_status, "task_id": task_id},
            },
        )
        status.update(
            {
                "system_status": system_status,
                "current_task_id": task_id,
                "last_event_id": event_id,
            }
        )
        self.write_json("status.json", status)

    def next_event_id(self, ts: str, status_log: Path) -> str:
        if not status_log.exists():
            return self.event_id(ts, 1)
        lines = status_log.read_text(encoding="utf-8").splitlines()
        if not lines:
            return self.event_id(ts, 1)
        try:
            last = json.loads(lines[-1])
            last_id = last.get("event_id", "")
            last_ts = last.get("ts")
        except json.JSONDecodeError:
            last_id = ""
            last_ts = None
        if last_ts != ts:
            return self.event_id(ts, 1)
        match = re.search(r"-(\\d{4})$", last_id)
        seq = int(match.group(1)) + 1 if match else 1
        return self.event_id(ts, seq)

    def ensure_required(self) -> None:
        missing = self.missing_required()
        if not missing:
            return
        reason = f"missing required files: {', '.join(missing)}"
        self.block(reason, missing)
        raise FileNotFoundError(reason)

    def block(self, reason: str, missing: list[str] | None = None) -> str:
        ts = self.now()
        qid = self.create_question(ts, None, reason)
        status = self._read_status()
        blocked = status.get("blocked_count", 0) + 1
        status.update(
            {
                "system_status": "BLOCKED",
                "blocked_count": blocked,
            }
        )
        status["last_event_id"] = self._append_block_event(ts, reason, missing)
        self.write_json("status.json", status)
        return qid

    def _read_status(self) -> dict:
        path = self.p("status.json")
        if not path.exists():
            return {
                "system_status": "UNKNOWN",
                "plan_major_version": None,
                "plan_revision": None,
                "current_task_id": None,
                "blocked_count": 0,
                "last_event_id": None,
            }
        return json.loads(path.read_text(encoding="utf-8"))

    def _next_question_id(self, ts: str) -> str:
        date = ts.split("T", 1)[0].replace("-", "")
        qdir = self.p("execution/questions")
        qdir.mkdir(parents=True, exist_ok=True)
        existing = []
        for path in qdir.glob(f"Q-{date}-*.json"):
            parts = path.stem.split("-")
            if len(parts) == 3 and parts[-1].isdigit():
                existing.append(int(parts[-1]))
        seq = (max(existing) + 1) if existing else 1
        return f"Q-{date}-{seq:04d}"

    def create_question(self, ts: str, task_id: str | None, question: str) -> str:
        if not question or not question.strip():
            raise ValueError("question is required")
        qid = self._next_question_id(ts)
        payload = {
            "id": qid,
            "task_id": task_id,
            "ts": ts,
            "question": question,
            "status": "OPEN",
        }
        self.write_json(f"execution/questions/{qid}.json", payload)
        return qid

    def _append_block_event(
        self, ts: str, reason: str, missing: list[str] | None
    ) -> str | None:
        status_log = self.p("plan/active/status_log.ndjson")
        if not status_log.exists():
            return None
        event_id = self.next_event_id(ts, status_log)
        self.append_ndjson(
            "plan/active/status_log.ndjson",
            {
                "event_id": event_id,
                "ts": ts,
                "actor": "Planner",
                "type": "SYSTEM_BLOCKED",
                "detail": {"reason": reason, "missing": missing or []},
            },
        )
        return event_id
