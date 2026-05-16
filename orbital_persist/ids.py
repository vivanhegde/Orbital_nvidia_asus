"""Stable identifiers for conjunction events."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone


def stable_event_id(norad_a: int, norad_b: int, tca: datetime) -> str:
    """
    SHA1 hex of ``min:max:tca_hour_utc`` where ``tca_hour`` is truncated to whole hours in UTC.
    """
    lo, hi = (norad_a, norad_b) if norad_a <= norad_b else (norad_b, norad_a)
    t = tca.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    raw = f"{lo}:{hi}:{t.isoformat()}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def covariance_inflation_from_kp(kp: float) -> float:
    """1.0 at Kp≤2, linear to ~1.5 near Kp 5, capped at 2.0 for Kp≥7."""
    if kp <= 2.0:
        return 1.0
    if kp >= 7.0:
        return 2.0
    return 1.0 + (kp - 2.0) * 0.1
