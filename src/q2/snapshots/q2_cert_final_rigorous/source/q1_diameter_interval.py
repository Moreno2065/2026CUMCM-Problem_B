"""Branch-complete interval enclosure of the pure Q1 localization diameter.

For the frozen representative case (S1 = origin, theta1 = 0, eps = pi/180):

    P_Q1(S2, beta) = K(S1, theta1)  intersect  K(S2, beta)
    D_Q1(S2, beta) = diam P_Q1

K(S, theta) = { X : |arg(X - S) - theta| <= eps } is a closed wedge.
Because both wedges have half-angle eps, P_Q1 is bounded iff the direction
intervals [theta1 - eps, theta1 + eps] and [beta - eps, beta + eps] are
disjoint, i.e. |beta - theta1| > 2*eps (mod 2*pi).  When bounded, every
vertex of the convex polygon P_Q1 is one of:

* apex O  = (0,0)         (feasible iff O in wedge 2)
* apex S2                  (feasible iff S2 in wedge 1)
* V[i,j] = line(O, u_i) ∩ line(S2, v_j), i,j in {+,-}

with u_± = dir(theta1 ± eps), v_± = dir(beta ± eps).  Feasibility of V[i,j]
reduces to t >= 0 (ray of wedge 1) plus the opposite wedge-2 half-plane.

The kernel returns a rigorous *lower* enclosure (max over definitely
feasible vertex pairs of the minimum pair distance) and a rigorous *upper*
enclosure (max over not-definitely-infeasible pairs of the maximum pair
distance).  Both are valid simultaneously over the whole input box
(S2box, beta) - spec sections 15, 16, 27.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.q2.formal.rigorous_arithmetic import Ivl, Tri
from src.q2.formal.ivl_geometry import (
    EPS,
    IvlPoint,
    box_point_distance,
    cross,
    dir_vec,
    sub,
)


@dataclass(frozen=True)
class VertexCand:
    name: str
    point: IvlPoint | None  # None if construction impossible (parallel etc.)
    feasible: Tri


@dataclass
class Q1DiamEnclosure:
    bounded: Tri            # TRUE: bounded for all inputs; UNKNOWN: maybe +inf
    lower: Ivl | None       # rigorous lower bound of diameter (None if none found)
    upper: Ivl | None       # rigorous upper bound (only when bounded is TRUE)
    vertices: tuple[VertexCand, ...] = field(default_factory=tuple)
    lower_pair: str = ""
    upper_pair: str = ""


def _wedge2_feasibility(p: IvlPoint, s2: IvlPoint, v_plus: IvlPoint, v_minus: IvlPoint) -> Tri:
    """Tri-state of p in wedge(S2, beta): both half-plane checks."""
    rel = sub(p, s2)
    c_plus = cross(v_plus.x, v_plus.y, rel.x, rel.y)   # need <= 0
    c_minus = cross(v_minus.x, v_minus.y, rel.x, rel.y)  # need >= 0
    ok_plus = Ivl.le(c_plus, 0)
    ok_minus = Ivl.ge(c_minus, 0)
    if ok_plus is Tri.FALSE or ok_minus is Tri.FALSE:
        return Tri.FALSE
    if ok_plus is Tri.TRUE and ok_minus is Tri.TRUE:
        return Tri.TRUE
    return Tri.UNKNOWN


def q1_diameter_enclosure(s2: IvlPoint, beta: Ivl) -> Q1DiamEnclosure:
    """Enclose D_Q1(S2, beta) for all S2 in s2 box and all beta in beta."""
    zero = Ivl.from_int(0)
    apex1 = IvlPoint.point(0, 0)

    # --- boundedness: direction intervals disjoint? ---
    two_eps = EPS * 2
    abs_beta = abs(beta)  # theta1 = 0 case; |beta| > 2 eps <=> bounded
    bounded = Ivl.gt(abs_beta, two_eps)

    u_plus = dir_vec(EPS)
    u_minus = dir_vec(-EPS)
    v_plus = dir_vec(beta + EPS)
    v_minus = dir_vec(beta - EPS)

    vertices: list[VertexCand] = []

    # apex O in wedge 2
    vertices.append(VertexCand("apex1", apex1, _wedge2_feasibility(apex1, s2, v_plus, v_minus)))

    # apex S2 in wedge 1: cross(u_plus, S2) <= 0 and cross(u_minus, S2) >= 0
    c_p = cross(u_plus.x, u_plus.y, s2.x, s2.y)
    c_m = cross(u_minus.x, u_minus.y, s2.x, s2.y)
    t_p = Ivl.le(c_p, 0)
    t_m = Ivl.ge(c_m, 0)
    if t_p is Tri.FALSE or t_m is Tri.FALSE:
        apex2_tri = Tri.FALSE
    elif t_p is Tri.TRUE and t_m is Tri.TRUE:
        apex2_tri = Tri.TRUE
    else:
        apex2_tri = Tri.UNKNOWN
    vertices.append(VertexCand("apex2", s2, apex2_tri))

    # four line intersections
    for i_name, u in (("+", u_plus), ("-", u_minus)):
        for j_name, v in (("+", v_plus), ("-", v_minus)):
            denom = cross(u.x, u.y, v.x, v.y)
            sgn = Ivl.sign(denom)
            name = f"V{i_name}{j_name}"
            if sgn is Tri.UNKNOWN:
                vertices.append(VertexCand(name, None, Tri.UNKNOWN))
                continue
            # t = cross(S2, v) / cross(u, v);  V = t * u
            t = cross(s2.x, s2.y, v.x, v.y) / denom
            point = IvlPoint(t * u.x, t * u.y)
            t_nonneg = Ivl.ge(t, zero)
            if t_nonneg is Tri.FALSE:
                vertices.append(VertexCand(name, point, Tri.FALSE))
                continue
            # opposite wedge-2 half-plane (on-line one is automatic)
            rel = sub(point, s2)
            if j_name == "+":
                c_other = cross(v_minus.x, v_minus.y, rel.x, rel.y)  # need >= 0
                other_ok = Ivl.ge(c_other, zero)
            else:
                c_other = cross(v_plus.x, v_plus.y, rel.x, rel.y)   # need <= 0
                other_ok = Ivl.le(c_other, zero)
            if t_nonneg is Tri.TRUE and other_ok is Tri.TRUE:
                tri = Tri.TRUE
            elif t_nonneg is Tri.FALSE or other_ok is Tri.FALSE:
                tri = Tri.FALSE
            else:
                tri = Tri.UNKNOWN
            vertices.append(VertexCand(name, point, tri))

    # --- pair distances ---
    lower = None
    lower_pair = ""
    upper = None
    upper_pair = ""
    n = len(vertices)
    for a in range(n):
        va = vertices[a]
        if va.feasible is Tri.FALSE or va.point is None:
            continue
        for b in range(a + 1, n):
            vb = vertices[b]
            if vb.feasible is Tri.FALSE or vb.point is None:
                continue
            d_lo, d_hi = box_point_distance(va.point, vb.point)
            name = f"{va.name}|{vb.name}"
            if va.feasible is Tri.TRUE and vb.feasible is Tri.TRUE:
                if lower is None or bool(d_lo._b > lower._b):
                    lower = d_lo
                    lower_pair = name
            # upper uses all not-infeasible pairs
            if upper is None or bool(d_hi._b > upper._b):
                upper = d_hi
                upper_pair = name

    if bounded is not Tri.TRUE:
        upper = None
        upper_pair = ""
    return Q1DiamEnclosure(
        bounded=bounded,
        lower=lower,
        upper=upper,
        vertices=tuple(vertices),
        lower_pair=lower_pair,
        upper_pair=upper_pair,
    )
