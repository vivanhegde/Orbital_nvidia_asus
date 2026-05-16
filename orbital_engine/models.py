"""Dataclasses for propagation, screening, and probability of collision."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class PropagatedState:
    """ECI/TEME state from SGP4 (position and velocity in km and km/s)."""

    norad_id: int
    t: datetime
    r_eci: tuple[float, float, float] | None
    v_eci: tuple[float, float, float] | None
    error_code: int


@dataclass(frozen=True)
class ConjunctionCandidate:
    """A close approach found by coarse + refined time search."""

    id: str
    obj1_norad_id: int
    obj2_norad_id: int
    obj1_name: str
    obj2_name: str
    tca: datetime
    miss_distance_km: float
    relative_velocity_km_s: float
    obj1_state_at_tca: PropagatedState
    obj2_state_at_tca: PropagatedState
    detected_at: datetime = field(compare=False)
