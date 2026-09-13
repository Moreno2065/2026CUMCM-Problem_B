"""Adversarial-scenario loss for the frozen Q2 model (spec sections 6, 15).

A physical scenario is s = (G, e) with G a *strictly legal* A1 point
(5 < |G| <= 1500, |arg G| <= eps, verified at construction) and a bearing
error e in [-eps, +eps].  For a second station S2:

    loss(S2; s) = 0                                  if ||S2 - G|| <= 5
                = D_Q1(S2, arg(G - S2) + e)          otherwise
                = +inf                               if the Q1 join is
                                                       unbounded

This module provides:

* ``float_point_loss``   - fast deterministic float oracle (heuristics only)
* ``point_loss_enclosure`` - rigorous point enclosure (testing/validation)
* ``box_loss_lower``     - rigorous lower bound over an S2 box (spec s.15)

The master lower bound of spec section 16 is max over scenarios of
``box_loss_lower``; validity rests on: for every S2 in the box the true
measured bearing arg(G - S2) + e lies in the enclosure beta(B), and every
definitely-feasible vertex pair is feasible at the true (S2, beta), so the
true diameter dominates the pair's minimum distance over the box.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.q2.formal.q1_diameter_interval import Q1DiamEnclosure, q1_diameter_enclosure
from src.q2.formal.rigorous_arithmetic import Ivl, Tri
from src.q2.formal.ivl_geometry import (
    EPS,
    BranchCutError,
    IvlPoint,
    arg_enclosure,
    box_point_distance,
)


class NearMixedBranch(Exception):
    """Internal signal: box straddles the near circle (split, don't average)."""


@dataclass(frozen=True)
class Scenario:
    """A physically legal adversarial scenario s = (G, e)."""

    gx: float
    gy: float
    e_deg: float          # bearing error in degrees, in [-1, 1]
    label: str = ""

    def __post_init__(self):
        rho = math.hypot(self.gx, self.gy)
        phi = math.degrees(math.atan2(self.gy, self.gx))
        if not (5.0 < rho <= 1500.0):
            raise ValueError(f"scenario G not in radial range: rho={rho}")
        if not (-1.0 - 1e-12 <= phi <= 1.0 + 1e-12):
            raise ValueError(f"scenario G outside wedge: phi={phi}")
        if not (-1.0 - 1e-12 <= self.e_deg <= 1.0 + 1e-12):
            raise ValueError(f"scenario error outside [-1,1] deg: {self.e_deg}")

    @property
    def rho(self) -> float:
        return math.hypot(self.gx, self.gy)

    @property
    def phi_deg(self) -> float:
        return math.degrees(math.atan2(self.gy, self.gx))

    def g_point(self) -> IvlPoint:
        return IvlPoint.from_floats(self.gx, self.gy)

    def e_interval(self) -> Ivl:
        return Ivl.from_float(math.radians(self.e_deg))


# ----------------------------------------------------------------------
# float oracle (NOT for certificates; candidate generation and fuzzing)
# ----------------------------------------------------------------------
def _float_diameter(s2x: float, s2y: float, beta: float, eps: float) -> float:
    """Fast float D_Q1 for the frozen case; mirrors the interval kernel."""
    up = (math.cos(eps), math.sin(eps))
    um = (math.cos(-eps), math.sin(-eps))
    vp = (math.cos(beta + eps), math.sin(beta + eps))
    vm = (math.cos(beta - eps), math.sin(beta - eps))
    bd = (beta + math.pi) % (2 * math.pi) - math.pi
    if abs(bd) <= 2 * eps:
        return math.inf  # direction intervals overlap -> unbounded
    pts: list[tuple[float, float]] = []

    def in_wedge2(px: float, py: float) -> bool:
        rx, ry = px - s2x, py - s2y
        return (vp[0] * ry - vp[1] * rx <= 0.0) and (vm[0] * ry - vm[1] * rx >= 0.0)

    if in_wedge2(0.0, 0.0):
        pts.append((0.0, 0.0))
    if up[0] * s2y - up[1] * s2x <= 0.0 and um[0] * s2y - um[1] * s2x >= 0.0:
        pts.append((s2x, s2y))
    for u in (up, um):
        for v, other in ((vp, vm), (vm, vp)):
            denom = u[0] * v[1] - u[1] * v[0]
            t = (s2x * v[1] - s2y * v[0]) / denom
            if t < 0.0:
                continue
            px, py = t * u[0], t * u[1]
            rx, ry = px - s2x, py - s2y
            c = other[0] * ry - other[1] * rx
            if v is vp and c >= 0.0 or v is vm and c <= 0.0:
                pts.append((px, py))
    best = 0.0
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            dx = pts[i][0] - pts[j][0]
            dy = pts[i][1] - pts[j][1]
            d = math.hypot(dx, dy)
            if d > best:
                best = d
    return best


def float_point_loss(s2x: float, s2y: float, scen: Scenario) -> float:
    """Float loss; returns math.inf for the unbounded branch."""
    dx = scen.gx - s2x
    dy = scen.gy - s2y
    if dx * dx + dy * dy <= 25.0:
        return 0.0
    beta = math.atan2(dy, dx) + math.radians(scen.e_deg)
    return _float_diameter(s2x, s2y, beta, math.radians(1.0))


# ----------------------------------------------------------------------
# rigorous enclosures
# ----------------------------------------------------------------------
def point_loss_enclosure(s2: IvlPoint, scen: Scenario) -> Q1DiamEnclosure:
    """Rigorous loss enclosure at an exact point (s2 may be tiny box)."""
    g = scen.g_point()
    d_lo, d_hi = box_point_distance(s2, g)
    if Ivl.le(d_hi, Ivl.from_int(5)) is Tri.TRUE:
        enc = Q1DiamEnclosure(bounded=Tri.TRUE, lower=Ivl.from_int(0),
                              upper=Ivl.from_int(0))
        return enc
    beta = arg_enclosure(IvlPoint(g.x - s2.x, g.y - s2.y)) + scen.e_interval()
    return q1_diameter_enclosure(s2, beta)


def box_loss_lower(s2box: IvlPoint, scen: Scenario) -> tuple[Ivl, str]:
    """Rigorous lower bound of loss(S2; scen) over the box (spec s.15).

    Returns (lower, branch) with branch in {"near", "bearing", "mixed"}.
    """
    g = scen.g_point()
    d_lo, d_hi = box_point_distance(s2box, g)
    five = Ivl.from_int(5)
    if Ivl.le(d_hi, five) is Tri.TRUE:
        return Ivl.from_int(0), "near"
    if Ivl.gt(d_lo, five) is not Tri.TRUE:
        # mixed branch: safe lower bound 0 (spec s.15); caller may split
        return Ivl.from_int(0), "mixed"
    rel = IvlPoint(g.x - s2box.x, g.y - s2box.y)
    try:
        beta = arg_enclosure(rel) + scen.e_interval()
    except BranchCutError:
        # box straddles the atan2 branch cut (spec s.26): safe lower 0,
        # leave it to the master to subdivide
        return Ivl.from_int(0), "mixed"
    enc = q1_diameter_enclosure(s2box, beta)
    if enc.bounded is not Tri.TRUE:
        # boundedness undecided on this box: if every reachable beta is
        # definitely within 2 eps of theta1 the loss is +inf everywhere
        # on the box; otherwise the box must be split (safe lower 0).
        abs_beta = abs(beta)
        if Ivl.le(abs_beta, EPS * 2) is Tri.TRUE:
            return None, "unbounded"
        return Ivl.from_int(0), "mixed"
    if enc.lower is None:
        return Ivl.from_int(0), "bearing"
    return enc.lower, "bearing"
