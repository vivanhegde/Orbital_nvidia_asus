"""Development-only helpers (synthetic verdicts for demo).

`POST /api/dev/synthesize-verdict` does TWO things now:

  1. Inserts a hardcoded `recommended` verdict into the verdicts table so
     the Approver tab renders the full Conjunction Assessment Report.

  2. Asynchronously publishes a fake reasoning trail (thoughts, tool calls,
     tool results, and the final verdict_drafted) to the AgentEventBus so
     the Agent Activity panel streams what looks like a real investigation
     happening over ~8 seconds. The final FINAL row carries the
     "OPEN APPROVER →" action, which navigates to the assessment report.

This means a single POST gives a complete demo of the agent → SSE → UI →
Approver flow without needing the LLM, Ollama, or OpenClaw involved.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from orbital_api.agent_bus import AgentEventBus
from orbital_api.deps import require_event_store
from orbital_persist.store import EventStore

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dev", tags=["dev"])


class SynthesizeBody(BaseModel):
    event_id: str = Field(..., min_length=8, max_length=64)


def _build_plan() -> dict[str, Any]:
    return {
        "recommended": "B",
        "plans": {
            "B": {
                "label": "Plan B — split burn",
                "burns_ms": [0.15, 0.12],
                "total_delta_v_ms": 0.27,
                "events_resolved": 1,
            },
            "A": {
                "label": "Plan A — single burn",
                "burns_ms": [0.35],
                "total_delta_v_ms": 0.35,
                "events_resolved": 1,
            },
        },
        "urgency": "act_within_24hr",
    }


def _build_reasoning(obj1_name: str, obj2_name: str) -> str:
    return (
        f"Refined Pc remains in the action band after covariance inflation. "
        f"{obj1_name} is the maneuverable asset; {obj2_name} is uncontrollable "
        f"debris, so the burden of avoidance is on us. Plan B (split prograde "
        f"burn) resolves the conjunction at lower total Δv than the single-burn "
        f"alternative and preserves more of the asset's fuel budget. Plan A is "
        f"included as a single-event-focus fallback. Recommend act within 24 "
        f"hours; the long lead time allows operator review."
    )


# Fake reasoning trail — each entry is (delay_seconds_since_previous, event_dict).
# All events get `related_event_id` and timestamp filled in before publish.
def _trail(
    event_id: str, obj1_name: str, obj1_norad: int, obj2_name: str, obj2_norad: int
) -> list[tuple[float, dict[str, Any]]]:
    return [
        (0.0, {
            "type": "thought",
            "content": (
                f"New conjunction flagged: {obj1_name} (NORAD {obj1_norad}) vs "
                f"{obj2_name} (NORAD {obj2_norad}). Initial Pc is in the action "
                f"band; following protocol — check weather, refine, decide."
            ),
        }),
        (0.6, {
            "type": "tool_call",
            "content": {"name": "orbital__get_space_weather", "args": "{}"},
        }),
        (0.5, {
            "type": "tool_result",
            "content": {"name": "orbital__get_space_weather",
                        "summary": "Kp 3.30 · X-ray C · Quiet"},
        }),
        (0.5, {
            "type": "thought",
            "content": "Kp below 5 — no covariance inflation needed for drag noise.",
        }),
        (0.7, {
            "type": "tool_call",
            "content": {"name": "orbital__get_object_metadata",
                        "args": f'{{"norad_id":{obj1_norad}}}'},
        }),
        (0.6, {
            "type": "tool_result",
            "content": {"name": "orbital__get_object_metadata",
                        "summary": f"{obj1_name} (PAY, SpaceX) · maneuverable · 18.2 m/s Δv remaining"},
        }),
        (0.7, {
            "type": "tool_call",
            "content": {"name": "orbital__get_object_metadata",
                        "args": f'{{"norad_id":{obj2_norad}}}'},
        }),
        (0.6, {
            "type": "tool_result",
            "content": {"name": "orbital__get_object_metadata",
                        "summary": f"{obj2_name} (DEB) · non-maneuverable"},
        }),
        (0.6, {
            "type": "thought",
            "content": (
                f"Burden of avoidance is on {obj1_name} — partner is debris. "
                f"Querying memory for prior decisions on this asset."
            ),
        }),
        (0.7, {
            "type": "tool_call",
            "content": {"name": "orbital__query_memory",
                        "args": f'{{"norad_id":{obj1_norad},"limit":5}}'},
        }),
        (0.6, {
            "type": "tool_result",
            "content": {"name": "orbital__query_memory",
                        "summary": f"2 prior events for NORAD {obj1_norad}"},
        }),
        (0.7, {
            "type": "tool_call",
            "content": {"name": "orbital__compute_collision_probability",
                        "args": f'{{"norad_id_a":{obj1_norad},"norad_id_b":{obj2_norad},"kp_index":3.3}}'},
        }),
        (0.8, {
            "type": "tool_result",
            "content": {"name": "orbital__compute_collision_probability",
                        "summary": "Pc 3.20e-04 · band=action · miss 0.712 km"},
        }),
        (0.5, {
            "type": "thought",
            "content": "Refined Pc still above 1e-4 — action required. Evaluating two candidate plans.",
        }),
        (0.7, {
            "type": "tool_call",
            "content": {"name": "orbital__evaluate_plan",
                        "args": "single-burn (0.35 m/s prograde)"},
        }),
        (0.6, {
            "type": "tool_result",
            "content": {"name": "orbital__evaluate_plan",
                        "summary": "Plan A: Δv 0.35 m/s · resolves 1/1 event"},
        }),
        (0.6, {
            "type": "tool_call",
            "content": {"name": "orbital__evaluate_plan",
                        "args": "split-burn (0.15 + 0.12 m/s prograde)"},
        }),
        (0.6, {
            "type": "tool_result",
            "content": {"name": "orbital__evaluate_plan",
                        "summary": "Plan B: Δv 0.27 m/s · resolves 1/1 event"},
        }),
        (0.4, {
            "type": "thought",
            "content": "Plan B uses 23% less Δv and resolves the same event. Recommending B with A as fallback.",
        }),
        (0.6, {
            "type": "tool_call",
            "content": {"name": "orbital__draft_recommendation",
                        "args": '{"event_id":"…","recommendation_json":"…"}'},
        }),
        (0.5, {
            "type": "verdict_drafted",
            "content": {
                "verdict_type": "recommended",
                "source_tool": "orbital__draft_recommendation",
            },
        }),
    ]


async def _publish_trail(
    bus: AgentEventBus,
    event_id: str,
    obj1_name: str, obj1_norad: int,
    obj2_name: str, obj2_norad: int,
) -> None:
    """Stream the fake reasoning trail into the SSE bus over ~8s."""
    try:
        for delay, ev in _trail(event_id, obj1_name, obj1_norad, obj2_name, obj2_norad):
            if delay > 0:
                await asyncio.sleep(delay)
            payload = dict(ev)
            payload["related_event_id"] = event_id
            payload["timestamp"] = datetime.now(timezone.utc).isoformat()
            await bus.publish(payload)
    except Exception as exc:  # noqa: BLE001
        _LOG.exception("Synthetic trail publish failed: %s", exc)


@router.post("/synthesize-verdict")
async def synthesize_verdict(
    body: SynthesizeBody,
    request: Request,
    store: EventStore = Depends(require_event_store),
) -> dict[str, object]:
    """Insert a recommended verdict AND stream a fake reasoning trail.

    Use this for demos when you want the full "agent investigates + verdict
    appears + approver renders" flow without running the LLM end-to-end.
    """
    ev = store.get_event(body.event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="Unknown event_id")

    plan = _build_plan()
    reasoning = _build_reasoning(ev.obj1_name, ev.obj2_name)
    vid = store.record_verdict(body.event_id, "recommended", reasoning, plan)

    # Spawn the fake reasoning trail as a background task — don't make the
    # caller wait 8+ seconds for the response.
    bus: AgentEventBus | None = getattr(request.app.state, "agent_bus", None)
    if bus is not None:
        asyncio.create_task(
            _publish_trail(
                bus,
                event_id=body.event_id,
                obj1_name=ev.obj1_name, obj1_norad=ev.obj1_norad_id,
                obj2_name=ev.obj2_name, obj2_norad=ev.obj2_norad_id,
            )
        )
    else:
        _LOG.warning("agent_bus not initialized — synthesize will skip reasoning trail")

    return {
        "verdict_id": vid,
        "event_id": body.event_id,
        "trail_published": bus is not None,
    }
