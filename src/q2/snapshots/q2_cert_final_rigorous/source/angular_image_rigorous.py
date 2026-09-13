"""Rigorous superset of the measured-bearing set for the frozen case (s.11).

For S2 outside closure(A1) the true-bearing image

    Theta2(S2) = { arg(G - S2) : G in A1, ||G - S2|| > 5 }

is a connected interval whose endpoints are attained on the boundary of the
polar rectangle.  Ignoring the near-disk removal and using the whole closure
rectangle can only enlarge the set, which is safe for an upper-bound scan:

    Theta2_hat = Theta2 ⊕ [-eps, +eps]  ⊆  [amin - eps, amax + eps]

with [amin, amax] the rigorous global min/max of arg(G - S2) over the
closure rectangle, computed by polar branch-and-bound.

If S2 lies inside closure(A1) (never for certified incumbents here) or the
branch cut is crossed, we return the full circle: still a valid superset.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.q2.formal.ivl_geometry import (
    EPS,
    IvlPoint,
    arg_enclosure,
    polar_point,
    BranchCutError,
)
from src.q2.formal.polar_bb import polar_max, polar_min
from src.q2.formal.rigorous_arithmetic import Ivl


@dataclass
class AngularSuperset:
    beta_lo: Ivl            # rigorous lower endpoint of the measured set
    beta_hi: Ivl            # rigorous upper endpoint
    full_circle: bool
    pieces: int


def measured_bearing_superset(s2: IvlPoint, target_tol: float = 1e-9) -> AngularSuperset:
    """Rigorous superset [beta_lo, beta_hi] of Theta2_hat(S2)."""
    s2x, s2y = s2.x.mid_float(), s2.y.mid_float()
    r2 = math.hypot(s2x, s2y)
    phi2 = math.degrees(math.atan2(s2y, s2x))
    if r2 <= 1500.0 and abs(phi2) <= 1.0 + 1e-12:
        # S2 inside closure(A1): angle set wraps; use the full circle
        return AngularSuperset(Ivl.from_float(-math.pi), Ivl.from_float(math.pi),
                               True, 0)

    def f(rho: Ivl, phi: Ivl) -> Ivl:
        g = polar_point(rho, phi)
        rel = IvlPoint(g.x - s2.x, g.y - s2.y)
        return arg_enclosure(rel)

    def ff(rho: float, phi: float) -> float:
        return math.atan2(rho * math.sin(phi) - s2y, rho * math.cos(phi) - s2x)

    try:
        amin = polar_min(f, ff, target_tol=target_tol)
        amax = polar_max(f, ff, target_tol=target_tol)
    except BranchCutError:
        return AngularSuperset(Ivl.from_float(-math.pi), Ivl.from_float(math.pi),
                               True, 0)
    beta_lo = amin.value - EPS
    beta_hi = amax.value + EPS
    return AngularSuperset(beta_lo, beta_hi, False,
                           amin.pieces_evaluated + amax.pieces_evaluated)
