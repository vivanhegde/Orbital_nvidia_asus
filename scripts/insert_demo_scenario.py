#!/usr/bin/env python3
"""Insert one realistic conjunction event into the SQLite store for testing.

Usage:
    source .venv/bin/activate
    python scripts/insert_demo_scenario.py

Inserts STARLINK-1008 (NORAD 44714) vs COSMOS 2251 DEB (NORAD 33757) with a
high-Pc value (3.2e-4) and a TCA ~12 hours in the future. Status is set to
'monitoring' so the agent will treat it as live work.

Prints the event_id so you can pipe it into:
    python -m orbital_agent --investigate <event_id>

Idempotent — if the same (assets, TCA hour) combination already exists, the
event_id will collide and SQLite will tell you. Delete the row first with
`DELETE FROM conjunction_events WHERE event_id = '<id>'` if you need a clean
re-insert.
"""

from __future__ import annotations

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


# Demo scenario constants — keep these in sync with asset_profiles.json entries.
ASSET_NORAD = 44714        # STARLINK-1008 (active, maneuverable)
ASSET_NAME = "STARLINK-1008"
PARTNER_NORAD = 33757      # COSMOS 2251 DEB (non-maneuverable debris)
PARTNER_NAME = "COSMOS 2251 DEB"
HOURS_TO_TCA = 12          # Far enough away that a maneuver is feasible
MISS_KM = 0.712            # Sub-km miss → above screening threshold
INITIAL_PC = 3.2e-4        # Above 1e-4 action threshold (per design doc §6)
REL_V_KMS = 14.8           # Typical high-relative-velocity LEO crossing


def main() -> int:
    cfg = load_config()
    store = EventStore(cfg.db_path)
    try:
        now = datetime.now(timezone.utc)
        tca = now + timedelta(hours=HOURS_TO_TCA)
        eid = stable_event_id(ASSET_NORAD, PARTNER_NORAD, tca)

        existing = store.get_event(eid)
        if existing is not None:
            print(f"Event already exists (status={existing.status}):")
            print(f"  event_id: {eid}")
            print(f"  use it directly, or delete the row to re-insert.")
            return 0

        # Insert directly via the connection — we don't have a real
        # ConjunctionCandidate (would need propagation+screening) and don't
        # need one for this fake-event injection.
        with store._lock:  # noqa: SLF001 — fixture script, breaking the seal here is fine
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
                    ASSET_NORAD, ASSET_NAME,
                    PARTNER_NORAD, PARTNER_NAME,
                    now.isoformat(), now.isoformat(),
                    tca.isoformat(),
                    MISS_KM, INITIAL_PC, REL_V_KMS,
                    json.dumps({"kp_index": 3.3, "geomag_storm_level": "Unsettled"}),
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
                    eid, now.isoformat(), INITIAL_PC, MISS_KM,
                    1.0, 3.3,
                    json.dumps({"kp_index": 3.3}),
                ),
            )
            store._conn.commit()  # noqa: SLF001

        print(f"Inserted demo scenario:")
        print(f"  event_id:           {eid}")
        print(f"  objects:            {ASSET_NAME} (NORAD {ASSET_NORAD}) vs {PARTNER_NAME} (NORAD {PARTNER_NORAD})")
        print(f"  tca:                {tca.isoformat()}")
        print(f"  initial Pc:         {INITIAL_PC:.2e}  (action band)")
        print(f"  miss distance:      {MISS_KM:.3f} km")
        print()
        print(f"Run an investigation:")
        print(f"  python -m orbital_agent --investigate {eid}")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
