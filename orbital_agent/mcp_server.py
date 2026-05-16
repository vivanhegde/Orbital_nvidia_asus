"""MCP server exposing the 11 Orbital domain tools to OpenClaw.

Runs over stdio by default — OpenClaw spawns this process (configured via
`openclaw mcp set orbital`) and talks to it through stdin/stdout. Tools are
declared with type hints + docstrings; FastMCP introspects them to publish
their schemas to the connected agent.

CLI usage:
    python -m orbital_agent.mcp_server         # run as stdio server
    python -m orbital_agent.mcp_server --list  # introspect tools (dev tool)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from mcp.server.fastmcp import FastMCP

from orbital_agent._paths import ensure_repo_on_path

ensure_repo_on_path()

from orbital_agent.tools import analysis, data, memory, output  # noqa: E402
from orbital_agent.tools._pydantic_models import (  # noqa: E402
    Burn,
    ObjectStateInput,
    RecommendationOutput,
)

_LOG = logging.getLogger(__name__)

mcp = FastMCP("orbital")


# ── Data-fetch tools ────────────────────────────────────────────────────────

@mcp.tool()
def get_flagged_conjunctions(
    min_pc: float = 0.0,
    asset_norad_id: int | None = None,
) -> dict:
    """Return the screening engine's currently flagged conjunctions.

    The primary "what's happening" signal. Use min_pc=1e-6 to skip noise,
    min_pc=1e-4 to see only action-required events. Pass asset_norad_id to
    filter to one asset.
    """
    return data.get_flagged_conjunctions(min_pc=min_pc, asset_norad_id=asset_norad_id)


@mcp.tool()
def get_object_metadata(norad_id: int) -> dict:
    """Return human-readable metadata for one object (SATCAT + operator profile).

    Combines public SATCAT data (name, country, type, RCS size, orbital period,
    inclination) with operator-supplied profile (is_maneuverable, fuel_remaining_mps,
    mission_criticality). Critical for deciding whose burden the avoidance falls on.
    """
    return data.get_object_metadata(int(norad_id))


@mcp.tool()
def get_space_weather() -> dict:
    """Return the current NOAA SWPC snapshot: Kp index + trend, X-ray flux/class, storm level.

    Above Kp=5, atmospheric drag predictions are noisier — inflate covariance
    accordingly when computing Pc.
    """
    return data.get_space_weather()


@mcp.tool()
def get_conjunctions_for_asset(norad_id: int, limit: int = 20) -> dict:
    """Return upcoming + recent conjunctions involving one asset.

    Used in Plan mode to decide whether one burn can resolve multiple events.
    Sorted by last_seen_at descending; filter the result by TCA > now to
    focus on the upcoming window.
    """
    return data.get_conjunctions_for_asset(int(norad_id), limit=limit)


# ── Memory tools ───────────────────────────────────────────────────────────

@mcp.tool()
def query_memory(
    norad_id: int | None = None,
    event_id: str | None = None,
    limit: int = 10,
) -> dict:
    """Retrieve prior conjunction events + any verdicts attached to them.

    Pass event_id for one specific event (with its full verdict if any), or
    norad_id to list the most recent events involving that asset. Use this
    BEFORE recommending — the operator's past decision on similar events is
    informative.
    """
    return memory.query_memory(norad_id=norad_id, event_id=event_id, limit=limit)


@mcp.tool()
def write_memory(
    event_id: str,
    verdict_type: str,
    reasoning: str,
    plan: dict | None = None,
) -> dict:
    """Persist a verdict (dismiss/watch/recommended) for an event.

    Call this at the end of every Investigate cycle. For "recommended" verdicts,
    prefer draft_recommendation — it validates the plan structure for the
    Approver UI. Use write_memory directly only for "dismissed" or "watch".
    """
    return memory.write_memory(
        event_id=event_id,
        verdict_type=verdict_type,
        reasoning=reasoning,
        plan=plan,
    )


# ── Analysis tools ─────────────────────────────────────────────────────────

@mcp.tool()
def re_propagate(norad_id: int, at_iso: str | None = None) -> dict:
    """Force fresh SGP4 propagation with the most recent TLE.

    Use this when you suspect a stale TLE is producing a false-positive Pc.
    Returns position (km) and velocity (km/s) in ECI at `at_iso` (UTC ISO;
    defaults to "now"), plus the TLE epoch age so you can judge staleness.
    """
    return analysis.re_propagate(int(norad_id), at_iso=at_iso)


@mcp.tool()
def compute_collision_probability(
    obj1: ObjectStateInput,
    obj2: ObjectStateInput,
    covariance_inflation: float | None = None,
    kp_index: float | None = None,
) -> dict:
    """Compute probability of collision between two propagated states.

    Pass either covariance_inflation directly, or kp_index (the tool will
    derive inflation: Kp<5 → 1.0, 5≤Kp<6 → 1.18, Kp≥6 → 1.4). Returns Pc plus
    pc_band ('noise' / 'watch' / 'action') so you can immediately tell which
    threshold the event crosses.
    """
    return analysis.compute_collision_probability(
        obj1=obj1,
        obj2=obj2,
        covariance_inflation=covariance_inflation,
        kp_index=kp_index,
    )


@mcp.tool()
def simulate_maneuver(
    norad_id: int,
    dv_mps: float,
    direction: str,
    burn_time_iso: str,
    look_ahead_hours: float = 24.0,
) -> dict:
    """Apply an impulsive Δv burn to an asset and return the post-burn trajectory.

    Direction must be one of: prograde / retrograde / radial / anti-radial /
    normal / anti-normal. The asset is SGP4-propagated to burn time, the Δv
    is added to its velocity, and the new trajectory is Kepler-propagated
    forward (two-body — accurate to ~km over ~hours, no J2/drag).
    """
    return analysis.simulate_maneuver(
        norad_id=int(norad_id),
        dv_mps=dv_mps,
        direction=direction,
        burn_time_iso=burn_time_iso,
        look_ahead_hours=look_ahead_hours,
    )


@mcp.tool()
def evaluate_plan(
    asset_norad_id: int,
    burns: list[Burn],
    miss_threshold_km: float = 1.0,
) -> dict:
    """Score a maneuver plan against the asset's upcoming flagged conjunctions.

    For each upcoming conjunction event involving the asset, predicts the
    post-burn miss distance and reports whether the burn resolves it
    (new miss ≥ miss_threshold_km). Returns total Δv plus the per-event
    resolved/unresolved breakdown — use this to compare candidate plans.
    """
    return analysis.evaluate_plan(
        asset_norad_id=int(asset_norad_id),
        burns=burns,
        miss_threshold_km=miss_threshold_km,
    )


# ── Output tools ───────────────────────────────────────────────────────────

@mcp.tool()
def draft_recommendation(
    event_id: str,
    recommendation: RecommendationOutput,
) -> dict:
    """Persist a maneuver recommendation as a verdict row for the Approver UI.

    Call this at the end of Plan mode after evaluating at least two candidate
    plans. The RecommendationOutput must include the primary plan, at least
    one alternative, plain-English reasoning a flight director reads in <30s,
    and an urgency level. The Approver UI polls /api/verdicts/pending and
    will render this as a card with Approve/Reject buttons.
    """
    return output.draft_recommendation(event_id=event_id, recommendation=recommendation)


# ── Entrypoint ─────────────────────────────────────────────────────────────

def _cli_list() -> int:
    """Print every registered tool with its derived schema. Dev introspection only."""
    import asyncio

    async def list_async() -> int:
        tools = await mcp.list_tools()
        print(f"# orbital MCP server — {len(tools)} tools registered")
        for t in tools:
            print(f"\n## {t.name}")
            desc = (t.description or "").strip().splitlines()
            if desc:
                print(desc[0])
            schema = t.inputSchema or {}
            props = schema.get("properties", {}) or {}
            required = set(schema.get("required", []) or [])
            for pname, pspec in props.items():
                mark = "*" if pname in required else " "
                typ = pspec.get("type") or pspec.get("anyOf") or pspec.get("$ref") or "?"
                print(f"  {mark} {pname}: {typ}")
        return 0

    return asyncio.run(list_async())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orbital_agent.mcp_server", description=__doc__)
    parser.add_argument("--list", action="store_true", help="List registered tools and exit")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.list:
        return _cli_list()

    # Default: stdio MCP server (OpenClaw spawns us with this contract).
    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
