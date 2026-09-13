"""Near-aware angular image of the frozen physical A1 set.

This module consumes only :class:`A1BoundaryRegistry`.  Reception witnesses
belong to a separate physical registry and are intentionally not imported.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .a1 import (
    A1BoundaryRegistry,
    A1Dimension,
    A1Region,
    EPSILON_DEG,
    INNER_RADIUS_M,
    OUTER_RADIUS_M,
)
from .circular_intervals import CircularIntervalUnion
from .primitives import BoundaryPoint, CircularArc, LineSegment, Point2


NEAR_RADIUS_M = 5.0
DISTANCE_TOL_M = 1e-9
# Tangency is a measure-zero property, so this comparison must be scale-aware
# but *tight*: it has to stay strictly below the smallest positive near-circle
# gap that Gate C exercises (5e-14 m).  At 1e-15 m (sub-femtometre, ~1e-15 of a
# metre-scale geometry) exact tangency is detected while a genuine
# sub-nanometre wedge channel is not collapsed into the tangent-bridge branch.
TANGENCY_TOL_M = 1e-15


@dataclass(frozen=True)
class AngularExtremumWitness:
    """A boundary point whose bearing is an endpoint of an angular component."""

    point: Point2
    angle_rad: float
    source_label: str
    source_component_index: int
    source_piece_index: int
    event_kind: str


@dataclass(frozen=True)
class AngularBoundaryEvent:
    """One explicit event in the clipped physical boundary arrangement."""

    source_component_index: int
    source_piece_index: int
    source_label: str
    event_kind: str
    point: Point2
    angle_rad: float


@dataclass(frozen=True)
class AngularImageResult:
    """Closed angular image and its frozen one-degree bearing expansion."""

    all_near: bool
    spatial_component_count: int
    raw_component_intervals: tuple[CircularIntervalUnion, ...]
    merged_closure: CircularIntervalUnion
    expanded_closure: CircularIntervalUnion
    full_circle: bool
    extrema_witnesses: tuple[AngularExtremumWitness, ...]
    boundary_events: tuple[AngularBoundaryEvent, ...]


def build_angular_image(a1: A1Region, station2: Point2) -> AngularImageResult:
    """Construct closure(arg(A1 minus the closed five-metre near disk))."""
    if not isinstance(a1, A1Region):
        raise TypeError("a1 must be an A1Region.")
    if not isinstance(a1.boundary, A1BoundaryRegistry):
        raise TypeError("Angular image requires the physical A1BoundaryRegistry.")

    if a1.dimension == A1Dimension.EMPTY:
        return _empty_result(all_near=False, event="a1_empty")

    if a1.dimension == A1Dimension.POINT:
        points = tuple(piece.curve.point for piece in a1.boundary.point_pieces)
        visible = tuple(
            point for point in points if point.distance_to(station2) > NEAR_RADIUS_M
        )
        if not visible:
            return _empty_result(all_near=True, event="point_a1_all_near")
        interval = CircularIntervalUnion.from_intervals(
            ((_bearing(station2, point), _bearing(station2, point)) for point in visible)
        )
        witnesses = tuple(
            AngularExtremumWitness(
                point, _bearing(station2, point), "a1_degenerate_point", index, index, "point"
            )
            for index, point in enumerate(visible)
        )
        events = tuple(
            AngularBoundaryEvent(index, index, "a1_degenerate_point", "point", point, _bearing(station2, point))
            for index, point in enumerate(visible)
        )
        expanded = interval.dilated(math.radians(EPSILON_DEG))
        return AngularImageResult(
            all_near=False,
            spatial_component_count=len(visible),
            raw_component_intervals=(interval,),
            merged_closure=interval,
            expanded_closure=expanded,
            full_circle=interval.is_full,
            extrema_witnesses=witnesses,
            boundary_events=events,
        )

    cuts, _ = _critical_bearings(a1, station2)
    raw = _angular_cells(a1, station2, cuts)
    if raw.is_empty:
        return _empty_result(all_near=True, event="area_a1_all_near")

    component_intervals, witnesses, events = _clipped_boundary_components(a1, station2)
    tangent_bridge = _double_wedge_tangent_bridge(a1, station2)
    if tangent_bridge is not None:
        ordered_bridge = sorted(tangent_bridge, key=lambda item: item[0])
        lower_angle, upper_angle = (item[0] for item in ordered_bridge)
        component_intervals = (
            CircularIntervalUnion.from_intervals(((lower_angle, upper_angle),)),
            CircularIntervalUnion.from_intervals(((upper_angle, lower_angle + math.tau),)),
        )
        source_index = len(a1.boundary.pieces)
        witnesses = tuple(
            AngularExtremumWitness(
                point, angle, "near_circle", component_index, source_index,
                "tangent_bridge_endpoint",
            )
            for component_index in (0, 1)
            for angle, point in ordered_bridge
        )
        events = tuple(
            AngularBoundaryEvent(
                component_index, source_index, "near_circle",
                "tangent_bridge_endpoint", point, angle,
            )
            for component_index in (0, 1)
            for angle, point in ordered_bridge
        )
    component_count = len(component_intervals)
    if component_count == 0:
        # Defensive fallback for a numerically collapsed boundary arrangement.
        component_intervals = (raw,)
        component_count = 1
    expanded = raw.dilated(math.radians(EPSILON_DEG))
    return AngularImageResult(
        all_near=False,
        spatial_component_count=component_count,
        raw_component_intervals=component_intervals,
        merged_closure=raw,
        expanded_closure=expanded,
        full_circle=raw.is_full,
        extrema_witnesses=witnesses,
        boundary_events=events,
    )


def _bearing(origin: Point2, point: Point2) -> float:
    return math.atan2(point.y - origin.y, point.x - origin.x) % math.tau


def _critical_bearings(
    a1: A1Region, station2: Point2
) -> tuple[tuple[float, ...], tuple[AngularExtremumWitness, ...]]:
    """Return every endpoint/tangency at which ray feasibility can change."""
    events: list[tuple[float, Point2, str]] = []
    for piece in a1.boundary.pieces:
        curve = piece.curve
        label = piece.label.value
        if isinstance(curve, LineSegment):
            points = [curve.start, curve.end]
            points.extend(_segment_circle_intersections(curve, station2, NEAR_RADIUS_M))
        elif isinstance(curve, CircularArc):
            points = list(curve.endpoints)
            points.extend(_arc_tangent_points(curve, station2))
            points.extend(_arc_circle_intersections(curve, station2, NEAR_RADIUS_M))
        elif isinstance(curve, BoundaryPoint):
            points = (curve.point,)
        else:  # construction invariant, retained as a defensive API boundary
            raise TypeError("Unsupported A1 boundary primitive.")
        for point in points:
            if point.distance_to(station2) <= DISTANCE_TOL_M:
                continue
            events.append((_bearing(station2, point), point, label))

    cuts = _unique_angles([0.0, *(event[0] for event in events)])
    witnesses = tuple(
        AngularExtremumWitness(point, angle, label, -1, -1, "critical")
        for angle, point, label in events
    )
    return cuts, witnesses


def _arc_tangent_points(arc: CircularArc, observer: Point2) -> tuple[Point2, ...]:
    offset = observer - arc.center
    distance = offset.norm()
    if distance <= arc.radius + DISTANCE_TOL_M:
        return ()
    axis = offset.scaled(1.0 / distance)
    along = arc.radius * arc.radius / distance
    height = arc.radius * math.sqrt(max(0.0, 1.0 - (arc.radius / distance) ** 2))
    base = arc.center + axis.scaled(along)
    normal = Point2(-axis.y, axis.x)
    candidates = (base + normal.scaled(height), base - normal.scaled(height))
    return tuple(point for point in candidates if _point_on_arc(arc, point))


def _segment_circle_intersections(
    segment: LineSegment, center: Point2, radius: float
) -> tuple[Point2, ...]:
    delta = segment.end - segment.start
    relative = segment.start - center
    length_sq = delta.dot(delta)
    projection = -relative.dot(delta) / length_sq
    closest = segment.start + delta.scaled(projection)
    height_sq_m = radius * radius - closest.distance_to(center) ** 2
    if height_sq_m < 0.0:
        return ()
    if height_sq_m == 0.0:
        values = (projection,)
    else:
        offset = math.sqrt(height_sq_m / length_sq)
        values = (projection - offset, projection + offset)
    result: list[Point2] = []
    for value in values:
        if -1e-11 <= value <= 1.0 + 1e-11:
            point = segment.point_at(min(1.0, max(0.0, value)))
            if all(point.distance_to(old) > DISTANCE_TOL_M for old in result):
                result.append(point)
    return tuple(result)


def _double_wedge_tangent_bridge(
    a1: A1Region, station2: Point2
) -> tuple[tuple[float, Point2], tuple[float, Point2]] | None:
    """Detect a near closed disk tangent to both wedge sides.

    The two excluded tangency points disconnect the strict bearing domain even
    though its closure boundary graph is point-connected.  The two component
    images are the complementary near-circle arcs and their union is FULL.
    """
    tangent_points: list[Point2] = []
    for piece in a1.boundary.line_pieces:
        segment = piece.curve
        delta = segment.end - segment.start
        fraction = (station2 - segment.start).dot(delta) / delta.dot(delta)
        if not (0.0 < fraction < 1.0):
            continue
        closest = segment.start + delta.scaled(fraction)
        if math.isclose(
            closest.distance_to(station2),
            NEAR_RADIUS_M,
            rel_tol=0.0,
            abs_tol=TANGENCY_TOL_M,
        ):
            tangent_points.append(closest)
    if len(tangent_points) != 2:
        return None
    midpoint = station2 + Point2(1.0, 0.0).scaled(NEAR_RADIUS_M)
    if not a1.closure_contains(midpoint, tol_m=2e-9):
        return None
    return tuple((_bearing(station2, point), point) for point in tangent_points)  # type: ignore[return-value]


def _arc_circle_intersections(
    arc: CircularArc, center: Point2, radius: float
) -> tuple[Point2, ...]:
    delta = center - arc.center
    distance = delta.norm()
    if distance <= DISTANCE_TOL_M:
        return ()
    if distance > arc.radius + radius + DISTANCE_TOL_M:
        return ()
    if distance < abs(arc.radius - radius) - DISTANCE_TOL_M:
        return ()
    along = (arc.radius**2 - radius**2 + distance**2) / (2.0 * distance)
    height_sq = arc.radius**2 - along**2
    if height_sq < -DISTANCE_TOL_M:
        return ()
    axis = delta.scaled(1.0 / distance)
    base = arc.center + axis.scaled(along)
    normal = Point2(-axis.y, axis.x)
    height = math.sqrt(max(0.0, height_sq))
    candidates = (base + normal.scaled(height), base - normal.scaled(height))
    result: list[Point2] = []
    for point in candidates:
        if _point_on_arc(arc, point) and all(
            point.distance_to(old) > DISTANCE_TOL_M for old in result
        ):
            result.append(point)
    return tuple(result)


def _point_on_arc(arc: CircularArc, point: Point2) -> bool:
    angle = (point - arc.center).angle_rad()
    for shift in (-math.tau, 0.0, math.tau):
        candidate = angle + shift
        if arc.start_angle_rad - 1e-11 <= candidate <= arc.end_angle_rad + 1e-11:
            return True
    return False


def _unique_angles(values: list[float]) -> tuple[float, ...]:
    ordered = sorted(value % math.tau for value in values)
    result: list[float] = []
    for value in ordered:
        if not result or value - result[-1] > 1e-11:
            result.append(value)
    if result and math.tau - result[-1] + result[0] <= 1e-11:
        result[0] = 0.0
        result.pop()
    return tuple(result or [0.0])


def _angular_cells(
    a1: A1Region, station2: Point2, cuts: tuple[float, ...]
) -> CircularIntervalUnion:
    """Classify analytic angular cells by exact one-dimensional ray feasibility."""
    unwrapped = list(cuts) + [cuts[0] + math.tau]
    result = CircularIntervalUnion.empty()
    for start, end in zip(unwrapped, unwrapped[1:]):
        midpoint = 0.5 * (start + end)
        if _ray_has_actual_target(a1, station2, midpoint):
            result = result.union(CircularIntervalUnion.from_intervals(((start, end),)))
    for angle in cuts:
        if _ray_has_actual_target(a1, station2, angle):
            result = result.union(CircularIntervalUnion.from_intervals(((angle, angle),)))
    return result


def _ray_has_actual_target(a1: A1Region, station2: Point2, angle: float) -> bool:
    """Test whether one S2 ray contains a point in A1 at strict distance >5."""
    direction = Point2(math.cos(angle), math.sin(angle))
    lo, hi = NEAR_RADIUS_M, math.inf
    for center, radius in (
        (a1.omega_center, a1.omega_radius_m),
        (a1.observation.station, OUTER_RADIUS_M),
    ):
        interval = _ray_disk_interval(station2, direction, center, radius)
        if interval is None:
            return False
        lo, hi = max(lo, interval[0]), min(hi, interval[1])
        if hi <= lo + DISTANCE_TOL_M:
            return False

    lower, upper = a1.observation.wedge_limits_rad
    lower_u = Point2(math.cos(lower), math.sin(lower))
    upper_u = Point2(math.cos(upper), math.sin(upper))
    relative = station2 - a1.observation.station
    constrained = _intersect_linear_halfline(lo, hi, _cross(lower_u, relative), _cross(lower_u, direction), True)
    if constrained is None:
        return False
    lo, hi = constrained
    constrained = _intersect_linear_halfline(lo, hi, _cross(upper_u, relative), _cross(upper_u, direction), False)
    if constrained is None:
        return False
    lo, hi = constrained
    if hi <= max(lo, NEAR_RADIUS_M) + DISTANCE_TOL_M:
        return False

    # The inner station disk is open in A1.  A convex norm attains its maximum
    # on this ray interval at an endpoint, so no subdivision is necessary.
    probes = (lo, hi)
    return max(
        (station2 + direction.scaled(t)).distance_to(a1.observation.station)
        for t in probes
    ) > INNER_RADIUS_M + DISTANCE_TOL_M


def _ray_disk_interval(
    origin: Point2, direction: Point2, center: Point2, radius: float
) -> tuple[float, float] | None:
    delta = origin - center
    projection = delta.dot(direction)
    discriminant = projection * projection - (delta.dot(delta) - radius * radius)
    if discriminant < -DISTANCE_TOL_M:
        return None
    root = math.sqrt(max(0.0, discriminant))
    return -projection - root, -projection + root


def _intersect_linear_halfline(
    lo: float, hi: float, offset: float, slope: float, want_nonnegative: bool
) -> tuple[float, float] | None:
    sign = 1.0 if want_nonnegative else -1.0
    offset, slope = sign * offset, sign * slope
    if abs(slope) <= 1e-14:
        return (lo, hi) if offset >= -1e-10 else None
    root = -offset / slope
    if slope > 0.0:
        lo = max(lo, root)
    else:
        hi = min(hi, root)
    return None if hi < lo - DISTANCE_TOL_M else (lo, hi)


def _cross(left: Point2, right: Point2) -> float:
    return left.x * right.y - left.y * right.x


@dataclass(frozen=True)
class _ClippedPiece:
    curve: LineSegment | CircularArc | BoundaryPoint
    source_piece_index: int
    source_label: str
    event_kind: str
    is_near_arc: bool = False


def _clipped_boundary_components(
    a1: A1Region, station2: Point2
) -> tuple[
    tuple[CircularIntervalUnion, ...],
    tuple[AngularExtremumWitness, ...],
    tuple[AngularBoundaryEvent, ...],
]:
    """Clip the physical boundary and enumerate every endpoint-graph component."""
    pieces: list[_ClippedPiece] = []
    for piece_index, piece in enumerate(a1.boundary.pieces):
        curve = piece.curve
        label = piece.label.value
        if isinstance(curve, LineSegment):
            pieces.extend(_clip_segment(curve, station2, piece_index, label))
        elif isinstance(curve, CircularArc):
            pieces.extend(_clip_arc(curve, station2, piece_index, label))
        else:
            if curve.point.distance_to(station2) >= NEAR_RADIUS_M:
                pieces.append(_ClippedPiece(curve, piece_index, label, "boundary_point"))

    near_pieces = _active_near_arcs(a1, station2, len(a1.boundary.pieces))
    pieces.extend(near_pieces)
    if not pieces:
        return (), (), ()

    parents = list(range(len(pieces)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def unite(left: int, right: int) -> None:
        left, right = find(left), find(right)
        if left != right:
            parents[right] = left

    endpoints = [_curve_endpoints(piece.curve) for piece in pieces]
    for left in range(len(pieces)):
        for right in range(left):
            if any(
                first.distance_to(second) <= 2e-7
                for first in endpoints[left]
                for second in endpoints[right]
            ):
                unite(left, right)

    groups: dict[int, list[int]] = {}
    for index in range(len(pieces)):
        groups.setdefault(find(index), []).append(index)

    # A complete active near circle is a hole boundary of its containing A1
    # component, not a separate spatial component.  A1 AREA is connected in
    # the frozen radial-wedge construction, so merge that loop with the other
    # boundary group without relying on a positional heuristic for FULL.
    full_near_groups = [
        root
        for root, indices in groups.items()
        if any(
            pieces[index].is_near_arc
            and isinstance(pieces[index].curve, CircularArc)
            and pieces[index].curve.angle_span_rad >= math.tau - 1e-14
            for index in indices
        )
    ]
    if full_near_groups and len(groups) > 1:
        merged_indices = [index for indices in groups.values() for index in indices]
        groups = {min(groups): merged_indices}

    component_intervals: list[CircularIntervalUnion] = []
    witnesses: list[AngularExtremumWitness] = []
    events: list[AngularBoundaryEvent] = []
    for component_index, indices in enumerate(groups.values()):
        component_union = CircularIntervalUnion.empty()
        component_candidates: list[tuple[Point2, float, _ClippedPiece, str]] = []
        for index in indices:
            piece = pieces[index]
            curve_union, candidates = _curve_angular_image(piece, station2)
            component_union = component_union.union(curve_union)
            component_candidates.extend(candidates)
        component_intervals.append(component_union)
        for point, angle, piece, event_kind in component_candidates:
            events.append(
                AngularBoundaryEvent(
                    component_index,
                    piece.source_piece_index,
                    piece.source_label,
                    event_kind,
                    point,
                    angle,
                )
            )
            if _is_union_endpoint(component_union, angle) or component_union.is_full:
                witnesses.append(
                    AngularExtremumWitness(
                        point,
                        angle,
                        piece.source_label,
                        component_index,
                        piece.source_piece_index,
                        event_kind,
                    )
                )
    return tuple(component_intervals), tuple(witnesses), tuple(events)


def _clip_segment(
    segment: LineSegment, station2: Point2, piece_index: int, label: str
) -> tuple[_ClippedPiece, ...]:
    delta = segment.end - segment.start
    length_sq = delta.dot(delta)
    params = [0.0, 1.0]
    for point in _segment_circle_intersections(segment, station2, NEAR_RADIUS_M):
        params.append((point - segment.start).dot(delta) / length_sq)
    params = _unique_scalars(params)
    result: list[_ClippedPiece] = []
    for start, end in zip(params, params[1:]):
        if end <= start:
            continue
        midpoint = segment.point_at(0.5 * (start + end))
        if midpoint.distance_to(station2) < NEAR_RADIUS_M:
            continue
        first, last = segment.point_at(start), segment.point_at(end)
        if first.distance_to(last) > 1e-10:
            result.append(
                _ClippedPiece(LineSegment(first, last), piece_index, label, "clipped_original")
            )
    return tuple(result)


def _clip_arc(
    arc: CircularArc, station2: Point2, piece_index: int, label: str
) -> tuple[_ClippedPiece, ...]:
    params = [0.0, 1.0]
    for point in _arc_circle_intersections(arc, station2, NEAR_RADIUS_M):
        params.append(_arc_fraction(arc, point))
    params = _unique_scalars(params)
    result: list[_ClippedPiece] = []
    for start, end in zip(params, params[1:]):
        if end <= start:
            continue
        midpoint = arc.point_at(0.5 * (start + end))
        if midpoint.distance_to(station2) < NEAR_RADIUS_M:
            continue
        first_angle = arc.start_angle_rad + start * arc.angle_span_rad
        last_angle = arc.start_angle_rad + end * arc.angle_span_rad
        result.append(
            _ClippedPiece(
                CircularArc(arc.center, arc.radius, first_angle, last_angle),
                piece_index,
                label,
                "clipped_original",
            )
        )
    return tuple(result)


def _active_near_arcs(
    a1: A1Region, station2: Point2, source_piece_index: int
) -> tuple[_ClippedPiece, ...]:
    cuts = [0.0, math.tau]
    for piece in a1.boundary.pieces:
        curve = piece.curve
        if isinstance(curve, LineSegment):
            points = _segment_circle_intersections(curve, station2, NEAR_RADIUS_M)
            endpoints = (curve.start, curve.end)
        elif isinstance(curve, CircularArc):
            points = _arc_circle_intersections(curve, station2, NEAR_RADIUS_M)
            endpoints = curve.endpoints
        else:
            points, endpoints = (), (curve.point,)
        for point in (*points, *endpoints):
            if abs(point.distance_to(station2) - NEAR_RADIUS_M) <= 2e-7:
                cuts.append(_bearing(station2, point))
    cuts = _unique_scalars(cuts, tolerance=1e-12)
    result: list[_ClippedPiece] = []
    for start, end in zip(cuts, cuts[1:]):
        if end <= start:
            continue
        midpoint_angle = 0.5 * (start + end)
        point = station2 + Point2(math.cos(midpoint_angle), math.sin(midpoint_angle)).scaled(
            NEAR_RADIUS_M
        )
        if a1.closure_contains(point, tol_m=2e-8):
            result.append(
                _ClippedPiece(
                    CircularArc(station2, NEAR_RADIUS_M, start, end),
                    source_piece_index,
                    "near_circle",
                    "active_near_arc",
                    True,
                )
            )
    return tuple(result)


def _curve_angular_image(
    piece: _ClippedPiece, station2: Point2
) -> tuple[CircularIntervalUnion, tuple[tuple[Point2, float, _ClippedPiece, str], ...]]:
    curve = piece.curve
    if isinstance(curve, BoundaryPoint):
        angle = _bearing(station2, curve.point)
        return CircularIntervalUnion.from_intervals(((angle, angle),)), (
            (curve.point, angle, piece, "point"),
        )
    if piece.is_near_arc and isinstance(curve, CircularArc):
        union = CircularIntervalUnion.from_intervals(((curve.start_angle_rad, curve.end_angle_rad),))
        candidates = tuple(
            (point, _bearing(station2, point), piece, "near_arc_endpoint")
            for point in curve.endpoints
        )
        return union, candidates

    points: list[tuple[float, Point2, str]] = [(0.0, curve.point_at(0.0), "endpoint"), (1.0, curve.point_at(1.0), "endpoint")]
    if isinstance(curve, CircularArc):
        for point in _arc_tangent_points(curve, station2):
            points.append((_arc_fraction(curve, point), point, "tangent"))
    points.sort(key=lambda value: value[0])
    union = CircularIntervalUnion.empty()
    for left, right in zip(points, points[1:]):
        middle = curve.point_at(0.5 * (left[0] + right[0]))
        angles = [_bearing(station2, left[1]), _bearing(station2, middle), _bearing(station2, right[1])]
        angles[1] = _unwrap_near(angles[1], angles[0])
        angles[2] = _unwrap_near(angles[2], angles[1])
        union = union.union(CircularIntervalUnion.from_intervals(((min(angles[0], angles[2]), max(angles[0], angles[2])),)))
    candidates = tuple((point, _bearing(station2, point), piece, kind) for _, point, kind in points)
    return union, candidates


def _curve_endpoints(curve: LineSegment | CircularArc | BoundaryPoint) -> tuple[Point2, ...]:
    if isinstance(curve, BoundaryPoint):
        return (curve.point,)
    if isinstance(curve, LineSegment):
        return curve.start, curve.end
    return curve.endpoints


def _arc_fraction(arc: CircularArc, point: Point2) -> float:
    angle = (point - arc.center).angle_rad()
    candidates = [angle + shift for shift in (-math.tau, 0.0, math.tau)]
    unwrapped = min(candidates, key=lambda value: abs(value - 0.5 * (arc.start_angle_rad + arc.end_angle_rad)))
    return min(1.0, max(0.0, (unwrapped - arc.start_angle_rad) / arc.angle_span_rad))


def _unique_scalars(values: list[float], tolerance: float = 1e-12) -> list[float]:
    ordered = sorted(values)
    result: list[float] = []
    for value in ordered:
        if not result or value - result[-1] > tolerance:
            result.append(value)
    return result


def _unwrap_near(angle: float, reference: float) -> float:
    return min((angle - math.tau, angle, angle + math.tau), key=lambda value: abs(value - reference))


def _is_union_endpoint(union: CircularIntervalUnion, angle: float) -> bool:
    normalized = angle % math.tau
    return any(
        abs(normalized - interval.start_rad) <= 2e-10
        or abs(normalized - (interval.end_rad % math.tau)) <= 2e-10
        for interval in union.intervals
    )


def _empty_result(*, all_near: bool, event: str) -> AngularImageResult:
    empty = CircularIntervalUnion.empty()
    return AngularImageResult(
        all_near=all_near,
        spatial_component_count=0,
        raw_component_intervals=(),
        merged_closure=empty,
        expanded_closure=empty,
        full_circle=False,
        extrema_witnesses=(),
        boundary_events=(),
    )
