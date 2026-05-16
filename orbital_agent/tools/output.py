"""Output MCP tools: draft_recommendation persists the agent's final verdict."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from orbital_agent._paths import ensure_repo_on_path
from orbital_agent.tools._pydantic_models import RecommendationOutput

ensure_repo_on_path()

from orbital_agent.tools.memory import _store  # noqa: E402

_LOG = logging.getLogger(__name__)


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"error": msg}
    out.update(extra)
    return out


def draft_recommendation(
    event_id: str,
    recommendation: RecommendationOutput,
) -> dict[str, Any]:
    """Persist an action-required maneuver recommendation for the Approver UI.

    Use this tool **only** when refined Pc and policy indicate action is required
    (typically Pc >= 1e-4 after fresh propagation, unless metadata shows the asset
    is non-maneuverable). Do not use `write_memory` for these cases.

    Call after evaluating at least two candidate plans when possible. The
    recommendation must include the asset and conjunctions involved, a primary
    plan with burns and total Δv, at least one alternative plan, plain-English
    reasoning the flight director can read in <30 seconds, and an urgency level.

    Args:
        event_id: Stable event ID this recommendation is for (from the
            conjunction that triggered the investigation).
        recommendation: RecommendationOutput — see schema for required fields.

    Returns:
        {verdict_id, event_id, verdict_type: "recommended", issued_at,
         primary_total_dv_mps, alternative_count, conjunctions_resolved}
    """
    store = _store()
    if store.get_event(event_id) is None:
        return _err(f"event_id not found: {event_id}")

    plan_blob: dict[str, Any] = {
        "asset_id": recommendation.asset_id,
        "urgency": recommendation.urgency,
        "primary_plan": {
            "name": recommendation.primary_plan.name,
            "burns": [
                {
                    "dv_mps": b.dv_mps,
                    "direction": b.direction,
                    "burn_time": b.burn_time.astimezone(timezone.utc).isoformat(),
                }
                for b in recommendation.primary_plan.burns
            ],
            "total_dv_mps": recommendation.primary_plan.total_dv_mps,
            "conjunctions_resolved": recommendation.primary_plan.conjunctions_resolved,
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
            for ap in recommendation.alternative_plans
        ],
        "reasoning": recommendation.reasoning,
    }

    vid = store.record_verdict(
        event_id=event_id,
        verdict_type="recommended",
        reasoning=recommendation.reasoning,
        plan=plan_blob,
    )
    return {
        "verdict_id": vid,
        "event_id": event_id,
        "verdict_type": "recommended",
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "primary_total_dv_mps": recommendation.primary_plan.total_dv_mps,
        "alternative_count": len(recommendation.alternative_plans),
        "conjunctions_resolved": recommendation.primary_plan.conjunctions_resolved,
    }
