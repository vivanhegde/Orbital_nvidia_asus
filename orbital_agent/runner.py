"""Autonomous runner: polls SQLite for new conjunctions and fires investigations.

Architecture (per PLAN.md Feature 4):

  ┌──────────────────────────────────────────────────────────────┐
  │ Runner.run() — single-task async loop                        │
  │   - poll queue every N seconds                               │
  │   - if event found: mark in_progress, fire kickoff,          │
  │     block on subprocess, mark done                           │
  │   - else: sleep / wait for shutdown signal                   │
  │                                                              │
  │   parallel: HeartbeatLoop.run() emits status when idle       │
  └──────────────────────────────────────────────────────────────┘

Investigations run one at a time. The `openclaw agent` subprocess is
blocking, so we offload it to a worker thread (`asyncio.to_thread`) — the
heartbeat coroutine keeps running on the event loop and reports "active
investigation" rather than emitting beats during work.

Shutdown: SIGINT / SIGTERM trigger graceful stop. In-flight investigations
finish (we don't have a clean way to cancel a subprocess mid-reasoning); a
second Ctrl+C from the user will force-exit.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Optional

from orbital_agent._paths import ensure_repo_on_path
from orbital_agent.config import AgentConfig, load as load_config
from orbital_agent.heartbeat import HeartbeatLoop
from orbital_agent.kickoff import send_kickoff_for_event
from orbital_agent.queue import (
    clear_in_progress,
    mark_done,
    mark_in_progress,
    next_pending_event,
)

ensure_repo_on_path()

from orbital_persist.store import EventStore  # noqa: E402

_LOG = logging.getLogger(__name__)


class Runner:
    def __init__(self, config: AgentConfig) -> None:
        self._config = config
        self._store = EventStore(config.db_path)
        self._stop = asyncio.Event()
        self._active = False
        self._active_event_id: Optional[str] = None
        self._heartbeat = HeartbeatLoop(
            config, self._store, is_active=lambda: self._active
        )

    def request_stop(self) -> None:
        if not self._stop.is_set():
            _LOG.info("Stop requested — runner will exit after current investigation (if any)")
            self._stop.set()
            self._heartbeat.stop()

    async def run(self) -> int:
        clear_in_progress()
        hb_task = asyncio.create_task(self._heartbeat.run(), name="heartbeat")
        _LOG.info(
            "Runner started — poll_interval=%.1fs, heartbeat=%.1fs, db=%s",
            self._config.poll_interval_seconds,
            self._config.heartbeat_seconds,
            self._config.db_path,
        )
        try:
            while not self._stop.is_set():
                event = next_pending_event(self._store)
                if event is None:
                    try:
                        await asyncio.wait_for(
                            self._stop.wait(),
                            timeout=self._config.poll_interval_seconds,
                        )
                    except asyncio.TimeoutError:
                        pass
                    continue

                await self._investigate(event.event_id, event.obj1_name, event.obj2_name)
        finally:
            hb_task.cancel()
            try:
                await hb_task
            except asyncio.CancelledError:
                pass
            self._store.close()
            _LOG.info("Runner stopped cleanly")
        return 0

    async def _investigate(self, event_id: str, obj1_name: str, obj2_name: str) -> None:
        mark_in_progress(event_id)
        self._active = True
        self._active_event_id = event_id
        _LOG.info("Picked up event %s (%s vs %s)", event_id, obj1_name, obj2_name)
        try:
            # send_kickoff_for_event is blocking (subprocess.run). Run it in
            # a worker thread so the event loop (and heartbeat coroutine,
            # which currently skips when active=True) stays responsive.
            result = await asyncio.to_thread(
                send_kickoff_for_event,
                event_id,
                config=self._config,
                store=self._store,
            )
            _LOG.info(
                "Event %s done: verdict=%s tools=%d duration=%.1fs",
                event_id,
                result.verdict_type,
                len(result.tool_calls),
                result.duration_ms / 1000.0,
            )
        except (ValueError, RuntimeError) as exc:
            _LOG.error("Investigation failed for %s: %s", event_id, exc)
        except Exception as exc:  # noqa: BLE001 — keep the runner alive on unexpected errors
            _LOG.exception("Unexpected error during investigation %s: %s", event_id, exc)
        finally:
            self._active = False
            self._active_event_id = None
            mark_done(event_id)


async def run_async(config: AgentConfig) -> int:
    runner = Runner(config)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, runner.request_stop)
        except (NotImplementedError, RuntimeError):
            # Windows / no event loop signals — fall back to default handler
            pass
    return await runner.run()


def main(argv: list[str] | None = None) -> int:  # convenience for `python -m orbital_agent.runner`
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    return asyncio.run(run_async(config))


if __name__ == "__main__":
    import sys

    sys.exit(main())
