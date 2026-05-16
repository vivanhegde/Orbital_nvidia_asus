"""Event queue: find the next conjunction needing investigation.

Backed by SQLite. "Pending" = an event in `conjunction_events` with
`status='monitoring'` that has **no verdict yet** in the `verdicts` table.
The runner adds an in-memory "in-progress" set so a long investigation
doesn't get picked up twice if the runner loops back before it finishes.

The runner uses one event at a time (synchronous, per PLAN.md §8), so the
in-progress set is effectively a single-element guard — but it survives
mid-investigation looping cleanly.
"""

from __future__ import annotations

import threading
from typing import Any

from orbital_agent._paths import ensure_repo_on_path

ensure_repo_on_path()

from orbital_persist.models import ConjunctionEventRecord  # noqa: E402
from orbital_persist.store import EventStore  # noqa: E402

_IN_PROGRESS: set[str] = set()
_IN_PROGRESS_LOCK = threading.Lock()


def mark_in_progress(event_id: str) -> None:
    with _IN_PROGRESS_LOCK:
        _IN_PROGRESS.add(event_id)


def mark_done(event_id: str) -> None:
    with _IN_PROGRESS_LOCK:
        _IN_PROGRESS.discard(event_id)


def is_in_progress(event_id: str) -> bool:
    with _IN_PROGRESS_LOCK:
        return event_id in _IN_PROGRESS


def clear_in_progress() -> None:
    """Reset the in-progress set. Useful for tests / runner restart."""
    with _IN_PROGRESS_LOCK:
        _IN_PROGRESS.clear()


def next_pending_event(store: EventStore) -> ConjunctionEventRecord | None:
    """Return the highest-priority event needing investigation, or None.

    Priority: `initial_pc DESC, first_detected_at ASC` — investigate the
    most-dangerous-looking event first; break ties by oldest-first so we
    don't starve older events.

    Skips anything currently marked in-progress.
    """
    with store._lock:  # noqa: SLF001 — sibling of EventStore in our package, breaking the seal is intentional
        cur = store._conn.cursor()  # noqa: SLF001
        cur.execute(
            """
            SELECT e.*
            FROM conjunction_events AS e
            LEFT JOIN verdicts AS v ON v.event_id = e.event_id
            WHERE e.status = 'monitoring'
              AND v.verdict_id IS NULL
            ORDER BY e.initial_pc DESC, e.first_detected_at ASC
            """
        )
        rows = cur.fetchall()
        colnames = [d[0] for d in cur.description]

    for row in rows:
        d: dict[str, Any] = dict(zip(colnames, row))
        if not is_in_progress(d["event_id"]):
            return store._row_to_event(d)  # noqa: SLF001
    return None


def count_pending(store: EventStore) -> int:
    """Total pending events (incl. in-progress) — useful for heartbeat stats."""
    with store._lock:  # noqa: SLF001
        cur = store._conn.cursor()  # noqa: SLF001
        cur.execute(
            """
            SELECT COUNT(*)
            FROM conjunction_events AS e
            LEFT JOIN verdicts AS v ON v.event_id = e.event_id
            WHERE e.status = 'monitoring'
              AND v.verdict_id IS NULL
            """
        )
        return int(cur.fetchone()[0])
