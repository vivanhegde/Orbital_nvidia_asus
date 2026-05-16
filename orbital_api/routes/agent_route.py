"""Agent reasoning bridge: SSE out to the UI, HTTP POST in from the runner."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse

from orbital_api.agent_bus import AgentEventBus

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _bus(request: Request) -> AgentEventBus:
    bus = getattr(request.app.state, "agent_bus", None)
    if bus is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="agent_bus not initialized — check app lifespan",
        )
    return bus


@router.get("/stream")
async def agent_stream(request: Request) -> EventSourceResponse:
    """SSE stream of agent reasoning events.

    Each event is a JSON object with shape:
        {type: "thought"|"tool_call"|"tool_result"|"heartbeat"|"verdict_drafted",
         content: <str or short object>,
         related_event_id: <str|null>,
         timestamp: <ISO 8601>}
    """
    bus = _bus(request)

    async def event_gen():
        try:
            async for event in bus.subscribe():
                if await request.is_disconnected():
                    break
                yield {"data": json.dumps(event)}
        except Exception as exc:  # noqa: BLE001 — surface the error to logs, not the connection
            _LOG.exception("agent_stream subscriber crashed: %s", exc)

    return EventSourceResponse(event_gen())


@router.post("/event", status_code=status.HTTP_204_NO_CONTENT)
async def post_agent_event(request: Request, payload: dict[str, Any]) -> None:
    """Ingestion endpoint the runner's forwarder POSTs to."""
    bus = _bus(request)
    # Light validation — we trust our own runner but drop obviously-bad shapes.
    if not isinstance(payload, dict) or "type" not in payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="event must be an object with a 'type' field",
        )
    await bus.publish(payload)


@router.get("/stats")
def agent_stats(request: Request) -> dict[str, int]:
    """Subscriber and buffer counts. Useful for debugging."""
    return _bus(request).stats()
