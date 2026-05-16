"""Local LLM agent endpoints (status + recommend)."""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from orbital_api import llm_client

router = APIRouter(prefix="/agent", tags=["agent"])
recommend_compat_router = APIRouter(tags=["agent-compat"])

ORBITAL_SYSTEM_PROMPT = (
    "You are Orbital, an autonomous orbital conjunction triage agent running locally on DGX Spark using NVIDIA Nemotron. "
    "You do not perform orbital mechanics calculations yourself. Deterministic code computes propagation, miss distance, "
    "relative velocity, probability estimates, and policy gates. Your job is to reason over structured tool outputs "
    "and produce an operator-reviewable recommendation. Return ONLY valid JSON."
)

JSON_SHAPE_HINT = """
Return a JSON object exactly in this shape (no markdown, no extra text):
{
  "summary": "string",
  "risk_level": "LOW" | "WATCH" | "HIGH" | "CRITICAL",
  "recommendation": "MONITOR_ONLY" | "REQUEST_FRESH_EPHEMERIS" | "HUMAN_REVIEW_REQUIRED" | "MANEUVER_RECOMMENDED",
  "confidence": "LOW" | "MEDIUM" | "HIGH",
  "rationale": ["string", ...],
  "suggested_next_steps": ["string", ...]
}
"""


class RecommendRequest(BaseModel):
    prompt: str
    context: dict[str, Any] = Field(default_factory=dict)


def _extract_json_object(text: str) -> str | None:
    m = re.search(r"\{[\s\S]*\}", text)
    return m.group(0) if m else None


def _parse_agent_output(raw: str) -> dict[str, Any] | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    blob = _extract_json_object(raw)
    if blob:
        try:
            obj = json.loads(blob)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _validate_output(obj: dict[str, Any]) -> dict[str, Any] | None:
    required = {"summary", "risk_level", "recommendation", "confidence", "rationale", "suggested_next_steps"}
    if not required.issubset(obj.keys()):
        return None
    if not isinstance(obj.get("rationale"), list) or not isinstance(obj.get("suggested_next_steps"), list):
        return None
    return {
        "summary": str(obj["summary"]),
        "risk_level": str(obj["risk_level"]),
        "recommendation": str(obj["recommendation"]),
        "confidence": str(obj["confidence"]),
        "rationale": [str(x) for x in obj["rationale"]],
        "suggested_next_steps": [str(x) for x in obj["suggested_next_steps"]],
    }


def _fallback(context: dict[str, Any]) -> dict[str, Any]:
    rl = context.get("risk_level")
    risk = rl if isinstance(rl, str) and rl else "HIGH"
    return {
        "summary": "Model returned malformed output.",
        "risk_level": risk,
        "recommendation": "HUMAN_REVIEW_REQUIRED",
        "confidence": "LOW",
        "rationale": ["Fallback used because model output was not valid JSON."],
        "suggested_next_steps": ["Request human review.", "Rerun with fresh data."],
    }


def run_recommend(req: RecommendRequest) -> dict[str, Any]:
    user_parts = [
        req.prompt.strip(),
        "",
        "Structured context (from deterministic tools, do not recompute):",
        json.dumps(req.context, indent=2, default=str),
        "",
        JSON_SHAPE_HINT,
    ]
    user_content = "\n".join(user_parts)
    result = llm_client.chat_completion(system=ORBITAL_SYSTEM_PROMPT, user=user_content)
    if result.error:
        out = _fallback(req.context)
        return out

    parsed = _parse_agent_output(result.raw_text)
    if parsed is None:
        return _fallback(req.context)

    validated = _validate_output(parsed)
    if validated is None:
        return _fallback(req.context)

    return validated


@router.get("/status")
def agent_status() -> dict[str, Any]:
    cfg = llm_client.read_llm_config()
    connected = llm_client.probe_model_connected()
    return {
        "agent_mode": cfg["agent_mode"],
        "llm_base_url": cfg["llm_base_url"],
        "llm_model": cfg["llm_model"],
        "chat_url": llm_client.chat_completions_url(),
        "model_connected": connected,
        "last_error": llm_client.get_last_error(),
    }


@router.post("/recommend")
def agent_recommend(req: RecommendRequest) -> dict[str, Any]:
    return run_recommend(req)


@recommend_compat_router.post("/recommend")
def recommend_compat(req: RecommendRequest) -> dict[str, Any]:
    return run_recommend(req)
