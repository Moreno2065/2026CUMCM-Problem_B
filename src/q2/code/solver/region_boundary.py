"""Minimal numerical boundary extraction for one sampled candidate cell.

The only membership authority here is the frozen production evaluator
(``src/q2/code/solver/q2_point.py::evaluate_q2_point``).  This module decides
nothing by itself: it locates the boundary of

    inside(p)  <=>  p in Crec, p admissible (or all-near), and Q(p) <= threshold

inside one rectangular cell by a local marching-triangle clip, and it returns
only the inside fragments it can defend with real evaluations.

Design constraints that this module deliberately honours:

* invalid samples stay masked -- ``None``/infinite results are never replaced
  by ``0`` and never interpolated through;
* every crossing is located by a bracketed bisection whose bracket
  ``(inside_fraction, outside_fraction, width_m)`` is recorded, so no
  monotonicity, no single-crossing and no linear-interpolation assumption is
  silently used;
* crossing points and fragment representatives are produced by the *same*
  production evaluator, so "interpolation disagrees with re-evaluation" cannot
  hide: a fragment whose representative disagrees is subdivided further or is
  reported as unresolved instead of being counted;
* areas come from the saved numeric rings (shoelace), never from a point count
  times an assumed cell area;
* fragments are per-triangle and are never merged, so holes, several branches
  and degenerate pieces stay separate; a triangle that would have to bridge two
  different feasible branches fails its representative check and is not emitted.

Everything produced here is numerical.  No fragment, area or bracket is a
set-inclusion certificate for the true sublevel set.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, MutableMapping

from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver.incumbent import is_valid_incumbent_result
from src.q2.code.solver.q2_point import Q2PointResult


BOUNDARY_KIND_INTERIOR = "interior_triangle"
BOUNDARY_KIND_CLIPPED = "clipped_triangle"

REASON_BUDGET = "probe_budget_exhausted"
REASON_INTERIOR = "interior_triangle_representative_outside_threshold"
REASON_CLIPPED = "clipped_triangle_representative_disagrees_with_evaluator"
REASON_DEGENERATE = "degenerate_clip"
REASON_MULTI_CROSSING = "multiple_crossings_on_triangle_edge"


@dataclass(frozen=True)
class BoundaryExtractionConfig:
    """Budgets for the local clip.  Every value has a safe default."""

    bisection_steps: int = 8
    tolerance_m: float = 0.25
    relative_tolerance: float = 0.05
    max_subdivision_depth: int = 1
    probe_budget_per_cell: int = 96

    def __post_init__(self) -> None:
        if self.bisection_steps < 1:
            raise ValueError("bisection_steps must be positive.")
        if self.tolerance_m <= 0.0 or not math.isfinite(self.tolerance_m):
            raise ValueError("tolerance_m must be finite and positive.")
        if not 0.0 < self.relative_tolerance <= 1.0:
            raise ValueError("relative_tolerance must lie in (0, 1].")
        if self.max_subdivision_depth < 0:
            raise ValueError("max_subdivision_depth must be nonnegative.")
        if self.probe_budget_per_cell < 4:
            raise ValueError("probe_budget_per_cell must be at least four.")


@dataclass(frozen=True)
class EdgeBracket:
    """Recorded bracket of one edge crossing (never assumed unique)."""

    edge_start: Point2
    edge_end: Point2
    inside_fraction: float
    outside_fraction: float
    width_m: float
    probes: int


@dataclass(frozen=True)
class BoundaryFragment:
    """One saved numerical ring and its shoelace area."""

    ring: tuple[Point2, ...]
    area_m2: float
    kind: str
    verified: bool


@dataclass(frozen=True)
class CellBoundaryResult:
    fragments: tuple[BoundaryFragment, ...]
    brackets: tuple[EdgeBracket, ...]
    unresolved_reasons: tuple[str, ...]
    mixed_triangle_count: int
    probes: int

    @property
    def resolved(self) -> bool:
        return not self.unresolved_reasons

    @property
    def area_m2(self) -> float:
        return math.fsum(fragment.area_m2 for fragment in self.fragments)


class _ProbeBudgetExhausted(RuntimeError):
    """Raised internally when a cell clip runs out of its probe budget."""


@dataclass
class _CrossingState:
    inside: Point2
    outside: Point2
    length: float
    low: float = 0.0
    high: float = 1.0
    width: float = 0.0
    probes: int = 0
    active: bool = True


def is_inside_threshold(result: Q2PointResult, threshold: float) -> bool:
    """Production membership predicate: feasible, admissible and below thresh."""
    if not is_valid_incumbent_result(result):
        return False
    if result.Q is None:
        return False
    value = float(result.Q)
    return math.isfinite(value) and value <= threshold


def ring_area_m2(ring: tuple[Point2, ...]) -> float:
    """Absolute shoelace area of one saved ring."""
    if len(ring) < 3:
        return 0.0
    total = 0.0
    for index in range(len(ring)):
        current = ring[index]
        following = ring[(index + 1) % len(ring)]
        total += current.x * following.y - following.x * current.y
    return abs(total) / 2.0


def extract_mixed_cell_boundary(
    corners: tuple[Point2, ...],
    center: Point2,
    cache: MutableMapping[Point2, Q2PointResult],
    threshold: float,
    probe: Callable[[Point2], Q2PointResult],
    *,
    probe_many: Callable[[tuple[Point2, ...]], list[Q2PointResult]] | None = None,
    config: BoundaryExtractionConfig | None = None,
    probe_budget: int | None = None,
    interior_points: tuple[Point2, ...] = (),
) -> CellBoundaryResult:
    """Clip one rectangular cell against Crec/admissibility and the Q threshold.

    ``cache`` holds every already evaluated point; ``probe`` must evaluate one
    new point with the production evaluator and store it in ``cache`` before
    returning.  Only *new* evaluations are charged against ``probe_budget``.

    ``interior_points`` are known in-threshold samples inside the cell.  They
    are inserted as triangulation vertices, so a cell whose four corners and
    centre all fail can still expose the band that holds a real candidate
    sample instead of being dropped as empty.
    """
    if not math.isfinite(threshold):
        raise ValueError("threshold must be finite.")
    if len(corners) != 4:
        raise ValueError("exactly four corners are required.")
    cfg = config or BoundaryExtractionConfig()
    budget = (
        cfg.probe_budget_per_cell
        if probe_budget is None
        else max(0, min(probe_budget, cfg.probe_budget_per_cell))
    )
    state = {"probes": 0}

    def values(points: tuple[Point2, ...]) -> tuple[Q2PointResult, ...]:
        unique = tuple(dict.fromkeys(points))
        missing = tuple(point for point in unique if point not in cache)
        if state["probes"] + len(missing) > budget:
            raise _ProbeBudgetExhausted()
        if missing:
            results = (
                probe_many(missing)
                if probe_many is not None
                else [probe(point) for point in missing]
            )
            if len(results) != len(missing):
                raise ValueError("probe_many must return one result for every point.")
            state["probes"] += len(missing)
            for point, result in zip(missing, results, strict=True):
                cache[point] = result
        return tuple(cache[point] for point in points)

    def value(point: Point2) -> Q2PointResult:
        return values((point,))[0]

    triangles = _panel_triangles(corners, center, interior_points)
    tolerance = min(
        cfg.tolerance_m, cfg.relative_tolerance * _diameter(tuple(corners) + (center,))
    )
    fragments: list[BoundaryFragment] = []
    brackets: list[EdgeBracket] = []
    reasons: list[str] = []
    mixed_count = 0
    try:
        for triangle in triangles:
            flags = tuple(
                is_inside_threshold(value(vertex), threshold) for vertex in triangle
            )
            if not any(flags):
                continue
            if all(flags):
                _resolve_interior(
                    triangle,
                    threshold,
                    value,
                    values,
                    cfg,
                    tolerance,
                    0,
                    fragments,
                    brackets,
                    reasons,
                )
                continue
            mixed_count += 1
            _resolve_mixed(
                triangle,
                flags,
                threshold,
                value,
                values,
                cfg,
                tolerance,
                0,
                fragments,
                brackets,
                reasons,
            )
    except _ProbeBudgetExhausted:
        reasons.append(REASON_BUDGET)

    return CellBoundaryResult(
        fragments=tuple(fragments),
        brackets=tuple(brackets),
        unresolved_reasons=tuple(dict.fromkeys(reasons)),
        mixed_triangle_count=mixed_count,
        probes=state["probes"],
    )


def _panel_triangles(
    corners: tuple[Point2, ...],
    center: Point2,
    interior_points: tuple[Point2, ...],
) -> tuple[tuple[Point2, Point2, Point2], ...]:
    """Fan-triangulate the cell, splitting it at every interior sample.

    Without interior samples this is the plain four-triangle fan around the
    centre.  With them the cell is cut at their x and y coordinates so each
    known in-threshold sample becomes a triangulation vertex and the local
    boundary can be traced from a point that is really inside.
    """
    x_min = min(corner.x for corner in corners)
    x_max = max(corner.x for corner in corners)
    y_min = min(corner.y for corner in corners)
    y_max = max(corner.y for corner in corners)
    inner = tuple(
        point
        for point in dict.fromkeys(interior_points)
        if x_min < point.x < x_max and y_min < point.y < y_max
    )
    if not inner:
        return (
            (center, corners[0], corners[1]),
            (center, corners[1], corners[2]),
            (center, corners[2], corners[3]),
            (center, corners[3], corners[0]),
        )
    x_breaks = sorted({x_min, x_max} | {point.x for point in inner})
    y_breaks = sorted({y_min, y_max} | {point.y for point in inner})
    triangles: list[tuple[Point2, Point2, Point2]] = []
    for x_index in range(len(x_breaks) - 1):
        for y_index in range(len(y_breaks) - 1):
            panel = (
                Point2(x_breaks[x_index], y_breaks[y_index]),
                Point2(x_breaks[x_index + 1], y_breaks[y_index]),
                Point2(x_breaks[x_index + 1], y_breaks[y_index + 1]),
                Point2(x_breaks[x_index], y_breaks[y_index + 1]),
            )
            panel_center = Point2(
                0.5 * (panel[0].x + panel[2].x), 0.5 * (panel[0].y + panel[2].y)
            )
            triangles.extend(
                (
                    (panel_center, panel[0], panel[1]),
                    (panel_center, panel[1], panel[2]),
                    (panel_center, panel[2], panel[3]),
                    (panel_center, panel[3], panel[0]),
                )
            )
    return tuple(triangles)


def _resolve_interior(
    triangle: tuple[Point2, Point2, Point2],
    threshold: float,
    value: Callable[[Point2], Q2PointResult],
    values: Callable[[tuple[Point2, ...]], tuple[Q2PointResult, ...]],
    cfg: BoundaryExtractionConfig,
    tolerance: float,
    depth: int,
    fragments: list[BoundaryFragment],
    brackets: list[EdgeBracket],
    reasons: list[str],
) -> None:
    """A triangle with three inside vertices still needs an interior probe."""
    representative = _centroid(triangle)
    if is_inside_threshold(value(representative), threshold):
        fragments.append(
            BoundaryFragment(
                ring=triangle,
                area_m2=ring_area_m2(triangle),
                kind=BOUNDARY_KIND_INTERIOR,
                verified=True,
            )
        )
        return
    if depth < cfg.max_subdivision_depth:
        _subdivide(
            triangle,
            threshold,
            value,
            values,
            cfg,
            tolerance,
            depth,
            fragments,
            brackets,
            reasons,
        )
        return
    reasons.append(REASON_INTERIOR)


def _resolve_mixed(
    triangle: tuple[Point2, Point2, Point2],
    flags: tuple[bool, bool, bool],
    threshold: float,
    value: Callable[[Point2], Q2PointResult],
    values: Callable[[tuple[Point2, ...]], tuple[Q2PointResult, ...]],
    cfg: BoundaryExtractionConfig,
    tolerance: float,
    depth: int,
    fragments: list[BoundaryFragment],
    brackets: list[EdgeBracket],
    reasons: list[str],
) -> None:
    """Clip a triangle with both inside and outside vertices."""
    if not _edges_are_single_crossing(triangle, flags, threshold, value):
        if depth < cfg.max_subdivision_depth:
            _subdivide(
                triangle,
                threshold,
                value,
                values,
                cfg,
                tolerance,
                depth,
                fragments,
                brackets,
                reasons,
            )
        else:
            reasons.append(REASON_MULTI_CROSSING)
        return
    clip = _clip_once(
        triangle, flags, threshold, values, cfg.bisection_steps, tolerance
    )
    if clip is not None:
        ring, local_brackets = clip
        if _representative_is_inside(ring, threshold, value):
            area = ring_area_m2(ring)
            if area <= 0.0:
                reasons.append(REASON_DEGENERATE)
            else:
                brackets.extend(local_brackets)
                fragments.append(
                    BoundaryFragment(
                        ring=ring,
                        area_m2=area,
                        kind=BOUNDARY_KIND_CLIPPED,
                        verified=True,
                    )
                )
            return
    if depth < cfg.max_subdivision_depth:
        _subdivide(
            triangle,
            threshold,
            value,
            values,
            cfg,
            tolerance,
            depth,
            fragments,
            brackets,
            reasons,
        )
        return
    reasons.append(REASON_CLIPPED)


def _subdivide(
    triangle: tuple[Point2, Point2, Point2],
    threshold: float,
    value: Callable[[Point2], Q2PointResult],
    values: Callable[[tuple[Point2, ...]], tuple[Q2PointResult, ...]],
    cfg: BoundaryExtractionConfig,
    tolerance: float,
    depth: int,
    fragments: list[BoundaryFragment],
    brackets: list[EdgeBracket],
    reasons: list[str],
) -> None:
    first, second, third = triangle
    first_second = _midpoint(first, second)
    second_third = _midpoint(second, third)
    third_first = _midpoint(third, first)
    children = (
        (first, first_second, third_first),
        (first_second, second, second_third),
        (third_first, second_third, third),
        (first_second, second_third, third_first),
    )
    for child in children:
        child_flags = tuple(
            is_inside_threshold(value(vertex), threshold) for vertex in child
        )
        if not any(child_flags):
            continue
        if all(child_flags):
            _resolve_interior(
                child,
                threshold,
                value,
                values,
                cfg,
                tolerance,
                depth + 1,
                fragments,
                brackets,
                reasons,
            )
            continue
        _resolve_mixed(
            child,
            child_flags,
            threshold,
            value,
            values,
            cfg,
            tolerance,
            depth + 1,
            fragments,
            brackets,
            reasons,
        )


def _edges_are_single_crossing(
    triangle: tuple[Point2, Point2, Point2],
    flags: tuple[bool, bool, bool],
    threshold: float,
    value: Callable[[Point2], Q2PointResult],
) -> bool:
    """Detect an even number of crossings hiding on one triangle edge.

    Two vertices of the same class whose edge midpoint has the other class mean
    the edge leaves and re-enters the threshold band.  The bracket scan must not
    assume one crossing per edge, so such a triangle is subdivided or reported
    unresolved instead of being clipped with a single straight chord.
    """
    for index in range(3):
        following = (index + 1) % 3
        if flags[index] != flags[following]:
            continue
        middle = _midpoint(triangle[index], triangle[following])
        if is_inside_threshold(value(middle), threshold) != flags[index]:
            return False
    return True


def _clip_once(
    triangle: tuple[Point2, Point2, Point2],
    flags: tuple[bool, bool, bool],
    threshold: float,
    values: Callable[[tuple[Point2, ...]], tuple[Q2PointResult, ...]],
    steps: int,
    tolerance: float,
) -> tuple[
    tuple[Point2, ...],
    tuple[EdgeBracket, EdgeBracket],
] | None:
    inside_index = [index for index in range(3) if flags[index]]
    outside_index = [index for index in range(3) if not flags[index]]
    if not inside_index or not outside_index:
        return None
    if len(inside_index) == 1:
        inside = inside_index[0]
        first = (inside + 1) % 3
        second = (inside + 2) % 3
        pairs = ((inside, first), (inside, second))
    else:
        outside = outside_index[0]
        first = (outside + 1) % 3
        second = (outside + 2) % 3
        pairs = ((first, outside), (second, outside))

    crossings, local_brackets = _locate_crossings(
        tuple(
            (triangle[inside_vertex], triangle[outside_vertex])
            for inside_vertex, outside_vertex in pairs
        ),
        values,
        threshold,
        steps,
        tolerance,
    )

    if len(inside_index) == 1:
        inside = inside_index[0]
        ring = (triangle[inside], crossings[0], crossings[1])
    else:
        outside = outside_index[0]
        first = (outside + 1) % 3
        second = (outside + 2) % 3
        ring = (crossings[0], triangle[first], triangle[second], crossings[1])
    return (
        tuple(ring),
        (local_brackets[0], local_brackets[1]),
    )


def _locate_crossings(
    edges: tuple[tuple[Point2, Point2], ...],
    values: Callable[[tuple[Point2, ...]], tuple[Q2PointResult, ...]],
    threshold: float,
    steps: int,
    tolerance: float,
) -> tuple[list[Point2], list[EdgeBracket]]:
    """Bracket independent edge crossings in synchronous, deterministic rounds."""
    states: list[_CrossingState] = []
    for inside_point, outside_point in edges:
        length = inside_point.distance_to(outside_point)
        states.append(
            _CrossingState(
                inside=inside_point,
                outside=outside_point,
                length=length,
                width=length,
                active=length > 0.0,
            )
        )

    for _ in range(max(1, steps)):
        active = [state for state in states if state.active]
        if not active:
            break
        points = tuple(
            _lerp(
                state.inside,
                state.outside,
                0.5 * (state.low + state.high),
            )
            for state in active
        )
        results = values(points)
        for state, result in zip(active, results, strict=True):
            fraction = 0.5 * (state.low + state.high)
            if is_inside_threshold(result, threshold):
                state.low = fraction
            else:
                state.high = fraction
            state.probes += 1
            state.width = (state.high - state.low) * state.length
            if state.width <= tolerance:
                state.active = False

    crossings: list[Point2] = []
    brackets: list[EdgeBracket] = []
    for state in states:
        crossings.append(_lerp(state.inside, state.outside, 0.5 * (state.low + state.high)))
        brackets.append(
            EdgeBracket(
                edge_start=state.inside,
                edge_end=state.outside,
                inside_fraction=state.low,
                outside_fraction=state.high,
                width_m=state.width,
                probes=state.probes,
            )
        )
    return crossings, brackets


def _representative_is_inside(
    ring: tuple[Point2, ...],
    threshold: float,
    value: Callable[[Point2], Q2PointResult],
) -> bool:
    """Re-evaluate the fragment representative with the production evaluator.

    The ring's own crossings were already located by that same evaluator
    (bracketed bisection), so the extra check targets the one place a straight
    cut can lie: a fragment whose representative is outside the threshold band
    is a fragment that bridged an excluded island or a second feasible branch,
    and it is subdivided further or reported unresolved instead of being
    counted.
    """
    if ring_area_m2(ring) <= 0.0:
        return False
    return is_inside_threshold(value(_centroid(ring)), threshold)


def _lerp(start: Point2, end: Point2, fraction: float) -> Point2:
    return Point2(
        start.x + (end.x - start.x) * fraction,
        start.y + (end.y - start.y) * fraction,
    )


def _midpoint(start: Point2, end: Point2) -> Point2:
    return Point2(0.5 * (start.x + end.x), 0.5 * (start.y + end.y))


def _centroid(ring: tuple[Point2, ...]) -> Point2:
    count = float(len(ring))
    return Point2(
        math.fsum(point.x for point in ring) / count,
        math.fsum(point.y for point in ring) / count,
    )


def _diameter(points: tuple[Point2, ...]) -> float:
    return max(
        (first.distance_to(second) for first in points for second in points),
        default=0.0,
    )
