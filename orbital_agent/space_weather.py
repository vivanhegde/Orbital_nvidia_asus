"""Helpers connecting space-weather inputs to engine parameters.

Kept separate from the MCP tool layer so other callers (the runner sidecar's
heartbeat, future analytics) can reuse them without importing tool code.
"""

from __future__ import annotations


def covariance_inflation_from_kp(kp: float) -> float:
    """Inflate position covariance when geomagnetic activity raises drag noise.

    Per design doc §5: "during elevated geomagnetic activity (Kp above 5),
    atmospheric drag predictions are noisier — inflate covariance and widen
    Pc uncertainty bounds."

    Returns a multiplier on the 1-σ position uncertainty:
        Kp < 5.0   → 1.0   (no inflation)
        5.0 ≤ Kp < 6.0 → 1.18 (minor storm)
        Kp ≥ 6.0   → 1.4   (moderate-or-worse storm)
    """
    if kp < 5.0:
        return 1.0
    if kp < 6.0:
        return 1.18
    return 1.4
