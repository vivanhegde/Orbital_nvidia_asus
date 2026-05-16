"""SQLite connection helpers and migration runner."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(db_path: Path) -> sqlite3.Connection:
    """Open SQLite DB with foreign keys enabled."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
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
