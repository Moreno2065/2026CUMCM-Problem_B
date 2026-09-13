"""Independent verification chain B for Q1.

This module intentionally does NOT reuse the main-chain feasibility/boundedness
logic from q1_geometry.solve_q1:
  * LP decides EMPTY / UNBOUNDED / bounded;
  * bounded LP extrema create a certified finite clipping box;
  * sequential half-plane clipping constructs the polygon;
  * a monotone-chain convex hull and rotating calipers compute the diameter;
  * deterministic 2-point / 3-point support-circle enumeration computes MEC.
"""

from __future__ import annotations

from dataclasses import dataclass
import itertools
import math
from typing import Optional, Sequence

import numpy as np
from scipy.optimize import linprog

from q1_geometry import (
    HalfPlane,
    Measurement,
    Point,
    Q1Result,
    STATUS_EMPTY,
    STATUS_OK,
    STATUS_UNBOUNDED,
    Tolerance,
)


@dataclass
class LPClassification:
    status: str
    box: Optional[tuple[float, float, float, float]]


@dataclass
class MECResult:
    center: Point
    radius: float
    support_indices: tuple[int, ...]


def _canonicalize_deg(angle_deg: float) -> float:
    a = math.fmod(float(angle_deg), 360.0)
    if a < 0.0:
        a += 360.0
    if a >= 360.0:
        a -= 360.0
    return a


def _verifier_halfplanes(
    measurements: Sequence[Measurement], epsilon_deg: float
) -> list[HalfPlane]:
    """Independent bearing->half-plane conversion for chain B.

    Deliberately duplicates the mathematics instead of calling the main-chain
    converter, so a sign/orientation bug in chain A can be detected.
    """
    hps: list[HalfPlane] = []
    for i, m in enumerate(measurements):
        alpha = _canonicalize_deg(m.bearing_deg)
        lo = _canonicalize_deg(alpha - epsilon_deg)
        hi = _canonicalize_deg(alpha + epsilon_deg)
        lr = math.radians(lo)
        hr = math.radians(hi)
        # Lower ray: cross(u_lo, P-S) >= 0.
        a1, b1 = math.sin(lr), -math.cos(lr)
        c1 = a1 * m.x + b1 * m.y
        # Upper ray: cross(P-S, u_hi) >= 0.
        a2, b2 = -math.sin(hr), math.cos(hr)
        c2 = a2 * m.x + b2 * m.y
        hps.append(HalfPlane(a1, b1, c1, i, "lower", lo))
        hps.append(HalfPlane(a2, b2, c2, i, "upper", hi))
    return hps


def _arrays(hps: Sequence[HalfPlane]) -> tuple[np.ndarray, np.ndarray]:
    A = np.array([[h.a, h.b] for h in hps], dtype=float)
    b = np.array([h.c for h in hps], dtype=float)
    return A, b


def lp_classify(hps: Sequence[HalfPlane]) -> LPClassification:
    """Independent EMPTY/UNBOUNDED/bounded classification using HiGHS LP."""
    A, b = _arrays(hps)
    bounds = [(None, None), (None, None)]

    feas = linprog([0.0, 0.0], A_ub=A, b_ub=b, bounds=bounds, method="highs")
    if feas.status == 2:
        return LPClassification(STATUS_EMPTY, None)
    if feas.status != 0:
        raise RuntimeError(f"Unexpected feasibility LP status={feas.status}: {feas.message}")

    objectives = {
        "xmin": np.array([1.0, 0.0]),
        "xmax": np.array([-1.0, 0.0]),
        "ymin": np.array([0.0, 1.0]),
        "ymax": np.array([0.0, -1.0]),
    }
    vals: dict[str, float] = {}
    for name, c in objectives.items():
        res = linprog(c, A_ub=A, b_ub=b, bounds=bounds, method="highs")
        if res.status == 3:
            return LPClassification(STATUS_UNBOUNDED, None)
        if res.status != 0:
            raise RuntimeError(f"Unexpected {name} LP status={res.status}: {res.message}")
        vals[name] = float(res.fun)

    return LPClassification(
        STATUS_OK,
        (vals["xmin"], -vals["xmax"], vals["ymin"], -vals["ymax"]),
    )


def _inside(p: Point, hp: HalfPlane, eps: float) -> bool:
    return hp.a * p.x + hp.b * p.y <= hp.c + eps


def _segment_boundary_intersection(p: Point, q: Point, hp: HalfPlane) -> Point:
    dx, dy = q.x - p.x, q.y - p.y
    den = hp.a * dx + hp.b * dy
    if abs(den) < 1e-30:
        return p
    t = (hp.c - hp.a * p.x - hp.b * p.y) / den
    t = min(1.0, max(0.0, t))
    return Point(p.x + t * dx, p.y + t * dy)


def clip_polygon(poly: Sequence[Point], hp: HalfPlane, eps: float) -> list[Point]:
    if not poly:
        return []
    out: list[Point] = []
    prev = poly[-1]
    prev_in = _inside(prev, hp, eps)
    for cur in poly:
        cur_in = _inside(cur, hp, eps)
        if prev_in and cur_in:
            out.append(cur)
        elif prev_in and not cur_in:
            out.append(_segment_boundary_intersection(prev, cur, hp))
        elif not prev_in and cur_in:
            out.append(_segment_boundary_intersection(prev, cur, hp))
            out.append(cur)
        prev, prev_in = cur, cur_in
    return out


def _cross(o: Point, a: Point, b: Point) -> float:
    return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)


def convex_hull(points: Sequence[Point]) -> list[Point]:
    pts = sorted(set(points))
    if len(pts) <= 1:
        return pts
    scale = max(1.0, *(abs(v) for p in pts for v in (p.x, p.y)))
    eps_cross = 5e-14 * scale * scale

    lower: list[Point] = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= eps_cross:
            lower.pop()
        lower.append(p)
    upper: list[Point] = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= eps_cross:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _dist2(a: Point, b: Point) -> float:
    return (a.x - b.x) ** 2 + (a.y - b.y) ** 2


def rotating_calipers_diameter(hull: Sequence[Point]) -> tuple[float, tuple[Point, Point]]:
    n = len(hull)
    if n == 0:
        raise ValueError("Empty hull")
    if n == 1:
        return 0.0, (hull[0], hull[0])
    if n == 2:
        return math.sqrt(_dist2(hull[0], hull[1])), (hull[0], hull[1])

    j = 1
    best_d2 = -1.0
    best_pair = (hull[0], hull[1])

    def area2(i: int, ni: int, jj: int) -> float:
        return abs(_cross(hull[i], hull[ni], hull[jj]))

    for i in range(n):
        ni = (i + 1) % n
        while area2(i, ni, (j + 1) % n) > area2(i, ni, j) + 1e-12:
            j = (j + 1) % n
        for a, b in ((hull[i], hull[j]), (hull[ni], hull[j])):
            d2 = _dist2(a, b)
            if d2 > best_d2:
                best_d2, best_pair = d2, (a, b)
    return math.sqrt(max(0.0, best_d2)), best_pair


def verifier_polygon(
    hps: Sequence[HalfPlane], box: tuple[float, float, float, float], tol: Tolerance = Tolerance()
) -> list[Point]:
    xmin, xmax, ymin, ymax = box
    scale = max(1.0, abs(xmin), abs(xmax), abs(ymin), abs(ymax))
    margin = max(1e-8, 2e-12 * scale)
    poly = [
        Point(xmin - margin, ymin - margin),
        Point(xmax + margin, ymin - margin),
        Point(xmax + margin, ymax + margin),
        Point(xmin - margin, ymax + margin),
    ]
    eps = tol.abs_m + tol.rel * scale
    for hp in hps:
        poly = clip_polygon(poly, hp, eps)
        if not poly:
            break
    return convex_hull(poly)


def _circle_covers(center: Point, radius: float, points: Sequence[Point], tol: float) -> bool:
    return all(math.hypot(p.x - center.x, p.y - center.y) <= radius + tol for p in points)


def _circumcircle(a: Point, b: Point, c: Point) -> Optional[tuple[Point, float]]:
    d = 2.0 * (a.x * (b.y - c.y) + b.x * (c.y - a.y) + c.x * (a.y - b.y))
    scale = max(1.0, abs(a.x), abs(a.y), abs(b.x), abs(b.y), abs(c.x), abs(c.y))
    if abs(d) <= 1e-14 * scale * scale:
        return None
    a2 = a.x * a.x + a.y * a.y
    b2 = b.x * b.x + b.y * b.y
    c2 = c.x * c.x + c.y * c.y
    ux = (a2 * (b.y - c.y) + b2 * (c.y - a.y) + c2 * (a.y - b.y)) / d
    uy = (a2 * (c.x - b.x) + b2 * (a.x - c.x) + c2 * (b.x - a.x)) / d
    center = Point(ux, uy)
    return center, math.hypot(center.x - a.x, center.y - a.y)


def deterministic_mec(points: Sequence[Point]) -> MECResult:
    """Exact combinatorial MEC oracle over finite points (up to floating arithmetic)."""
    pts = list(points)
    if not pts:
        raise ValueError("MEC needs at least one point")
    scale = max(1.0, *(abs(v) for p in pts for v in (p.x, p.y)))
    cover_tol = 2e-11 * scale

    best: Optional[MECResult] = None

    # 1-point circles matter for degenerate point fixtures.
    for i, p in enumerate(pts):
        if _circle_covers(p, 0.0, pts, cover_tol):
            cand = MECResult(p, 0.0, (i,))
            if best is None or cand.radius < best.radius:
                best = cand

    for i, j in itertools.combinations(range(len(pts)), 2):
        a, b = pts[i], pts[j]
        center = Point((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)
        radius = 0.5 * math.hypot(a.x - b.x, a.y - b.y)
        if _circle_covers(center, radius, pts, cover_tol):
            cand = MECResult(center, radius, (i, j))
            if best is None or cand.radius < best.radius:
                best = cand

    for i, j, k in itertools.combinations(range(len(pts)), 3):
        cc = _circumcircle(pts[i], pts[j], pts[k])
        if cc is None:
            continue
        center, radius = cc
        if _circle_covers(center, radius, pts, cover_tol):
            cand = MECResult(center, radius, (i, j, k))
            if best is None or cand.radius < best.radius:
                best = cand

    if best is None:
        raise RuntimeError("No enclosing circle candidate found; numerical failure")
    return best


def hausdorff_vertex_distance(a: Sequence[Point], b: Sequence[Point]) -> float:
    if not a or not b:
        return math.inf if bool(a) != bool(b) else 0.0

    def one_way(x: Sequence[Point], y: Sequence[Point]) -> float:
        return max(min(math.hypot(p.x - q.x, p.y - q.y) for q in y) for p in x)

    return max(one_way(a, b), one_way(b, a))


def verify_measurements(
    measurements: Sequence[Measurement],
    main: Optional[Q1Result] = None,
    epsilon_deg: float = 1.0,
    tol: Tolerance = Tolerance(),
) -> dict:
    hps = _verifier_halfplanes(measurements, epsilon_deg)
    lp = lp_classify(hps)
    report: dict = {"lp_status": lp.status, "lp_box": lp.box}

    if main is not None:
        report["status_agrees"] = main.status == lp.status

    if lp.status != STATUS_OK:
        return report

    assert lp.box is not None
    hull = verifier_polygon(hps, lp.box, tol)
    d, pair = rotating_calipers_diameter(hull)
    report.update(
        {
            "verifier_vertices": [{"x": p.x, "y": p.y} for p in hull],
            "verifier_diameter": d,
            "verifier_diameter_pair": [
                {"x": pair[0].x, "y": pair[0].y},
                {"x": pair[1].x, "y": pair[1].y},
            ],
        }
    )
    if hull:
        mec = deterministic_mec(hull)
        report["mec_radius"] = mec.radius
        report["mec_center"] = {"x": mec.center.x, "y": mec.center.y}
        report["mec_support_size"] = len(mec.support_indices)
        report["mec_support_indices"] = list(mec.support_indices)
        report["two_r_mec_over_d"] = 1.0 if d == 0 else 2.0 * mec.radius / d

    if main is not None and main.status == STATUS_OK and main.diameter is not None:
        scale = max(1.0, d, main.diameter)
        report["diameter_abs_diff"] = abs(d - main.diameter)
        report["diameter_rel_diff"] = abs(d - main.diameter) / scale
        report["vertex_hausdorff"] = hausdorff_vertex_distance(main.vertices, hull)
    return report
