"""Development-only helpers (synthetic verdicts for demo)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from orbital_api.deps import require_event_store
from orbital_persist.store import EventStore

router = APIRouter(prefix="/api/dev", tags=["dev"])


class SynthesizeBody(BaseModel):
    event_id: str = Field(..., min_length=8, max_length=64)


@router.post("/synthesize-verdict")
def synthesize_verdict(
    body: SynthesizeBody,
    store: EventStore = Depends(require_event_store),
) -> dict[str, object]:
    """Insert a plausible maneuver recommendation for demo (no live agent)."""
    ev = store.get_event(body.event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="Unknown event_id")
    plan = {
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
    reasoning = (
        f"Synthetic demo verdict: recommend prograde split burn for {ev.obj1_name} "
        f"vs {ev.obj2_name}; covariance-inflated Pc exceeds watch threshold."
    )
    # Use "recommended" so the agent's verdicts and synthesized ones share
    # the same surface — both appear in the Approver queue and render via
    # the same AssessmentReport component.
    vid = store.record_verdict(
        body.event_id,
        "recommended",
        reasoning,
        plan,
    )
    return {"verdict_id": vid, "event_id": body.event_id}
