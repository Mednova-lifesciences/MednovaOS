from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

BASE_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
SEED_PATH = Path(__file__).resolve().parent / "seed.sql"


def _read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def initialize_database(db_path: str | Path | None = None) -> Path:
    database_path = Path(db_path or BASE_DIR / "database" / "nafdac_intelligence.db")
    database_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(database_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_read_sql(SCHEMA_PATH))
        conn.executescript(_read_sql(SEED_PATH))
        conn.commit()
    finally:
        conn.close()

    return database_path


if __name__ == "__main__":
    initialize_database()
