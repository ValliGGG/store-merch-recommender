"""SQLite helpers — connection + schema bootstrap + run logging."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_FILE  = PROJECT_ROOT / "db" / "schema.sql"


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    # Lightweight migrations for caches created before a column existed
    # (CREATE TABLE IF NOT EXISTS won't add columns to an existing table).
    cols = {r[1] for r in conn.execute("PRAGMA table_info(products)")}
    for col in ("own_available", "external_only"):
        if col not in cols:
            conn.execute(f"ALTER TABLE products ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
    conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def run(conn: sqlite3.Connection, kind: str, notes: str = ""):
    cur = conn.execute(
        "INSERT INTO sync_runs(kind, started_at, status, notes) VALUES (?, ?, 'running', ?)",
        (kind, now_iso(), notes),
    )
    run_id = cur.lastrowid
    conn.commit()
    try:
        yield run_id
        conn.execute(
            "UPDATE sync_runs SET finished_at=?, status='ok' WHERE id=?",
            (now_iso(), run_id),
        )
        conn.commit()
    except Exception as e:
        conn.execute(
            "UPDATE sync_runs SET finished_at=?, status='failed', notes=? WHERE id=?",
            (now_iso(), f"{notes}\nERROR: {e}", run_id),
        )
        conn.commit()
        raise
