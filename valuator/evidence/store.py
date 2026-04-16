from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from valuator.utils.time_utils import kst_isoformat

EvidenceStatus = Literal["satisfied", "empty", "failed"]


def stable_args(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    del tool_name
    normalized = json.dumps(
        dict(args),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return json.loads(normalized)


def stable_args_hash(tool_name: str, args: dict[str, Any]) -> str:
    payload = json.dumps(
        stable_args(tool_name, args),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return f"{tool_name}:{payload}"


@dataclass(frozen=True)
class EvidenceRow:
    session_id: str
    tool_name: str
    stable_args_hash: str
    status: EvidenceStatus
    value_summary: str
    value_ref: str
    task_id: str
    unit_objective: str
    created_at: str
    updated_at: str
    stable_args: dict[str, Any] = field(default_factory=dict)


class SqliteEvidenceStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence (
                    session_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    stable_args_hash TEXT NOT NULL,
                    stable_args_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    value_summary TEXT NOT NULL,
                    value_ref TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    unit_objective TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, tool_name, stable_args_hash)
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_evidence_session_updated
                ON evidence (session_id, updated_at DESC)
                """
            )
            self._conn.commit()

    def record(self, row: EvidenceRow) -> EvidenceRow:
        with self._lock:
            existing = self.lookup(
                session_id=row.session_id,
                tool_name=row.tool_name,
                args=row.stable_args,
            )
            now = kst_isoformat()
            stored = EvidenceRow(
                session_id=row.session_id,
                tool_name=row.tool_name,
                stable_args_hash=row.stable_args_hash,
                status=row.status,
                value_summary=row.value_summary,
                value_ref=row.value_ref,
                task_id=row.task_id,
                unit_objective=row.unit_objective,
                created_at=existing.created_at if existing is not None else (row.created_at or now),
                updated_at=row.updated_at or now,
                stable_args=stable_args(row.tool_name, row.stable_args),
            )
            self._conn.execute(
                """
                INSERT INTO evidence (
                    session_id,
                    tool_name,
                    stable_args_hash,
                    stable_args_json,
                    status,
                    value_summary,
                    value_ref,
                    task_id,
                    unit_objective,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, tool_name, stable_args_hash) DO UPDATE SET
                    stable_args_json=excluded.stable_args_json,
                    status=excluded.status,
                    value_summary=excluded.value_summary,
                    value_ref=excluded.value_ref,
                    task_id=excluded.task_id,
                    unit_objective=excluded.unit_objective,
                    updated_at=excluded.updated_at
                """,
                (
                    stored.session_id,
                    stored.tool_name,
                    stored.stable_args_hash,
                    json.dumps(
                        stored.stable_args,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ),
                    stored.status,
                    stored.value_summary,
                    stored.value_ref,
                    stored.task_id,
                    stored.unit_objective,
                    stored.created_at,
                    stored.updated_at,
                ),
            )
            self._conn.commit()
            return stored

    def lookup(
        self,
        *,
        session_id: str,
        tool_name: str,
        args: dict[str, object],
    ) -> EvidenceRow | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT
                    session_id,
                    tool_name,
                    stable_args_hash,
                    stable_args_json,
                    status,
                    value_summary,
                    value_ref,
                    task_id,
                    unit_objective,
                    created_at,
                    updated_at
                FROM evidence
                WHERE session_id = ?
                  AND tool_name = ?
                  AND stable_args_hash = ?
                """,
                (
                    session_id,
                    tool_name,
                    stable_args_hash(tool_name, dict(args)),
                ),
            ).fetchone()
        return self._row_to_evidence(row) if row is not None else None

    def list_for_session(self, session_id: str) -> list[EvidenceRow]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT
                    session_id,
                    tool_name,
                    stable_args_hash,
                    stable_args_json,
                    status,
                    value_summary,
                    value_ref,
                    task_id,
                    unit_objective,
                    created_at,
                    updated_at
                FROM evidence
                WHERE session_id = ?
                ORDER BY updated_at DESC, tool_name ASC
                """,
                (session_id,),
            ).fetchall()
        return [self._row_to_evidence(row) for row in rows]

    @staticmethod
    def _row_to_evidence(row: sqlite3.Row) -> EvidenceRow:
        return EvidenceRow(
            session_id=str(row["session_id"]),
            tool_name=str(row["tool_name"]),
            stable_args_hash=str(row["stable_args_hash"]),
            status=str(row["status"]),  # type: ignore[arg-type]
            value_summary=str(row["value_summary"]),
            value_ref=str(row["value_ref"]),
            task_id=str(row["task_id"]),
            unit_objective=str(row["unit_objective"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            stable_args=json.loads(str(row["stable_args_json"])),
        )
