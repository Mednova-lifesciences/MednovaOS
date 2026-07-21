from __future__ import annotations

import sqlite3
from typing import Any

from .utils import iso_now


class SyncCheckpoint:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._ensure_table()

    def _ensure_table(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                current_page INTEGER NOT NULL DEFAULT 0,
                last_processed_product_id TEXT,
                total_pages INTEGER,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

    def load(self) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT current_page, last_processed_product_id, total_pages, status, updated_at, created_at FROM sync_state WHERE id = 1").fetchone()
        if not row:
            return None
        return {
            "current_page": int(row[0] or 0),
            "last_processed_product_id": row[1],
            "total_pages": int(row[2] or 0),
            "status": row[3],
            "updated_at": row[4],
            "created_at": row[5],
        }

    def save(self, current_page: int, last_processed_product_id: str | None, total_pages: int | None, status: str) -> None:
        now = iso_now()
        self.conn.execute(
            """
            INSERT INTO sync_state (id, current_page, last_processed_product_id, total_pages, status, updated_at, created_at)
            VALUES (1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                current_page = excluded.current_page,
                last_processed_product_id = excluded.last_processed_product_id,
                total_pages = excluded.total_pages,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (current_page, last_processed_product_id, total_pages, status, now, now),
        )

    def clear(self) -> None:
        self.conn.execute("DELETE FROM sync_state WHERE id = 1")
