"""Render the investigation kickoff message and send it to OpenClaw.

The reasoning loop itself runs inside the OpenClaw daemon — this module is
just the glue that turns a `conjunction_events` row into a user-turn message,
fires `openclaw agent --agent orbital --json --thinking high --session-id <uuid>`
as a subprocess, and parses the structured response.

A fresh session ID per investigation keeps OpenClaw's per-session memory
isolated between events so the model doesn't conflate them.
"""

from __future__ import annotations

import json
import logging
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orbital_agent._paths import ensure_repo_on_path
from orbital_agent.config import AgentConfig, load as load_config

ensure_repo_on_path()

from orbital_persist.models import ConjunctionEventRecord  # noqa: E402
from orbital_persist.store import EventStore  # noqa: E402

_LOG = logging.getLogger(__name__)

_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "investigate_kickoff.txt"


@dataclass(frozen=True)
class InvestigationResult:
    event_id: str
    session_id: str
    duration_ms: int
    reply_text: str
    tool_calls: list[str]                     # tool names invoked, in order
    assistant_text_events: int                # how many distinct text emissions
    verdict_written: bool                     # whether a verdict landed in the verdicts table
    verdict_type: str | None                  # dismissed | watch | recommended | None
    verdict_id: str | None
    raw_response: dict[str, Any]              # full parsed JSON from openclaw


def build_kickoff(event: ConjunctionEventRecord) -> str:
    """Render the investigation-kickoff user-turn message for one event."""
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.format(
        event_id=event.event_id,
        obj1_name=event.obj1_name,
        obj1_norad_id=event.obj1_norad_id,
        obj2_name=event.obj2_name,
        obj2_norad_id=event.obj2_norad_id,
        tca=event.tca.astimezone(timezone.utc).isoformat(),
        miss_km=event.initial_miss_distance_km,
        initial_pc=event.initial_pc,
        rel_v_kms=event.relative_velocity_km_s,
        first_detected_at=event.first_detected_at.astimezone(timezone.utc).isoformat(),
    )


def send_kickoff_for_event(
    event_id: str,
    *,
    config: AgentConfig | None = None,
    store: EventStore | None = None,
    thinking: str = "high",
    timeout_seconds: int = 600,
) -> InvestigationResult:
    """Run one full investigation for `event_id` through OpenClaw.

    Looks the event up in the EventStore, renders the kickoff message, calls
    the OpenClaw CLI with a fresh session ID, and parses the response.
    """
    cfg = config or load_config()
    owned_store = False
    if store is None:
        store = EventStore(cfg.db_path)
        owned_store = True

    try:
        event = store.get_event(event_id)
        if event is None:
            raise ValueError(f"event_id not found in store: {event_id}")
        kickoff_text = build_kickoff(event)
        session_id = uuid.uuid4().hex

        _LOG.info(
            "Kicking off investigation event_id=%s session=%s agent=%s",
            event_id, session_id, cfg.openclaw_agent_id,
        )

        cmd = [
            "openclaw", "agent",
            "--agent", cfg.openclaw_agent_id,
            "--session-id", session_id,
            "--thinking", thinking,
            "--timeout", str(timeout_seconds),
            "--json",
            "--message", kickoff_text,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds + 30)
        if proc.returncode != 0:
            raise RuntimeError(
                f"openclaw agent exited {proc.returncode}\n"
                f"stderr: {proc.stderr[:1000]}\nstdout: {proc.stdout[:500]}"
            )
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Could not parse openclaw agent output as JSON: {exc}\n"
                f"stdout (first 800): {proc.stdout[:800]}"
            ) from exc

        return _build_result(event_id, session_id, payload, store)
    finally:
        if owned_store:
            store.close()


def _build_result(
    event_id: str,
    session_id: str,
    payload: dict[str, Any],
    store: EventStore,
) -> InvestigationResult:
    result = payload.get("result", {}) or {}
    payloads = result.get("payloads", []) or []
    reply_text = payloads[0].get("text", "") if payloads else ""

    meta = result.get("meta", {}) or {}
    agent_meta = meta.get("agentMeta", {}) or {}
    duration_ms = int(meta.get("durationMs", 0) or 0)

    # Parse the session jsonl. OpenClaw's actual format is:
    #   {"type":"message","message":{"role":"assistant","content":[
    #       {"type":"thinking","thinking":"..."},
    #       {"type":"toolCall","name":"orbital__...","arguments":{...}}
    #   ]}}
    #   {"type":"message","message":{"role":"toolResult", ...}}
    tool_calls: list[str] = []
    text_events = 0
    session_file = agent_meta.get("sessionFile")
    if session_file:
        try:
            with open(session_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = entry.get("message") or {}
                    role = msg.get("role")
                    if role != "assistant":
                        continue
                    for item in msg.get("content", []) or []:
                        kind = item.get("type")
                        if kind == "toolCall":
                            tool_calls.append(item.get("name", "?"))
                        elif kind in ("thinking", "text"):
                            text_events += 1
        except OSError as exc:
            _LOG.warning("Could not read session file %s: %s", session_file, exc)

    # Look up any verdict for this event (not just pending — agent verdicts
    # land with operator_decision IS NULL but list_pending_verdicts filters
    # at the SQL level, so we query directly).
    verdict_written = False
    verdict_type: str | None = None
    verdict_id: str | None = None
    with store._lock:  # noqa: SLF001
        cur = store._conn.cursor()  # noqa: SLF001
        cur.execute(
            "SELECT verdict_id, verdict_type FROM verdicts "
            "WHERE event_id = ? ORDER BY issued_at DESC LIMIT 1",
            (event_id,),
        )
        row = cur.fetchone()
        if row:
            verdict_written = True
            verdict_id = str(row[0])
            verdict_type = str(row[1])

    return InvestigationResult(
        event_id=event_id,
        session_id=session_id,
        duration_ms=duration_ms,
        reply_text=reply_text,
        tool_calls=tool_calls,
        assistant_text_events=text_events,
        verdict_written=verdict_written,
        verdict_type=verdict_type,
        verdict_id=verdict_id,
        raw_response=payload,
    )


def summarize(result: InvestigationResult) -> str:
    """One-screen human summary of an investigation."""
    lines = [
        f"Investigation summary",
        f"  event_id:           {result.event_id}",
        f"  session_id:         {result.session_id}",
        f"  duration:           {result.duration_ms / 1000:.1f} s",
        f"  assistant text events: {result.assistant_text_events}",
        f"  tool calls ({len(result.tool_calls)}):",
    ]
    for name in result.tool_calls:
        lines.append(f"    - {name}")
    if not result.tool_calls:
        lines.append(f"    (none — check session file format if you expected some)")
    lines.append(f"  verdict written:    {result.verdict_written}")
    if result.verdict_written:
        lines.append(f"  verdict type:       {result.verdict_type}")
        lines.append(f"  verdict id:         {result.verdict_id}")
    lines.append(f"")
    lines.append(f"  final reply (first 400 chars):")
    lines.append(f"    {result.reply_text[:400]!r}")
    return "\n".join(lines)
