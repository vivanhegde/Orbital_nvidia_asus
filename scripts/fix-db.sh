#!/usr/bin/env bash
# Recover from "disk I/O error" or "readonly database" SQLite errors.
#
# Usage:  ./scripts/fix-db.sh
#
# Run from the repo root (or wherever your live DB lives). Kills anything
# holding the DB, removes stale WAL/SHM/journal sidecar files, verifies
# the DB is readable, and restarts the stack.
#
# Safe to run repeatedly. Doesn't touch the main .db file — only the
# transient -wal / -shm / -journal sidecars.

set -u

DB=orbital_data/orbital.db

if [ ! -f "$DB" ]; then
  echo "ERROR: $DB not found. Are you in the repo root with a working DB?"
  exit 1
fi

echo "[1/5] Killing processes that may hold the DB open…"
pkill -f "uvicorn orbital_api"      2>/dev/null || true
pkill -f "orbital_agent.mcp_server" 2>/dev/null || true
pkill -f "orbital_agent --run"      2>/dev/null || true
sleep 2

echo "[2/5] Confirming no process still holds the DB…"
if command -v lsof >/dev/null 2>&1; then
  HOLDERS=$(lsof "$DB"* 2>/dev/null | tail -n +2)
  if [ -n "$HOLDERS" ]; then
    echo "  WARNING: something still has the DB open:"
    echo "$HOLDERS"
    echo "  Kill those PIDs manually before continuing."
    exit 2
  fi
  echo "  OK — no holders."
else
  echo "  (skipped — lsof not installed)"
fi

echo "[3/5] Removing stale WAL/SHM/journal sidecars…"
rm -f "$DB-wal" "$DB-shm" "$DB-journal"
ls -la "$DB"* 2>/dev/null

echo "[4/5] Sanity check — can SQLite open and read the DB?"
if ! sqlite3 "$DB" "PRAGMA journal_mode = WAL; SELECT count(*) FROM verdicts;" 2>&1; then
  echo "  ERROR: DB is not readable. Restore from backup or recreate."
  exit 3
fi

echo "[5/5] Restarting the stack…"
uvicorn orbital_api.main:app --host 127.0.0.1 --port 8000 \
  > /tmp/orbital-uvicorn.log 2>&1 &
sleep 2
python -m orbital_agent.mcp_server --transport sse --port 8765 \
  > /tmp/orbital-mcp.log 2>&1 &
sleep 2
python -m orbital_agent --run > /tmp/orbital-runner.log 2>&1 &

echo
echo "Done. Tail logs:"
echo "  tail -f /tmp/orbital-runner.log"
echo "  tail -f /tmp/orbital-uvicorn.log"
echo "  tail -f /tmp/orbital-mcp.log"
