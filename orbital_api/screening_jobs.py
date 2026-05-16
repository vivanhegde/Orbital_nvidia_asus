"""Background screening job for conjunction cache."""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from orbital_persist.store import EventStore


def _bootstrap_paths() -> None:
    root = Path(__file__).resolve().parent.parent
    od = root / "orbital_data"
    if od.is_dir():
        s = str(od)
        if s not in sys.path:
            sys.path.insert(0, s)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


_bootstrap_paths()

from models import TLE  # noqa: E402
from orbital_engine.pc import compute_pc  # noqa: E402
from orbital_engine.screening import screen_conjunctions  # noqa: E402
from store import get_satcat_record, get_space_weather, list_all_tles  # noqa: E402

from orbital_api.geo import camera_aim_from_teme_pair_km  # noqa: E402
from orbital_api.sector import STARLINK_550_SECTOR, list_tles_in_sector  # noqa: E402
from orbital_persist.ids import covariance_inflation_from_kp, stable_event_id  # noqa: E402

log = logging.getLogger(__name__)

_SCREEN_GROUPS_OTHER = frozenset(
    {
        "stations",
        "fengyun-1c-debris",
        "cosmos-2251-debris",
        "iridium-33-debris",
    }
)
_STARLINK_LIMIT = 500

_event_store: EventStore | None = None
_screening_pass_index: int = 0
_last_expire_monotonic: float = 0.0


def configure_event_store(store: EventStore | None) -> None:
    """Set the SQLite EventStore used for persistence (or None to disable)."""
    global _event_store
    _event_store = store


def get_event_store() -> EventStore | None:
    return _event_store


def build_screening_catalog(all_tles: list[TLE]) -> list[TLE]:
    starlink = sorted(
        [t for t in all_tles if t.source_group == "starlink"],
        key=lambda t: t.norad_id,
    )[:_STARLINK_LIMIT]
    others = [t for t in all_tles if t.source_group in _SCREEN_GROUPS_OTHER]
    return starlink + others


def _pc_band(pc: float) -> str:
    if pc < 1e-6:
        return "noise"
    if pc < 1e-4:
        return "watch"
    return "action"


def _sat_type(rec: object | None) -> str:
    if rec is None:
        return "unknown"
    return str(getattr(rec, "object_type", "unknown") or "unknown")


def run_screening_job(cache: Any) -> None:
    """Execute one screening pass and write results into ``cache``."""
    global _screening_pass_index, _last_expire_monotonic

    if not cache.try_begin_screening():
        log.info("Screening skipped: already running")
        return
    try:
        with cache._data_lock:
            cache.screening_in_progress = True
            cache.last_error = None

        now = datetime.now(timezone.utc)
        all_tles = list_all_tles()
        full_sector = list_tles_in_sector(all_tles, STARLINK_550_SECTOR)
        catalog = full_sector[:500]

        space_weather = get_space_weather()
        kp = space_weather.kp_index
        covariance_inflation = covariance_inflation_from_kp(kp)
        log.info(
            "Screening covariance_inflation=%.4f from Kp=%.2f (catalog size=%d of %d in sector)",
            covariance_inflation,
            kp,
            len(catalog),
            len(full_sector),
        )

        candidates = screen_conjunctions(
            catalog,
            now,
            now + timedelta(hours=24),
            step_seconds=60,
            miss_distance_threshold_km=10.0,
            pre_filter=True,
            catalog_filter=None,
            satcat_names=None,
        )

        rows: list[dict[str, Any]] = []
        for c in candidates:
            pc_val = compute_pc(
                c.obj1_state_at_tca,
                c.obj2_state_at_tca,
                covariance1_m=1500.0,
                covariance2_m=3000.0,
                covariance_inflation=covariance_inflation,
            )
            band = _pc_band(pc_val)
            r1 = get_satcat_record(c.obj1_norad_id)
            r2 = get_satcat_record(c.obj2_norad_id)
            event_id = stable_event_id(c.obj1_norad_id, c.obj2_norad_id, c.tca)
            row: dict[str, Any] = {
                "id": event_id,
                "obj1": {
                    "norad_id": c.obj1_norad_id,
                    "name": c.obj1_name,
                    "type": _sat_type(r1),
                },
                "obj2": {
                    "norad_id": c.obj2_norad_id,
                    "name": c.obj2_name,
                    "type": _sat_type(r2),
                },
                "tca": c.tca.astimezone(timezone.utc),
                "miss_distance_km": c.miss_distance_km,
                "relative_velocity_km_s": c.relative_velocity_km_s,
                "pc": pc_val,
                "pc_band": band,
                "detected_at": c.detected_at.astimezone(timezone.utc),
            }
            st1 = c.obj1_state_at_tca
            st2 = c.obj2_state_at_tca
            if (
                st1.r_eci is not None
                and st2.r_eci is not None
                and st1.error_code == 0
                and st2.error_code == 0
            ):
                aim_lat, aim_lon = camera_aim_from_teme_pair_km(
                    st1.r_eci,
                    st2.r_eci,
                    c.tca,
                )
                row["camera_aim_lat"] = aim_lat
                row["camera_aim_lon"] = aim_lon
            rows.append(row)

        rows.sort(key=lambda r: float(r["pc"]), reverse=True)

        if _event_store is not None:
            try:
                _event_store.record_screening_pass(
                    candidates,
                    space_weather,
                    covariance_inflation,
                    now,
                )
            except Exception as exc:
                log.exception("EventStore.record_screening_pass failed: %s", exc)

            _screening_pass_index += 1
            should_expire = (
                _screening_pass_index % 10 == 0
                or (time.monotonic() - _last_expire_monotonic) >= 3600.0
            )
            if should_expire:
                try:
                    nexp = _event_store.expire_stale_events(older_than_hours=6)
                    if nexp:
                        log.info("Expired %d stale conjunction events", nexp)
                    _last_expire_monotonic = time.monotonic()
                except Exception as exc:
                    log.exception("expire_stale_events failed: %s", exc)

        with cache._data_lock:
            cache.conjunctions = rows
            cache.cache_updated_at = datetime.now(timezone.utc)
            cache.screening_in_progress = False
        log.info("Screening complete: %d conjunctions", len(rows))
    except Exception as exc:
        log.exception("Screening failed")
        with cache._data_lock:
            cache.last_error = str(exc)
            cache.screening_in_progress = False
    finally:
        cache.end_screening()
