"""Idle heartbeat: every N seconds while no investigation is running,
publish a status line so the UI shows the agent is alive.

Runner-side (not model-side) so heartbeats cost zero LLM tokens. POSTs to
the bus endpoint Feature 5 will mount at /api/agent/event; if that endpoint
isn't built yet, the heartbeat logs locally and continues without erroring.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

import httpx

from orbital_agent._paths import ensure_repo_on_path
from orbital_agent.config import AgentConfig
from orbital_agent.queue import count_pending

ensure_repo_on_path()

from orbital_persist.store import EventStore  # noqa: E402

_LOG = logging.getLogger(__name__)


class HeartbeatLoop:
    """Periodic status emitter. Pass `is_active` to skip beats during work."""

    def __init__(
        self,
        config: AgentConfig,
        store: EventStore,
        is_active: Callable[[], bool] | None = None,
    ) -> None:
        self._config = config
        self._store = store
        self._is_active = is_active or (lambda: False)
        self._stop = asyncio.Event()
        self._endpoint_warned = False

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        interval = float(self._config.heartbeat_seconds)
        _LOG.info("Heartbeat loop started (interval=%.1fs)", interval)
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
            if self._stop.is_set():
                break
            if self._is_active():
                # Investigation in flight — its own events are the heartbeat
                continue
            try:
                await self._emit()
            except Exception as exc:  # noqa: BLE001 — heartbeats must never crash the runner
                _LOG.warning("Heartbeat emit failed: %s", exc)
        _LOG.info("Heartbeat loop stopped")

    async def _emit(self) -> None:
        n_monitoring = count_pending(self._store)
        n_watch = self._count_watch_band()
        ts = datetime.now(timezone.utc).isoformat()
        message = (
            f"Monitoring catalog. {n_monitoring} flagged event(s) pending, "
            f"{n_watch} in elevated-risk watch. No new flags in last "
            f"{int(self._config.heartbeat_seconds)}s."
        )
        payload = {
            "type": "heartbeat",
            "content": message,
            "related_event_id": None,
            "timestamp": ts,
        }
        url = f"{self._config.api_base_url.rstrip('/')}/api/agent/event"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                # Endpoint exists but rejected us — surface that
                if not self._endpoint_warned:
                    _LOG.warning(
                        "/api/agent/event returned HTTP %d for heartbeat (will keep retrying silently)",
                        resp.status_code,
                    )
                    self._endpoint_warned = True
                _LOG.info("[heartbeat] %s", message)
        except httpx.HTTPError:
            # Feature 5 not yet wired — degrade to logging.
            if not self._endpoint_warned:
                _LOG.info(
                    "Heartbeat bus endpoint not reachable; logging locally until Feature 5 lands"
                )
                self._endpoint_warned = True
            _LOG.info("[heartbeat] %s", message)

    def _count_watch_band(self) -> int:
        """Count events whose latest Pc snapshot is in [1e-6, 1e-4) — design doc §4 'watch' band."""
        with self._store._lock:  # noqa: SLF001
            cur = self._store._conn.cursor()  # noqa: SLF001
            cur.execute(
                """
                SELECT COUNT(DISTINCT s.event_id)
                FROM pc_snapshots AS s
                INNER JOIN conjunction_events AS e ON e.event_id = s.event_id
                WHERE e.status = 'monitoring'
                  AND s.snapshot_id = (
                      SELECT MAX(snapshot_id) FROM pc_snapshots WHERE event_id = s.event_id
                  )
                  AND s.pc >= 1e-6
                  AND s.pc <  1e-4
                """
            )
            return int(cur.fetchone()[0])
