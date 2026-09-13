"""Q1 geometry solver for CUMCM 2026 Problem B.

Frozen mathematical contract: Q1_MATH_v1.2

Main chain A (deterministic, no external dependencies):
    bearing wedges -> all boundary-line intersections -> feasibility filtering
    -> EMPTY check -> common recession direction check -> UNBOUNDED check
    -> affine-dimension classification -> O(k^2) diameter
    -> diameter-disk coverage test.

Important modeling boundary:
    This module uses ONLY the +/- epsilon bearing wedges to define the Q1
    localization region. It does not intersect with the 1800 m target disk,
    reception-radius disks, or the <=5 m 'near' rule.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Optional, Sequence

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy is optional for reference backend
    np = None

try:
    from numba import njit
    NUMBA_AVAILABLE = np is not None
except Exception:  # pragma: no cover - graceful fallback on minimal environments
    njit = None
    NUMBA_AVAILABLE = False


STATUS_EMPTY = "EMPTY"
STATUS_UNBOUNDED = "UNBOUNDED"
STATUS_OK = "OK"


@dataclass(frozen=True, order=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Measurement:
    x: float
    y: float
    bearing_deg: float
    label: str = ""

    @property
    def station(self) -> Point:
        return Point(self.x, self.y)


@dataclass(frozen=True)
class HalfPlane:
    """Closed half-plane a*x + b*y <= c.

    For Q1 wedge constraints, (a,b) is a unit normal, so the residual
    a*x+b*y-c has units of metres and is a signed perpendicular distance.
    """

    a: float
    b: float
    c: float
    source_index: int
    side: str
    boundary_angle_deg: float


@dataclass(frozen=True)
class Tolerance:
    # Geometry is measured in metres. Relative term protects large-coordinate cases.
    abs_m: float = 1e-9
    rel: float = 2e-14
    # Determinant of two unit normals. 1e-14 is far below the T8 0.01-degree gap.
    parallel_det: float = 1e-14
    angle_deg: float = 1e-12


@dataclass
class Q1Result:
    status: str
    dimension: Optional[int]
    vertices: list[Point]
    area: Optional[float]
    diameter: Optional[float]
    diameter_pair: Optional[tuple[Point, Point]]
    covered_by_diameter_disk: Optional[bool]
    diameter_disk_center: Optional[Point]
    diameter_disk_radius: Optional[float]
    max_radial_excess: Optional[float]
    rho_viol: Optional[float]
    escape_direction_deg: Optional[float]
    feasible_vertex_witnesses: list[Point]

    def as_dict(self) -> dict:
        def p2d(p: Optional[Point]):
            return None if p is None else {"x": p.x, "y": p.y}

        return {
            "status": self.status,
            "dimension": self.dimension,
            "vertices": [p2d(p) for p in self.vertices],
            "area": self.area,
            "diameter": (
                None
                if self.diameter is None or not math.isfinite(self.diameter)
                else self.diameter
            ),
            "diameter_is_infinite": bool(
                self.diameter is not None and math.isinf(self.diameter)
            ),
            "diameter_pair": None
            if self.diameter_pair is None
            else [p2d(self.diameter_pair[0]), p2d(self.diameter_pair[1])],
            "covered_by_diameter_disk": self.covered_by_diameter_disk,
            "diameter_disk_center": p2d(self.diameter_disk_center),
            "diameter_disk_radius": self.diameter_disk_radius,
            "max_radial_excess": self.max_radial_excess,
            "rho_viol": self.rho_viol,
            "escape_direction_deg": self.escape_direction_deg,
            "feasible_vertex_witnesses": [p2d(p) for p in self.feasible_vertex_witnesses],
        }


def canonicalize_deg(angle_deg: float) -> float:
    """Map an angle to [0, 360)."""
    a = math.fmod(float(angle_deg), 360.0)
    if a < 0.0:
        a += 360.0
    # Avoid returning 360 because of rounding around tiny negatives.
    if a >= 360.0:
        a -= 360.0
    return a


def signed_angle_diff_deg(angle_deg: float, reference_deg: float) -> float:
    """Signed circular difference angle-reference in [-180, 180)."""
    return ((canonicalize_deg(angle_deg) - canonicalize_deg(reference_deg) + 180.0) % 360.0) - 180.0


def _unit_from_deg(angle_deg: float) -> tuple[float, float]:
    r = math.radians(canonicalize_deg(angle_deg))
    return math.cos(r), math.sin(r)


def _length_tol(scale: float, tol: Tolerance) -> float:
    return tol.abs_m + tol.rel * max(1.0, abs(scale))


def build_halfplanes(
    measurements: Sequence[Measurement], epsilon_deg: float = 1.0
) -> list[HalfPlane]:
    if not measurements:
        raise ValueError("At least one bearing measurement is required.")
    if not (0.0 < epsilon_deg < 90.0):
        raise ValueError("epsilon_deg must satisfy 0 < epsilon_deg < 90 degrees.")

    hps: list[HalfPlane] = []
    for i, m in enumerate(measurements):
        alpha = canonicalize_deg(m.bearing_deg)
        beta_minus = canonicalize_deg(alpha - epsilon_deg)
        beta_plus = canonicalize_deg(alpha + epsilon_deg)
        ux_m, uy_m = _unit_from_deg(beta_minus)
        ux_p, uy_p = _unit_from_deg(beta_plus)

        # lower boundary: cross(u-, P-S) >= 0
        # <=> uy*x - ux*y <= uy*x_i - ux*y_i
        a1, b1 = uy_m, -ux_m
        c1 = a1 * m.x + b1 * m.y
        hps.append(HalfPlane(a1, b1, c1, i, "lower", beta_minus))

        # upper boundary: cross(P-S, u+) >= 0
        # <=> -uy*x + ux*y <= -uy*x_i + ux*y_i
        a2, b2 = -uy_p, ux_p
        c2 = a2 * m.x + b2 * m.y
        hps.append(HalfPlane(a2, b2, c2, i, "upper", beta_plus))
    return hps


def _line_intersection(h1: HalfPlane, h2: HalfPlane, tol: Tolerance) -> Optional[Point]:
    det = h1.a * h2.b - h2.a * h1.b
    if abs(det) <= tol.parallel_det:
        return None
    # Solve [a1 b1; a2 b2] [x y]^T = [c1 c2]^T
    x = (h1.c * h2.b - h2.c * h1.b) / det
    y = (h1.a * h2.c - h2.a * h1.c) / det
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return Point(x, y)


def _point_scale(p: Point, hps: Sequence[HalfPlane]) -> float:
    cscale = max((abs(h.c) for h in hps), default=1.0)
    return max(1.0, abs(p.x), abs(p.y), cscale)


def point_satisfies_all(p: Point, hps: Sequence[HalfPlane], tol: Tolerance = Tolerance()) -> bool:
    eps = _length_tol(_point_scale(p, hps), tol)
    return all(h.a * p.x + h.b * p.y <= h.c + eps for h in hps)


def _dedupe_points(points: Iterable[Point], tol: Tolerance) -> list[Point]:
    pts = list(points)
    if not pts:
        return []
    scale = max(1.0, *(abs(v) for p in pts for v in (p.x, p.y)))
    eps = _length_tol(scale, tol)
    eps2 = eps * eps
    out: list[Point] = []
    for p in sorted(pts):
        if all((p.x - q.x) ** 2 + (p.y - q.y) ** 2 > eps2 for q in out):
            out.append(p)
    return out


def enumerate_feasible_intersections(
    hps: Sequence[HalfPlane], tol: Tolerance = Tolerance()
) -> list[Point]:
    """Enumerate all feasible intersections of nonparallel boundary lines.

    Under the frozen Q1 wedge structure, R != empty iff this list is nonempty
    (Proposition 2A in the frozen mathematical contract).
    """
    feasible: list[Point] = []
    for i in range(len(hps)):
        for j in range(i + 1, len(hps)):
            p = _line_intersection(hps[i], hps[j], tol)
            if p is not None and point_satisfies_all(p, hps, tol):
                feasible.append(p)
    return _dedupe_points(feasible, tol)




def _halfplanes_to_arrays(hps: Sequence[HalfPlane]):
    """Convert half-planes to compact float arrays for the Numba hot loop."""
    if np is None:
        raise RuntimeError("NumPy is required by the Numba backend.")
    abc = np.empty((len(hps), 3), dtype=np.float64)
    for i, h in enumerate(hps):
        abc[i, 0] = h.a
        abc[i, 1] = h.b
        abc[i, 2] = h.c
    return abc


if NUMBA_AVAILABLE:
    # The same source file is imported both as top-level ``q1_geometry`` by
    # the Q1 tests and as ``src.q1.code.q1_geometry`` by the Q2 adapter.  A
    # disk cache compiled under one module name cannot be unpickled under the
    # other in an isolated handoff.  The JIT remains enabled; only the
    # path-sensitive cache is disabled so clean-room execution is deterministic.
    @njit(cache=False, fastmath=False)
    def _enumerate_feasible_intersections_numba_kernel(
        abc, abs_m, rel, parallel_det
    ):
        """JIT hot loop: line-pair intersections + all-half-plane filtering.

        The output intentionally contains duplicates. Deduplication stays in the
        audited Python layer so the Numba backend changes performance, not the
        frozen geometric semantics.
        """
        m = abc.shape[0]
        max_pairs = m * (m - 1) // 2
        out = np.empty((max_pairs, 2), dtype=np.float64)
        count = 0
        cscale = 1.0
        for k in range(m):
            ck = abs(abc[k, 2])
            if ck > cscale:
                cscale = ck

        for i in range(m):
            a1 = abc[i, 0]
            b1 = abc[i, 1]
            c1 = abc[i, 2]
            for j in range(i + 1, m):
                a2 = abc[j, 0]
                b2 = abc[j, 1]
                c2 = abc[j, 2]
                det = a1 * b2 - a2 * b1
                if abs(det) <= parallel_det:
                    continue

                x = (c1 * b2 - c2 * b1) / det
                y = (a1 * c2 - a2 * c1) / det
                if not (math.isfinite(x) and math.isfinite(y)):
                    continue

                scale = cscale
                ax = abs(x)
                ay = abs(y)
                if ax > scale:
                    scale = ax
                if ay > scale:
                    scale = ay
                if scale < 1.0:
                    scale = 1.0
                eps = abs_m + rel * scale

                feasible = True
                for k in range(m):
                    if abc[k, 0] * x + abc[k, 1] * y > abc[k, 2] + eps:
                        feasible = False
                        break
                if feasible:
                    out[count, 0] = x
                    out[count, 1] = y
                    count += 1

        return out[:count]
else:
    _enumerate_feasible_intersections_numba_kernel = None


def enumerate_feasible_intersections_numba(
    hps: Sequence[HalfPlane], tol: Tolerance = Tolerance()
) -> list[Point]:
    """Numba-accelerated version of the frozen feasibility/vertex enumeration.

    Falls back only when explicitly requested by the public dispatcher; calling
    this function directly requires Numba to be available.
    """
    if not NUMBA_AVAILABLE or _enumerate_feasible_intersections_numba_kernel is None:
        raise RuntimeError("Numba backend is not available in this environment.")
    abc = _halfplanes_to_arrays(hps)
    arr = _enumerate_feasible_intersections_numba_kernel(
        abc, tol.abs_m, tol.rel, tol.parallel_det
    )
    return _dedupe_points((Point(float(x), float(y)) for x, y in arr), tol)


def common_escape_direction_deg(
    measurements: Sequence[Measurement], epsilon_deg: float = 1.0, tol: Tolerance = Tolerance()
) -> Optional[float]:
    """Return a common recession direction if all bearing arcs overlap.

    This is only a boundedness oracle AFTER non-emptiness has been established.
    Because every interval has width 2*epsilon < 180 degrees, unwrapping all
    centers relative to the first bearing is unambiguous whenever a common
    direction exists.
    """
    if not measurements:
        raise ValueError("At least one measurement is required.")
    a0 = canonicalize_deg(measurements[0].bearing_deg)
    lows: list[float] = []
    highs: list[float] = []
    for m in measurements:
        d = signed_angle_diff_deg(m.bearing_deg, a0)
        lows.append(d - epsilon_deg)
        highs.append(d + epsilon_deg)
    lo = max(lows)
    hi = min(highs)
    if lo <= hi + tol.angle_deg:
        return canonicalize_deg(a0 + 0.5 * (lo + hi))
    return None


def _dist2(p: Point, q: Point) -> float:
    return (p.x - q.x) ** 2 + (p.y - q.y) ** 2


def _polygon_signed_area(vertices: Sequence[Point]) -> float:
    if len(vertices) < 3:
        return 0.0
    s = 0.0
    for p, q in zip(vertices, vertices[1:] + vertices[:1]):
        s += p.x * q.y - q.x * p.y
    return 0.5 * s


def _farthest_pair(points: Sequence[Point]) -> tuple[float, tuple[Point, Point]]:
    if not points:
        raise ValueError("Need at least one point.")
    if len(points) == 1:
        return 0.0, (points[0], points[0])
    best_d2 = -1.0
    best_pair: Optional[tuple[Point, Point]] = None
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            d2 = _dist2(points[i], points[j])
            pair = (points[i], points[j])
            if d2 > best_d2:
                best_d2 = d2
                best_pair = pair
            elif d2 == best_d2 and best_pair is not None and pair < best_pair:
                best_pair = pair
    assert best_pair is not None
    return math.sqrt(max(0.0, best_d2)), best_pair


def analyze_bounded_vertices(
    vertices: Sequence[Point], tol: Tolerance = Tolerance()
) -> tuple[int, list[Point], float, float, tuple[Point, Point], bool, Point, float, float, float]:
    """Classify a nonempty bounded feasible vertex set and compute Q1 functionals.

    Returns:
        dimension, ordered_vertices, area, diameter, diameter_pair,
        covered, disk_center, disk_radius, max_radial_excess, rho_viol
    """
    pts = _dedupe_points(vertices, tol)
    if not pts:
        raise ValueError("Bounded nonempty region must have at least one vertex.")

    if len(pts) == 1:
        p = pts[0]
        return 0, [p], 0.0, 0.0, (p, p), True, p, 0.0, 0.0, 1.0

    diameter, diameter_pair = _farthest_pair(pts)
    scale = max(1.0, diameter, *(abs(v) for p in pts for v in (p.x, p.y)))
    eps_len = _length_tol(scale, tol)

    if diameter <= eps_len:
        p = pts[0]
        return 0, [p], 0.0, 0.0, (p, p), True, p, 0.0, 0.0, 1.0

    # Affine-dimension test: max distance from the farthest-pair supporting line.
    A, B = diameter_pair
    vx, vy = B.x - A.x, B.y - A.y
    max_perp = 0.0
    for p in pts:
        perp = abs(vx * (p.y - A.y) - vy * (p.x - A.x)) / diameter
        max_perp = max(max_perp, perp)

    if max_perp <= eps_len:
        ordered = [A, B] if A <= B else [B, A]
        center = Point((A.x + B.x) / 2.0, (A.y + B.y) / 2.0)
        return 1, ordered, 0.0, diameter, (A, B), True, center, diameter / 2.0, 0.0, 1.0

    # Full-dimensional case. For a convex feasible vertex set, polar order around
    # the arithmetic mean gives the polygon boundary order.
    cx = sum(p.x for p in pts) / len(pts)
    cy = sum(p.y for p in pts) / len(pts)
    ordered = sorted(pts, key=lambda p: math.atan2(p.y - cy, p.x - cx))
    if _polygon_signed_area(ordered) < 0.0:
        ordered.reverse()
    area = abs(_polygon_signed_area(ordered))

    # Recompute diameter on the final deterministic order to make tie handling reproducible.
    diameter, diameter_pair = _farthest_pair(ordered)
    A, B = diameter_pair
    center = Point((A.x + B.x) / 2.0, (A.y + B.y) / 2.0)
    radius = diameter / 2.0

    # Frozen theorem 2': (V-A).(V-B) <= 0 for every vertex.
    # Use a scale-aware squared-distance tolerance with the correct physical units.
    dot_tol = max(1.0, diameter) * _length_tol(scale, tol)
    covered = True
    max_excess = -math.inf
    max_r = 0.0
    for v in ordered:
        dot = (v.x - A.x) * (v.x - B.x) + (v.y - A.y) * (v.y - B.y)
        if dot > dot_tol:
            covered = False
        rv = math.hypot(v.x - center.x, v.y - center.y)
        max_r = max(max_r, rv)
        max_excess = max(max_excess, rv - radius)

    max_excess = max(0.0, max_excess)
    rho_viol = 1.0 if radius == 0.0 else max_r / radius
    return 2, ordered, area, diameter, diameter_pair, covered, center, radius, max_excess, rho_viol


def solve_q1(
    measurements: Sequence[Measurement],
    epsilon_deg: float = 1.0,
    tol: Tolerance = Tolerance(),
    backend: str = "numba",
) -> Q1Result:
    """Solve Q1 under the frozen mathematical contract.

    Parameters
    ----------
    backend:
        ``"numba"`` (default): JIT-accelerate the O(n^3) line-pair feasibility
        enumeration. If Numba is unavailable, automatically fall back to the
        reference backend without changing mathematical semantics.
        ``"reference"``: pure-Python audited implementation.
    """
    measurements = [
        Measurement(float(m.x), float(m.y), canonicalize_deg(float(m.bearing_deg)), m.label)
        for m in measurements
    ]
    hps = build_halfplanes(measurements, epsilon_deg)

    backend_norm = str(backend).strip().lower()
    if backend_norm not in {"numba", "reference"}:
        raise ValueError("backend must be 'numba' or 'reference'.")

    # Step 1: FEASIBILITY. For Q1 wedges, Proposition 2A makes vertex enumeration
    # a complete non-emptiness oracle. Only this O(n^3) hot loop is JIT-accelerated.
    if backend_norm == "numba" and NUMBA_AVAILABLE:
        feasible_vertices = enumerate_feasible_intersections_numba(hps, tol)
    else:
        feasible_vertices = enumerate_feasible_intersections(hps, tol)

    if not feasible_vertices:
        return Q1Result(
            status=STATUS_EMPTY,
            dimension=None,
            vertices=[],
            area=None,
            diameter=None,
            diameter_pair=None,
            covered_by_diameter_disk=None,
            diameter_disk_center=None,
            diameter_disk_radius=None,
            max_radial_excess=None,
            rho_viol=None,
            escape_direction_deg=None,
            feasible_vertex_witnesses=[],
        )

    # Step 2: BOUNDEDNESS. This test is valid only after non-emptiness is proven.
    escape = common_escape_direction_deg(measurements, epsilon_deg, tol)
    if escape is not None:
        return Q1Result(
            status=STATUS_UNBOUNDED,
            dimension=None,
            vertices=[],
            area=None,
            diameter=math.inf,
            diameter_pair=None,
            covered_by_diameter_disk=None,
            diameter_disk_center=None,
            diameter_disk_radius=None,
            max_radial_excess=None,
            rho_viol=None,
            escape_direction_deg=escape,
            feasible_vertex_witnesses=feasible_vertices,
        )

    # Steps 3-5: vertices -> dimension -> diameter -> diameter-disk coverage.
    (
        dimension,
        ordered,
        area,
        diameter,
        pair,
        covered,
        center,
        radius,
        max_excess,
        rho_viol,
    ) = analyze_bounded_vertices(feasible_vertices, tol)

    return Q1Result(
        status=STATUS_OK,
        dimension=dimension,
        vertices=ordered,
        area=area,
        diameter=diameter,
        diameter_pair=pair,
        covered_by_diameter_disk=covered,
        diameter_disk_center=center,
        diameter_disk_radius=radius,
        max_radial_excess=max_excess,
        rho_viol=rho_viol,
        escape_direction_deg=None,
        feasible_vertex_witnesses=feasible_vertices,
    )


def solve_q1_reference(
    measurements: Sequence[Measurement],
    epsilon_deg: float = 1.0,
    tol: Tolerance = Tolerance(),
) -> Q1Result:
    """Explicit audited reference path for regression tests and debugging."""
    return solve_q1(measurements, epsilon_deg=epsilon_deg, tol=tol, backend="reference")


def measurements_from_dicts(rows: Sequence[dict]) -> list[Measurement]:
    """Parse [{'x':..., 'y':..., 'bearing_deg':..., 'label':...}, ...]."""
    out: list[Measurement] = []
    for i, row in enumerate(rows):
        missing = {"x", "y", "bearing_deg"} - row.keys()
        if missing:
            raise ValueError(f"Measurement row {i} missing fields: {sorted(missing)}")
        out.append(
            Measurement(
                x=float(row["x"]),
                y=float(row["y"]),
                bearing_deg=float(row["bearing_deg"]),
                label=str(row.get("label", f"S{i+1}")),
            )
        )
    return out
