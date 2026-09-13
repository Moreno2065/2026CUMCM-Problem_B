"""Interval 2-D geometry kernels for the frozen representative Q2 case.

Frozen case data (representative illustrative case, see
``src/q2/code/artifacts/q2_final_evidence_config.json``):

* S1 = (0, 0), theta1 = 0 deg, epsilon = 1 deg (rigorous: pi/180 via arb).
* A1 = { G : 5 < |G| <= 1500, |arg G| <= eps } (Omega = B(0,1800) inactive
  because 1500 < 1800; verified rigorously at import of polar_a1).

All functions operate on ``Ivl`` values and therefore carry rigorous outward
error enclosure.  Geometric decisions return ``Tri`` tri-states; callers must
subdivide or raise precision on ``UNKNOWN`` (spec section 13).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.q2.formal.rigorous_arithmetic import Ivl, Tri, epsilon_radians


# ----------------------------------------------------------------------
# frozen constants (representative case)
# ----------------------------------------------------------------------
EPS: Ivl = epsilon_radians()          # bearing half-angle [rad], pi/180
RHO_LO: Ivl = Ivl.from_int(5)         # first-station exclusion radius (strict)
RHO_HI: Ivl = Ivl.from_int(1500)      # first-station outer radius
OMEGA_R: Ivl = Ivl.from_int(1800)     # region Omega radius about S1
RECEPTION_R: Ivl = Ivl.from_int(1000)  # minimum reception radius
NEAR_R: Ivl = Ivl.from_int(5)         # second-station near radius
S1X: Ivl = Ivl.from_int(0)
S1Y: Ivl = Ivl.from_int(0)
THETA1: Ivl = Ivl.from_int(0)


@dataclass(frozen=True)
class IvlPoint:
    x: Ivl
    y: Ivl

    @staticmethod
    def from_floats(x: float, y: float) -> "IvlPoint":
        return IvlPoint(Ivl.from_float(x), Ivl.from_float(y))

    @staticmethod
    def point(x, y) -> "IvlPoint":
        return IvlPoint(Ivl.point(x), Ivl.point(y))


def sub(p: IvlPoint, q: IvlPoint) -> IvlPoint:
    return IvlPoint(p.x - q.x, p.y - q.y)


def cross(ax: Ivl, ay: Ivl, bx: Ivl, by: Ivl) -> Ivl:
    """2-D cross product a x b."""
    return ax * by - ay * bx


def cross_points(u: IvlPoint, v: IvlPoint) -> Ivl:
    return cross(u.x, u.y, v.x, v.y)


def dir_vec(angle: Ivl) -> IvlPoint:
    """Unit direction vector enclosure for an angle interval."""
    return IvlPoint(angle.cos(), angle.sin())


def norm2(p: IvlPoint) -> Ivl:
    return p.x.square() + p.y.square()


def norm_enclosure(p: IvlPoint) -> Ivl:
    """Interval enclosure of ||p|| for an interval point p."""
    return norm2(p).sqrt()


def box_point_distance(p: IvlPoint, q: IvlPoint) -> tuple[Ivl, Ivl]:
    """Exact (min, max) euclidean distance between two axis boxes.

    Both returned values are rigorous interval enclosures of the exact
    extrema (the intervals have small width from outward rounding only).
    """
    zero = Ivl.from_int(0)
    # per-axis gap for the minimum
    gap_x = Ivl.max(Ivl.max(p.x - q.x.upper_arb(), q.x - p.x.upper_arb()), zero)
    gap_y = Ivl.max(Ivl.max(p.y - q.y.upper_arb(), q.y - p.y.upper_arb()), zero)
    lo = (gap_x.square() + gap_y.square()).sqrt()
    # per-axis spread for the maximum
    span_x = Ivl.max(p.x - q.x.lower_arb(), q.x - p.x.lower_arb())
    span_y = Ivl.max(p.y - q.y.lower_arb(), q.y - p.y.lower_arb())
    hi = (span_x.square() + span_y.square()).sqrt()
    return lo, hi


class BranchCutError(Exception):
    """atan2 argument box crosses the negative real axis or hits the origin."""


def arg_enclosure(p: IvlPoint) -> Ivl:
    """Rigorous enclosure of arg(p) = atan2(y, x) for an interval point.

    The box must not contain the origin.  If the box straddles the negative
    real axis (x definitely negative, y containing 0) the caller must split
    the box (spec section 26); we raise ``BranchCutError``.
    """
    x_zero = p.x.contains(0)
    y_zero = p.y.contains(0)
    if x_zero and y_zero:
        raise BranchCutError("atan2 box contains the origin")
    if Ivl.sign(p.x) is Tri.FALSE and y_zero:
        raise BranchCutError("atan2 box straddles the branch cut")
    return p.y.atan2(p.x)


def line_line_intersection(
    p1: IvlPoint, u: IvlPoint, p2: IvlPoint, v: IvlPoint
) -> tuple[IvlPoint | None, Ivl | None, Tri]:
    """Intersection of line (p1, u) with line (p2, v).

    Returns (point, t, denom_sign) where point = p1 + t*u.  If the
    denominator cross(u, v) is definitely zero -> (None, None, FALSE/TRUE by
    sign); if the denominator may be zero -> (None, None, UNKNOWN).
    """
    denom = cross_points(u, v)
    sgn = Ivl.sign(denom)
    if sgn is Tri.UNKNOWN:
        return None, None, Tri.UNKNOWN
    w = sub(p2, p1)
    t = cross_points(w, v) / denom
    point = IvlPoint(p1.x + t * u.x, p1.y + t * u.y)
    return point, t, sgn


def polar_point(rho: Ivl, phi: Ivl) -> IvlPoint:
    """G = (rho cos phi, rho sin phi) with rigorous trig enclosure."""
    return IvlPoint(rho * phi.cos(), rho * phi.sin())
