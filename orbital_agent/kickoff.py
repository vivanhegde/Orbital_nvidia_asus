"""Build and send OpenClaw investigation kickoff messages (Feature 3)."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orbital_agent.config import load as load_config

_LOG = logging.getLogger(__name__)

_KICKOFF_TEMPLATE = Path(__file__).resolve().parent / "prompts" / "investigate_kickoff.txt"
# OpenClaw CLI thinking budget when supported (low for faster Spark runs).
_DEFAULT_THINKING_LEVEL = "low"


def build_kickoff(event: Any) -> str:
    """Render investigate_kickoff.txt for a ConjunctionEventRecord."""
    template = _KICKOFF_TEMPLATE.read_text(encoding="utf-8")
    tca = event.tca
    if isinstance(tca, datetime):
        if tca.tzinfo is None:
            tca = tca.replace(tzinfo=timezone.utc)
        tca_s = tca.astimezone(timezone.utc).isoformat()
    else:
        tca_s = str(tca)

    return template.format(
        event_id=event.event_id,
        obj1_name=event.obj1_name,
        obj1_id=event.obj1_norad_id,
        obj2_name=event.obj2_name,
        obj2_id=event.obj2_norad_id,
        tca=tca_s,
        miss_km=f"{float(event.initial_miss_distance_km):.3f}",
        initial_pc=f"{float(event.initial_pc):.3e}",
    )


async def send_kickoff_for_event(
    event: Any,
    *,
    gateway: Any | None = None,
    timeout_s: float = 600.0,
) -> dict[str, Any]:
    """Send the kickoff via OpenClaw REST; returns the gateway JSON response."""
    from orbital_agent.gateway import OpenClawGateway

    text = build_kickoff(event)
    gw = gateway or OpenClawGateway(load_config())
    return await gw.send_message_rest(text, timeout_s=timeout_s)


def send_kickoff_cli(
    event: Any,
    *,
    thinking: str = _DEFAULT_THINKING_LEVEL,
    timeout_s: float = 600.0,
) -> dict[str, Any]:
    """Send kickoff through `openclaw agent` (used by demo script on Spark)."""
    text = build_kickoff(event)
    cfg = load_config()
    cmd = [
        "openclaw",
        "agent",
        "--agent",
        cfg.openclaw_agent_id,
        "--json",
        "--message",
        text,
    ]
    # Pass thinking level when the installed CLI supports it.
    cmd_with_thinking = [*cmd, "--thinking", thinking]
    try:
        out = subprocess.run(
            cmd_with_thinking, capture_output=True, text=True, timeout=timeout_s
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"openclaw agent did not finish within {timeout_s:.0f}s. "
            "Check `openclaw logs --follow` for Ollama timeouts (often 120s per turn) "
            "or increase OpenClaw agents.defaults.timeoutSeconds. "
            "Prefer a real event_id from the DB, not CONJ-DEMO-001 (NORAD 99999 has no TLE)."
        ) from exc
    if out.returncode != 0 and "--thinking" in (out.stderr or "").lower():
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    if out.returncode != 0:
        raise RuntimeError(
            f"openclaw agent failed (exit {out.returncode}): {(out.stderr or '')[:500]}"
        )

    return json.loads(out.stdout)


def run_kickoff_cli_sync(event: Any, **kwargs: Any) -> dict[str, Any]:
    return send_kickoff_cli(event, **kwargs)
