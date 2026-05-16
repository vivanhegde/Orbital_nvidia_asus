"""Typed records for persisted state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ConjunctionEventRecord:
    event_id: str
    obj1_norad_id: int
    obj1_name: str
    obj2_norad_id: int
    obj2_name: str
    first_detected_at: datetime
    last_seen_at: datetime
    tca: datetime
    initial_miss_distance_km: float
    initial_pc: float
    relative_velocity_km_s: float
    status: str
    space_weather_at_detection: dict[str, Any] | None


@dataclass(frozen=True)
class PcSnapshotRow:
    snapshot_id: int
    event_id: str
    snapshot_at: datetime
    pc: float
    miss_distance_km: float
    covariance_inflation: float
    kp_index: float | None
    space_weather_snapshot: dict[str, Any] | None


@dataclass(frozen=True)
class VerdictRecord:
    verdict_id: str
    event_id: str
    issued_at: datetime
    verdict_type: str
    reasoning: str
    plan_json: dict[str, Any] | None
    operator_decision: str | None
    operator_decided_at: datetime | None
    operator_notes: str | None
