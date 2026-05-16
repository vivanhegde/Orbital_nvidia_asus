#!/usr/bin/env python3
"""Render (and optionally send) a demo investigation kickoff.

From repo root with venv active:

    python scripts/run_demo_investigation.py          # render only
    python scripts/run_demo_investigation.py --send  # invoke openclaw on Spark

Does not start the runner or touch SSE/UI.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from orbital_agent.kickoff import build_kickoff, send_kickoff_cli  # noqa: E402
from orbital_persist.models import ConjunctionEventRecord  # noqa: E402


def _demo_event() -> ConjunctionEventRecord:
    now = datetime.now(timezone.utc)
    return ConjunctionEventRecord(
        event_id="CONJ-DEMO-001",
        obj1_norad_id=25544,
        obj1_name="ISS (ZARYA)",
        obj2_norad_id=99999,
        obj2_name="DEBRIS-123",
        first_detected_at=now,
        last_seen_at=now,
        tca=now,
        initial_miss_distance_km=0.82,
        initial_pc=1.2e-4,
        relative_velocity_km_s=11.7,
        status="monitoring",
        space_weather_at_detection=None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--send",
        action="store_true",
        help="Send kickoff via openclaw agent (requires gateway + Ollama on Spark)",
    )
    args = parser.parse_args()

    text = build_kickoff(_demo_event())

    if re.search(r"\{[a-z_0-9]+\}", text):
        print("FAIL: kickoff still contains unfilled placeholders", file=sys.stderr)
        print(text, file=sys.stderr)
        return 1

    print("=== Rendered kickoff ===")
    print(text)
    print("=== OK: template rendered ===")

    if args.send:
        print("=== Sending via openclaw ===")
        resp = send_kickoff_cli(_demo_event())
        payloads = (resp.get("result") or {}).get("payloads") or []
        reply = payloads[0].get("text", "") if payloads else resp
        print("reply:", (str(reply) or "")[:500])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
