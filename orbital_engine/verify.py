"""
End-to-end checks for propagation, screening, and PoC.

Run from the repository root::

    PYTHONPATH=. python -m orbital_engine.verify
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone

from orbital_engine._paths import ensure_orbital_data_on_path

ensure_orbital_data_on_path()

from store import cache_dir, get_satcat_record, list_all_tles  # noqa: E402

from orbital_engine.pc import compute_pc  # noqa: E402
from orbital_engine.propagation import propagate, propagate_batch  # noqa: E402
from orbital_engine.screening import prefilter_pair_count, screen_conjunctions  # noqa: E402

_ISS_NORAD = 25544
_EARTH_RADIUS_KM = 6378.137
_SCREENING_SUBSET = 2000


def _load_satcat_names() -> dict[int, str]:
    path = cache_dir() / "satcat.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[int, str] = {}
    for key, row in data.get("records", {}).items():
        if isinstance(row, dict) and "object_name" in row:
            out[int(key)] = str(row["object_name"])
    return out


def _altitude_km(state_r_eci: tuple[float, float, float]) -> float:
    import math

    r = math.sqrt(sum(x * x for x in state_r_eci))
    return r - _EARTH_RADIUS_KM


def main() -> int:
    print("=== orbital_engine verification ===\n")

    catalog = list_all_tles()
    print(f"[Catalog] total_cached_tles={len(catalog)}")

    iss_tle = next((t for t in catalog if t.norad_id == _ISS_NORAD), None)
    if iss_tle is None:
        print("ERROR: ISS (25544) not present in cached catalog.", file=sys.stderr)
        return 1
    now = datetime.now(timezone.utc)
    iss_state = propagate(iss_tle, now)
    if iss_state.r_eci is None:
        print("ERROR: ISS propagation failed.", file=sys.stderr)
        return 1
    alt_km = _altitude_km(iss_state.r_eci)
    print(f"[Sanity] ISS altitude_km @ now ~= {alt_km:.1f} (expect ~380–420)")
    if alt_km < 380.0 or alt_km > 420.0:
        print("ERROR: ISS altitude out of expected LEO band.", file=sys.stderr)
        return 1

    t0 = time.perf_counter()
    batch = propagate_batch(catalog, now)
    elapsed = time.perf_counter() - t0
    bad = sum(1 for s in batch if s.r_eci is None)
    print(f"[Timing] propagate_batch(all) wall_s={elapsed:.3f} ok={len(batch)-bad} failed={bad}")

    satcat_lookup = _load_satcat_names()
    screen_catalog = catalog
    subset_note = ""
    if len(screen_catalog) > _SCREENING_SUBSET:
        screen_catalog = screen_catalog[:_SCREENING_SUBSET]
        subset_note = f" (first {_SCREENING_SUBSET} TLEs for screening load)"

    t_start = now
    t_end = now + timedelta(hours=24)
    t_screen0 = time.perf_counter()
    pairs_prefilter = prefilter_pair_count(
        screen_catalog,
        5.0,
        catalog_filter=None,
    )
    candidates = screen_conjunctions(
        screen_catalog,
        t_start,
        t_end,
        step_seconds=60,
        miss_distance_threshold_km=5.0,
        pre_filter=True,
        catalog_filter=None,
        satcat_names=satcat_lookup or None,
    )
    screen_s = time.perf_counter() - t_screen0
    print(f"[Screening] wall_s={screen_s:.1f}{subset_note}")
    print(f"[Screening] pairs_after_pre_filter~={pairs_prefilter}")
    print(f"[Screening] candidates_under_5km={len(candidates)}")
    if not candidates:
        print("WARNING: no conjunction candidates in window (try full catalog or debris groups).")

    print("\nTop 10 by miss distance (km):")
    for c in candidates[:10]:
        print(
            f"  {c.obj1_name!s} / {c.obj2_name!s} | TCA={c.tca.isoformat()} | "
            f"miss_km={c.miss_distance_km:.4f} | vrel_km_s={c.relative_velocity_km_s:.4f}"
        )

    if candidates:
        top = candidates[0]
        pc = compute_pc(top.obj1_state_at_tca, top.obj2_state_at_tca)
        print(f"\n[Pc] top candidate Pc (defaults) = {pc:.6e}")

        r1 = get_satcat_record(top.obj1_norad_id)
        r2 = get_satcat_record(top.obj2_norad_id)
        n1_sat = r1.object_name.strip() if r1 else None
        n2_sat = r2.object_name.strip() if r2 else None
        print(
            f"[Integration] SATCAT names for top pair: "
            f"{top.obj1_norad_id} -> {n1_sat!r}, {top.obj2_norad_id} -> {n2_sat!r}"
        )
        if n1_sat and not n1_sat.isdigit():
            print("[Integration] obj1 label is not NORAD-only (SATCAT ok).")
        if n2_sat and not n2_sat.isdigit():
            print("[Integration] obj2 label is not NORAD-only (SATCAT ok).")

    print("\n=== done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
