"""Space weather snapshot."""

from __future__ import annotations

from fastapi import APIRouter

from orbital_engine._paths import ensure_orbital_data_on_path

ensure_orbital_data_on_path()

from store import get_space_weather  # noqa: E402

router = APIRouter(prefix="/api/space-weather", tags=["space-weather"])


@router.get("")
def space_weather() -> dict[str, object]:
    sw = get_space_weather()
    d = sw.to_json_dict()
    return d
