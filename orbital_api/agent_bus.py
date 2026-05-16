"""In-memory ring buffer for agent events → SSE subscribers (Feature 5 lite)."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

_MAX_EVENTS = 500
_events: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENTS)
_lock = threading.Lock()
_seq: int = 0


def push_agent_event(payload: dict[str, Any]) -> None:
    """Append one event (thread-safe)."""
    global _seq
    with _lock:
        _seq += 1
        row = dict(payload)
        row["_seq"] = _seq
        _events.append(row)


def snapshot_events() -> list[dict[str, Any]]:
    """Copy of all buffered events (oldest first)."""
    with _lock:
        return list(_events)


def latest_seq() -> int:
    with _lock:
        return _seq


def wait_for_seq_after(min_seq: int, timeout_s: float) -> int:
    """Block until _seq > min_seq or timeout. Returns current seq after wait."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with _lock:
            if _seq > min_seq:
                return _seq
        time.sleep(0.15)
    with _lock:
        return _seq
