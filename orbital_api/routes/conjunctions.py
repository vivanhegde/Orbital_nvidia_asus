"""Flagged conjunctions from screening cache."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from orbital_api.cache import screening_cache

router = APIRouter(prefix="/api/conjunctions", tags=["conjunctions"])


def _serialize_item(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row["id"],
        "obj1": row["obj1"],
        "obj2": row["obj2"],
        "tca": row["tca"].isoformat(),
        "miss_distance_km": row["miss_distance_km"],
        "relative_velocity_km_s": row["relative_velocity_km_s"],
        "pc": row["pc"],
        "pc_band": row["pc_band"],
        "detected_at": row["detected_at"].isoformat(),
    }
    if "camera_aim_lat" in row and "camera_aim_lon" in row:
        out["camera_aim_lat"] = row["camera_aim_lat"]
        out["camera_aim_lon"] = row["camera_aim_lon"]
    return out


@router.get("/flagged")
def conjunctions_flagged() -> dict[str, Any]:
    snap = screening_cache.snapshot()
    items = [_serialize_item(r) for r in snap["conjunctions"]]
    cu = snap["cache_updated_at"]
    return {
        "conjunctions": items,
        "cache_updated_at": cu.isoformat() if cu else None,
        "screening_in_progress": snap["screening_in_progress"],
        "last_error": snap["last_error"],
    }
