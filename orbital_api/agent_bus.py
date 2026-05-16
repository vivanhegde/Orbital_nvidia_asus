"""In-process pub/sub for agent reasoning events.

Producers (the runner's per-investigation forwarder) call `publish(event)`.
Subscribers (each open `/api/agent/stream` SSE connection) iterate
`subscribe()`. New connections see the most recent N events immediately
so they don't open into an empty stream while the agent is mid-reasoning.

Async-only — meant to run inside the FastAPI event loop. No thread safety
because publish is called from async tasks the API process owns.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any, AsyncIterator

_LOG = logging.getLogger(__name__)

_REPLAY_BUFFER = 100   # last-N events delivered to each new subscriber
_QUEUE_MAX = 200       # per-subscriber backpressure cap; slow consumers drop oldest


class AgentEventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._recent: deque[dict[str, Any]] = deque(maxlen=_REPLAY_BUFFER)

    async def publish(self, event: dict[str, Any]) -> None:
        self._recent.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Drop the oldest item to make room for the newest — preferable
                # to dropping the new one since the agent's most recent thought
                # is usually the most relevant.
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    _LOG.warning("AgentEventBus subscriber queue jammed — event dropped")

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAX)
        # Replay buffer so a fresh page-load shows context.
        for ev in list(self._recent):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                break
        self._subscribers.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subscribers.discard(q)

    def stats(self) -> dict[str, int]:
        return {
            "subscribers": len(self._subscribers),
            "buffered_events": len(self._recent),
        }
