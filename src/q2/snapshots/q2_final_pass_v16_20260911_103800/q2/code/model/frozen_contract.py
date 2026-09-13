"""Named constants for the frozen Q2 contract.

This module is deliberately declarative: production geometry modules retain
their existing typed implementations, while reports and downstream tooling
can import one unambiguous set of model constants without retyping them.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.q2.code.geometry.primitives import Point2


OMEGA_CENTER = Point2(0.0, 0.0)
OMEGA_RADIUS_M = 1800.0
RADIAL_LO_M = 5.0
RADIAL_HI_M = 1500.0
NEAR_DISTANCE_M = 5.0
RECEPTION_RADIUS_M = 1000.0
EPSILON_DEG = 1.0
ADMISSIBILITY_MULTIPLIER = 3.0


@dataclass(frozen=True)
class FrozenQ2Contract:
    """Immutable, serializable summary of the mathematical constants."""

    omega_center: Point2 = OMEGA_CENTER
    omega_radius_m: float = OMEGA_RADIUS_M
    radial_lo_m: float = RADIAL_LO_M
    radial_hi_m: float = RADIAL_HI_M
    near_distance_m: float = NEAR_DISTANCE_M
    reception_radius_m: float = RECEPTION_RADIUS_M
    epsilon_deg: float = EPSILON_DEG
    admissibility_multiplier: float = ADMISSIBILITY_MULTIPLIER


FROZEN_Q2_CONTRACT = FrozenQ2Contract()

