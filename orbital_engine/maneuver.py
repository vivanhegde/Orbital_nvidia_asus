"""Impulsive Δv burns + two-body Keplerian propagation for maneuver simulation.

Hackathon-grade: applies an instantaneous Δv to a propagated state, then
propagates forward via two-body Kepler dynamics (no J2, no drag) to predict
the asset's post-burn trajectory. The other object in each conjunction stays
on its SGP4 trajectory (we don't touch its TLE).

For evaluating a burn against an upcoming conjunction: propagate both objects
to TCA — the asset via SGP4 to the burn time, then Kepler from the burned
state to TCA; the other object via SGP4 from its TLE to TCA — and compute
the new miss distance.

References: Vallado, "Fundamentals of Astrodynamics and Applications", §2.3
(universal variable Kepler propagation, Stumpff functions).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np

from orbital_engine._paths import ensure_orbital_data_on_path
from orbital_engine.models import PropagatedState
from orbital_engine.propagation import propagate

ensure_orbital_data_on_path()
from models import TLE  # noqa: E402

_MU_KM3S2 = 398_600.4418  # Earth GM


def apply_burn(
    state: PropagatedState,
    dv_eci_kms: tuple[float, float, float],
    at_time: datetime,
) -> PropagatedState:
    """Return a new state with `dv_eci_kms` added to its velocity at `at_time`.

    `state` must already be propagated to `at_time` (caller's responsibility).
    The burn is treated as instantaneous (impulsive) — position is unchanged,
    velocity gets `dv` added.
    """
    if state.r_eci is None or state.v_eci is None:
        raise ValueError("Cannot apply burn to a state with no position/velocity")
    new_v = (
        state.v_eci[0] + dv_eci_kms[0],
        state.v_eci[1] + dv_eci_kms[1],
        state.v_eci[2] + dv_eci_kms[2],
    )
    return PropagatedState(
        norad_id=state.norad_id,
        t=at_time.astimezone(timezone.utc),
        r_eci=state.r_eci,
        v_eci=new_v,
        error_code=0,
    )


def prograde_unit_vector(state: PropagatedState) -> tuple[float, float, float]:
    """Unit vector along the orbital velocity (prograde direction in ECI)."""
    if state.v_eci is None:
        raise ValueError("State has no velocity")
    v = np.asarray(state.v_eci, dtype=np.float64)
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise ValueError("Velocity is degenerate")
    return float(v[0] / n), float(v[1] / n), float(v[2] / n)


def _stumpff_c2c3(psi: float) -> tuple[float, float]:
    """Stumpff functions c2(ψ), c3(ψ) used by the universal-variable Kepler solver."""
    if psi > 1e-6:
        s = math.sqrt(psi)
        c2 = (1.0 - math.cos(s)) / psi
        c3 = (s - math.sin(s)) / (psi * s)
    elif psi < -1e-6:
        s = math.sqrt(-psi)
        c2 = (1.0 - math.cosh(s)) / psi
        c3 = (math.sinh(s) - s) / ((-psi) * s)
    else:
        # Series expansion near 0 to keep numerical stability.
        c2 = 0.5 - psi / 24.0 + psi * psi / 720.0
        c3 = 1.0 / 6.0 - psi / 120.0 + psi * psi / 5040.0
    return c2, c3


def kepler_propagate(state: PropagatedState, dt_seconds: float) -> PropagatedState:
    """Two-body Keplerian propagation of `state` by `dt_seconds`.

    Used post-burn since the asset's TLE no longer reflects its new orbit.
    Pure two-body: no J2, no drag, no perturbations. Acceptable for the
    demo's hours-to-days timescales where we just need a credible
    "where would the asset be?" answer.
    """
    if state.r_eci is None or state.v_eci is None:
        return state
    if dt_seconds == 0.0:
        return state

    r0 = np.asarray(state.r_eci, dtype=np.float64)
    v0 = np.asarray(state.v_eci, dtype=np.float64)
    r0_norm = float(np.linalg.norm(r0))
    v0_norm = float(np.linalg.norm(v0))
    if r0_norm < 1e-6:
        return state

    alpha = 2.0 / r0_norm - v0_norm * v0_norm / _MU_KM3S2
    sqrt_mu = math.sqrt(_MU_KM3S2)
    rd_v = float(np.dot(r0, v0))

    # Initial guess for the universal variable χ.
    if alpha > 1e-12:                   # bound (elliptical) orbit
        chi = sqrt_mu * dt_seconds * alpha
    elif abs(alpha) < 1e-12:            # parabolic — unlikely for LEO, fallback
        chi = sqrt_mu * dt_seconds / r0_norm
    else:                               # hyperbolic — defensive only
        a = 1.0 / alpha
        sign = 1.0 if dt_seconds >= 0 else -1.0
        # Vallado eq. 2-110 initial estimate
        chi = sign * math.sqrt(-a) * math.log(
            max(1e-12, abs(-2.0 * _MU_KM3S2 * alpha * dt_seconds
                           / (rd_v + sign * math.sqrt(-_MU_KM3S2 * a)
                              * (1.0 - r0_norm * alpha))))
        )

    # Newton iteration. `residual` is F(χ) - sqrt(μ)·Δt; we want it zero.
    # dF/dχ = r(χ), so the Newton step is χ -= residual / r.
    converged = False
    for _ in range(100):
        psi = chi * chi * alpha
        c2, c3 = _stumpff_c2c3(psi)
        r_norm = (
            chi * chi * c2
            + (rd_v / sqrt_mu) * chi * (1.0 - psi * c3)
            + r0_norm * (1.0 - psi * c2)
        )
        residual = (
            (rd_v / sqrt_mu) * chi * chi * c2
            + (1.0 - r0_norm * alpha) * chi * chi * chi * c3
            + r0_norm * chi
            - sqrt_mu * dt_seconds
        )
        if abs(residual) < 1e-7:
            converged = True
            break
        chi = chi - residual / max(r_norm, 1e-9)

    psi = chi * chi * alpha
    c2, c3 = _stumpff_c2c3(psi)
    f = 1.0 - (chi * chi / r0_norm) * c2
    g = dt_seconds - (chi * chi * chi / sqrt_mu) * c3
    r = f * r0 + g * v0
    r_norm_final = float(np.linalg.norm(r))
    if r_norm_final < 1e-6:
        return state
    fdot = (sqrt_mu / (r0_norm * r_norm_final)) * chi * (psi * c3 - 1.0)
    gdot = 1.0 - (chi * chi / r_norm_final) * c2
    v = fdot * r0 + gdot * v0

    return PropagatedState(
        norad_id=state.norad_id,
        t=datetime.fromtimestamp(state.t.timestamp() + dt_seconds, tz=timezone.utc),
        r_eci=(float(r[0]), float(r[1]), float(r[2])),
        v_eci=(float(v[0]), float(v[1]), float(v[2])),
        error_code=0 if converged else -2,
    )


def simulate_maneuver(
    asset_tle: TLE,
    dv_eci_kms: tuple[float, float, float],
    burn_time: datetime,
    sample_at: list[datetime] | None = None,
) -> dict:
    """Propagate `asset_tle` via SGP4 to `burn_time`, apply Δv, then return
    the post-burn state plus optional samples at `sample_at` times via Kepler.

    Returns:
        {
          'pre_burn_state':  {r_eci, v_eci, t},
          'post_burn_state': {r_eci, v_eci, t},
          'dv_magnitude_mps': float,
          'samples': [{r_eci, v_eci, t}, ...]   # only if sample_at provided
        }
    """
    pre = propagate(asset_tle, burn_time)
    if pre.r_eci is None or pre.v_eci is None:
        return {"error": "pre-burn propagation failed", "error_code": pre.error_code}
    post = apply_burn(pre, dv_eci_kms, burn_time)
    out: dict = {
        "pre_burn_state": _state_to_json(pre),
        "post_burn_state": _state_to_json(post),
        "dv_magnitude_mps": float(np.linalg.norm(dv_eci_kms)) * 1000.0,
    }
    if sample_at:
        samples = []
        t0 = burn_time.astimezone(timezone.utc)
        for t in sample_at:
            dt = (t.astimezone(timezone.utc) - t0).total_seconds()
            if dt < 0:
                continue
            s = kepler_propagate(post, dt)
            samples.append(_state_to_json(s))
        out["samples"] = samples
    return out


def predict_post_burn_position_at(
    asset_tle: TLE,
    burns: list[tuple[tuple[float, float, float], datetime]],
    when: datetime,
) -> PropagatedState | None:
    """Return the asset's predicted state at `when`, applying `burns` in order.

    Algorithm: SGP4-propagate to the first burn time, apply Δv, Kepler to the
    next burn time, apply its Δv, ... Kepler to `when`. Returns None if the
    SGP4 step fails. Pre-`when` burns only; burns at or after `when` are
    silently skipped because they don't affect position at `when`.
    """
    when_utc = when.astimezone(timezone.utc)
    sorted_burns = sorted(
        ((dv, t.astimezone(timezone.utc)) for dv, t in burns), key=lambda x: x[1]
    )
    state: PropagatedState | None = None
    cursor: datetime | None = None
    for dv, t_burn in sorted_burns:
        if t_burn > when_utc:
            break
        if state is None:
            state = propagate(asset_tle, t_burn)
            if state.r_eci is None:
                return None
        else:
            assert cursor is not None
            state = kepler_propagate(state, (t_burn - cursor).total_seconds())
        state = apply_burn(state, dv, t_burn)
        cursor = t_burn

    if state is None:
        return propagate(asset_tle, when_utc)
    assert cursor is not None
    if when_utc <= cursor:
        return state
    return kepler_propagate(state, (when_utc - cursor).total_seconds())


def evaluate_burn_against_conjunction(
    asset_tle: TLE,
    burns: list[tuple[tuple[float, float, float], datetime]],
    other_tle: TLE,
    tca: datetime,
    miss_threshold_km: float = 1.0,
) -> dict:
    """Compute the new miss distance at `tca` after `burns` are applied to the asset.

    Returns:
        {
          'new_miss_km': float,
          'resolved': bool,            # new miss >= miss_threshold_km
          'asset_state_at_tca':  {...},
          'other_state_at_tca':  {...},
        }
        Or {'error': '...'} if propagation fails.
    """
    asset_state = predict_post_burn_position_at(asset_tle, burns, tca)
    if asset_state is None or asset_state.r_eci is None:
        return {"error": "asset propagation failed"}
    other_state = propagate(other_tle, tca)
    if other_state.r_eci is None:
        return {"error": "other-object propagation failed"}
    r1 = np.asarray(asset_state.r_eci, dtype=np.float64)
    r2 = np.asarray(other_state.r_eci, dtype=np.float64)
    new_miss = float(np.linalg.norm(r1 - r2))
    return {
        "new_miss_km": new_miss,
        "resolved": new_miss >= miss_threshold_km,
        "asset_state_at_tca": _state_to_json(asset_state),
        "other_state_at_tca": _state_to_json(other_state),
    }


def _state_to_json(s: PropagatedState) -> dict:
    return {
        "norad_id": s.norad_id,
        "t": s.t.astimezone(timezone.utc).isoformat(),
        "r_eci_km": list(s.r_eci) if s.r_eci else None,
        "v_eci_kms": list(s.v_eci) if s.v_eci else None,
        "error_code": s.error_code,
    }
