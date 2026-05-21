from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from valuator.utils.time_utils import kst_isoformat

from .types import IndexedDocument, Page, TreeNode


class IndexStore:
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
                CREATE TABLE IF NOT EXISTS page_index_documents (
                    doc_hash TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    page_count INTEGER NOT NULL,
                    tree_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS page_index_pages (
                    doc_hash TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    doc_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    source_locator_json TEXT NOT NULL,
                    PRIMARY KEY (doc_hash, ordinal),
                    FOREIGN KEY (doc_hash)
                        REFERENCES page_index_documents(doc_hash)
                        ON DELETE CASCADE
                )
                """
            )
            self._conn.commit()

    def record(self, document: IndexedDocument, pages: list[Page]) -> IndexedDocument:
        now = kst_isoformat()
        with self._lock:
            row = self._conn.execute(
                """
                SELECT created_at
                FROM page_index_documents
                WHERE doc_hash = ?
                """,
                (document.doc_hash,),
            ).fetchone()
            created_at = str(row["created_at"]) if row is not None else now
            self._conn.execute(
                """
                INSERT INTO page_index_documents (
                    doc_hash,
                    doc_id,
                    page_count,
                    tree_json,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_hash) DO UPDATE SET
                    doc_id=excluded.doc_id,
                    page_count=excluded.page_count,
                    tree_json=excluded.tree_json,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    document.doc_hash,
                    document.doc_id,
                    document.page_count,
                    json.dumps(
                        document.tree.model_dump(mode="json"),
                        ensure_ascii=False,
                    ),
                    json.dumps(document.metadata, ensure_ascii=False, sort_keys=True),
                    created_at,
                    now,
                ),
            )
            self._conn.execute(
                "DELETE FROM page_index_pages WHERE doc_hash = ?",
                (document.doc_hash,),
            )
            self._conn.executemany(
                """
                INSERT INTO page_index_pages (
                    doc_hash,
                    ordinal,
                    doc_id,
                    text,
                    token_count,
                    source_locator_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        document.doc_hash,
                        page.ordinal,
                        page.doc_id,
                        page.text,
                        page.token_count,
                        json.dumps(
                            page.source_locator,
                            ensure_ascii=False,
                            sort_keys=True,
                            default=str,
                        ),
                    )
                    for page in pages
                ],
            )
            self._conn.commit()
            return document

    def get(self, doc_hash: str) -> IndexedDocument | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT
                    doc_hash,
                    doc_id,
                    page_count,
                    tree_json,
                    metadata_json
                FROM page_index_documents
                WHERE doc_hash = ?
                """,
                (doc_hash,),
            ).fetchone()
        if row is None:
            return None
        return IndexedDocument(
            doc_id=str(row["doc_id"]),
            doc_hash=str(row["doc_hash"]),
            page_count=int(row["page_count"]),
            tree=TreeNode.model_validate_json(str(row["tree_json"])),
            metadata=json.loads(str(row["metadata_json"])),
        )

    def get_by_doc_id(self, doc_id: str) -> IndexedDocument | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT
                    doc_hash,
                    doc_id,
                    page_count,
                    tree_json,
                    metadata_json
                FROM page_index_documents
                WHERE doc_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (doc_id,),
            ).fetchone()
        if row is None:
            return None
        return IndexedDocument(
            doc_id=str(row["doc_id"]),
            doc_hash=str(row["doc_hash"]),
            page_count=int(row["page_count"]),
            tree=TreeNode.model_validate_json(str(row["tree_json"])),
            metadata=json.loads(str(row["metadata_json"])),
        )

    def get_pages(
        self,
        doc_hash: str,
        *,
        start: int | None = None,
        end: int | None = None,
    ) -> list[Page]:
        where = ["doc_hash = ?"]
        args: list[Any] = [doc_hash]
        if start is not None:
            where.append("ordinal >= ?")
            args.append(start)
        if end is not None:
            where.append("ordinal <= ?")
            args.append(end)

        sql = f"""
            SELECT
                doc_id,
                ordinal,
                text,
                token_count,
                source_locator_json
            FROM page_index_pages
            WHERE {' AND '.join(where)}
            ORDER BY ordinal ASC
        """
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [
            Page(
                doc_id=str(row["doc_id"]),
                ordinal=int(row["ordinal"]),
                text=str(row["text"]),
                token_count=int(row["token_count"]),
                source_locator=json.loads(str(row["source_locator_json"])),
            )
            for row in rows
        ]
