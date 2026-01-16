import json

from .hdps import HDPS


class SessionWriter:
    def __init__(self, hdps: HDPS | None = None):
        self.hdps = hdps or HDPS()

    def _session_id(self, ts: str) -> str:
        return self.hdps.new_session_id(ts)

    def _root(self, sid: str):
        if self.hdps.session_id:
            if sid != self.hdps.session_id:
                raise ValueError("session_id mismatch")
            return self.hdps.root
        return self.hdps.p(f"sessions/{sid}")

    def write(
        self,
        user_input: str,
        system_prompt: str,
        final: str,
        summary: dict,
        verdict: str,
        pointers: dict | None = None,
        artifacts: list[dict] | None = None,
        execution_task_ids: list[str] | None = None,
        session_id: str | None = None,
    ) -> str:
        if not user_input:
            raise ValueError("user_input is required")
        if system_prompt is None:
            raise ValueError("system_prompt is required")
        if final is None:
            raise ValueError("final is required")
        if not isinstance(summary, dict):
            raise ValueError("summary must be a dict")
        if not verdict:
            raise ValueError("verdict is required")
        ts = self.hdps.now()
        sid = session_id or self.hdps.session_id or self._session_id(ts)
        root = self._root(sid)
        (root / "input").mkdir(parents=True, exist_ok=True)
        (root / "output").mkdir(parents=True, exist_ok=True)
        (root / "output" / "artifacts").mkdir(parents=True, exist_ok=True)
        self.hdps.write_atomic(root / "input" / "user_input.md", user_input)
        self.hdps.write_atomic(root / "input" / "system_prompt.md", system_prompt)
        self.hdps.write_atomic(root / "output" / "final.md", final)
        artifact_names = []
        if artifacts:
            for artifact in artifacts:
                name = artifact.get("name")
                content = artifact.get("content")
                if not name or content is None:
                    raise ValueError("artifact requires name and content")
                self.hdps.write_atomic(root / "output" / "artifacts" / name, str(content))
                artifact_names.append(name)
        if execution_task_ids:
            if not all(isinstance(t, str) and t for t in execution_task_ids):
                raise ValueError("execution_task_ids must be non-empty strings")
            artifact_names.extend(self._copy_execution_artifacts(root, execution_task_ids))
        summary = {"session_id": sid, **summary}
        if artifact_names:
            existing = summary.get("artifacts_produced")
            if isinstance(existing, list):
                summary["artifacts_produced"] = list(dict.fromkeys(existing + artifact_names))
            elif existing is None:
                summary["artifacts_produced"] = artifact_names
        self.hdps.write_atomic(
            root / "output" / "summary.json",
            json.dumps(summary, indent=2, ensure_ascii=True) + "\n",
        )
        self.hdps.write_atomic(root / "verdict.md", verdict)
        pointers = pointers or self._default_pointers(sid)
        self.hdps.write_atomic(
            root / "pointers.json",
            json.dumps(pointers, indent=2, ensure_ascii=True) + "\n",
        )
        return sid

    def _default_pointers(self, sid: str) -> dict:
        base = f"/sessions/{sid}"
        return {
            "status": f"{base}/status.json",
            "plan": f"{base}/plan/active/decomposition.json",
            "context_index": f"{base}/context/index.json",
        }

    def _copy_execution_artifacts(self, root, task_ids: list[str]) -> list[str]:
        names = []
        for task_id in task_ids:
            src_dir = self.hdps.p(f"execution/outputs/{task_id}")
            if not src_dir.exists():
                raise FileNotFoundError(f"missing outputs for {task_id}")
            for path in src_dir.iterdir():
                if path.is_dir() or path.name == "artifact_manifest.json":
                    continue
                dest = root / "output" / "artifacts" / path.name
                if dest.exists():
                    raise FileExistsError(f"artifact exists: {dest.name}")
                content = path.read_text(encoding="utf-8")
                self.hdps.write_atomic(dest, content)
                names.append(path.name)
        return names
