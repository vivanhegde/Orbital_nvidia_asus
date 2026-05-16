"""SQLite connection helpers and migration runner."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(db_path: Path) -> sqlite3.Connection:
    """Open SQLite DB for safe multi-process access.

    The MCP server, FastAPI's screening worker, and the runner all open
    their own connections to this same file. Default rollback-journal mode
    is fragile under that pattern (lock contention can surface as
    SQLITE_READONLY on some filesystems). WAL mode handles multi-reader +
    single-writer cleanly with a separate -wal file, and busy_timeout lets
    writers wait through transient lock contention instead of erroring.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30.0)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")   # safe with WAL, ~3x faster than FULL
    conn.execute("PRAGMA busy_timeout = 30000")   # 30s — wait through lock contention
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def run_migrations(conn: sqlite3.Connection, migrations_dir: Path) -> None:
    """Apply all ``*.sql`` files in ``migrations_dir`` in sorted order."""
    if not migrations_dir.is_dir():
        raise FileNotFoundError(f"Migrations directory missing: {migrations_dir}")
    for path in sorted(migrations_dir.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        conn.executescript(sql)
    conn.commit()
