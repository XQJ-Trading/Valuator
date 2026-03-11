from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ..contracts.plan import Plan, ReviewResult


class Workspace:
    def __init__(self, session_id: str, base_dir: Path | None = None):
        if not session_id.strip():
            raise ValueError("session_id is required")
        root = base_dir or (Path(__file__).resolve().parents[2] / "sessions")
        self.base_dir = root
        self.session_id = session_id
        self.session_dir = root / session_id
        self.current_round: int | None = None
        self._cache_index: dict[tuple[str, str], Path] | None = None

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
        self._cache_index = None

    def write_user_input(self, query: str) -> Path:
        return self._write_text("input/user_input.md", query.strip())

    def write_plan(self, plan: Plan) -> Path:
        payload = asdict(plan)
        active = self._write_json("plan/active/decomposition.json", payload)
        if self.current_round is not None:
            self._write_json(
                f"plan/round-{self.current_round:02d}/decomposition.json", payload
            )
        return active

    def write_output(self, rel_output_path: str, content: str) -> Path:
        return self._write_text(rel_output_path, content)

    def write_review(self, review: ReviewResult) -> Path:
        return self._write_json("review/latest.json", asdict(review))

    def write_final(self, markdown: str) -> Path:
        return self._write_text("output/final.md", markdown.strip() + "\n")

    def leaf_output_path(self, task_id: str) -> str:
        return f"/execution/outputs/{task_id}/result.md"

    def aggregation_report_path(self, task_id: str) -> str:
        return f"/aggregation/{task_id}/report.md"

    def write_leaf_output(self, task_id: str, content: str) -> Path:
        rel_output_path = self.leaf_output_path(task_id)
        return self.write_output(rel_output_path, content)

    def write_aggregation_report(self, task_id: str, markdown: str) -> Path:
        rel_output_path = self.aggregation_report_path(task_id)
        return self.write_output(rel_output_path, markdown)

    def write_output_metadata(self, rel_output_path: str, payload: dict) -> Path:
        return self._write_json(self._metadata_rel_path(rel_output_path), payload)

    def find_cached_output(self, tool: str, args_hash: str) -> str | None:
        """Find cached output from previous rounds via pre-built metadata index."""
        if self.current_round is None or self.current_round <= 1:
            return None
        if self._cache_index is None:
            self._cache_index = self._build_cache_index()
        cached_path = self._cache_index.get((tool, args_hash))
        if cached_path is None or not cached_path.exists():
            return None
        return cached_path.read_text(encoding="utf-8")

    def _build_cache_index(self) -> dict[tuple[str, str], Path]:
        index: dict[tuple[str, str], Path] = {}
        if self.current_round is None:
            return index
        exec_dir = self.session_dir / "execution"
        if not exec_dir.exists():
            return index
        for round_idx in range(self.current_round - 1, 0, -1):
            round_dir = exec_dir / f"round-{round_idx:02d}" / "outputs"
            if not round_dir.exists():
                continue
            for meta_path in round_dir.rglob("*.meta.json"):
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                if not isinstance(meta, dict):
                    continue
                tool = meta.get("tool")
                args_hash = meta.get("args_hash")
                if not tool or not args_hash:
                    continue
                key = (str(tool), str(args_hash))
                if key in index:
                    continue
                content_path = meta_path.with_name(meta_path.name.removesuffix(".meta.json"))
                if content_path.exists():
                    index[key] = content_path
        return index

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
            suffix = clean_rel_path[len(exec_prefix):]
            return f"execution/round-{self.current_round:02d}/outputs/{suffix}"

        agg_prefix = "aggregation/"
        if clean_rel_path.startswith(agg_prefix):
            if self.current_round is None:
                raise ValueError("current round is not set")
            suffix = clean_rel_path[len(agg_prefix):]
            return f"aggregation/round-{self.current_round:02d}/{suffix}"

        return clean_rel_path

    def _metadata_rel_path(self, rel_output_path: str) -> str:
        return f"{rel_output_path}.meta.json"
