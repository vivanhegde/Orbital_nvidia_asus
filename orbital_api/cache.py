"""In-memory screening cache with background refresh."""

from __future__ import annotations

import copy
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class ScreeningCache:
    """Thread-safe store for last screening results and status."""

    _data_lock: threading.RLock = field(default_factory=threading.RLock)
    _run_lock: threading.Lock = field(default_factory=threading.Lock)
    conjunctions: list[dict[str, Any]] = field(default_factory=list)
    cache_updated_at: datetime | None = None
    screening_in_progress: bool = False
    last_error: str | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _worker: threading.Thread | None = None

    def snapshot(self) -> dict[str, Any]:
        with self._data_lock:
            return {
                "conjunctions": copy.deepcopy(self.conjunctions),
                "cache_updated_at": self.cache_updated_at,
                "screening_in_progress": self.screening_in_progress,
                "last_error": self.last_error,
            }

    def try_begin_screening(self) -> bool:
        """Non-blocking: return True if this caller owns the screening run."""
        return self._run_lock.acquire(blocking=False)

    def end_screening(self) -> None:
        self._run_lock.release()

    def start_worker(self, interval_s: float = 60.0) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop.clear()

        def _loop() -> None:
            while not self._stop.is_set():
                try:
                    from orbital_api.screening_jobs import run_screening_job

                    run_screening_job(self)
                except Exception as exc:  # pragma: no cover
                    log.exception("Screening loop error: %s", exc)
                if self._stop.wait(timeout=interval_s):
                    break

        self._worker = threading.Thread(target=_loop, name="orbital-screening", daemon=True)
        self._worker.start()

    def stop_worker(self) -> None:
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=10.0)


screening_cache = ScreeningCache()
