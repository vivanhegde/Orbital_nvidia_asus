#!/usr/bin/env python3
"""End-to-end Feature 3 acceptance test.

Usage:
    source .venv/bin/activate
    python scripts/run_demo_investigation.py

Steps:
  1. Insert the demo conjunction scenario (STARLINK-1008 vs Cosmos-2251 debris,
     Pc 3.2e-4) — skipped if already present.
  2. Run one full investigation through OpenClaw (`openclaw agent --agent orbital
     --thinking medium --json --message <kickoff>`).
  3. Print a structured summary: tool calls made, assistant text events, verdict
     written, time elapsed.
  4. Report PASS / FAIL against the Feature 3 acceptance criteria:
       - investigation completes
       - ≥ 3 tool calls during the loop (re_propagate, get_*, etc.)
       - a verdict row lands in the verdicts table
       - duration under ~3 minutes (soft target)

Exits 0 on PASS, 1 on FAIL.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "orbital_data", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from orbital_agent.config import load as load_config  # noqa: E402
from orbital_agent.kickoff import send_kickoff_for_event, summarize  # noqa: E402
from orbital_persist.ids import stable_event_id  # noqa: E402
from orbital_persist.store import EventStore  # noqa: E402

# Mirror scripts/insert_demo_scenario.py — keep these in sync.
ASSET_NORAD = 44714
PARTNER_NORAD = 33757
HOURS_TO_TCA = 12

# Acceptance criteria
MIN_TOOL_CALLS = 3
# 300s aligns with kickoff default timeout (240s OpenClaw + buffer).
MAX_DURATION_SECONDS = 300


def _ensure_scenario_exists() -> str:
    """Return the demo scenario's event_id, inserting it if missing."""
    cfg = load_config()
    store = EventStore(cfg.db_path)
    try:
        now = datetime.now(timezone.utc)
        tca = now + timedelta(hours=HOURS_TO_TCA)
        eid = stable_event_id(ASSET_NORAD, PARTNER_NORAD, tca)
        if store.get_event(eid) is None:
            print(f"Demo scenario not present — inserting now…")
            proc = subprocess.run(
                ["python", str(_ROOT / "scripts" / "insert_demo_scenario.py")],
                capture_output=True, text=True,
            )
            print(proc.stdout)
            if proc.returncode != 0:
                print(f"Insert failed: {proc.stderr}", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"Demo scenario already in store: {eid}")
        return eid
    finally:
        store.close()


def main() -> int:
    print("=" * 60)
    print("Feature 3 end-to-end investigation test")
    print("=" * 60)

    eid = _ensure_scenario_exists()
    print()
    print(f"Kicking off investigation for {eid}…")
    print("(this typically takes 30-120s depending on tool-call depth)")
    print()

    result = send_kickoff_for_event(eid)
    print(summarize(result))
    print()

    # Acceptance evaluation
    print("=" * 60)
    print("Acceptance criteria")
    print("=" * 60)
    checks: list[tuple[str, bool, str]] = []
    checks.append((
        f"Investigation completes",
        bool(result.reply_text),
        f"reply length: {len(result.reply_text)} chars",
    ))
    checks.append((
        f"≥ {MIN_TOOL_CALLS} tool calls",
        len(result.tool_calls) >= MIN_TOOL_CALLS,
        f"got: {len(result.tool_calls)} ({result.tool_calls})",
    ))
    checks.append((
        f"Verdict written to store",
        result.verdict_written,
        f"verdict_type: {result.verdict_type}, verdict_id: {result.verdict_id}",
    ))
    checks.append((
        f"Duration under {MAX_DURATION_SECONDS}s (soft target)",
        result.duration_ms <= MAX_DURATION_SECONDS * 1000,
        f"{result.duration_ms / 1000:.1f}s",
    ))

    all_pass = True
    for name, ok, detail in checks:
        tag = "[PASS]" if ok else "[FAIL]"
        print(f"{tag} {name}  — {detail}")
        if not ok:
            all_pass = False

    print()
    print("=" * 60)
    if all_pass:
        print("FEATURE 3 PASS — agent reasoning loop is working end-to-end.")
    else:
        print("FEATURE 3 FAIL — investigate the failing criteria above.")
        print("Common issues:")
        print("  - 0 tool calls: model produced tool-call text but OpenClaw didn't")
        print("    execute them. Verify our 11 MCP tools are in alsoAllow.")
        print("  - No verdict written: model never called orbital__write_memory or")
        print("    orbital__draft_recommendation. Tighten SOUL.md or kickoff template.")
        print("  - Long duration: bump --thinking lower or simplify the prompt.")
    print("=" * 60)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
