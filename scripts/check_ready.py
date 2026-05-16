#!/usr/bin/env python3
"""Feature-3 readiness check.

Run from the repo root with the venv activated:

    source .venv/bin/activate
    python scripts/check_ready.py

Verifies Features 1 + 2 are working end-to-end AND the FOLLOWUPS.md cleanup
has been applied (tool surface narrowed, workspace files neutralized).

Prints PASS/FAIL per criterion and a final READY / NOT READY verdict.
Exits 0 if ready, 1 if not.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request


OK = "[PASS]"
NO = "[FAIL]"
status: dict[str, bool] = {}


def check(name: str, cond: bool, detail: str = "") -> None:
    status[name] = bool(cond)
    tag = OK if cond else NO
    print(f"{tag} {name}" + (f": {detail}" if detail else ""))


def http_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def cli_json(cmd: list[str]) -> dict:
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"\nCould not parse JSON from `{' '.join(cmd)}`:\n"
            f"  stdout (first 400 chars): {out.stdout[:400]!r}\n"
            f"  stderr (first 400 chars): {out.stderr[:400]!r}\n"
            f"  parse error: {exc}"
        )


def section(title: str) -> None:
    print(f"\n── {title} ──")


def main() -> int:
    # ── A. Services up ────────────────────────────────────────────────────
    section("A. Services")
    check("Ollama reachable", http_ok("http://127.0.0.1:11434/api/tags"))
    check("OpenClaw gateway reachable", http_ok("http://127.0.0.1:18789"))
    check("FastAPI reachable", http_ok("http://127.0.0.1:8000/health"))
    check("MCP server SSE endpoint", http_ok("http://127.0.0.1:8765/sse"))

    if not all(status.values()):
        _verdict()
        return 1 if not all(status.values()) else 0

    # ── B. Feature 1 — agent runtime ──────────────────────────────────────
    section("B. Feature 1")
    agents = cli_json(["openclaw", "config", "get", "agents.list"])
    orbital = next((a for a in agents if a.get("id") == "orbital"), None)
    check("orbital agent registered", orbital is not None)
    if orbital:
        check(
            "orbital model is nemotron-3-nano:30b",
            orbital.get("model") == "ollama/nemotron-3-nano:30b",
            orbital.get("model", ""),
        )
        check(
            "orbital workspace points at our repo",
            "Orbital_nvidia_asus" in (orbital.get("workspace") or ""),
            orbital.get("workspace", ""),
        )

    probe = cli_json(
        ["openclaw", "agent", "--agent", "orbital", "--json",
         "--message", "Reply with only the word: ack"]
    )
    reply = probe.get("result", {}).get("payloads", [{}])[0].get("text", "")
    check("orbital responds to kickoff", "ack" in reply.lower(), repr(reply[:80]))

    sp = probe["result"]["meta"]["systemPromptReport"]
    prompt_chars = sp["systemPrompt"]["chars"]
    input_tokens = probe["result"]["meta"]["agentMeta"]["usage"]["input"]

    # ── C. Feature 2 — MCP server & 11 tools ──────────────────────────────
    section("C. Feature 2")
    our_tools = {
        "get_flagged_conjunctions", "get_object_metadata", "get_space_weather",
        "get_conjunctions_for_asset", "query_memory", "write_memory",
        "re_propagate", "compute_collision_probability", "simulate_maneuver",
        "evaluate_plan", "draft_recommendation",
    }
    mcp_tool_names = {t["name"] for t in sp.get("tools", {}).get("entries", [])}
    missing_ours = our_tools - mcp_tool_names
    check(
        "all 11 MCP tools visible to agent",
        not missing_ours,
        f"missing: {sorted(missing_ours)}" if missing_ours else "11/11",
    )

    rp = cli_json(
        ["openclaw", "agent", "--agent", "orbital", "--json",
         "--message", (
             "Call re_propagate with norad_id=25544. "
             "Report the three ECI x, y, z coordinates from the tool's response exactly "
             "as returned. No estimation."
         )]
    )
    rp_reply = rp.get("result", {}).get("payloads", [{}])[0].get("text", "")
    nums = [float(x) for x in re.findall(r"-?\d+\.\d+", rp_reply)]
    plausible = (
        len(nums) >= 3
        and all(abs(n) < 50_000 for n in nums[:3])
        and any(abs(n) > 100 for n in nums[:3])
    )
    check(
        "agent invokes our SGP4 tool end-to-end",
        plausible,
        f"reply: {rp_reply[:120]!r}",
    )

    # ── D. Followups cleanup ──────────────────────────────────────────────
    section("D. Followups cleanup")

    if orbital:
        profile = (orbital.get("tools") or {}).get("profile")
        check(
            "orbital tools.profile = minimal",
            profile == "minimal",
            f"got: {profile!r}",
        )
        check(
            "orbital skills override = []",
            orbital.get("skills") == [],
            f"got: {orbital.get('skills')!r}",
        )

    coding_tools = {
        "read", "edit", "write", "exec", "process",
        "web_search", "web_fetch", "memory_search", "memory_get",
    }
    still_leaking = mcp_tool_names & coding_tools
    check(
        "default coding tools not visible to agent",
        not still_leaking,
        f"still leaking: {sorted(still_leaking)}" if still_leaking else "",
    )

    skills_entries = sp.get("skills", {}).get("entries", [])
    check(
        "agent has 0 skills enabled",
        len(skills_entries) == 0,
        f"skills: {[s['name'] for s in skills_entries]}",
    )

    workspace_files = sp.get("injectedWorkspaceFiles", [])
    soul = next((f for f in workspace_files if f["name"] == "SOUL.md"), {})
    others = [f for f in workspace_files if f["name"] != "SOUL.md"]
    big_others = [f for f in others if (not f["missing"]) and f["rawChars"] > 200]
    check(
        "SOUL.md present and substantive",
        bool(soul) and not soul.get("missing") and soul.get("rawChars", 0) > 1000,
    )
    check(
        "other workspace files neutralized",
        not big_others,
        f"still substantive: {[(f['name'], f['rawChars']) for f in big_others]}",
    )

    check(
        "prompt chars below 12K (was 24,666 before cleanup)",
        prompt_chars < 12_000,
        f"current: {prompt_chars} chars, {input_tokens} input tokens",
    )

    _verdict()
    return 0 if all(status.values()) else 1


def _verdict() -> None:
    print()
    print("=" * 60)
    if all(status.values()):
        print("READY FOR FEATURE 3 — everything verified.")
    else:
        print("NOT READY — failing checks:")
        for name, ok in status.items():
            if not ok:
                print(f"    - {name}")
        print()
        print("Fix the failing items above before starting Feature 3.")
        print("See orbital_agent/openclaw/FOLLOWUPS.md for cleanup commands.")
    print("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
