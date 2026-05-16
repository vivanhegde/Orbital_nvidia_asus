"""Catalog summary and object detail endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from orbital_engine._paths import ensure_orbital_data_on_path
from orbital_engine.propagation import propagate

ensure_orbital_data_on_path()

from models import TLE  # noqa: E402
from store import get_satcat_record, list_all_tles  # noqa: E402

from orbital_api.geo import teme_km_to_lat_lon_alt_km
from orbital_api.positions import PositionsParams, get_positions_cached
from orbital_api.sector import SECTORS_BY_ID

router = APIRouter(prefix="/api/catalog", tags=["catalog"])

GROUP_ORDER: tuple[str, ...] = (
    "starlink",
    "stations",
    "fengyun-1c-debris",
    "cosmos-2251-debris",
    "iridium-33-debris",
)


@router.get("/summary")
def catalog_summary() -> dict[str, object]:
    tles = list_all_tles()
    by_group: dict[str, int] = {g: 0 for g in GROUP_ORDER}
    epochs: list[datetime] = []
    for t in tles:
        if t.source_group in by_group:
            by_group[t.source_group] += 1
        epochs.append(t.epoch)
    if not epochs:
        return {
            "total_objects": 0,
            "by_group": by_group,
            "newest_tle_epoch": None,
            "oldest_tle_epoch": None,
        }
    newest = max(epochs)
    oldest = min(epochs)
    return {
        "total_objects": len(tles),
        "by_group": by_group,
        "newest_tle_epoch": newest.astimezone(timezone.utc).isoformat(),
        "oldest_tle_epoch": oldest.astimezone(timezone.utc).isoformat(),
    }


def _tle_to_dict(t: TLE) -> dict[str, object]:
    return {
        "name": t.name,
        "norad_id": t.norad_id,
        "line1": t.line1,
        "line2": t.line2,
        "epoch": t.epoch.astimezone(timezone.utc).isoformat(),
        "source_group": t.source_group,
        "fetched_at": t.fetched_at.astimezone(timezone.utc).isoformat(),
    }


@router.get("/positions")
def catalog_positions(
    limit: int = Query(500, ge=1, le=2000),
    groups: list[str] | None = Query(None),
    norad_ids: str | None = Query(
        None,
        description="Comma-separated NORAD IDs (optional fly-to / preview at ``at``)",
    ),
    at: datetime | None = Query(
        None,
        description="UTC propagation epoch (ISO 8601). Defaults to now.",
    ),
    sector: str | None = Query(
        None,
        description='When set (e.g. "starlink-550"), only objects in that sector.',
    ),
    include_paths: bool = Query(
        False,
        description="If true, compute and include the orbital path array for each object.",
    ),
) -> list[dict[str, object]]:
    nids: list[int] | None = None
    if norad_ids:
        parts = [p.strip() for p in norad_ids.split(",") if p.strip()]
        try:
            nids = [int(p) for p in parts[:50]]
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="norad_ids must be integers"
            ) from exc
    if sector is not None and sector not in SECTORS_BY_ID:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown sector {sector!r}",
        )
    params = PositionsParams(
        limit=limit,
        groups=groups,
        norad_ids=nids,
        at=at,
        sector=sector,
        include_paths=include_paths,
    )
    return get_positions_cached(params)


@router.get("/object/{norad_id}")
def catalog_object(norad_id: int) -> dict[str, object]:
    tles = list_all_tles()
    tle = next((t for t in tles if t.norad_id == norad_id), None)
    if tle is None:
        raise HTTPException(status_code=404, detail=f"No TLE for NORAD {norad_id}")
    rec = get_satcat_record(norad_id)
    now = datetime.now(timezone.utc)
    state = propagate(tle, now)
    pos: dict[str, object] | None = None
    if state.r_eci is not None and state.error_code == 0:
        lat, lon, alt = teme_km_to_lat_lon_alt_km(state.r_eci, now)
        pos = {
            "latitude_deg": lat,
            "longitude_deg": lon,
            "altitude_km": alt,
            "error_code": 0,
        }
    else:
        pos = {"latitude_deg": None, "longitude_deg": None, "altitude_km": None, "error_code": state.error_code}
    return {
        "tle": _tle_to_dict(tle),
        "satcat": rec.to_json_dict() if rec else None,
        "propagation": {"state_time_utc": now.isoformat(), "position": pos},
    }
