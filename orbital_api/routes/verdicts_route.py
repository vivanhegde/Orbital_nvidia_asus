"""Operator verdict queue and decisions.

The /pending endpoint returns "Conjunction Assessment Report"-shaped data:
each pending verdict carries the conjunction event, latest refined Pc,
both objects' profiles (SATCAT + operator notes), current space weather,
prior-event history for the primary asset, and refinement metadata.

Filter: only verdict types that need a human decision (`recommended` or the
legacy `recommend_maneuver` from synthesize) appear. `dismissed`/`watch`
verdicts are agent-internal and stay in memory; the Memory tab surfaces
them, not the Approver queue.

Cap: top 20 most recent. Enrichment is O(verdicts × constant), and with
real screening + the runner producing one verdict per minute this would
slow the page quickly without a cap.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from orbital_api.deps import require_event_store
from orbital_persist.store import EventStore

_LOG = logging.getLogger(__name__)

# Make sure orbital_data is importable (it uses `from fetchers import ...`)
_ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (_ROOT / "orbital_data", _ROOT):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from orbital_data.store import (  # noqa: E402
    cache_dir,
    get_satcat_record,
    get_space_weather,
)

router = APIRouter(prefix="/api/verdicts", tags=["verdicts"])

# Verdict types that show up in the Approver queue (operator action required).
_HUMAN_ACTION_VERDICTS = {"recommended", "recommend_maneuver"}

# Max pending verdicts to enrich per request — keeps response time bounded
# when the runner has produced a backlog.
_PENDING_LIMIT = 20


# ── Asset profile cache (operator-supplied data layered on top of SATCAT) ──

_PROFILES_CACHE: dict[int, dict[str, Any]] | None = None


def _asset_profiles() -> dict[int, dict[str, Any]]:
    global _PROFILES_CACHE
    if _PROFILES_CACHE is not None:
        return _PROFILES_CACHE
    path = cache_dir() / "asset_profiles.json"
    if not path.is_file():
        _PROFILES_CACHE = {}
        return _PROFILES_CACHE
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        _PROFILES_CACHE = {int(k): v for k, v in raw.get("assets", {}).items()}
    except (OSError, ValueError, KeyError) as exc:
        _LOG.warning("Could not parse asset_profiles.json (%s); using empty dict", exc)
        _PROFILES_CACHE = {}
    return _PROFILES_CACHE


def _object_profile(norad_id: int, fallback_name: str | None) -> dict[str, Any]:
    """SATCAT + operator profile merged into the shape the UI expects."""
    rec = None
    try:
        rec = get_satcat_record(int(norad_id))
    except Exception as exc:  # noqa: BLE001
        _LOG.debug("SATCAT lookup failed for %s: %s", norad_id, exc)
    profile = _asset_profiles().get(int(norad_id), {})

    name = (rec.object_name if rec else None) or fallback_name
    out: dict[str, Any] = {
        "norad_id": int(norad_id),
        "name": name,
        "country": rec.country if rec else None,
        "object_type": rec.object_type if rec else None,
        "launch_date": rec.launch_date.isoformat() if rec and rec.launch_date else None,
        "inclination_deg": rec.inclination if rec else None,
        "period_min": rec.period if rec else None,
        "is_maneuverable": profile.get("is_maneuverable"),
        "fuel_remaining_mps": profile.get("fuel_remaining_mps"),
        "mission_criticality": profile.get("mission_criticality"),
        "operator": profile.get("operator"),
    }
    # Fallback heuristic: debris and rocket bodies are non-maneuverable.
    if out["is_maneuverable"] is None and rec is not None:
        kind = (rec.object_type or "").upper()
        if "DEB" in kind or "R/B" in kind:
            out["is_maneuverable"] = False
    return out


# ── Plan-shape translation (agent format → UI format) ─────────────────────

def _translate_plan(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Convert any stored plan blob into the SyntheticPlanPayload shape the UI renders.

    The DB stores two slightly different plan shapes:

    (1) Agent-written (via draft_recommendation):
        {asset_id, urgency, primary_plan: {name, burns: [{dv_mps, direction, burn_time}],
         total_dv_mps, conjunctions_resolved}, alternative_plans: [...], reasoning}

    (2) Synthetic demo (via /api/dev/synthesize-verdict):
        Already in UI shape: {recommended, plans: {A, B}, urgency}

    The UI shape is:
        {recommended: str, plans: {<label>: ManeuverPlanOption}, urgency?: str}
    """
    if not raw or not isinstance(raw, dict):
        return None

    # Case (2): already in the UI shape
    if "plans" in raw and isinstance(raw["plans"], dict):
        return raw

    # Case (1): agent-written → translate
    primary = raw.get("primary_plan")
    if not primary or not isinstance(primary, dict):
        return None

    plans: dict[str, Any] = {}
    primary_key = primary.get("name") or "primary"
    plans[primary_key] = _plan_option_from_agent(primary)

    for i, alt in enumerate(raw.get("alternative_plans") or []):
        if not isinstance(alt, dict):
            continue
        key = alt.get("name") or f"alternative_{i + 1}"
        # Keys must be unique
        if key in plans:
            key = f"{key}_{i + 1}"
        plans[key] = _plan_option_from_agent(alt)

    return {
        "recommended": primary_key,
        "plans": plans,
        "urgency": raw.get("urgency"),
    }


def _plan_option_from_agent(plan: dict[str, Any]) -> dict[str, Any]:
    burns = plan.get("burns") or []
    burns_ms: list[float] = []
    for b in burns:
        if isinstance(b, dict) and isinstance(b.get("dv_mps"), (int, float)):
            burns_ms.append(float(b["dv_mps"]))
    resolved = plan.get("conjunctions_resolved") or []
    return {
        "label": str(plan.get("name") or "Plan"),
        "burns_ms": burns_ms,
        "total_delta_v_ms": float(plan["total_dv_mps"])
        if isinstance(plan.get("total_dv_mps"), (int, float))
        else None,
        "events_resolved": len(resolved) if isinstance(resolved, list) else None,
    }


# ── Enrichment ─────────────────────────────────────────────────────────────

def _enrich_verdict(store: EventStore, verdict_id: str) -> dict[str, Any] | None:
    v = store.get_verdict(verdict_id)
    if v is None:
        return None
    ev = store.get_event(v.event_id)
    snap = store.get_latest_pc_snapshot(v.event_id) if ev else None

    out: dict[str, Any] = {
        "verdict_id": v.verdict_id,
        "event_id": v.event_id,
        "issued_at": v.issued_at.isoformat(),
        "verdict_type": v.verdict_type,
        "reasoning": v.reasoning,
        "plan": _translate_plan(v.plan_json),
        "operator_decision": v.operator_decision,
        "operator_decided_at": v.operator_decided_at.isoformat() if v.operator_decided_at else None,
        "operator_notes": v.operator_notes,
    }

    if ev is None:
        return out

    out["event"] = {
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
    out["current_pc"] = float(snap.pc) if snap else float(ev.initial_pc)
    out["current_miss_km"] = float(snap.miss_distance_km) if snap else float(ev.initial_miss_distance_km)

    if snap is not None:
        out["refinement"] = {
            "covariance_inflation": float(snap.covariance_inflation),
            "kp_index": float(snap.kp_index) if snap.kp_index is not None else None,
        }

    out["obj1_profile"] = _object_profile(ev.obj1_norad_id, ev.obj1_name)
    out["obj2_profile"] = _object_profile(ev.obj2_norad_id, ev.obj2_name)

    # Current space weather (best effort — don't fail the whole request)
    try:
        sw = get_space_weather()
        out["space_weather"] = sw.to_json_dict()
    except Exception as exc:  # noqa: BLE001
        _LOG.debug("space-weather lookup failed for verdict %s: %s", verdict_id, exc)
        out["space_weather"] = None

    # Asset history: prior events for the primary asset that already have a verdict.
    # The operator cares about "what did we decide before for this satellite?", not
    # raw screening noise.
    history_norad = ev.obj1_norad_id
    prior = store.query_events_for_asset(history_norad, limit=10)
    pending_by_event = {pv.event_id for pv in store.list_pending_verdicts()}
    history: list[dict[str, Any]] = []
    for prev in prior:
        if prev.event_id == ev.event_id:
            continue
        # Include events that have ANY verdict (pending or operator-decided).
        # Cheap approximation: anything that isn't in the still-fully-pending
        # queue can be assumed to have either operator-decided or be processed.
        has_verdict = (
            prev.event_id in pending_by_event
            or store.get_event(prev.event_id) is not None  # always true; just doc
        )
        # Tighten further: actually look up a verdict for this prior event.
        had_decision = bool(_any_verdict_for(store, prev.event_id))
        if not had_decision:
            continue
        _ = has_verdict  # silence linter; logical path retained for clarity
        history.append(
            {
                "event_id": prev.event_id,
                "obj1_name": prev.obj1_name,
                "obj2_name": prev.obj2_name,
                "tca": prev.tca.isoformat(),
                "initial_pc": prev.initial_pc,
                "status": prev.status,
            }
        )
        if len(history) >= 5:
            break
    out["asset_history"] = history

    return out


def _any_verdict_for(store: EventStore, event_id: str) -> bool:
    """Cheap existence check — does ANY verdict row reference this event?"""
    with store._lock:  # noqa: SLF001
        cur = store._conn.cursor()  # noqa: SLF001
        cur.execute("SELECT 1 FROM verdicts WHERE event_id = ? LIMIT 1", (event_id,))
        return cur.fetchone() is not None


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("/pending")
def verdicts_pending(
    store: EventStore = Depends(require_event_store),
) -> dict[str, object]:
    pending = store.list_pending_verdicts()
    # Filter to verdict types that need operator action, cap at the limit,
    # most-recent-issued first.
    actionable = [v for v in pending if v.verdict_type in _HUMAN_ACTION_VERDICTS]
    actionable.sort(key=lambda v: v.issued_at, reverse=True)
    actionable = actionable[:_PENDING_LIMIT]

    verdicts: list[dict[str, Any]] = []
    for v in actionable:
        enriched = _enrich_verdict(store, v.verdict_id)
        if enriched:
            verdicts.append(enriched)
    return {"verdicts": verdicts}


@router.get("/decided")
def verdicts_decided(
    limit: int = Query(50, ge=1, le=200),
    store: EventStore = Depends(require_event_store),
) -> dict[str, object]:
    """Verdicts already decided by the operator (approved or rejected).

    Used by the Memory tab's decision log. Reuses the same enrichment as
    the pending endpoint so the UI can render the same AssessmentReport
    shape if it wants — but the row layout in Memory is more compact.
    """
    decided = store.list_decided_verdicts(limit=limit)
    out: list[dict[str, Any]] = []
    for v in decided:
        enriched = _enrich_verdict(store, v.verdict_id)
        if enriched:
            out.append(enriched)
    return {"verdicts": out}


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
