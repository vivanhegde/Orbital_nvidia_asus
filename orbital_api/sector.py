"""Orbital regime sectors for filtering catalog, positions, and screening."""

from __future__ import annotations

import math
from typing import Any, TypedDict

from models import TLE

_MU_KM3S2 = 398600.4418
_EARTH_RADIUS_KM = 6378.137


class SectorDict(TypedDict):
    id: str
    display_name: str
    altitude_min_km: float
    altitude_max_km: float
    inclination_min_deg: float
    inclination_max_deg: float


STARLINK_550_SECTOR: SectorDict = {
    "id": "starlink-550",
    "display_name": "Starlink-550 Shell",
    "altitude_min_km": 530.0,
    "altitude_max_km": 580.0,
    "inclination_min_deg": 52.0,
    "inclination_max_deg": 54.0,
}

SECTORS_BY_ID: dict[str, SectorDict] = {
    STARLINK_550_SECTOR["id"]: STARLINK_550_SECTOR,
}


def _parse_line2_orbital(line2: str) -> tuple[float, float, float]:
    """
    Return (perigee_alt_km, apogee_alt_km, inclination_deg) from TLE line 2.

    Matches the orbital_engine.screening mean-motion / eccentricity convention.
    """
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


def tle_in_sector(tle: TLE, sector: SectorDict) -> bool:
    """
    True if the TLE's orbital plane and altitude band overlap the sector.

    Altitude: orbit interval [perigee, apogee] intersects
    [altitude_min_km, altitude_max_km].
    Inclination must lie within [inclination_min_deg, inclination_max_deg].
    """
    try:
        hp, ha, inc = _parse_line2_orbital(tle.line2)
    except (ValueError, IndexError, ArithmeticError):
        return False
    amn = sector["altitude_min_km"]
    amx = sector["altitude_max_km"]
    if ha < amn or hp > amx:
        return False
    imn = sector["inclination_min_deg"]
    imx = sector["inclination_max_deg"]
    return imn <= inc <= imx


def sector_json(sector: SectorDict) -> dict[str, Any]:
    """JSON-serializable sector definition."""
    return {
        "id": sector["id"],
        "display_name": sector["display_name"],
        "altitude_min_km": sector["altitude_min_km"],
        "altitude_max_km": sector["altitude_max_km"],
        "inclination_min_deg": sector["inclination_min_deg"],
        "inclination_max_deg": sector["inclination_max_deg"],
    }


def list_tles_in_sector(all_tles: list[TLE], sector: SectorDict) -> list[TLE]:
    """All TLEs matching ``sector``, sorted by NORAD ID."""
    matched = [t for t in all_tles if tle_in_sector(t, sector)]
    matched.sort(key=lambda t: t.norad_id)
    return matched
