"""Close-approach screening over a catalog and time window."""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np

from orbital_engine._paths import ensure_orbital_data_on_path
from orbital_engine.models import ConjunctionCandidate

ensure_orbital_data_on_path()
from models import TLE  # noqa: E402

from orbital_engine.propagation import propagate, propagate_batch  # noqa: E402

_MU_KM3S2 = 398600.4418
_EARTH_RADIUS_KM = 6378.137
_REFINE_HALF_S = 60
_REFINE_STEP_S = 1


def _parse_tle_altitude_band_km(line2: str) -> tuple[float, float, float]:  # hp, ha, inc_deg
    parts = line2.split()
    if len(parts) < 8:
        raise ValueError("line2 too short")
    inc = float(parts[2])
    ecc_tok = parts[4]
    if ecc_tok.startswith("."):
        ecc = float(ecc_tok)
    else:
        ecc = float("0." + ecc_tok.lstrip())
    n_rev_day = float(parts[7])
    n_rad_s = n_rev_day * 2.0 * math.pi / 86400.0
    if n_rad_s <= 0.0:
        raise ValueError("invalid mean motion")
    a_km = (_MU_KM3S2 / (n_rad_s**2)) ** (1.0 / 3.0)
    rp_km = a_km * (1.0 - ecc)
    ra_km = a_km * (1.0 + ecc)
    hp = rp_km - _EARTH_RADIUS_KM
    ha = ra_km - _EARTH_RADIUS_KM
    return hp, ha, inc


def _altitude_overlap(hp1: float, ha1: float, hp2: float, ha2: float, thresh_km: float) -> bool:
    """True if altitudes might come within ``thresh_km`` (vertical clearance filter)."""
    if ha1 < hp2 - thresh_km:
        return False
    if ha2 < hp1 - thresh_km:
        return False
    return True


def _prefilter_pair_indices(
    catalog: list[TLE],
    miss_distance_threshold_km: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return index arrays ``i < j`` that passaltitude-band pre-filtering."""
    n = len(catalog)
    bands: list[tuple[float, float, float]] = []
    for tle in catalog:
        try:
            bands.append(_parse_tle_altitude_band_km(tle.line2))
        except (ValueError, IndexError):
            bands.append((-math.inf, math.inf, 0.0))
    ii_list: list[int] = []
    jj_list: list[int] = []
    for i in range(n):
        hp_i, ha_i, _inc_i = bands[i]
        for j in range(i + 1, n):
            hp_j, ha_j, _inc_j = bands[j]
            if _altitude_overlap(hp_i, ha_i, hp_j, ha_j, miss_distance_threshold_km):
                ii_list.append(i)
                jj_list.append(j)
    return np.asarray(ii_list, dtype=np.int32), np.asarray(jj_list, dtype=np.int32)


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("require timezone-aware UTC")
    return dt.astimezone(timezone.utc)


def _label_for(
    tle: TLE,
    satcat_names: dict[int, str] | None,
) -> str:
    if satcat_names and tle.norad_id in satcat_names:
        return satcat_names[tle.norad_id]
    return tle.name.strip()


def prefilter_pair_count(
    catalog: list[TLE],
    miss_distance_threshold_km: float,
    catalog_filter: list[str] | None = None,
) -> int:
    """Return the number of index pairs ``i<j`` kept by altitude pre-filtering."""
    cat = list(catalog)
    if catalog_filter is not None:
        allow = set(catalog_filter)
        cat = [t for t in cat if t.source_group in allow]
    if len(cat) < 2:
        return 0
    ii, jj = _prefilter_pair_indices(cat, miss_distance_threshold_km)
    return int(ii.shape[0])


def screen_conjunctions(
    catalog: list[TLE],
    t_start: datetime,
    t_end: datetime,
    step_seconds: int = 60,
    miss_distance_threshold_km: float = 5.0,
    pre_filter: bool = True,
    catalog_filter: list[str] | None = None,
    satcat_names: dict[int, str] | None = None,
) -> list[ConjunctionCandidate]:
    """
    Coarse time grid plus local refinement for conjunction candidates.

    Returns:
        :class:`ConjunctionCandidate` rows sorted by ``miss_distance_km``
        ascending.

    Notes:
        Pairwise distance magnitudes use ``numpy`` on pre-filtered index
        lists. No console logging here.
    """
    t_start = _utc(t_start)
    t_end = _utc(t_end)
    if t_end < t_start:
        raise ValueError("t_end must be >= t_start")
    if step_seconds <= 0:
        raise ValueError("step_seconds must be positive")

    cat = list(catalog)
    if catalog_filter is not None:
        allow = set(catalog_filter)
        cat = [t for t in cat if t.source_group in allow]

    n = len(cat)
    if n < 2:
        return []

    if pre_filter:
        ii, jj = _prefilter_pair_indices(cat, miss_distance_threshold_km)
    else:
        ii = []
        jj = []
        for i in range(n):
            for j in range(i + 1, n):
                ii.append(i)
                jj.append(j)
        ii = np.asarray(ii, dtype=np.int32)
        jj = np.asarray(jj, dtype=np.int32)

    if ii.size == 0:
        return []

    pcount = ii.shape[0]
    best_d = np.full(pcount, np.inf, dtype=np.float64)
    best_epoch = np.zeros(pcount, dtype=np.float64)

    t = t_start
    step = timedelta(seconds=step_seconds)
    while t <= t_end:
        epoch = t.timestamp()
        states = propagate_batch(cat, t)
        pos = np.zeros((n, 3), dtype=np.float64)
        for k, st in enumerate(states):
            if st.r_eci is None:
                pos[k] = np.nan
            else:
                pos[k, 0] = st.r_eci[0]
                pos[k, 1] = st.r_eci[1]
                pos[k, 2] = st.r_eci[2]
        pi = pos[ii]
        pj = pos[jj]
        valid = np.isfinite(pi).all(axis=1) & np.isfinite(pj).all(axis=1)
        diff = pi - pj
        dist = np.linalg.norm(diff, axis=1)
        dist = np.where(valid, dist, np.inf)
        improve = dist < best_d
        best_d = np.where(improve, dist, best_d)
        best_epoch = np.where(improve, epoch, best_epoch)
        t = t + step

    detected_at = datetime.now(timezone.utc)
    candidates: list[ConjunctionCandidate] = []

    refine_step = timedelta(seconds=_REFINE_STEP_S)
    for k in range(pcount):
        if not math.isfinite(best_d[k]) or best_d[k] >= miss_distance_threshold_km:
            continue
        i = int(ii[k])
        j = int(jj[k])
        center = datetime.fromtimestamp(best_epoch[k], tz=timezone.utc)
        center = center.replace(microsecond=0)
        t_lo = center - timedelta(seconds=_REFINE_HALF_S)
        t_hi = center + timedelta(seconds=_REFINE_HALF_S)
        fine_d = math.inf
        fine_t = center
        tr = t_lo
        while tr <= t_hi:
            s1 = propagate(cat[i], tr)
            s2 = propagate(cat[j], tr)
            if s1.r_eci is None or s2.r_eci is None:
                tr = tr + refine_step
                continue
            p1 = np.asarray(s1.r_eci, dtype=np.float64)
            p2 = np.asarray(s2.r_eci, dtype=np.float64)
            d = float(np.linalg.norm(p1 - p2))
            if d < fine_d:
                fine_d = d
                fine_t = tr
            tr = tr + refine_step

        if fine_d >= miss_distance_threshold_km or not math.isfinite(fine_d):
            continue

        st1 = propagate(cat[i], fine_t)
        st2 = propagate(cat[j], fine_t)
        if (
            st1.r_eci is None
            or st2.r_eci is None
            or st1.v_eci is None
            or st2.v_eci is None
        ):
            continue
        v1 = np.asarray(st1.v_eci, dtype=np.float64)
        v2 = np.asarray(st2.v_eci, dtype=np.float64)
        vrel = float(np.linalg.norm(v2 - v1))

        cid = uuid.uuid4().hex
        name_i = _label_for(cat[i], satcat_names)
        name_j = _label_for(cat[j], satcat_names)
        candidates.append(
            ConjunctionCandidate(
                id=cid,
                obj1_norad_id=cat[i].norad_id,
                obj2_norad_id=cat[j].norad_id,
                obj1_name=name_i,
                obj2_name=name_j,
                tca=fine_t,
                miss_distance_km=fine_d,
                relative_velocity_km_s=vrel,
                obj1_state_at_tca=st1,
                obj2_state_at_tca=st2,
                detected_at=detected_at,
            )
        )

    candidates.sort(key=lambda c: c.miss_distance_km)
    return candidates
