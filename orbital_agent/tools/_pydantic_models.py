"""Pydantic models for nested tool arguments + recommendation output schema.

FastMCP introspects type hints and docstrings to publish each tool's schema
to the connected agent. Where a tool argument is a nested structure, we use
a Pydantic model so the schema is precise instead of devolving to "object".
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DeltaV(BaseModel):
    """Δv vector in ECI/TEME frame, km/s."""

    x_kms: float = Field(..., description="X component in km/s")
    y_kms: float = Field(..., description="Y component in km/s")
    z_kms: float = Field(..., description="Z component in km/s")

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.x_kms, self.y_kms, self.z_kms)


class Burn(BaseModel):
    """One impulsive burn in a maneuver plan."""

    dv_mps: float = Field(..., gt=0, description="Δv magnitude in meters per second")
    direction: Literal["prograde", "retrograde", "radial", "anti-radial", "normal", "anti-normal"] = Field(
        ...,
        description=(
            "Burn direction relative to the asset's orbit at the burn time. "
            "Prograde adds to velocity; retrograde subtracts. Radial points "
            "away from Earth; anti-radial toward Earth. Normal is out of the "
            "orbit plane."
        ),
    )
    burn_time: datetime = Field(..., description="UTC time at which the burn is applied")

    @field_validator("burn_time")
    @classmethod
    def _require_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("burn_time must be timezone-aware UTC")
        return v


class ObjectStateInput(BaseModel):
    """Position + velocity input for compute_collision_probability.

    Units: position in km, velocity in km/s, ECI frame.
    """

    norad_id: int
    r_eci_km: list[float] = Field(..., min_length=3, max_length=3)
    v_eci_kms: list[float] = Field(..., min_length=3, max_length=3)


class ManeuverPlanInput(BaseModel):
    """A candidate maneuver plan: an ordered burn sequence + bookkeeping."""

    name: str = Field(..., description="Short human label, e.g. 'single-burn' / 'split-burn'")
    burns: list[Burn] = Field(..., min_length=1)
    total_dv_mps: float = Field(..., ge=0)
    conjunctions_resolved: list[str] = Field(
        default_factory=list,
        description="Event IDs this plan is expected to resolve.",
    )

    @field_validator("total_dv_mps")
    @classmethod
    def _sum_matches(cls, v: float, info) -> float:
        burns = info.data.get("burns") or []
        if not burns:
            return v
        actual = sum(b.dv_mps for b in burns)
        if abs(actual - v) > 0.01 + 0.1 * actual:
            raise ValueError(
                f"total_dv_mps={v} does not match sum of burn dv_mps={actual:.3f} (±10% tolerance)"
            )
        return v


class RecommendationOutput(BaseModel):
    """The structured object draft_recommendation persists into the verdict row."""

    asset_id: int = Field(..., description="NORAD ID of the asset to maneuver")
    urgency: Literal[
        "informational",
        "act_within_24hr",
        "act_within_12hr",
        "act_within_6hr",
        "act_immediately",
    ]
    primary_plan: ManeuverPlanInput
    alternative_plans: list[ManeuverPlanInput] = Field(..., min_length=1)
    reasoning: str = Field(..., min_length=20, description="Plain-English rationale a human reads in <30s")
