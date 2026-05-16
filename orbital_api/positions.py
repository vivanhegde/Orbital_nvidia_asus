"""Compute and cache satellite positions for /api/catalog/positions."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from orbital_engine._paths import ensure_orbital_data_on_path
from orbital_engine.propagation import propagate_batch

ensure_orbital_data_on_path()

from models import TLE  # noqa: E402
from store import get_satcat_records_for_norads, list_all_tles  # noqa: E402

from orbital_api.geo import teme_km_to_lat_lon_alt_km
from orbital_api.screening_jobs import build_screening_catalog
from orbital_api.sector import SECTORS_BY_ID, list_tles_in_sector

log = logging.getLogger(__name__)

_CACHE_TTL_S = 30.0
"""How long to serve identical catalog-position signatures without recomputing."""

_BUCKET_SEC_BULK = 15
"""Bulk sector/catalog queries share a cache key by snapping epoch to this step (seconds)."""

DEFAULT_WARM_SECTOR_ID = "starlink-550"
_LOCK = threading.Lock()
_cache_key: str | None = None
_cache_expiry: float = 0.0
_cache_payload: list[dict[str, Any]] = []


def _satcat_orbit_type(object_type: str | None) -> str:
    """Map CelesTrak OBJECT_TYPE to API enum."""
    c = (object_type or "").upper().strip()
    if c in ("PAY", "PAYLOAD"):
        return "payload"
    if c == "DEB" or "DEBRIS" in c:
        return "debris"
    if c in ("R/B", "RB", "RBD", "ROCKET BODY", "ROCKET"):
        return "rocket_body"
    if c.startswith("R/B") or c.startswith("RB"):
        return "rocket_body"
    return "debris"


def _tles_for_catalog(
    *,
    limit: int,
    groups: list[str] | None,
    sector_id: str | None,
) -> list[TLE]:
    all_tles = list_all_tles()
    if sector_id:
        sector = SECTORS_BY_ID.get(sector_id)
        if sector is None:
            return []
        cat = list_tles_in_sector(all_tles, sector)[:limit]
        return cat
    if groups:
        allow = frozenset(groups)
        cat = [t for t in all_tles if t.source_group in allow]
    else:
        cat = build_screening_catalog(all_tles)
    cat = sorted(cat, key=lambda t: t.norad_id)[:limit]
    return cat


def _tles_for_norads(norad_ids: list[int]) -> list[TLE]:
    want = frozenset(norad_ids)
    all_tles = list_all_tles()
    return [t for t in all_tles if t.norad_id in want]


def _snap_utc_for_positions_cache(when: datetime, *, norad_only: bool) -> datetime:
    """Use coarse time buckets for bulk queries to improve cache hits; keep exact time for norad+at fly-tos."""
    when = when.astimezone(timezone.utc).replace(microsecond=0)
    if norad_only:
        return when
    epoch = int(when.timestamp())
    snapped = epoch - (epoch % _BUCKET_SEC_BULK)
    return datetime.fromtimestamp(snapped, tz=timezone.utc)


def _compute_positions(tles: list[TLE], when: datetime, include_paths: bool = False) -> list[dict[str, Any]]:
    when = when.astimezone(timezone.utc)
    states = propagate_batch(tles, when)
    need = {tle.norad_id for tle in tles}
    satcat_by_norad = get_satcat_records_for_norads(need)
    
    path_by_norad: dict[int, list[list[float]]] = {tle.norad_id: [] for tle in tles}
    if include_paths:
        steps = 32
        from datetime import timedelta
        step_delta = timedelta(minutes=3)
        for i in range(steps):
            step_time = when + step_delta * i
            step_states = propagate_batch(tles, step_time)
            for tle, st in zip(tles, step_states):
                if st.error_code == 0 and st.r_eci is not None:
                    plat, plon, palt = teme_km_to_lat_lon_alt_km(st.r_eci, step_time)
                    path_by_norad[tle.norad_id].append([plat, plon, palt])

    rows: list[dict[str, Any]] = []
    for tle, st in zip(tles, states, strict=True):
        if st.error_code != 0 or st.r_eci is None:
            continue
        lat, lon, alt = teme_km_to_lat_lon_alt_km(st.r_eci, when)
        rec = satcat_by_norad.get(tle.norad_id)
        ot = _satcat_orbit_type(rec.object_type if rec else None)
        row = {
            "norad_id": tle.norad_id,
            "name": tle.name,
            "lat": lat,
            "lon": lon,
            "alt_km": alt,
            "type": ot,
            "source_group": tle.source_group,
        }
        if include_paths:
            row["path"] = path_by_norad[tle.norad_id]
        rows.append(row)
    return rows


def _cache_signature(
    *,
    limit: int,
    groups: tuple[str, ...] | None,
    norad_ids: tuple[int, ...] | None,
    at_iso: str,
    sector_id: str | None,
    include_paths: bool,
) -> str:
    g = "" if groups is None else ",".join(groups)
    n = "" if norad_ids is None else ",".join(str(x) for x in norad_ids)
    s = sector_id or ""
    p = "1" if include_paths else "0"
    return f"{limit}|{g}|{n}|{at_iso}|{s}|{p}"


@dataclass(frozen=True)
class PositionsParams:
    limit: int
    groups: list[str] | None
    norad_ids: list[int] | None
    at: datetime | None
    sector: str | None
    include_paths: bool = False


def get_positions_cached(params: PositionsParams) -> list[dict[str, Any]]:
    """Return positions JSON rows (mutated copy safe for FastAPI)."""
    when_raw = params.at if params.at is not None else datetime.now(timezone.utc)

    nid_t: tuple[int, ...] | None = None
    if params.norad_ids:
        nid_t = tuple(sorted(set(params.norad_ids)))[:50]
        when_eff = _snap_utc_for_positions_cache(when_raw, norad_only=True)
        sig = _cache_signature(
            limit=0,
            groups=None,
            norad_ids=nid_t,
            at_iso=when_eff.isoformat(),
            sector_id=None,
            include_paths=params.include_paths,
        )
    else:
        when_eff = _snap_utc_for_positions_cache(when_raw, norad_only=False)
        sig = _cache_signature(
            limit=params.limit,
            groups=tuple(sorted(params.groups)) if params.groups else None,
            norad_ids=None,
            at_iso=when_eff.isoformat(),
            sector_id=params.sector,
            include_paths=params.include_paths,
        )

    now_m = time.monotonic()
    with _LOCK:
        global _cache_key, _cache_expiry, _cache_payload
        if _cache_key == sig and now_m < _cache_expiry:
            return list(_cache_payload)

    if nid_t is not None:
        tles = _tles_for_norads(list(nid_t))
        rows = _compute_positions(tles, when_eff, include_paths=params.include_paths)
    else:
        tles = _tles_for_catalog(
            limit=params.limit,
            groups=params.groups,
            sector_id=params.sector,
        )
        rows = _compute_positions(tles, when_eff, include_paths=params.include_paths)

    with _LOCK:
        _cache_key = sig
        _cache_expiry = time.monotonic() + _CACHE_TTL_S
        _cache_payload = rows

    return list(rows)


def warm_default_sector_positions() -> None:
    """Pre-compute the dashboard's usual sector query so the first UI load is often instant."""
    params = PositionsParams(
        limit=500,
        groups=None,
        norad_ids=None,
        at=None,
        sector=DEFAULT_WARM_SECTOR_ID,
    )
    try:
        get_positions_cached(params)
        log.info(
            "positions cache warmed sector=%s",
            DEFAULT_WARM_SECTOR_ID,
        )
    except Exception as exc:
        log.warning("positions warm failed: %s", exc)
