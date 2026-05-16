"""Active orbital sector metadata."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from orbital_engine._paths import ensure_orbital_data_on_path

ensure_orbital_data_on_path()

from store import list_all_tles  # noqa: E402

from orbital_api.sector import SECTORS_BY_ID, list_tles_in_sector, sector_json

router = APIRouter(prefix="/api/sector", tags=["sector"])


@router.get("/current")
def sector_current(
    sector_id: str = Query(
        "starlink-550",
        description="Sector identifier (e.g. starlink-550)",
    ),
) -> dict[str, object]:
    sector = SECTORS_BY_ID.get(sector_id)
    if sector is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown sector {sector_id!r}",
        )
    all_tles = list_all_tles()
    inside = list_tles_in_sector(all_tles, sector)
    return {
        "sector": sector_json(sector),
        "norad_ids_in_sector": [t.norad_id for t in inside[:500]],
        "total_in_catalog": len(inside),
    }
