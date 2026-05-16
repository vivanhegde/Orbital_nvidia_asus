"""
File-backed JSON cache for CelesTrak and NOAA SWPC data.

All paths resolve under ``orbital_data/cache/``. Freshness is enforced
per dataset; failed refreshes fall back to the newest on-disk payload.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from fetchers.celestrak import (
    CelestrakGPUnchangedError,
    TLE_SOURCE_GROUPS,
    fetch_satcat_for_groups,
    fetch_satcat_single,
    fetch_tle_group,
)
from fetchers.noaa_swpc import fetch_space_weather_snapshot
from models import SatcatRecord, SpaceWeatherSnapshot, TLE

log = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
CACHE_DIR = PACKAGE_DIR / "cache"

_SESSION: requests.Session | None = None

DEFAULT_HTTP_HEADERS: dict[str, str] = {
    "User-Agent": (
        "OrbitalDataIngestion/1.0 (orbital mechanics research; "
        "respectful automated fetch; +https://celestrak.org/)"
    ),
}


def _session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update(DEFAULT_HTTP_HEADERS)
    return _SESSION


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def _cache_age_ok(fetched_at: datetime, max_age: timedelta) -> bool:
    return _utc_now() - fetched_at < max_age


def _tle_cache_path(group: str) -> Path:
    safe = group.replace("/", "_")
    return CACHE_DIR / f"tle_{safe}.json"


def _satcat_cache_path() -> Path:
    return CACHE_DIR / "satcat.json"


def _space_weather_cache_path() -> Path:
    return CACHE_DIR / "space_weather.json"


def _load_tle_cache_file(path: Path) -> tuple[list[TLE], datetime] | None:
    if not path.is_file():
        return None
    try:
        raw = _read_json(path)
        fetched_at = datetime.fromisoformat(str(raw["fetched_at"]))
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        fetched_at = fetched_at.astimezone(timezone.utc)
        tles = [TLE.from_json_dict(x) for x in raw["tles"]]
        return tles, fetched_at
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("Unreadable TLE cache %s (%s); ignoring", path, exc)
        return None


def _save_tle_cache(group: str, tles: list[TLE], fetched_at: datetime) -> None:
    path = _tle_cache_path(group)
    payload = {
        "group": group,
        "fetched_at": fetched_at.astimezone(timezone.utc).isoformat(),
        "tles": [t.to_json_dict() for t in tles],
    }
    _write_json(path, payload)


def get_tles(group: str, max_age_hours: int = 6) -> list[TLE]:
    """
    Return all TLEs for ``group``, refreshing from CelesTrak when stale.

    Returns:
        Parsed :class:`TLE` objects for the requested CelesTrak ``GROUP``.

    Raises:
        ValueError: If no usable cache exists and the network fetch fails or
            the response cannot be parsed.
        CelestrakGPUnchangedError: If CelesTrak blocks both the ``GROUP`` and
            INTDES recovery paths and there is no cache file to reuse.
        requests.RequestException: If the live fetch fails and there is no
            readable stale cache to recover.
    """
    path = _tle_cache_path(group)
    max_age = timedelta(hours=max_age_hours)
    cached = _load_tle_cache_file(path)

    if cached is not None:
        tles, fetched_at = cached
        if _cache_age_ok(fetched_at, max_age):
            log.info(
                "TLE cache hit group=%r count=%d fetched_at=%s",
                group,
                len(tles),
                fetched_at.isoformat(),
            )
            return tles

    try:
        fresh = fetch_tle_group(group, session=_session())
        ts = fresh[0].fetched_at if fresh else _utc_now()
        _save_tle_cache(group, fresh, ts)
        return fresh
    except CelestrakGPUnchangedError as exc:
        log.warning("CelesTrak GP unchanged for group=%r: %s", group, exc.message)
        if cached is not None:
            tles, fetched_at = cached
            log.warning(
                "Keeping cached TLEs for group=%r count=%d fetched_at=%s",
                group,
                len(tles),
                fetched_at.isoformat(),
            )
            return tles
        raise
    except (requests.RequestException, ValueError) as exc:
        log.warning("TLE refresh failed for group=%r: %s", group, exc)
        if cached is not None:
            tles, fetched_at = cached
            log.warning(
                "Using stale TLE cache group=%r count=%d fetched_at=%s",
                group,
                len(tles),
                fetched_at.isoformat(),
            )
            return tles
        raise


def list_all_tles() -> list[TLE]:
    """
    Load TLEs for every configured CelesTrak group (using cache freshness rules).

    Returns:
        All :class:`TLE` objects from every group in :data:`TLE_SOURCE_GROUPS`.

    Raises:
        ValueError: Delegates from :func:`get_tles` if a group cannot be loaded.
        requests.RequestException: If a group refresh fails without stale data.
    """
    out: list[TLE] = []
    for group in TLE_SOURCE_GROUPS:
        out.extend(get_tles(group))
    return out


def _load_satcat_payload(
    path: Path,
) -> tuple[dict[int, SatcatRecord], datetime] | None:
    if not path.is_file():
        return None
    try:
        raw = _read_json(path)
        fetched_at = datetime.fromisoformat(str(raw["fetched_at"]))
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        fetched_at = fetched_at.astimezone(timezone.utc)
        records: dict[int, SatcatRecord] = {}
        for key, row in raw["records"].items():
            records[int(key)] = SatcatRecord.from_json_dict(row)
        return records, fetched_at
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("Unreadable SATCAT cache %s (%s); ignoring", path, exc)
        return None


def _save_satcat(records: dict[int, SatcatRecord], fetched_at: datetime) -> None:
    path = _satcat_cache_path()
    payload = {
        "fetched_at": fetched_at.astimezone(timezone.utc).isoformat(),
        "records": {str(n): r.to_json_dict() for n, r in sorted(records.items())},
    }
    _write_json(path, payload)


def _refresh_satcat_merge() -> tuple[dict[int, SatcatRecord], datetime]:
    merged = fetch_satcat_for_groups(TLE_SOURCE_GROUPS, session=_session())
    return merged, _utc_now()


def get_satcat_records_for_norads(need: set[int]) -> dict[int, SatcatRecord | None]:
    """
    Batch SATCAT lookup: one ``list_all_tles()`` + one cache load/refresh for many NORADs.

    Same freshness and gap-fill rules as :func:`get_satcat_record`, but avoids O(n)
    duplicate work when building hundreds of position rows.
    """
    if not need:
        return {}
    max_age = timedelta(hours=24)
    cached = _load_satcat_payload(_satcat_cache_path())

    stale_payload: tuple[dict[int, SatcatRecord], datetime] | None = cached
    tles = list_all_tles()
    wanted: set[int] = {t.norad_id for t in tles}
    wanted.update(need)

    def pick_many(records: dict[int, SatcatRecord]) -> dict[int, SatcatRecord | None]:
        return {n: records.get(n) for n in need}

    if cached is not None:
        records, fetched_at = cached
        if _cache_age_ok(fetched_at, max_age):
            log.info(
                "SATCAT cache hit need=%d catalog_keys=%d fetched_at=%s",
                len(need),
                len(records),
                fetched_at.isoformat(),
            )
            return pick_many(records)

    try:
        merged, ts = _refresh_satcat_merge()
        missing = [n for n in wanted if n not in merged]
        for n in missing:
            extra = fetch_satcat_single(n, session=_session())
            if extra is not None:
                merged[extra.norad_id] = extra
        _save_satcat(merged, ts)
        log.info(
            "SATCAT store refreshed: %d records fetched_at=%s",
            len(merged),
            ts.isoformat(),
        )
        return pick_many(merged)
    except (requests.RequestException, ValueError) as exc:
        log.warning("SATCAT refresh failed: %s", exc)
        if stale_payload is not None:
            records, fetched_at = stale_payload
            log.warning(
                "Using stale SATCAT cache keys=%d fetched_at=%s",
                len(records),
                fetched_at.isoformat(),
            )
            return pick_many(records)
        raise


def get_satcat_record(norad_id: int) -> SatcatRecord | None:
    """
    Return SATCAT metadata keyed by ``norad_id`` refresh daily at most.

    Performs a merged ``GROUP`` fetch across configured element lists, filtered
    to NORAD IDs present in cached TLEs (plus the requested id). If the bulk
    catalog lacks an entry, ``CATNR`` lookups fill gaps.

    Returns:
        :class:`SatcatRecord` when found, otherwise ``None``.

    Raises:
        requests.RequestException: If the cache is missing or stale and both
            bulk and single-record fetches fail without recoverable disk data.
    """
    return get_satcat_records_for_norads({norad_id}).get(norad_id)


def _load_space_weather_file(
    path: Path,
) -> tuple[SpaceWeatherSnapshot, datetime] | None:
    if not path.is_file():
        return None
    try:
        raw = _read_json(path)
        fetched_at = datetime.fromisoformat(str(raw["fetched_at"]))
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        fetched_at = fetched_at.astimezone(timezone.utc)
        snap = SpaceWeatherSnapshot.from_json_dict(raw["snapshot"])
        return snap, fetched_at
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("Unreadable space weather cache %s (%s); ignoring", path, exc)
        return None


def get_space_weather(max_age_minutes: int = 15) -> SpaceWeatherSnapshot:
    """
    Return the latest NOAA SWPC snapshot, cached up to ``max_age_minutes``.

    Returns:
        :class:`SpaceWeatherSnapshot` with KPIs and UTC ``fetched_at``.

    Raises:
        ValueError: If live parsing fails and no stale cache exists.
        requests.RequestException: If both live pulls fail without stale data.
    """
    path = _space_weather_cache_path()
    max_age = timedelta(minutes=max_age_minutes)
    cached = _load_space_weather_file(path)

    if cached is not None:
        snap, fetched_at = cached
        if _cache_age_ok(fetched_at, max_age):
            log.info(
                "Space weather cache hit fetched_at=%s Kp=%.2f",
                fetched_at.isoformat(),
                snap.kp_index,
            )
            return snap

    try:
        fresh = fetch_space_weather_snapshot(session=_session())
        payload = {
            "fetched_at": fresh.fetched_at.astimezone(timezone.utc).isoformat(),
            "snapshot": fresh.to_json_dict(),
        }
        _write_json(path, payload)
        return fresh
    except (requests.RequestException, ValueError) as exc:
        log.warning("Space weather refresh failed: %s", exc)
        if cached is not None:
            snap, fetched_at = cached
            log.warning(
                "Using stale space weather fetched_at=%s",
                fetched_at.isoformat(),
            )
            return snap
        raise


def cache_dir() -> Path:
    """Filesystem directory where JSON caches are written."""
    return CACHE_DIR
