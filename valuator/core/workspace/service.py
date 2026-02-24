from __future__ import annotations

import json
import re
from pathlib import Path

from ..contracts.plan import Plan


class Workspace:
    def __init__(self, session_id: str, base_dir: Path | None = None):
        if not session_id.strip():
            raise ValueError("session_id is required")
        root = base_dir or (Path(__file__).resolve().parents[2] / "sessions")
        self.base_dir = root
        self.session_id = session_id
        self.session_dir = root / session_id
        self.current_round: int | None = None

    def prepare(self) -> None:
        for rel in (
            "input",
            "plan/active",
            "execution",
            "aggregation",
            "review",
            "output",
        ):
            (self.session_dir / rel).mkdir(parents=True, exist_ok=True)

    def set_round(self, round_idx: int) -> None:
        if round_idx < 1:
            raise ValueError("round_idx must be >= 1")
        self.current_round = round_idx

    def write_user_input(self, query: str) -> Path:
        return self._write_text("input/user_input.md", query.strip())

    def write_plan(self, plan: Plan) -> Path:
        payload = plan.model_dump()
        active = self._write_json("plan/active/decomposition.json", payload)
        if self.current_round is not None:
            self._write_json(
                f"plan/round-{self.current_round:02d}/decomposition.json", payload
            )
        return active

    def read_plan(self) -> Plan:
        path = self._resolve("plan/active/decomposition.json")
        if not path.exists():
            raise ValueError("plan file not found")
        return Plan.model_validate_json(path.read_text(encoding="utf-8"))

    def output_exists(self, rel_output_path: str) -> bool:
        return self._resolve(rel_output_path).exists()

    def write_output(self, rel_output_path: str, content: str) -> Path:
        return self._write_text(rel_output_path, content)

    def read_output(self, rel_output_path: str) -> str:
        path = self._resolve(rel_output_path)
        if not path.exists():
            raise ValueError(f"missing output file: {rel_output_path}")
        return path.read_text(encoding="utf-8")

    def write_strategy(self, strategy: str) -> Path:
        return self._write_text("plan/analysis_strategy.md", strategy.strip())

    def write_review(self, review: dict) -> Path:
        return self._write_json("review/latest.json", review)

    def write_final(self, markdown: str) -> Path:
        return self._write_text("output/final.md", markdown.strip() + "\n")

    def write_output_metadata(self, rel_output_path: str, payload: dict) -> Path:
        return self._write_json(self._metadata_rel_path(rel_output_path), payload)

    def read_output_metadata(self, rel_output_path: str) -> dict[str, str] | None:
        path = self._resolve(self._metadata_rel_path(rel_output_path))
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return {str(k): str(v) for k, v in data.items()}

    def list_task_output_paths(self, task_id: str) -> list[str]:
        root = self._resolve(f"/execution/outputs/{task_id}")
        if not root.exists():
            return []
        files: list[str] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.name.endswith(".meta.json"):
                continue
            files.append(self._logical_output_path(path))
        return files

    def find_cached_output(self, tool: str, args_hash: str) -> str | None:
        """Scan previous rounds for a matching (tool, args_hash) and return content."""
        if self.current_round is None or self.current_round <= 1:
            return None
        exec_dir = self.session_dir / "execution"
        if not exec_dir.exists():
            return None
        for round_idx in range(self.current_round - 1, 0, -1):
            round_dir = exec_dir / f"round-{round_idx:02d}" / "outputs"
            if not round_dir.exists():
                continue
            for meta_path in round_dir.rglob("*.meta.json"):
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                if (
                    isinstance(meta, dict)
                    and meta.get("tool") == tool
                    and meta.get("args_hash") == args_hash
                ):
                    content_path = meta_path.with_name(
                        meta_path.name.removesuffix(".meta.json")
                    )
                    if content_path.exists():
                        return content_path.read_text(encoding="utf-8")
        return None

    def _write_text(self, rel_path: str, content: str) -> Path:
        path = self._resolve(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _write_json(self, rel_path: str, payload: dict) -> Path:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        return self._write_text(rel_path, text)

    def _resolve(self, rel_path: str) -> Path:
        clean = rel_path.strip().lstrip("/")
        physical_rel = self._physical_rel_path(clean)
        path = (self.session_dir / physical_rel).resolve()
        root = self.session_dir.resolve()
        if root not in path.parents and path != root:
            raise ValueError(f"invalid session path: {rel_path}")
        return path

    def _physical_rel_path(self, clean_rel_path: str) -> str:
        exec_prefix = "execution/outputs/"
        if clean_rel_path.startswith(exec_prefix):
            if self.current_round is None:
                raise ValueError("current round is not set")
            suffix = clean_rel_path[len(exec_prefix) :]
            return f"execution/round-{self.current_round:02d}/outputs/{suffix}"

        agg_prefix = "aggregation/"
        if clean_rel_path.startswith(agg_prefix):
            if self.current_round is None:
                raise ValueError("current round is not set")
            suffix = clean_rel_path[len(agg_prefix) :]
            return f"aggregation/round-{self.current_round:02d}/{suffix}"

        return clean_rel_path

    def _logical_output_path(self, path: Path) -> str:
        rel = path.resolve().relative_to(self.session_dir.resolve()).as_posix()
        round_match = re.match(r"execution/round-\d+/outputs/(.+)", rel)
        if round_match:
            return f"/execution/outputs/{round_match.group(1)}"
        if rel.startswith("execution/outputs/"):
            return f"/{rel}"
        raise ValueError(f"invalid output path for session workspace: {path}")

    def _metadata_rel_path(self, rel_output_path: str) -> str:
        return f"{rel_output_path}.meta.json"
