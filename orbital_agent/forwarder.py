"""Tail an OpenClaw session JSONL file and forward events to the agent bus.

OpenClaw writes one JSON object per line to
`~/.openclaw/agents/<agent>/sessions/<session_id>.jsonl` as the agent
reasons. Each line typically contains an assistant message (with embedded
`thinking` and `toolCall` items) or a `toolResult`. This module:

  1. Polls the file for new lines (file-tail with seek/read)
  2. Normalizes each line into 0+ UI-shaped events
  3. POSTs each event to /api/agent/event so the SSE stream picks them up

Runs as one asyncio task per investigation, started by the runner before
the `openclaw agent` subprocess and cancelled after it returns.

We use file-tailing rather than the OpenClaw WebSocket protocol because
the WebSocket protocol isn't publicly documented and the JSONL file is
the source of truth OpenClaw itself writes to.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

_LOG = logging.getLogger(__name__)

_TAIL_POLL_S = 0.5      # how often to re-read the file for new lines
_WAIT_FILE_S = 0.5      # poll interval while waiting for the file to appear
_POST_TIMEOUT_S = 3.0


def predict_session_file_path(home: Path, agent_id: str, session_id: str) -> Path:
    """Return the path OpenClaw will write to for this session.

    OpenClaw's layout is `~/.openclaw/agents/<agent>/sessions/<session_id>.jsonl`.
    """
    return home / ".openclaw" / "agents" / agent_id / "sessions" / f"{session_id}.jsonl"


async def forward_session_events(
    session_file: Path,
    api_base_url: str,
    related_event_id: str,
    stop: asyncio.Event,
) -> None:
    """Tail `session_file` and POST normalized events to /api/agent/event.

    Runs until `stop` is set. Tolerates the file not existing yet (OpenClaw
    creates it lazily) and partial-read race conditions (we always seek to
    the last known byte position).
    """
    api_url = f"{api_base_url.rstrip('/')}/api/agent/event"
    pos = 0
    waiting_logged = False
    posted = 0
    async with httpx.AsyncClient(timeout=_POST_TIMEOUT_S) as client:
        while not stop.is_set():
            if not session_file.exists():
                if not waiting_logged:
                    _LOG.debug("Forwarder waiting for %s", session_file)
                    waiting_logged = True
                try:
                    await asyncio.wait_for(stop.wait(), timeout=_WAIT_FILE_S)
                except asyncio.TimeoutError:
                    pass
                continue

            try:
                with session_file.open("r", encoding="utf-8") as f:
                    f.seek(pos)
                    chunk = f.read()
                    new_pos = f.tell()
            except OSError as exc:
                _LOG.warning("Forwarder read failed (%s): %s", session_file, exc)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=_TAIL_POLL_S)
                except asyncio.TimeoutError:
                    pass
                continue

            if new_pos == pos:
                # No new bytes — sleep and re-poll
                try:
                    await asyncio.wait_for(stop.wait(), timeout=_TAIL_POLL_S)
                except asyncio.TimeoutError:
                    pass
                continue

            pos = new_pos
            # Process any complete lines in the chunk. Partial trailing
            # lines (no newline) get re-read next iteration via the seek.
            lines = chunk.splitlines(keepends=True)
            complete_lines = [l for l in lines if l.endswith("\n")]
            # Rewind position if there was a partial trailing line.
            if lines and not lines[-1].endswith("\n"):
                pos -= len(lines[-1])

            for raw in complete_lines:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                for event in _normalize(entry, related_event_id):
                    try:
                        await client.post(api_url, json=event)
                        posted += 1
                    except httpx.HTTPError as exc:
                        _LOG.warning("Forwarder POST failed: %s", exc)

    _LOG.info(
        "Forwarder done for %s (event=%s, posted=%d events)",
        session_file.name, related_event_id, posted,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(entry: dict[str, Any], related_event_id: str) -> list[dict[str, Any]]:
    """Translate one OpenClaw JSONL entry into 0+ UI-shaped events.

    OpenClaw's actual JSONL shape (observed):
      {"type":"message","message":{"role":"assistant","content":[
          {"type":"thinking","thinking":"..."},
          {"type":"toolCall","id":"...","name":"...","arguments":{...}}
      ]}}
      {"type":"message","message":{"role":"toolResult","toolName":"...","content":[...]}}
    """
    out: list[dict[str, Any]] = []
    msg = entry.get("message") or {}
    role = msg.get("role")
    ts = entry.get("timestamp") or _now()

    if role == "assistant":
        for item in msg.get("content") or []:
            kind = item.get("type")
            if kind == "thinking":
                text = (item.get("thinking") or "").strip()
                if text:
                    out.append({
                        "type": "thought",
                        "content": text,
                        "related_event_id": related_event_id,
                        "timestamp": ts,
                    })
            elif kind == "text":
                text = (item.get("text") or "").strip()
                if text:
                    out.append({
                        "type": "thought",
                        "content": text,
                        "related_event_id": related_event_id,
                        "timestamp": ts,
                    })
            elif kind == "toolCall":
                name = item.get("name") or "?"
                args = item.get("arguments") or {}
                out.append({
                    "type": "tool_call",
                    "content": {"name": name, "args": _summarize_args(args)},
                    "related_event_id": related_event_id,
                    "timestamp": ts,
                })
                # Both write_memory and draft_recommendation terminate an
                # investigation. Emit a guaranteed FINAL marker so the UI
                # can render the verdict regardless of whether the model
                # happens to use \boxed{} convention in its reasoning.
                short = _strip_prefix(name)
                if short == "draft_recommendation":
                    out.append({
                        "type": "verdict_drafted",
                        "content": {
                            "verdict_type": "recommended",
                            "source_tool": name,
                        },
                        "related_event_id": related_event_id,
                        "timestamp": ts,
                    })
                elif short == "write_memory":
                    verdict_type = (args.get("verdict_type")
                                    if isinstance(args, dict) else None) or "?"
                    out.append({
                        "type": "verdict_drafted",
                        "content": {
                            "verdict_type": verdict_type,
                            "source_tool": name,
                        },
                        "related_event_id": related_event_id,
                        "timestamp": ts,
                    })
    elif role == "toolResult":
        tool_name = msg.get("toolName") or "?"
        summary = _summarize_tool_result(msg, tool_name)
        out.append({
            "type": "tool_result",
            "content": {"name": tool_name, "summary": summary},
            "related_event_id": related_event_id,
            "timestamp": ts,
        })
    return out


def _summarize_args(args: dict[str, Any], max_chars: int = 240) -> str:
    """Render tool args as a compact JSON string clipped to max_chars."""
    try:
        s = json.dumps(args, separators=(",", ":"))
    except (TypeError, ValueError):
        s = repr(args)
    return s if len(s) <= max_chars else s[: max_chars - 1] + "…"


def _summarize_tool_result(msg: dict[str, Any], tool_name: str, max_chars: int = 240) -> str:
    """Produce a human-readable one-line summary of a tool result.

    Each tool returns a JSON payload (per `orbital_agent.tools.*`); we parse
    it and dispatch to a tool-specific formatter for legibility. On parse
    failure we fall back to a clipped raw string.
    """
    items = msg.get("content") or []
    raw_pieces: list[str] = []
    for it in items:
        if isinstance(it, dict) and it.get("type") == "text":
            raw_pieces.append(it.get("text") or "")
    raw = " ".join(p.strip() for p in raw_pieces).strip()
    if not raw:
        return "(empty result)"

    # Try to parse as JSON; if it's our tool's response dict, format it nicely.
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw if len(raw) <= max_chars else raw[: max_chars - 1] + "…"

    if isinstance(payload, dict) and "error" in payload:
        msg_text = str(payload.get("error", "unknown error"))
        return f"⚠ {msg_text}"

    formatter = _RESULT_FORMATTERS.get(_strip_prefix(tool_name))
    if formatter is not None:
        try:
            return formatter(payload)
        except (KeyError, TypeError, ValueError):
            pass  # fall through to clipped raw

    return raw if len(raw) <= max_chars else raw[: max_chars - 1] + "…"


def _strip_prefix(tool_name: str) -> str:
    """`orbital__get_space_weather` → `get_space_weather`."""
    return tool_name.split("__", 1)[-1] if "__" in tool_name else tool_name


# ── Per-tool result formatters ─────────────────────────────────────────────
# Each formatter takes the parsed payload dict and returns a one-line string.
# Keep summaries short, factual, and useful to a flight director reading the
# stream — not a debugger reading the raw return.

def _fmt_flagged_conjunctions(p: dict[str, Any]) -> str:
    items = p.get("conjunctions") or []
    n = p.get("count", len(items))
    return f"Found {n} flagged conjunction{'s' if n != 1 else ''}."


def _fmt_object_metadata(p: dict[str, Any]) -> str:
    name = p.get("name") or "?"
    kind = p.get("object_type") or "?"
    op = p.get("operator")
    is_man = p.get("is_maneuverable")
    fuel = p.get("fuel_remaining_mps")
    parts = [f"{name} ({kind}"]
    if op:
        parts[0] += f", {op}"
    parts[0] += ")"
    if is_man is True:
        parts.append("maneuverable")
        if fuel is not None:
            parts.append(f"{fuel:.1f} m/s Δv remaining")
    elif is_man is False:
        parts.append("non-maneuverable")
    return " · ".join(parts)


def _fmt_space_weather(p: dict[str, Any]) -> str:
    kp = p.get("kp_index")
    xray = p.get("xray_class") or "?"
    storm = p.get("geomag_storm_level") or "?"
    kp_s = f"Kp {kp:.2f}" if isinstance(kp, (int, float)) else "Kp ?"
    return f"{kp_s} · X-ray {xray} · {storm}"


def _fmt_conjunctions_for_asset(p: dict[str, Any]) -> str:
    norad = p.get("norad_id", "?")
    events = p.get("events") or []
    return f"{len(events)} upcoming event{'s' if len(events) != 1 else ''} for NORAD {norad}"


def _fmt_query_memory(p: dict[str, Any]) -> str:
    if p.get("found") and p.get("event_id"):
        events = p.get("events") or []
        e = events[0] if events else {}
        v = e.get("verdict") or {}
        if v:
            return f"Event {p['event_id'][:8]}: prior verdict={v.get('verdict_type', '?')}"
        return f"Event {p['event_id'][:8]}: no prior verdict"
    norad = p.get("norad_id", "?")
    n = p.get("count", len(p.get("events") or []))
    return f"{n} prior event{'s' if n != 1 else ''} for NORAD {norad}"


def _fmt_write_memory(p: dict[str, Any]) -> str:
    vt = p.get("verdict_type", "?")
    eid = p.get("event_id", "?")
    return f"Verdict '{vt}' recorded for event {eid[:8]}"


def _fmt_re_propagate(p: dict[str, Any]) -> str:
    state = p.get("state") or {}
    age_h = p.get("tle_age_hours")
    name = p.get("tle_name") or f"NORAD {state.get('norad_id', '?')}"
    r = state.get("r_eci_km") or []
    if isinstance(age_h, (int, float)) and len(r) == 3:
        return (
            f"{name}: r=({r[0]:.0f}, {r[1]:.0f}, {r[2]:.0f}) km · "
            f"TLE {age_h:.1f}h old"
        )
    return f"{name} propagated"


def _fmt_compute_pc(p: dict[str, Any]) -> str:
    pc = p.get("pc")
    band = p.get("pc_band", "?")
    miss = p.get("miss_distance_km")
    inf = p.get("covariance_inflation_used")
    pc_s = f"Pc {pc:.2e}" if isinstance(pc, (int, float)) else "Pc ?"
    parts = [pc_s, f"band={band}"]
    if isinstance(miss, (int, float)):
        parts.append(f"miss {miss:.3f} km")
    if isinstance(inf, (int, float)) and inf != 1.0:
        parts.append(f"σ×{inf:.2f}")
    return " · ".join(parts)


def _fmt_simulate_maneuver(p: dict[str, Any]) -> str:
    dv = p.get("dv_magnitude_mps")
    samples = p.get("samples") or []
    dv_s = f"{dv:.3f} m/s" if isinstance(dv, (int, float)) else "?"
    return f"Burn applied: Δv={dv_s} · {len(samples)} post-burn samples"


def _fmt_evaluate_plan(p: dict[str, Any]) -> str:
    total = p.get("total_dv_mps")
    resolved = len(p.get("resolved_event_ids") or [])
    evaluated = p.get("evaluated_event_count", 0)
    total_s = f"{total:.3f} m/s" if isinstance(total, (int, float)) else "?"
    return f"Plan: Δv total {total_s} · resolves {resolved}/{evaluated} events"


def _fmt_draft_recommendation(p: dict[str, Any]) -> str:
    vid = p.get("verdict_id", "?")
    dv = p.get("primary_total_dv_mps")
    alts = p.get("alternative_count", 0)
    resolved = p.get("conjunctions_resolved") or []
    dv_s = f"{dv:.3f} m/s" if isinstance(dv, (int, float)) else "?"
    return (
        f"Recommendation drafted ({vid[:8]}): primary Δv {dv_s} · "
        f"{alts} alternative{'s' if alts != 1 else ''} · "
        f"resolves {len(resolved)} event{'s' if len(resolved) != 1 else ''}"
    )


_RESULT_FORMATTERS = {
    "get_flagged_conjunctions": _fmt_flagged_conjunctions,
    "get_object_metadata": _fmt_object_metadata,
    "get_space_weather": _fmt_space_weather,
    "get_conjunctions_for_asset": _fmt_conjunctions_for_asset,
    "query_memory": _fmt_query_memory,
    "write_memory": _fmt_write_memory,
    "re_propagate": _fmt_re_propagate,
    "compute_collision_probability": _fmt_compute_pc,
    "simulate_maneuver": _fmt_simulate_maneuver,
    "evaluate_plan": _fmt_evaluate_plan,
    "draft_recommendation": _fmt_draft_recommendation,
}
