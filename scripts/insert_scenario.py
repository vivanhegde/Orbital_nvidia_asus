#!/usr/bin/env python3
"""Insert a conjunction scenario from a JSON file into the SQLite store.

Usage:
    source .venv/bin/activate
    python scripts/insert_scenario.py orbital_agent/scenarios/01_action_required.json

Skips insert if the stable event_id already exists (prints existing id).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "orbital_data", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from orbital_agent.config import load as load_config  # noqa: E402
from orbital_persist.ids import stable_event_id  # noqa: E402
from orbital_persist.store import EventStore  # noqa: E402


def insert_from_file(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    ev = data["event"]
    cfg = load_config()
    store = EventStore(cfg.db_path)
    try:
        now = datetime.now(timezone.utc)
        hours = float(ev.get("hours_to_tca", 12))
        tca = now + timedelta(hours=hours)
        eid = stable_event_id(int(ev["obj1_norad_id"]), int(ev["obj2_norad_id"]), tca)

        if store.get_event(eid) is not None:
            print(f"Scenario already present: {eid}")
            print(f"  id label: {data.get('id', path.stem)}")
            return 0

        miss = float(ev["miss_km"])
        ipc = float(ev["initial_pc"])
        relv = float(ev["relative_velocity_km_s"])
        sw_stub = json.dumps(
            {
                "kp_index": float(ev.get("kp_index", 3.3)),
                "geomag_storm_level": str(ev.get("geomag_storm_level", "Unsettled")),
            }
        )

        with store._lock:  # noqa: SLF001
            store._conn.execute(  # noqa: SLF001
                """
                INSERT INTO conjunction_events (
                  event_id, obj1_norad_id, obj1_name, obj2_norad_id, obj2_name,
                  first_detected_at, last_seen_at, tca,
                  initial_miss_distance_km, initial_pc, relative_velocity_km_s,
                  status, space_weather_at_detection
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'monitoring', ?)
                """,
                (
                    eid,
                    int(ev["obj1_norad_id"]),
                    str(ev["obj1_name"]),
                    int(ev["obj2_norad_id"]),
                    str(ev["obj2_name"]),
                    now.isoformat(),
                    now.isoformat(),
                    tca.isoformat(),
                    miss,
                    ipc,
                    relv,
                    sw_stub,
                ),
            )
            store._conn.execute(  # noqa: SLF001
                """
                INSERT INTO pc_snapshots (
                  event_id, snapshot_at, pc, miss_distance_km,
                  covariance_inflation, kp_index, space_weather_snapshot
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eid,
                    now.isoformat(),
                    ipc,
                    miss,
                    float(ev.get("covariance_inflation", 1.0)),
                    float(ev.get("kp_index", 3.3)),
                    sw_stub,
                ),
            )
            store._conn.commit()  # noqa: SLF001

        print(f"Inserted scenario {data.get('id', path.stem)}")
        print(f"  event_id: {eid}")
        print(f"  tca:      {tca.isoformat()}")
        print(f"  initial Pc: {ipc:.2e}")
        print()
        print(f"  python -m orbital_agent --investigate {eid}")
        return 0
    finally:
        store.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Insert scenario JSON into orbital.db")
    ap.add_argument("scenario_file", type=Path, help="Path to scenario JSON")
    args = ap.parse_args()
    path = args.scenario_file
    if not path.is_file():
        print(f"Not found: {path}", file=sys.stderr)
        return 1
    return insert_from_file(path)


if __name__ == "__main__":
    sys.exit(main())
