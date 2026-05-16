"""Data-fetch MCP tools: flagged conjunctions, object metadata, space weather, per-asset history.

HTTP-based tools call the local FastAPI (`orbital_api`) so we get the same
caching and sorting the UI sees. Direct-call tools touch `orbital_data.store`
for things that don't go through the API.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from orbital_agent._paths import ensure_repo_on_path
from orbital_agent.config import load as load_config

ensure_repo_on_path()

from orbital_data.store import cache_dir, get_satcat_record  # noqa: E402

_LOG = logging.getLogger(__name__)
_CONFIG = load_config()
_HTTP_TIMEOUT = 10.0


def _api(path: str) -> str:
    return f"{_CONFIG.api_base_url.rstrip('/')}{path}"


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"error": msg}
    out.update(extra)
    return out


def get_flagged_conjunctions(
    min_pc: float = 0.0,
    asset_norad_id: int | None = None,
) -> dict[str, Any]:
    """Return the screening engine's currently flagged conjunctions.

    Args:
        min_pc: Only return events whose probability of collision (latest
            cached value) is at least this. Use 1e-6 to filter out noise,
            1e-4 to see only action-required events.
        asset_norad_id: Optional filter — only events involving this NORAD ID.

    Returns:
        {conjunctions: [...], cache_updated_at, screening_in_progress, last_error}
        Each conjunction has id, obj1, obj2 (objects with name + norad_id),
        tca, miss_distance_km, relative_velocity_km_s, pc, pc_band, detected_at.
    """
    try:
        resp = httpx.get(_api("/api/conjunctions/flagged"), timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
    except httpx.HTTPError as exc:
        return _err(f"API unreachable: {type(exc).__name__}: {exc}")

    items: list[dict[str, Any]] = body.get("conjunctions", []) or []
    if min_pc > 0.0:
        items = [c for c in items if (c.get("pc") or 0.0) >= min_pc]
    if asset_norad_id is not None:
        items = [
            c for c in items
            if (c.get("obj1", {}).get("norad_id") == asset_norad_id
                or c.get("obj2", {}).get("norad_id") == asset_norad_id)
        ]
    return {
        "conjunctions": items,
        "cache_updated_at": body.get("cache_updated_at"),
        "screening_in_progress": body.get("screening_in_progress"),
        "last_error": body.get("last_error"),
        "count": len(items),
    }


_ASSET_PROFILES_CACHE: dict[int, dict[str, Any]] | None = None


def _asset_profiles() -> dict[int, dict[str, Any]]:
    global _ASSET_PROFILES_CACHE
    if _ASSET_PROFILES_CACHE is not None:
        return _ASSET_PROFILES_CACHE
    path = cache_dir() / "asset_profiles.json"
    if not path.is_file():
        _ASSET_PROFILES_CACHE = {}
        return _ASSET_PROFILES_CACHE
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        _ASSET_PROFILES_CACHE = {int(k): v for k, v in raw.get("assets", {}).items()}
    except (OSError, ValueError, KeyError) as exc:
        _LOG.warning("Could not parse asset_profiles.json (%s); using empty dict", exc)
        _ASSET_PROFILES_CACHE = {}
    return _ASSET_PROFILES_CACHE


def get_object_metadata(norad_id: int) -> dict[str, Any]:
    """Return human-readable metadata for one object (NORAD lookup).

    Combines SATCAT (name, country, launch date, object type, RCS size,
    orbital period, inclination) with operator-supplied asset profile data
    (is_maneuverable, fuel_remaining_mps, mission_criticality) from
    orbital_data/cache/asset_profiles.json when available.
    """
    try:
        rec = get_satcat_record(norad_id)
    except Exception as exc:  # network or parse error from SATCAT layer
        return _err(f"SATCAT lookup failed: {type(exc).__name__}: {exc}", norad_id=norad_id)
    if rec is None:
        return _err("object not found in SATCAT", norad_id=norad_id)

    out: dict[str, Any] = {
        "norad_id": rec.norad_id,
        "name": rec.object_name,
        "country": rec.country,
        "object_type": rec.object_type,
        "launch_date": rec.launch_date.isoformat() if rec.launch_date else None,
        "decay_date": rec.decay_date.isoformat() if rec.decay_date else None,
        "rcs_size_m2": rec.rcs_size,
        "period_min": rec.period,
        "inclination_deg": rec.inclination,
    }
    profile = _asset_profiles().get(norad_id)
    if profile:
        out["is_maneuverable"] = bool(profile.get("is_maneuverable", False))
        out["fuel_remaining_mps"] = profile.get("fuel_remaining_mps")
        out["mission_criticality"] = profile.get("mission_criticality")
        out["operator"] = profile.get("operator")
    else:
        # Default heuristic: debris and rocket bodies are not maneuverable,
        # active payloads might be (mark unknown).
        kind = (rec.object_type or "").upper()
        if "DEB" in kind or "R/B" in kind:
            out["is_maneuverable"] = False
        else:
            out["is_maneuverable"] = None
        out["fuel_remaining_mps"] = None
        out["mission_criticality"] = None
        out["operator"] = None
    return out


def get_space_weather() -> dict[str, Any]:
    """Return the current NOAA SWPC snapshot: Kp index, Kp trend, X-ray flux/class, storm level."""
    try:
        resp = httpx.get(_api("/api/space-weather"), timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        return _err(f"API unreachable: {type(exc).__name__}: {exc}")


def get_conjunctions_for_asset(
    norad_id: int,
    limit: int = 20,
) -> dict[str, Any]:
    """Return recent and upcoming conjunction events involving `norad_id`.

    Used by the agent during Plan mode to decide whether one burn can resolve
    multiple events. Returns events sorted by last_seen_at descending; the
    agent should filter by TCA itself to focus on upcoming ones.

    Args:
        norad_id: NORAD ID of the asset
        limit: Maximum number of events to return (1-100)

    Returns:
        {norad_id, events: [{event_id, partner_name, partner_norad_id, tca,
                              initial_pc, status, last_seen_at, ...}, ...]}
    """
    limit = max(1, min(100, int(limit)))
    try:
        resp = httpx.get(
            _api(f"/api/memory/asset/{norad_id}"),
            params={"limit": limit},
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        return _err(f"API unreachable: {type(exc).__name__}: {exc}", norad_id=norad_id)
