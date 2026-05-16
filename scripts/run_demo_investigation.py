#!/usr/bin/env python3
"""Render (and optionally send) a demo investigation kickoff.

From repo root with venv active:

    python scripts/run_demo_investigation.py
    python scripts/run_demo_investigation.py --send
    python scripts/run_demo_investigation.py --send --event-id <id-from-flagged>

Render-only is instant. --send runs a full OpenClaw investigation (often 5–15+ min;
may hit 600s Python timeout if Ollama is slow). Prefer --event-id with a real
screened conjunction, not the built-in demo (NORAD 99999 has no TLE).
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

from orbital_agent.config import load as load_config  # noqa: E402
from orbital_agent.kickoff import build_kickoff, send_kickoff_cli  # noqa: E402
from orbital_persist.models import ConjunctionEventRecord  # noqa: E402
from orbital_persist.store import EventStore  # noqa: E402


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


def _load_event(event_id: str) -> ConjunctionEventRecord:
    store = EventStore(load_config().db_path)
    try:
        ev = store.get_event(event_id)
    finally:
        store.close()
    if ev is None:
        raise SystemExit(f"event_id not in DB: {event_id}")
    return ev


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--send",
        action="store_true",
        help="Send kickoff via openclaw agent (slow; needs gateway + Ollama + MCP)",
    )
    parser.add_argument(
        "--event-id",
        metavar="ID",
        help="Use a real conjunction_events row (recommended for --send)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="Max seconds to wait for openclaw agent (default 600)",
    )
    args = parser.parse_args()

    event = _load_event(args.event_id) if args.event_id else _demo_event()
    text = build_kickoff(event)

    if re.search(r"\{[a-z_0-9]+\}", text):
        print("FAIL: kickoff still contains unfilled placeholders", file=sys.stderr)
        print(text, file=sys.stderr)
        return 1

    print("=== Rendered kickoff ===")
    print(text)
    print("=== OK: template rendered ===")

    if event.obj2_norad_id == 99999 or event.obj1_norad_id == 99999:
        print(
            "NOTE: built-in demo uses NORAD 99999 (no TLE). For --send use "
            "--event-id from: curl -s http://127.0.0.1:8000/api/conjunctions/flagged",
            file=sys.stderr,
        )

    if args.send:
        print(f"=== Sending via openclaw (timeout {args.timeout:.0f}s) ===", flush=True)
        print("(watch progress: openclaw logs --follow)", flush=True)
        try:
            resp = send_kickoff_cli(event, timeout_s=args.timeout)
        except TimeoutError as exc:
            print(f"TIMEOUT: {exc}", file=sys.stderr)
            return 2
        payloads = (resp.get("result") or {}).get("payloads") or []
        reply = payloads[0].get("text", "") if payloads else resp
        print("reply:", (str(reply) or "")[:2000])
        if not payloads:
            print("WARN: empty payloads — see openclaw logs for Ollama/agent errors", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
