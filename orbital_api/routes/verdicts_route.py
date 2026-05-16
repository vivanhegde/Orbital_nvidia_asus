"""Operator verdict queue and decisions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from orbital_api.deps import require_event_store
from orbital_persist.store import EventStore

router = APIRouter(prefix="/api/verdicts", tags=["verdicts"])


def _enrich_verdict(store: EventStore, verdict_id: str) -> dict[str, Any] | None:
    v = store.get_verdict(verdict_id)
    if v is None:
        return None
    ev = store.get_event(v.event_id)
    snap = store.get_latest_pc_snapshot(v.event_id) if ev else None
    pc = float(snap.pc) if snap and ev else (ev.initial_pc if ev else 0.0)
    miss_km = float(snap.miss_distance_km) if snap and ev else None
    m: dict[str, Any] = {
        "verdict_id": v.verdict_id,
        "event_id": v.event_id,
        "issued_at": v.issued_at.isoformat(),
        "verdict_type": v.verdict_type,
        "reasoning": v.reasoning,
        "plan": v.plan_json,
        "operator_decision": v.operator_decision,
        "operator_decided_at": v.operator_decided_at.isoformat() if v.operator_decided_at else None,
        "operator_notes": v.operator_notes,
    }
    if ev:
        m["event"] = {
            "obj1_name": ev.obj1_name,
            "obj2_name": ev.obj2_name,
            "obj1_norad_id": ev.obj1_norad_id,
            "obj2_norad_id": ev.obj2_norad_id,
            "tca": ev.tca.isoformat(),
        }
        m["current_pc"] = pc
        if miss_km is not None:
            m["current_miss_km"] = miss_km
    return m


@router.get("/pending")
def verdicts_pending(
    store: EventStore = Depends(require_event_store),
) -> dict[str, object]:
    pending = store.list_pending_verdicts()
    verdicts: list[dict[str, Any]] = []
    for v in pending:
        enriched = _enrich_verdict(store, v.verdict_id)
        if enriched:
            verdicts.append(enriched)
    return {"verdicts": verdicts}


class OperatorDecisionBody(BaseModel):
    notes: str | None = Field(None, max_length=4000)


@router.post("/{verdict_id}/approve")
def approve_verdict(
    verdict_id: str,
    body: OperatorDecisionBody | None = Body(default=None),
    store: EventStore = Depends(require_event_store),
) -> dict[str, object]:
    if store.get_verdict(verdict_id) is None:
        raise HTTPException(status_code=404, detail="Unknown verdict_id")
    notes = body.notes if body else None
    ok = store.update_operator_decision(verdict_id, "approved", notes=notes)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update verdict")

    return {
        "verdict_id": verdict_id,
        "operator_decision": "approved",
        "operator_decided_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/{verdict_id}/reject")
def reject_verdict(
    verdict_id: str,
    body: OperatorDecisionBody | None = Body(default=None),
    store: EventStore = Depends(require_event_store),
) -> dict[str, object]:
    if store.get_verdict(verdict_id) is None:
        raise HTTPException(status_code=404, detail="Unknown verdict_id")
    notes = body.notes if body else None
    ok = store.update_operator_decision(verdict_id, "rejected", notes=notes)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update verdict")

    return {
        "verdict_id": verdict_id,
        "operator_decision": "rejected",
        "operator_decided_at": datetime.now(timezone.utc).isoformat(),
    }
