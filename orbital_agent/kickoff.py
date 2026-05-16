"""Build and send OpenClaw investigation kickoff messages (Feature 3)."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orbital_agent.config import load as load_config

_LOG = logging.getLogger(__name__)

_KICKOFF_TEMPLATE = Path(__file__).resolve().parent / "prompts" / "investigate_kickoff.txt"
# OpenClaw CLI thinking budget when supported (was "high" in early demos).
_DEFAULT_THINKING_LEVEL = "medium"


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
    out = subprocess.run(cmd_with_thinking, capture_output=True, text=True, timeout=timeout_s)
    if out.returncode != 0 and "--thinking" in out.stderr.lower():
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    if out.returncode != 0:
        raise RuntimeError(
            f"openclaw agent failed (exit {out.returncode}): {out.stderr[:500]}"
        )
    import json

    return json.loads(out.stdout)


def run_kickoff_cli_sync(event: Any, **kwargs: Any) -> dict[str, Any]:
    return send_kickoff_cli(event, **kwargs)
