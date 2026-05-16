"""SGP4 propagation for :class:`models.TLE` instances (orbital data layer)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sgp4.api import WGS72, Satrec, jday

from orbital_engine._paths import ensure_orbital_data_on_path
from orbital_engine.models import PropagatedState

ensure_orbital_data_on_path()

from models import TLE  # noqa: E402

_GRAVITY = WGS72


def _require_utc_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware (UTC)")
    return dt.astimezone(timezone.utc)


def _jd_fr_utc(dt: datetime) -> tuple[float, float]:
    dt = _require_utc_aware(dt)
    return jday(
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second + dt.microsecond * 1e-6,
    )


def _satrec_from_tle(tle: TLE) -> Satrec:
    return Satrec.twoline2rv(tle.line1, tle.line2, _GRAVITY)


def propagate(tle: TLE, when: datetime) -> PropagatedState:
    """
    Propagate ``tle`` with SGP4 to ``when`` (UTC).

    Returns:
        :class:`~orbital_engine.models.PropagatedState` with position and
        velocity in km and km/s (TEME frame used by ``sgp4``, treated as
        ECI for screening). On SGP4 or TLE initialization failure, ``r_eci``
        and ``v_eci`` are ``None`` and ``error_code`` is non-zero.
    """
    when = _require_utc_aware(when)
    try:
        sat = _satrec_from_tle(tle)
    except (ValueError, RuntimeError, TypeError):
        return PropagatedState(
            norad_id=tle.norad_id,
            t=when,
            r_eci=None,
            v_eci=None,
            error_code=-1,
        )
    jd, fr = _jd_fr_utc(when)
    ec, r, v = sat.sgp4(jd, fr)
    if ec != 0:
        return PropagatedState(
            norad_id=tle.norad_id,
            t=when,
            r_eci=None,
            v_eci=None,
            error_code=int(ec),
        )
    return PropagatedState(
        norad_id=tle.norad_id,
        t=when,
        r_eci=(float(r[0]), float(r[1]), float(r[2])),
        v_eci=(float(v[0]), float(v[1]), float(v[2])),
        error_code=0,
    )


def propagate_batch(tles: list[TLE], when: datetime) -> list[PropagatedState]:
    """
    Propagate many TLEs at the same instant.

    Returns:
        States aligned with ``tles``. Reuses one Julian date tuple; SGP4
        itself is invoked once per object (scalar API).
    """
    when = _require_utc_aware(when)
    jd, fr = _jd_fr_utc(when)
    out: list[PropagatedState] = []
    for tle in tles:
        try:
            sat = _satrec_from_tle(tle)
        except (ValueError, RuntimeError, TypeError):
            out.append(
                PropagatedState(
                    norad_id=tle.norad_id,
                    t=when,
                    r_eci=None,
                    v_eci=None,
                    error_code=-1,
                )
            )
            continue
        ec, r, v = sat.sgp4(jd, fr)
        if ec != 0:
            out.append(
                PropagatedState(
                    norad_id=tle.norad_id,
                    t=when,
                    r_eci=None,
                    v_eci=None,
                    error_code=int(ec),
                )
            )
        else:
            out.append(
                PropagatedState(
                    norad_id=tle.norad_id,
                    t=when,
                    r_eci=(float(r[0]), float(r[1]), float(r[2])),
                    v_eci=(float(v[0]), float(v[1]), float(v[2])),
                    error_code=0,
                )
            )
    return out


def propagate_timeseries(
    tle: TLE,
    t_start: datetime,
    t_end: datetime,
    step_seconds: int,
) -> list[PropagatedState]:
    """
    Sample one object's trajectory at a fixed cadence.

    Returns:
        States from ``t_start`` through ``t_end`` inclusive.
    """
    if step_seconds <= 0:
        raise ValueError("step_seconds must be positive")
    t_start = _require_utc_aware(t_start)
    t_end = _require_utc_aware(t_end)
    if t_end < t_start:
        raise ValueError("t_end must be >= t_start")
    try:
        sat = _satrec_from_tle(tle)
    except (ValueError, RuntimeError, TypeError):
        return []

    out: list[PropagatedState] = []
    t = t_start
    step = timedelta(seconds=step_seconds)
    while t <= t_end:
        jd, fr = _jd_fr_utc(t)
        ec, r, v = sat.sgp4(jd, fr)
        if ec != 0:
            out.append(
                PropagatedState(
                    norad_id=tle.norad_id,
                    t=t,
                    r_eci=None,
                    v_eci=None,
                    error_code=int(ec),
                )
            )
        else:
            out.append(
                PropagatedState(
                    norad_id=tle.norad_id,
                    t=t,
                    r_eci=(float(r[0]), float(r[1]), float(r[2])),
                    v_eci=(float(v[0]), float(v[1]), float(v[2])),
                    error_code=0,
                )
            )
        t = t + step
    return out
