"""API routes for persisted conjunction events and Pc history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from orbital_api.deps import require_event_store
from orbital_persist.store import EventStore

router = APIRouter(prefix="/api/conjunctions", tags=["conjunctions"])


def _pc_band(pc: float) -> str:
    if pc < 1e-6:
        return "noise"
    if pc < 1e-4:
        return "watch"
    return "action"


@router.get("/event/{event_id}")
def get_conjunction_event(
    event_id: str,
    store: EventStore = Depends(require_event_store),
) -> dict[str, object]:
    """Single event with latest Pc/miss from snapshots (for deep links from Memory)."""
    ev = store.get_event(event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="Unknown event_id")
    snap = store.get_latest_pc_snapshot(event_id)
    pc = float(snap.pc) if snap else ev.initial_pc
    miss_km = float(snap.miss_distance_km) if snap else ev.initial_miss_distance_km
    return {
        "id": ev.event_id,
        "obj1": {
            "norad_id": ev.obj1_norad_id,
            "name": ev.obj1_name,
            "type": "unknown",
        },
        "obj2": {
            "norad_id": ev.obj2_norad_id,
            "name": ev.obj2_name,
            "type": "unknown",
        },
        "tca": ev.tca.isoformat(),
        "miss_distance_km": miss_km,
        "relative_velocity_km_s": ev.relative_velocity_km_s,
        "pc": pc,
        "pc_band": _pc_band(pc),
        "detected_at": ev.last_seen_at.isoformat(),
        "status": ev.status,
        "initial_pc": ev.initial_pc,
    }


@router.get("/{event_id}/pc-history")
def get_pc_history_route(
    event_id: str,
    hours: int = Query(48, ge=1, le=24 * 14),
    store: EventStore = Depends(require_event_store),
) -> dict[str, object]:
    """Pc snapshots ordered oldest-first for charts."""
    if store.get_event(event_id) is None:
        raise HTTPException(status_code=404, detail="Unknown event_id")
    rows = store.get_pc_history(event_id, hours_back=hours)
    snapshots = [
        {
            "snapshot_at": r.snapshot_at.isoformat(),
            "pc": r.pc,
            "miss_distance_km": r.miss_distance_km,
            "covariance_inflation": r.covariance_inflation,
            "kp_index": r.kp_index,
            "space_weather_snapshot": r.space_weather_snapshot,
        }
        for r in rows
    ]
    return {"snapshots": snapshots}
