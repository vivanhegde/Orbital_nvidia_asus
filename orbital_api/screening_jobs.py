"""Background screening job for conjunction cache."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


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
from store import get_satcat_record, list_all_tles  # noqa: E402

from orbital_api.geo import camera_aim_from_teme_pair_km  # noqa: E402
from orbital_api.sector import STARLINK_550_SECTOR, list_tles_in_sector  # noqa: E402

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
        log.info(
            "Screening sector catalog size=%d (of %d in sector shell)",
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
            )
            band = _pc_band(pc_val)
            r1 = get_satcat_record(c.obj1_norad_id)
            r2 = get_satcat_record(c.obj2_norad_id)
            row: dict[str, Any] = {
                "id": c.id,
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