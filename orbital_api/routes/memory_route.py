"""Memory / operator event list routes backed by SQLite."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from orbital_api.deps import require_event_store
from orbital_persist.store import EventStore

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/recent")
def memory_recent(
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None, description="Optional status filter"),
    store: EventStore = Depends(require_event_store),
) -> dict[str, object]:
    events = store.query_recent_events(limit=limit, status=status)
    out = []
    for e in events:
        out.append(
            {
                "event_id": e.event_id,
                "obj1_name": e.obj1_name,
                "obj2_name": e.obj2_name,
                "obj1_norad_id": e.obj1_norad_id,
                "obj2_norad_id": e.obj2_norad_id,
                "tca": e.tca.isoformat(),
                "initial_pc": e.initial_pc,
                "status": e.status,
                "last_seen_at": e.last_seen_at.isoformat(),
                "first_detected_at": e.first_detected_at.isoformat(),
            }
        )
    return {"events": out}


@router.get("/asset/{norad_id}")
def memory_asset(
    norad_id: int,
    limit: int = Query(20, ge=1, le=100),
    store: EventStore = Depends(require_event_store),
) -> dict[str, object]:
    events = store.query_events_for_asset(norad_id, limit=limit)
    rows: list[dict[str, object]] = []
    for e in events:
        if e.obj1_norad_id == norad_id:
            partner_name = e.obj2_name
            partner_norad = e.obj2_norad_id
        else:
            partner_name = e.obj1_name
            partner_norad = e.obj1_norad_id
        rows.append(
            {
                "event_id": e.event_id,
                "partner_name": partner_name,
                "partner_norad_id": partner_norad,
                "tca": e.tca.isoformat(),
                "initial_pc": e.initial_pc,
                "status": e.status,
                "last_seen_at": e.last_seen_at.isoformat(),
                "obj1_name": e.obj1_name,
                "obj2_name": e.obj2_name,
            }
        )
    return {"norad_id": norad_id, "events": rows}
