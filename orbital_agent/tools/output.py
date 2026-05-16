"""Output MCP tools: draft_recommendation persists the agent's final verdict.

The recommendation structure is deeply nested (primary plan + multiple
alternative plans, each with a burn sequence). Nemotron Nano can't reliably
construct that as a Pydantic-typed argument, so the tool takes the entire
recommendation as a JSON string and parses + validates it inside.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from orbital_agent._paths import ensure_repo_on_path
from orbital_agent.tools._pydantic_models import RecommendationOutput

ensure_repo_on_path()

from orbital_agent.tools.memory import _store  # noqa: E402

_LOG = logging.getLogger(__name__)


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"error": msg}
    out.update(extra)
    return out


_RECOMMENDATION_SCHEMA_HINT = """\
Required JSON shape for `recommendation_json`:
{
  "asset_id": <int NORAD ID of asset to maneuver>,
  "urgency": "informational" | "act_within_24hr" | "act_within_12hr" | "act_within_6hr" | "act_immediately",
  "primary_plan": {
    "name": "<short label, e.g. 'split-burn'>",
    "burns": [
      {"dv_mps": <float>, "direction": "prograde"|"retrograde"|"radial"|"anti-radial"|"normal"|"anti-normal",
       "burn_time": "<UTC ISO 8601 timestamp>"}
    ],
    "total_dv_mps": <float; must equal sum of burns.dv_mps within 10%>,
    "conjunctions_resolved": ["<event_id>", ...]
  },
  "alternative_plans": [ { ...same shape as primary_plan }, ... ]   (at least 1 entry),
  "reasoning": "<plain-English rationale, ≥20 chars, readable in <30s>"
}
"""


def draft_recommendation(
    event_id: str,
    recommendation_json: str,
) -> dict[str, Any]:
    """Persist a maneuver recommendation as a verdict row for the Approver UI.

    Call this at the end of Plan mode after evaluating at least two candidate
    plans. The recommendation is supplied as a JSON string; this tool parses
    and validates it via Pydantic before writing to the verdicts table. On
    invalid JSON or invalid shape, returns a clear error you can correct
    and retry.

    Args:
        event_id: Stable event ID this recommendation is for.
        recommendation_json: JSON string conforming to the schema below.

    Required shape:
        See the docstring's schema hint — fields are asset_id, urgency,
        primary_plan {name, burns[], total_dv_mps, conjunctions_resolved[]},
        alternative_plans (at least one, same shape), reasoning.
    """
    store = _store()
    if store.get_event(event_id) is None:
        return _err(f"event_id not found: {event_id}")

    try:
        parsed = json.loads(recommendation_json)
    except json.JSONDecodeError as exc:
        return _err(
            f"recommendation_json is not valid JSON: {exc}",
            schema_hint=_RECOMMENDATION_SCHEMA_HINT,
        )

    try:
        rec = RecommendationOutput.model_validate(parsed)
    except ValidationError as exc:
        return _err(
            f"recommendation_json shape is invalid: {exc.errors()}",
            schema_hint=_RECOMMENDATION_SCHEMA_HINT,
        )

    plan_blob: dict[str, Any] = {
        "asset_id": rec.asset_id,
        "urgency": rec.urgency,
        "primary_plan": {
            "name": rec.primary_plan.name,
            "burns": [
                {
                    "dv_mps": b.dv_mps,
                    "direction": b.direction,
                    "burn_time": b.burn_time.astimezone(timezone.utc).isoformat(),
                }
                for b in rec.primary_plan.burns
            ],
            "total_dv_mps": rec.primary_plan.total_dv_mps,
            "conjunctions_resolved": rec.primary_plan.conjunctions_resolved,
        },
        "alternative_plans": [
            {
                "name": ap.name,
                "burns": [
                    {
                        "dv_mps": b.dv_mps,
                        "direction": b.direction,
                        "burn_time": b.burn_time.astimezone(timezone.utc).isoformat(),
                    }
                    for b in ap.burns
                ],
                "total_dv_mps": ap.total_dv_mps,
                "conjunctions_resolved": ap.conjunctions_resolved,
            }
            for ap in rec.alternative_plans
        ],
        "reasoning": rec.reasoning,
    }

    vid = store.record_verdict(
        event_id=event_id,
        verdict_type="recommended",
        reasoning=rec.reasoning,
        plan=plan_blob,
    )
    return {
        "verdict_id": vid,
        "event_id": event_id,
        "verdict_type": "recommended",
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "primary_total_dv_mps": rec.primary_plan.total_dv_mps,
        "alternative_count": len(rec.alternative_plans),
        "conjunctions_resolved": rec.primary_plan.conjunctions_resolved,
    }
