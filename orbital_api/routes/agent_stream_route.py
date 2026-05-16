"""Agent event bus: POST events from runner/heartbeat, GET SSE stream for UI."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from orbital_api.agent_bus import latest_seq, push_agent_event, snapshot_events, wait_for_seq_after

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])


class AgentEventBody(BaseModel):
    type: str = Field(..., min_length=1, max_length=64)
    content: str = Field(..., min_length=1, max_length=20_000)
    related_event_id: str | None = Field(None, max_length=128)
    timestamp: str | None = Field(None, max_length=64)
    source: str | None = Field(None, max_length=64)


@router.post("/event")
def post_agent_event(body: AgentEventBody) -> dict[str, object]:
    """Accept an agent/heartbeat event and broadcast to SSE subscribers."""
    payload: dict[str, Any] = {
        "type": body.type,
        "content": body.content,
        "related_event_id": body.related_event_id,
        "timestamp": body.timestamp or "",
        "source": body.source or "client",
    }
    push_agent_event(payload)
    n = len(snapshot_events())
    _LOG.debug("agent event type=%s buffered=%d", body.type, n)
    return {"ok": True, "buffered": n}


def _matches_filter(ev: dict[str, Any], related_event_id: str | None) -> bool:
    if not related_event_id:
        return True
    rid = ev.get("related_event_id")
    if ev.get("type") == "heartbeat":
        return True
    return rid in (None, related_event_id)


def _sse_line(ev: dict[str, Any]) -> str:
    out = {k: v for k, v in ev.items() if k != "_seq"}
    return f"data: {json.dumps(out)}\n\n"


@router.get("/stream")
async def agent_event_stream(related_event_id: str | None = None) -> StreamingResponse:
    """Server-Sent Events stream of buffered + new agent events."""

    async def gen():
        buf = snapshot_events()
        last_seq = 0
        for ev in buf[-80:]:
            if not _matches_filter(ev, related_event_id):
                continue
            yield _sse_line(ev)
            last_seq = max(last_seq, ev.get("_seq", 0))
        for ev in buf:
            last_seq = max(last_seq, ev.get("_seq", 0))

        while True:
            prev = latest_seq()
            await asyncio.to_thread(wait_for_seq_after, prev, 25.0)
            if latest_seq() <= prev:
                yield ": keepalive\n\n"
                continue
            pending = [e for e in snapshot_events() if e.get("_seq", 0) > last_seq]
            pending.sort(key=lambda e: e.get("_seq", 0))
            for ev in pending:
                last_seq = ev.get("_seq", 0)
                if _matches_filter(ev, related_event_id):
                    yield _sse_line(ev)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
