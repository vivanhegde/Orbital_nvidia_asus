"""Probability of collision (2D isotropic Gaussian over a hard body disc).

Hackathon-grade Foster-style encounter: project geometry into the plane
perpendicular to relative velocity and integrate an isotropic Gaussian
(position uncertainty) over a disc of radius ``hard_body_radius_m`` centered
on the projected miss point.
"""

from __future__ import annotations

import numpy as np

from orbital_engine.models import PropagatedState


def _teme_basis_perpendicular(v_hat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return orthonormal ``u``, ``w`` spanning the plane perpendicular to ``v_hat``."""
    if np.linalg.norm(v_hat) < 1e-12:
        raise ValueError("relative velocity too small")
    v_hat = v_hat / np.linalg.norm(v_hat)
    if abs(float(v_hat[2])) < 0.9:
        aux = np.array([0.0, 0.0, 1.0])
    else:
        aux = np.array([1.0, 0.0, 0.0])
    u = np.cross(v_hat, aux)
    u = u / np.linalg.norm(u)
    w = np.cross(v_hat, u)
    return u, w


def compute_pc(
    state1: PropagatedState,
    state2: PropagatedState,
    covariance1_m: float = 100.0,
    covariance2_m: float = 200.0,
    hard_body_radius_m: float = 5.0,
    covariance_inflation: float = 1.0,
    grid_points: int = 401,
) -> float:
    """
    Estimate collision probability for a short encounter using a planar
    Gaussian and a circular hard body.

    Returns:
        Scalar in ``[0, 1]``. Returns ``0.0`` if states lack usable position
        or relative speed is degenerate.

    Notes:
        Combines spherical 1σ position uncertainties as independent
        contributors: effective ``σ = sqrt((σ₁·f)² + (σ₂·f)²)`` in the
        encounter plane. Integrates ``N(0, σ²I)`` over the disc of radius
        ``hard_body_radius_m`` centered at the projected miss vector.
    """
    if (
        state1.r_eci is None
        or state2.r_eci is None
        or state1.v_eci is None
        or state2.v_eci is None
    ):
        return 0.0

    r1 = np.array(state1.r_eci, dtype=np.float64) * 1000.0
    r2 = np.array(state2.r_eci, dtype=np.float64) * 1000.0
    v1 = np.array(state1.v_eci, dtype=np.float64) * 1000.0
    v2 = np.array(state2.v_eci, dtype=np.float64) * 1000.0

    r = r2 - r1
    v = v2 - v1
    v_norm = np.linalg.norm(v)
    if v_norm < 1e-3:
        return 0.0
    v_hat = v / v_norm

    # Miss vector in the B-plane (km → m already applied to r,v).
    r_perp = r - np.dot(r, v_hat) * v_hat
    u, w = _teme_basis_perpendicular(v_hat)
    bx = float(np.dot(r_perp, u))
    by = float(np.dot(r_perp, w))

    s1 = max(covariance1_m * covariance_inflation, 1e-6)
    s2 = max(covariance2_m * covariance_inflation, 1e-6)
    sigma = float(np.sqrt(s1**2 + s2**2))
    if sigma <= 0.0:
        return 0.0

    rhb = max(hard_body_radius_m, 1e-6)
    half_span = max(8.0 * sigma, rhb * 3.0, abs(bx), abs(by))

    xs = np.linspace(-half_span, half_span, grid_points)
    ys = np.linspace(-half_span, half_span, grid_points)
    dx = float(xs[1] - xs[0])
    dy = float(ys[1] - ys[0])
    X, Y = np.meshgrid(xs, ys, indexing="xy")
    pdf = (1.0 / (2.0 * np.pi * sigma**2)) * np.exp(-(X**2 + Y**2) / (2.0 * sigma**2))
    mask = (X - bx) ** 2 + (Y - by) ** 2 <= rhb**2
    pc = float(np.sum(pdf[mask]) * dx * dy)
    return max(0.0, min(1.0, pc))
