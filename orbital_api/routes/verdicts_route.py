"""Operator verdict queue and decisions."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from orbital_api.deps import require_event_store
from orbital_engine._paths import ensure_orbital_data_on_path
from orbital_persist.store import EventStore

ensure_orbital_data_on_path()

from store import get_satcat_record, get_space_weather  # noqa: E402

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/api/verdicts", tags=["verdicts"])


def _object_profile(norad_id: int) -> dict[str, Any]:
    """Build object profile from SATCAT + asset_profiles cache."""
    import json
    from pathlib import Path

    out: dict[str, Any] = {"norad_id": norad_id}
    rec = None
    try:
        rec = get_satcat_record(norad_id)
    except Exception:
        pass
    if rec:
        out["name"] = rec.object_name
        out["country"] = rec.country
        out["object_type"] = rec.object_type
        out["launch_date"] = rec.launch_date.isoformat() if rec.launch_date else None
        out["inclination_deg"] = rec.inclination
        out["period_min"] = rec.period
    else:
        out["name"] = None
        out["object_type"] = None

    profiles_path = Path(__file__).resolve().parent.parent.parent / "orbital_data" / "cache" / "asset_profiles.json"
    profile: dict[str, Any] | None = None
    if profiles_path.is_file():
        try:
            with profiles_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            assets = raw.get("assets", {})
            profile = assets.get(str(norad_id))
        except (OSError, ValueError):
            pass

    if profile:
        out["is_maneuverable"] = bool(profile.get("is_maneuverable", False))
        out["fuel_remaining_mps"] = profile.get("fuel_remaining_mps")
        out["mission_criticality"] = profile.get("mission_criticality")
        out["operator"] = profile.get("operator")
    else:
        kind = (out.get("object_type") or "").upper()
        out["is_maneuverable"] = False if ("DEB" in kind or "R/B" in kind) else None
        out["fuel_remaining_mps"] = None
        out["mission_criticality"] = None
        out["operator"] = None

    return out


def _space_weather_snapshot() -> dict[str, Any] | None:
    """Get current space weather, returns None on failure."""
    try:
        sw = get_space_weather()
        return sw.to_json_dict()
    except Exception:
        return None


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
            "miss_distance_km": ev.initial_miss_distance_km,
            "relative_velocity_km_s": ev.relative_velocity_km_s,
            "initial_pc": ev.initial_pc,
            "first_detected_at": ev.first_detected_at.isoformat(),
        }
        m["current_pc"] = pc
        if miss_km is not None:
            m["current_miss_km"] = miss_km

        m["obj1_profile"] = _object_profile(ev.obj1_norad_id)
        m["obj2_profile"] = _object_profile(ev.obj2_norad_id)

        m["space_weather"] = _space_weather_snapshot()

        if snap:
            m["refinement"] = {
                "covariance_inflation": snap.covariance_inflation,
                "kp_index": snap.kp_index,
            }

        history = store.query_events_for_asset(ev.obj1_norad_id, limit=10)
        m["asset_history"] = [
            {
                "event_id": h.event_id,
                "obj1_name": h.obj1_name,
                "obj2_name": h.obj2_name,
                "tca": h.tca.isoformat(),
                "initial_pc": h.initial_pc,
                "status": h.status,
            }
            for h in history
            if h.event_id != ev.event_id
        ][:5]

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
