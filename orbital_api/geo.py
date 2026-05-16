"""TEME (km) to WGS84 geodetic using GMST rotation + pymap3d."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pymap3d

def _datetime_to_jd_utc(dt: datetime) -> float:
    dt = dt.astimezone(timezone.utc)
    y, m = dt.year, dt.month
    d = (
        dt.day
        + dt.hour / 24.0
        + dt.minute / 1440.0
        + (dt.second + dt.microsecond * 1e-6) / 86400.0
    )
    if m <= 2:
        y -= 1
        m += 12
    A = y // 100
    B = 2 - A + A // 4
    jd0 = int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + B - 1524.5
    return float(jd0)


def _gmst_deg(jd_ut1: float) -> float:
    """Greenwich Mean Sidereal Time in degrees (low-precision navigation)."""
    d = jd_ut1 - 2451545.0
    T = d / 36525.0
    gmst = (
        280.46061837
        + 360.98564736629 * d
        + 0.000387933 * T * T
        - T * T * T / 38710000.0
    )
    return gmst % 360.0


def teme_km_to_ecef_m(
    r_km: tuple[float, float, float],
    t_utc: datetime,
) -> tuple[float, float, float]:
    """TEME (km) to WGS84 ECEF (m) using GMST rotation (SGP4 convention)."""
    jd = _datetime_to_jd_utc(t_utc)
    theta = math.radians(_gmst_deg(jd))
    x, y, z = r_km
    x_e = x * math.cos(theta) + y * math.sin(theta)
    y_e = -x * math.sin(theta) + y * math.cos(theta)
    z_e = z
    return x_e * 1000.0, y_e * 1000.0, z_e * 1000.0


def camera_aim_from_teme_pair_km(
    r1_km: tuple[float, float, float],
    r2_km: tuple[float, float, float],
    t_utc: datetime,
) -> tuple[float, float]:
    """
    Lat/lon (deg) for globe ``pointOfView``: ECEF midpoint of the two TEME positions.

    Matches the same frame pipeline as screening / catalog positions so the camera
    targets the geometry that produced the conjunction.
    """
    e1 = teme_km_to_ecef_m(r1_km, t_utc)
    e2 = teme_km_to_ecef_m(r2_km, t_utc)
    mx = (e1[0] + e2[0]) * 0.5
    my = (e1[1] + e2[1]) * 0.5
    mz = (e1[2] + e2[2]) * 0.5
    lat, lon, _alt_m = pymap3d.ecef2geodetic(mx, my, mz, deg=True)
    return float(lat), float(lon)


def teme_km_to_lat_lon_alt_km(
    r_km: tuple[float, float, float],
    t_utc: datetime,
) -> tuple[float, float, float]:
    """
    Convert SGP4 TEME position (km) to WGS84 geodetic.

    Returns:
        (latitude_deg, longitude_deg, altitude_km).
    """
    x_e, y_e, z_e = teme_km_to_ecef_m(r_km, t_utc)
    lat, lon, alt_m = pymap3d.ecef2geodetic(
        x_e,
        y_e,
        z_e,
        deg=True,
    )
    return float(lat), float(lon), float(alt_m) / 1000.0
