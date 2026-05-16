#!/usr/bin/env python3
"""
End-to-end verification for the orbital data ingestion layer.

Run from the ``orbital_data`` directory::

    python verify.py
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from fetchers.celestrak import TLE_SOURCE_GROUPS
from models import TLE
from store import cache_dir, get_satcat_record, get_space_weather, get_tles, list_all_tles


def _configure_logging() -> None:
    logging.Formatter.converter = time.gmtime  # type: ignore[assignment]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def _format_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _print_tle_block(title: str, tle: TLE) -> None:
    print(f"\n{title}")
    print(f"  name:          {tle.name!r}")
    print(f"  norad_id:      {tle.norad_id}")
    print(f"  source_group:  {tle.source_group!r}")
    print(f"  epoch (UTC):   {_format_dt(tle.epoch)}")
    print(f"  fetched_at:    {_format_dt(tle.fetched_at)}")
    print(f"  line1:         {tle.line1}")
    print(f"  line2:         {tle.line2}")


def _pick_sample_starlink(tles_by_group: dict[str, list[TLE]]) -> TLE:
    group = "starlink"
    rows = tles_by_group[group]
    if not rows:
        raise RuntimeError(f"No TLEs available for group {group!r}")
    return rows[0]


def _pick_sample_iss(tles_by_group: dict[str, list[TLE]]) -> TLE:
    stations = tles_by_group["stations"]
    for tle in stations:
        upper = tle.name.upper()
        if "ZARYA" in upper or upper.startswith("ISS"):
            return tle
    if stations:
        return stations[0]
    raise RuntimeError("No station TLEs available")


def _pick_sample_debris(tles_by_group: dict[str, list[TLE]]) -> TLE:
    for group in ("fengyun-1c-debris", "cosmos-2251-debris", "iridium-33-debris"):
        rows = tles_by_group[group]
        for tle in rows:
            name = tle.name.upper()
            if " DEB" in name or name.endswith("DEB"):
                return tle
        if rows:
            return rows[0]
    raise RuntimeError("No debris-group TLEs available")


def _satcat_coverage() -> tuple[int, int, Path | None]:
    path = cache_dir() / "satcat.json"
    if not path.is_file():
        return 0, 0, None
    data = json.loads(path.read_text(encoding="utf-8"))
    cached_ids = {int(k) for k in data["records"].keys()}
    all_norad = {t.norad_id for t in list_all_tles()}
    hit = sum(1 for n in all_norad if n in cached_ids)
    return hit, len(all_norad), path


def _cache_health() -> tuple[Path, int, datetime | None]:
    root = cache_dir()
    total = 0
    oldest: datetime | None = None
    if not root.is_dir():
        return root, 0, oldest
    for p in root.rglob("*"):
        if p.is_file() and p.name != ".gitkeep":
            st = p.stat()
            total += st.st_size
            mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
            if oldest is None or mtime < oldest:
                oldest = mtime
    return root, total, oldest


def main() -> int:
    _configure_logging()

    print("=== Orbital data layer verification ===\n")

    tles_by_group: dict[str, list[TLE]] = {}
    for group in TLE_SOURCE_GROUPS:
        rows = get_tles(group)
        tles_by_group[group] = rows
        epochs = [t.epoch for t in rows]
        if epochs:
            oldest = min(epochs)
            newest = max(epochs)
            print(f"[TLE] group={group!r} count={len(rows)}")
            print(f"      oldest_epoch_utc={_format_dt(oldest)}")
            print(f"      newest_epoch_utc={_format_dt(newest)}")
        else:
            print(f"[TLE] group={group!r} count=0 (empty group)")

    all_rows = [t for g in TLE_SOURCE_GROUPS for t in tles_by_group[g]]
    print(f"\n[TLE] total_across_configured_groups={len(all_rows)}")

    star = _pick_sample_starlink(tles_by_group)
    iss = _pick_sample_iss(tles_by_group)
    deb = _pick_sample_debris(tles_by_group)

    _print_tle_block("Sample — Starlink", star)
    _print_tle_block("Sample — ISS / stations", iss)
    _print_tle_block("Sample — debris fragment", deb)

    for sample in (star, iss, deb):
        rec = get_satcat_record(sample.norad_id)
        label = sample.name.strip() or str(sample.norad_id)
        if rec is None:
            print(f"\n[SATCAT] No catalog row cached yet for NORAD {sample.norad_id} ({label})")
        else:
            print(
                f"\n[SATCAT] NORAD {sample.norad_id} ({label}): "
                f"{rec.object_name!r} owner={rec.country!r} type={rec.object_type!r}"
            )

    hits, total, satcat_path = _satcat_coverage()
    if satcat_path is None:
        print("\n[SATCAT] cache missing (unexpected after lookups)")
    else:
        pct = (100.0 * hits / total) if total else 0.0
        print(f"\n[SATCAT] coverage: {hits}/{total} TLE NORAD IDs have catalog rows ({pct:.1f}%)")

    sw = get_space_weather()
    print("\n[Space weather]")
    print(f"  Kp index (latest):      {sw.kp_index:.2f}")
    print(f"  Geomagnetic storm lvl:  {sw.geomag_storm_level}")
    print(f"  X-ray class (GOES):     {sw.xray_class}")
    print(f"  X-ray flux (0.1-0.8nm): {sw.xray_flux_short:.5e} W/m²")
    print(f"  Kp trend points (6h):   {len(sw.kp_trend)}")
    print(f"  snapshot fetched_at:    {_format_dt(sw.fetched_at)}")

    cdir, csize, oldest_mtime = _cache_health()
    print("\n[Cache health]")
    print(f"  directory:        {cdir}")
    print(f"  total_size_bytes: {csize}")
    if oldest_mtime is not None:
        print(f"  oldest_file_utc:  {_format_dt(oldest_mtime)}")
    else:
        print("  oldest_file_utc:  (no files)")

    print("\n=== Verification complete ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
