"""
NOAA Space Weather Prediction Center (SWPC) JSON fetchers.

Combines planetary K-index and GOES primary X-ray products into a single
snapshot suitable for downstream atmosphere / drag models.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from dateutil.parser import isoparse

from models import SpaceWeatherSnapshot

log = logging.getLogger(__name__)

NOAA_SWPC_JSON_BASE = "https://services.swpc.noaa.gov/json"
K_INDEX_URL = f"{NOAA_SWPC_JSON_BASE}/planetary_k_index_1m.json"
GOES_XRAY_URL = f"{NOAA_SWPC_JSON_BASE}/goes/primary/xrays-1-day.json"

# GOES short X-ray band used for NOAA-style class (0.1--0.8 nm).
GOES_XRAY_SHORT_ENERGY = "0.1-0.8nm"


def classify_xray_flux(flux_w_m2: float) -> str:
    """Map W/m² X-ray flux to coarse class letters A/B/C/M/X."""
    if flux_w_m2 < 1e-8:
        return "A"
    if flux_w_m2 < 1e-7:
        return "B"
    if flux_w_m2 < 1e-6:
        return "C"
    if flux_w_m2 < 1e-5:
        return "M"
    return "X"


def geomag_level_from_kp(kp: float) -> str:
    """Map Kp to quiet/unsettled/active or NOAA G-scale labels."""
    if kp < 3.0:
        return "Quiet"
    if kp < 4.0:
        return "Unsettled"
    if kp < 5.0:
        return "Active"
    if kp < 6.0:
        return "G1"
    if kp < 7.0:
        return "G2"
    if kp < 8.0:
        return "G3"
    if kp < 9.0:
        return "G4"
    return "G5"


def fetch_space_weather_snapshot(
    session: requests.Session | None = None,
) -> SpaceWeatherSnapshot:
    """
    Pull latest Kp trend and GOES X-ray flux, returning a snapshot.

    Returns:
        :class:`SpaceWeatherSnapshot` with ``fetched_at`` in UTC.

    Raises:
        requests.RequestException: On transport failures.
        ValueError: If JSON shapes are unexpected or time series are empty.
    """
    sess = session or requests.Session()
    fetched_at = datetime.now(timezone.utc)

    kp_rows = _fetch_json_list(sess, K_INDEX_URL, "planetary_k_index_1m")
    xray_rows = _fetch_json_list(sess, GOES_XRAY_URL, "goes_xrays_1d")

    kp_index, kp_trend = _parse_kp_series(kp_rows, fetched_at)
    xflux = _latest_xray_flux(xray_rows, energy=GOES_XRAY_SHORT_ENERGY)
    x_class = classify_xray_flux(xflux)
    storm = geomag_level_from_kp(kp_index)

    snap = SpaceWeatherSnapshot(
        kp_index=kp_index,
        kp_trend=kp_trend,
        xray_flux_short=xflux,
        xray_class=x_class,
        geomag_storm_level=storm,
        fetched_at=fetched_at,
    )
    log.info(
        "Fetched space weather: Kp=%.2f %s X-class=%s flux=%.3e at %s",
        kp_index,
        storm,
        x_class,
        xflux,
        fetched_at.isoformat(),
    )
    return snap


def _fetch_json_list(sess: requests.Session, url: str, label: str) -> list[dict[str, Any]]:
    log.info("Fetching NOAA SWPC JSON %s", label)
    resp = sess.get(url, timeout=60)
    resp.raise_for_status()
    data: Any = resp.json()
    if not isinstance(data, list):
        raise ValueError(f"{label}: expected top-level JSON list")
    out: list[dict[str, Any]] = []
    for row in data:
        if isinstance(row, dict):
            out.append(row)
    return out


def _parse_kp_series(
    rows: list[dict[str, Any]],
    now_utc: datetime,
) -> tuple[float, tuple[float, ...]]:
    """Most recent estimated Kp and trailing 6 hours of estimated Kp (1-minute data)."""
    parsed: list[tuple[datetime, float]] = []
    for row in rows:
        ts_raw = row.get("time_tag")
        if ts_raw is None:
            continue
        t = isoparse(str(ts_raw))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        t = t.astimezone(timezone.utc)
        est = row.get("estimated_kp")
        if est is None:
            continue
        parsed.append((t, float(est)))
    if not parsed:
        raise ValueError("K-index series empty after parse")
    parsed.sort(key=lambda x: x[0])
    latest_t, latest_kp = parsed[-1]
    cutoff = now_utc - timedelta(hours=6)
    trend_vals = [kp for t, kp in parsed if t >= cutoff]
    if not trend_vals:
        trend_vals = [latest_kp]
    return latest_kp, tuple(trend_vals)


def _latest_xray_flux(rows: list[dict[str, Any]], energy: str) -> float:
    """Return the most recent flux for the given GOES energy band label."""
    matching: list[tuple[datetime, float]] = []
    for row in rows:
        if str(row.get("energy", "")) != energy:
            continue
        ts_raw = row.get("time_tag")
        if ts_raw is None:
            continue
        t = isoparse(str(ts_raw))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        t = t.astimezone(timezone.utc)
        fl = row.get("flux")
        if fl is None:
            continue
        matching.append((t, float(fl)))
    if not matching:
        raise ValueError(f"No X-ray rows for energy={energy!r}")
    matching.sort(key=lambda x: x[0])
    return matching[-1][1]
