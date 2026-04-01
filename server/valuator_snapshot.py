from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .services.valuator_snapshot import project_snapshot_plan

def _valuator_sessions_root() -> Path:
    return Path(__file__).resolve().parents[1] / "valuator" / "sessions"


def _resolve_valuator_session_dir(session_id: str) -> Path:
    root = _valuator_sessions_root().resolve()
    candidate = (root / session_id).resolve()
    if root not in candidate.parents:
        raise HTTPException(status_code=400, detail="Invalid session path")
    if not candidate.exists() or not candidate.is_dir():
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return candidate


def _latest_round_dir(parent: Path) -> tuple[Path | None, int | None]:
    if not parent.exists():
        return None, None
    best_dir: Path | None = None
    best_round: int | None = None
    for child in parent.iterdir():
        if not child.is_dir():
            continue
        match = re.fullmatch(r"round-(\d+)", child.name)
        if not match:
            continue
        value = int(match.group(1))
        if best_round is None or value > best_round:
            best_round = value
            best_dir = child
    return best_dir, best_round


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def _load_snapshot_plan(path: Path) -> dict[str, Any]:
    return _read_json_dict(path) or {}


def _load_valuator_snapshot_payload(
    session_dir: Path, session_id: str
) -> dict[str, Any]:
    plan_path = session_dir / "plan" / "active" / "decomposition.json"
    if not plan_path.exists():
        raise HTTPException(status_code=404, detail="Plan decomposition not found")
    plan = _load_snapshot_plan(plan_path)

    query = str(plan.get("query", "")).strip()
    if not query:
        for name in ("user_query.md", "user_input.md"):
            input_path = session_dir / "input" / name
            if input_path.exists():
                query = input_path.read_text(encoding="utf-8").strip()
                if query:
                    break

    execution_artifacts: list[dict[str, Any]] = []
    aggregation_reports: list[dict[str, Any]] = []
    session_root = session_dir.resolve()
    tasks_root = session_dir / "tasks"
    for task_json_path in sorted(tasks_root.rglob("task.json")):
        task_payload = _read_json_dict(task_json_path) or {}
        task_id = str(task_payload.get("task_id") or task_json_path.parent.name)
        artifacts = task_payload.get("artifacts")
        if not isinstance(artifacts, dict):
            continue

        execution_result_path = artifacts.get("execution_result_path")
        if isinstance(execution_result_path, str) and execution_result_path.strip():
            result_path = (task_json_path.parent / execution_result_path).resolve()
            meta: dict[str, Any] = {}
            execution_meta_path = artifacts.get("execution_meta_path")
            if isinstance(execution_meta_path, str) and execution_meta_path.strip():
                meta = (
                    _read_json_dict(
                        (task_json_path.parent / execution_meta_path).resolve()
                    )
                    or {}
                )
            try:
                logical_output_path = f"/{result_path.relative_to(session_root)}"
            except ValueError:
                logical_output_path = execution_result_path
            execution_artifacts.append(
                {
                    "task_id": task_id,
                    "logical_output_path": logical_output_path,
                    "tool": meta.get("tool"),
                    "args_hash": meta.get("args_hash"),
                    "exists": result_path.exists(),
                }
            )

        aggregation_report_path = artifacts.get("aggregation_report_path")
        if isinstance(aggregation_report_path, str) and aggregation_report_path.strip():
            report_path = (task_json_path.parent / aggregation_report_path).resolve()
            try:
                logical_report_path = f"/{report_path.relative_to(session_root)}"
            except ValueError:
                logical_report_path = aggregation_report_path
            aggregation_reports.append(
                {
                    "task_id": task_id,
                    "logical_report_path": logical_report_path,
                    "exists": report_path.exists(),
                }
            )

    review_raw = _read_json_dict(session_dir / "review" / "latest.json") or {
        "status": "running",
        "actions": [],
        "round": None,
    }
    review = {
        "status": str(review_raw.get("status") or "running"),
        "round": review_raw.get("round"),
        "actions": review_raw.get("actions") or [],
        "coverage_feedback": review_raw.get("coverage_feedback") or {},
        "now_utc": str(review_raw.get("now_utc") or ""),
        "quant_axes": review_raw.get("quant_axes") or {},
    }

    latest_round = review.get("round")
    output_exists = (session_dir / "output" / "final.md").exists()
    status = str(review.get("status") or ("completed" if output_exists else "running"))
    snapshot_plan = project_snapshot_plan(plan)

    return {
        "session_id": session_id,
        "query": query,
        "round": latest_round,
        "status": status,
        "plan": snapshot_plan,
        "execution": {"artifacts": execution_artifacts},
        "aggregation": {"reports": aggregation_reports},
        "review": {
            "status": review.get("status", "running"),
            "round": review.get("round"),
            "actions": review.get("actions", []),
            "coverage_feedback": review.get("coverage_feedback", {}),
            "now_utc": review.get("now_utc", ""),
            "quant_axes": review.get("quant_axes", {}),
        },
    }
