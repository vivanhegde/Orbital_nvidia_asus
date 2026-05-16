"""Memory MCP tools backed by orbital_persist.EventStore.

Both tools share one process-wide EventStore handle opened against the
configured SQLite path. The store is thread-safe (uses an internal RLock).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from orbital_agent._paths import ensure_repo_on_path
from orbital_agent.config import load as load_config

ensure_repo_on_path()

from orbital_persist.store import EventStore  # noqa: E402

_LOG = logging.getLogger(__name__)
_CONFIG = load_config()
_STORE: EventStore | None = None
_STORE_LOCK = threading.Lock()


def _store() -> EventStore:
    global _STORE
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                _STORE = EventStore(_CONFIG.db_path)
                _LOG.info("Memory tools attached to EventStore at %s", _CONFIG.db_path)
    return _STORE


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def query_memory(
    norad_id: int | None = None,
    event_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Retrieve prior conjunction events and any verdicts attached to them.

    Two modes:
      - If event_id is given, returns details for that single event including
        its latest Pc snapshot and any verdict (operator decision, plan, etc.).
      - Otherwise, returns the most recent events involving `norad_id` (capped
        by `limit`, max 50), each with its latest Pc snapshot and verdict
        summary. Used by the agent to check "what happened the last time this
        asset had a conjunction".

    Returns:
        {events: [...]} where each entry has event_id, partner_norad_id,
        partner_name, tca, initial_pc, latest_pc, miss_distance_km, status,
        verdict_type, operator_decision, issued_at, plan.
    """
    limit = max(1, min(50, int(limit)))
    store = _store()

    if event_id:
        ev = store.get_event(event_id)
        if ev is None:
            return {"events": [], "found": False, "event_id": event_id}
        snap = store.get_latest_pc_snapshot(event_id)
        pending = store.list_pending_verdicts()
        verdict = next((v for v in pending if v.event_id == event_id), None)
        return {
            "events": [_event_to_dict(ev, snap, verdict)],
            "found": True,
            "event_id": event_id,
        }

    if norad_id is None:
        return {"error": "Either norad_id or event_id is required.", "events": []}

    events = store.query_events_for_asset(int(norad_id), limit=limit)
    pending = store.list_pending_verdicts()
    pending_by_event = {v.event_id: v for v in pending}
    out: list[dict[str, Any]] = []
    for ev in events:
        snap = store.get_latest_pc_snapshot(ev.event_id)
        out.append(_event_to_dict(ev, snap, pending_by_event.get(ev.event_id)))
    return {"norad_id": int(norad_id), "events": out, "count": len(out)}


def write_memory(
    event_id: str,
    verdict_type: str,
    reasoning: str,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a verdict (dismiss / watch / recommended) for an event.

    The agent calls this at the end of every Investigate cycle. For dismiss
    and watch verdicts, `plan` is null. For recommended verdicts, `plan` is
    the full RecommendationOutput shape (primary + alternatives + reasoning
    + urgency) which the Approver UI consumes.

    Args:
        event_id: Stable event ID from conjunction_events
        verdict_type: One of "dismissed", "watch", "recommended"
        reasoning: Plain-English explanation a flight director can read in <30s
        plan: For "recommended" verdicts, the full plan JSON. Else null.

    Returns:
        {verdict_id, event_id, verdict_type, issued_at}
    """
    if verdict_type not in {"dismissed", "watch", "recommended"}:
        return {
            "error": f"verdict_type must be one of: dismissed, watch, recommended (got {verdict_type!r})",
        }
    store = _store()
    if store.get_event(event_id) is None:
        return {"error": f"event_id not found: {event_id}"}

    vid = store.record_verdict(
        event_id=event_id,
        verdict_type=verdict_type,
        reasoning=reasoning,
        plan=plan,
    )
    return {
        "verdict_id": vid,
        "event_id": event_id,
        "verdict_type": verdict_type,
        "issued_at": _iso(datetime.now(timezone.utc)),
    }


def _event_to_dict(ev, snap, verdict) -> dict[str, Any]:
    d: dict[str, Any] = {
        "event_id": ev.event_id,
        "obj1_norad_id": ev.obj1_norad_id,
        "obj1_name": ev.obj1_name,
        "obj2_norad_id": ev.obj2_norad_id,
        "obj2_name": ev.obj2_name,
        "tca": _iso(ev.tca),
        "first_detected_at": _iso(ev.first_detected_at),
        "last_seen_at": _iso(ev.last_seen_at),
        "initial_pc": ev.initial_pc,
        "initial_miss_distance_km": ev.initial_miss_distance_km,
        "relative_velocity_km_s": ev.relative_velocity_km_s,
        "status": ev.status,
    }
    if snap is not None:
        d["latest_pc"] = snap.pc
        d["latest_miss_km"] = snap.miss_distance_km
        d["latest_pc_at"] = _iso(snap.snapshot_at)
        d["latest_kp_index"] = snap.kp_index
    if verdict is not None:
        d["verdict"] = {
            "verdict_id": verdict.verdict_id,
            "verdict_type": verdict.verdict_type,
            "reasoning": verdict.reasoning,
            "issued_at": _iso(verdict.issued_at),
            "operator_decision": verdict.operator_decision,
            "operator_decided_at": _iso(verdict.operator_decided_at),
            "plan": verdict.plan_json,
        }
    return d
