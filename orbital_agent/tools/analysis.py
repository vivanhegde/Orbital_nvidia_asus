"""Analysis MCP tools: re-propagation, Pc computation, maneuver simulation, plan evaluation."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from orbital_agent._paths import ensure_repo_on_path
from orbital_agent.tools._pydantic_models import Burn, DeltaV, ObjectStateInput

ensure_repo_on_path()

from orbital_data.store import get_tles, list_all_tles  # noqa: E402
from orbital_engine.maneuver import (  # noqa: E402
    evaluate_burn_against_conjunction,
    predict_post_burn_position_at,
    prograde_unit_vector,
    simulate_maneuver as _simulate_maneuver_engine,
)
from orbital_engine.models import PropagatedState  # noqa: E402
from orbital_engine.pc import compute_pc  # noqa: E402
from orbital_engine.propagation import propagate  # noqa: E402

_LOG = logging.getLogger(__name__)

# Pc bands (per design doc §4 thresholds)
PC_THRESHOLD_NOISE = 1e-6
PC_THRESHOLD_ACTION = 1e-4


def covariance_inflation_from_kp(kp: float) -> float:
    """Inflate position covariance when geomagnetic activity makes drag predictions noisier."""
    if kp < 5.0:
        return 1.0
    if kp < 6.0:
        return 1.18
    return 1.4


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"error": msg}
    out.update(extra)
    return out


def _find_tle(norad_id: int):
    """Find the most recent TLE for `norad_id` across all configured groups."""
    for tle in list_all_tles():
        if tle.norad_id == int(norad_id):
            return tle
    return None


def _state_to_json(s: PropagatedState) -> dict[str, Any]:
    return {
        "norad_id": s.norad_id,
        "t": s.t.astimezone(timezone.utc).isoformat(),
        "r_eci_km": list(s.r_eci) if s.r_eci else None,
        "v_eci_kms": list(s.v_eci) if s.v_eci else None,
        "error_code": s.error_code,
    }


def re_propagate(
    norad_id: int,
    at_iso: str | None = None,
) -> dict[str, Any]:
    """Force a fresh SGP4 propagation using the most recent TLE for `norad_id`.

    Use this when you suspect a stale TLE is producing a false-positive Pc.
    Returns the propagated state (position in km, velocity in km/s, ECI) at
    `at_iso` (UTC ISO timestamp; defaults to "now") plus TLE epoch age in hours.
    """
    when: datetime
    if at_iso:
        try:
            when = datetime.fromisoformat(at_iso.replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
        except ValueError:
            return _err(f"at_iso must be ISO-8601 UTC, got: {at_iso}")
    else:
        when = datetime.now(timezone.utc)

    tle = _find_tle(int(norad_id))
    if tle is None:
        return _err("TLE not found for that NORAD ID in the catalog", norad_id=norad_id)

    state = propagate(tle, when)
    age_h = (when - tle.epoch).total_seconds() / 3600.0
    return {
        "state": _state_to_json(state),
        "tle_epoch": tle.epoch.astimezone(timezone.utc).isoformat(),
        "tle_age_hours": age_h,
        "tle_name": tle.name,
        "tle_source_group": tle.source_group,
    }


def compute_collision_probability(
    obj1: ObjectStateInput,
    obj2: ObjectStateInput,
    covariance_inflation: float | None = None,
    kp_index: float | None = None,
) -> dict[str, Any]:
    """Compute the probability of collision (Pc) between two propagated states.

    Uses a 2D isotropic-Gaussian integration over a 5 m hard-body disc in the
    plane perpendicular to relative velocity. Standard 1-σ position uncertainty
    is 100 m for active payloads and 200 m for unknown/debris.

    Args:
        obj1, obj2: ObjectStateInput with norad_id, r_eci_km, v_eci_kms
        covariance_inflation: Multiplier on position uncertainty. If None,
            derived from kp_index via covariance_inflation_from_kp().
        kp_index: Current Kp; only used when covariance_inflation is None.

    Returns:
        {pc, pc_band ('noise'|'watch'|'action'), miss_distance_km,
         covariance_inflation_used, hard_body_radius_m}
    """
    if covariance_inflation is None:
        if kp_index is None:
            covariance_inflation = 1.0
        else:
            covariance_inflation = covariance_inflation_from_kp(kp_index)

    s1 = PropagatedState(
        norad_id=obj1.norad_id,
        t=datetime.now(timezone.utc),
        r_eci=(obj1.r_eci_km[0], obj1.r_eci_km[1], obj1.r_eci_km[2]),
        v_eci=(obj1.v_eci_kms[0], obj1.v_eci_kms[1], obj1.v_eci_kms[2]),
        error_code=0,
    )
    s2 = PropagatedState(
        norad_id=obj2.norad_id,
        t=datetime.now(timezone.utc),
        r_eci=(obj2.r_eci_km[0], obj2.r_eci_km[1], obj2.r_eci_km[2]),
        v_eci=(obj2.v_eci_kms[0], obj2.v_eci_kms[1], obj2.v_eci_kms[2]),
        error_code=0,
    )
    pc = compute_pc(s1, s2, covariance_inflation=covariance_inflation)

    miss_km = (
        sum((a - b) ** 2 for a, b in zip(obj1.r_eci_km, obj2.r_eci_km)) ** 0.5
    )

    if pc < PC_THRESHOLD_NOISE:
        band = "noise"
    elif pc < PC_THRESHOLD_ACTION:
        band = "watch"
    else:
        band = "action"

    return {
        "pc": pc,
        "pc_band": band,
        "miss_distance_km": miss_km,
        "covariance_inflation_used": covariance_inflation,
        "hard_body_radius_m": 5.0,
    }


def _direction_unit_vector(state: PropagatedState, direction: str) -> tuple[float, float, float]:
    """Convert a named burn direction into an ECI unit vector at this state."""
    import numpy as np

    if state.r_eci is None or state.v_eci is None:
        raise ValueError("State must have position and velocity")
    r = np.asarray(state.r_eci, dtype=np.float64)
    v = np.asarray(state.v_eci, dtype=np.float64)
    v_hat = v / np.linalg.norm(v)
    r_hat = r / np.linalg.norm(r)
    n_hat = np.cross(r_hat, v_hat)
    n_hat = n_hat / np.linalg.norm(n_hat)

    table = {
        "prograde": v_hat,
        "retrograde": -v_hat,
        "radial": r_hat,
        "anti-radial": -r_hat,
        "normal": n_hat,
        "anti-normal": -n_hat,
    }
    if direction not in table:
        raise ValueError(f"unknown direction {direction!r}")
    u = table[direction]
    return float(u[0]), float(u[1]), float(u[2])


def simulate_maneuver(
    norad_id: int,
    dv_mps: float,
    direction: str,
    burn_time_iso: str,
    look_ahead_hours: float = 24.0,
) -> dict[str, Any]:
    """Apply an impulsive Δv burn to an asset and return the resulting trajectory.

    The asset is SGP4-propagated to burn time, the Δv is added to its velocity,
    and the post-burn state is Kepler-propagated forward (two-body — no J2, no
    drag) for the look-ahead window.

    Args:
        norad_id: Asset to maneuver.
        dv_mps: Δv magnitude in m/s.
        direction: One of prograde / retrograde / radial / anti-radial / normal / anti-normal.
        burn_time_iso: UTC ISO timestamp of the burn.
        look_ahead_hours: How far forward to sample the post-burn trajectory.

    Returns:
        {pre_burn_state, post_burn_state, dv_magnitude_mps, samples:[...]}
    """
    try:
        burn_time = datetime.fromisoformat(burn_time_iso.replace("Z", "+00:00"))
        if burn_time.tzinfo is None:
            burn_time = burn_time.replace(tzinfo=timezone.utc)
    except ValueError:
        return _err(f"burn_time_iso must be ISO-8601 UTC, got: {burn_time_iso}")

    tle = _find_tle(int(norad_id))
    if tle is None:
        return _err("TLE not found for that NORAD ID", norad_id=norad_id)

    pre = propagate(tle, burn_time)
    if pre.r_eci is None:
        return _err("Pre-burn SGP4 propagation failed", error_code=pre.error_code)

    try:
        u = _direction_unit_vector(pre, direction)
    except ValueError as exc:
        return _err(str(exc))

    dv_kms = (u[0] * dv_mps / 1000.0, u[1] * dv_mps / 1000.0, u[2] * dv_mps / 1000.0)

    sample_times = [
        burn_time + timedelta(minutes=m)
        for m in (1, 10, 30, 60, 180, 360, 720, int(look_ahead_hours * 60))
        if m <= look_ahead_hours * 60
    ]
    return _simulate_maneuver_engine(tle, dv_kms, burn_time, sample_at=sample_times)


def evaluate_plan(
    asset_norad_id: int,
    burns: list[Burn],
    miss_threshold_km: float = 1.0,
) -> dict[str, Any]:
    """Score a maneuver plan against the asset's currently flagged conjunctions.

    For each upcoming conjunction event involving the asset (status='monitoring'),
    predicts the post-burn miss distance and reports whether the burn resolves
    that event (new miss >= miss_threshold_km).

    Args:
        asset_norad_id: NORAD ID of the maneuvering asset
        burns: Ordered burn sequence (Δv magnitude + direction + burn_time)
        miss_threshold_km: Minimum acceptable miss distance to call "resolved"

    Returns:
        {
          total_dv_mps: float,
          per_event: [{event_id, partner_norad_id, tca, new_miss_km, resolved}, ...],
          resolved_event_ids: [...],
          unresolved_event_ids: [...],
          notes: "..."
        }
    """
    if not burns:
        return _err("Plan must contain at least one burn")

    tle = _find_tle(int(asset_norad_id))
    if tle is None:
        return _err("TLE not found for asset", norad_id=asset_norad_id)

    # Resolve each burn's direction at its own burn time to an ECI Δv vector.
    burn_dvs: list[tuple[tuple[float, float, float], datetime]] = []
    for b in burns:
        pre = propagate(tle, b.burn_time)
        if pre.r_eci is None:
            return _err("Pre-burn propagation failed", burn_time=b.burn_time.isoformat())
        try:
            u = _direction_unit_vector(pre, b.direction)
        except ValueError as exc:
            return _err(str(exc), burn=b.model_dump_json())
        dv_kms = (u[0] * b.dv_mps / 1000.0, u[1] * b.dv_mps / 1000.0, u[2] * b.dv_mps / 1000.0)
        burn_dvs.append((dv_kms, b.burn_time))

    # Query memory for upcoming events involving this asset.
    from orbital_agent.tools.memory import _store
    store = _store()
    events = store.query_events_for_asset(int(asset_norad_id), limit=50)
    now = datetime.now(timezone.utc)
    upcoming = [e for e in events if e.tca > now and e.status == "monitoring"]

    per_event: list[dict[str, Any]] = []
    resolved: list[str] = []
    unresolved: list[str] = []

    for ev in upcoming:
        partner_norad = ev.obj2_norad_id if ev.obj1_norad_id == int(asset_norad_id) else ev.obj1_norad_id
        other_tle = _find_tle(partner_norad)
        if other_tle is None:
            per_event.append({
                "event_id": ev.event_id,
                "partner_norad_id": partner_norad,
                "tca": ev.tca.isoformat(),
                "skipped": True,
                "reason": f"no TLE for partner {partner_norad}",
            })
            continue
        result = evaluate_burn_against_conjunction(
            asset_tle=tle,
            burns=burn_dvs,
            other_tle=other_tle,
            tca=ev.tca,
            miss_threshold_km=miss_threshold_km,
        )
        if "error" in result:
            per_event.append({
                "event_id": ev.event_id,
                "partner_norad_id": partner_norad,
                "tca": ev.tca.isoformat(),
                "skipped": True,
                "reason": result["error"],
            })
            continue
        row = {
            "event_id": ev.event_id,
            "partner_norad_id": partner_norad,
            "partner_name": ev.obj2_name if ev.obj1_norad_id == int(asset_norad_id) else ev.obj1_name,
            "tca": ev.tca.isoformat(),
            "initial_pc": ev.initial_pc,
            "initial_miss_km": ev.initial_miss_distance_km,
            "new_miss_km": result["new_miss_km"],
            "resolved": result["resolved"],
        }
        per_event.append(row)
        if result["resolved"]:
            resolved.append(ev.event_id)
        else:
            unresolved.append(ev.event_id)

    total_dv_mps = float(sum(b.dv_mps for b in burns))
    return {
        "total_dv_mps": total_dv_mps,
        "per_event": per_event,
        "resolved_event_ids": resolved,
        "unresolved_event_ids": unresolved,
        "evaluated_event_count": len([p for p in per_event if not p.get("skipped")]),
        "skipped_event_count": len([p for p in per_event if p.get("skipped")]),
        "miss_threshold_km": miss_threshold_km,
    }
