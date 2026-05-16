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
                if name.endswith("draft_recommendation"):
                    out.append({
                        "type": "verdict_drafted",
                        "content": {"name": name},
                        "related_event_id": related_event_id,
                        "timestamp": ts,
                    })
    elif role == "toolResult":
        tool_name = msg.get("toolName") or "?"
        summary = _summarize_tool_result(msg)
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


def _summarize_tool_result(msg: dict[str, Any], max_chars: int = 320) -> str:
    """Pull a short text summary out of a tool result for the UI."""
    items = msg.get("content") or []
    pieces: list[str] = []
    for it in items:
        if isinstance(it, dict) and it.get("type") == "text":
            pieces.append(it.get("text") or "")
    text = " ".join(p.strip() for p in pieces).strip()
    if not text:
        return "(empty result)"
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"
