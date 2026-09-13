"""Independent dense verifier for Gate C closed angular sets.

The two oracles sample registered physical boundaries and independently
reconstruct radial interiors.  This module deliberately does not import the
production solver or the reception-witness registry.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from ..geometry.a1 import (
    A1Dimension,
    A1Region,
    INNER_RADIUS_M,
    OUTER_RADIUS_M,
)
from ..geometry.circular_intervals import CircularIntervalUnion
from ..geometry.primitives import BoundaryPoint, CircularArc, LineSegment, Point2


NEAR_RADIUS_M = 5.0


@dataclass(frozen=True)
class AngularVerificationReport:
    passed: bool
    boundary_points_checked: int
    radial_points_checked: int
    expanded_error_checks: int
    max_missing_angle_rad: float
    max_endpoint_disagreement_rad: float
    failures: tuple[str, ...]


def verify_angular_image(
    a1: A1Region,
    station2: Point2,
    merged_closure: CircularIntervalUnion,
    expanded_closure: CircularIntervalUnion,
    all_near: bool,
    *,
    boundary_samples_per_piece: int = 101,
    radial_angle_samples: int = 101,
    radial_samples_per_angle: int = 31,
) -> AngularVerificationReport:
    if boundary_samples_per_piece < 3 or radial_angle_samples < 3 or radial_samples_per_angle < 3:
        raise ValueError("Verifier C sample counts must each be at least three.")

    failures: list[str] = []
    missing: list[float] = []
    truth_angles: list[float] = []
    boundary_count = 0
    radial_count = 0
    error_count = 0

    def check(point: Point2, source: str) -> None:
        nonlocal boundary_count, radial_count, error_count
        distance = point.distance_to(station2)
        if distance <= NEAR_RADIUS_M:
            return
        angle = math.atan2(point.y - station2.y, point.x - station2.x)
        truth_angles.append(angle % math.tau)
        if source == "boundary":
            boundary_count += 1
        else:
            radial_count += 1
        if all_near:
            failures.append(f"all_near contradicted by {source} sample")
        if not merged_closure.contains(angle, tolerance_rad=2e-10):
            gap = merged_closure.distance_to_angle(angle)
            missing.append(gap)
            failures.append(f"raw closure misses {source} bearing by {gap:.3e} rad")
        epsilon = math.radians(1.0)
        for error in (-epsilon, 0.0, epsilon):
            error_count += 1
            shifted = angle + error
            if not expanded_closure.contains(shifted, tolerance_rad=2e-10):
                gap = expanded_closure.distance_to_angle(shifted)
                missing.append(gap)
                failures.append(f"expanded closure misses error-shifted bearing by {gap:.3e} rad")

    # Oracle C1: sample only the physical A1 registry.
    for piece in a1.boundary.pieces:
        curve = piece.curve
        if isinstance(curve, BoundaryPoint):
            check(curve.point, "boundary")
            continue
        for index in range(boundary_samples_per_piece):
            check(curve.point_at(index / (boundary_samples_per_piece - 1)), "boundary")

    # Independently sample active portions of the newly introduced near circle.
    # The circle itself produces `near`, but directions approached from its
    # strict exterior belong to the worst-case bearing closure.
    for index in range(720):
        angle = math.tau * index / 720
        direction = Point2(math.cos(angle), math.sin(angle))
        outside = station2 + direction.scaled(NEAR_RADIUS_M + 1e-6)
        if _independent_point_in_a1(a1, outside):
            boundary_count += 1
            truth_angles.append(angle)
            if not merged_closure.contains(angle, tolerance_rad=2e-10):
                gap = merged_closure.distance_to_angle(angle)
                missing.append(gap)
                failures.append(f"raw closure misses active near-circle bearing by {gap:.3e} rad")
            for error in (-math.radians(1.0), 0.0, math.radians(1.0)):
                error_count += 1
                if not expanded_closure.contains(angle + error, tolerance_rad=2e-10):
                    gap = expanded_closure.distance_to_angle(angle + error)
                    missing.append(gap)
                    failures.append(
                        f"expanded closure misses near-circle error bearing by {gap:.3e} rad"
                    )

    # Oracle C2: derive Omega/radial intersections directly and sample interiors.
    lower, upper = a1.observation.wedge_limits_rad
    for angle_index in range(radial_angle_samples):
        theta = lower + (upper - lower) * angle_index / (radial_angle_samples - 1)
        radial = _independent_radial_interval(a1, theta)
        if radial is None:
            continue
        lo, hi = radial
        if hi <= max(lo, INNER_RADIUS_M) + 1e-9:
            continue
        lo = max(lo, INNER_RADIUS_M)
        direction = Point2(math.cos(theta), math.sin(theta))
        for radial_index in range(radial_samples_per_angle):
            fraction = (radial_index + 0.5) / radial_samples_per_angle
            rho = lo + fraction * (hi - lo)
            point = a1.observation.station + direction.scaled(rho)
            check(point, "radial")

    has_actual_sample = boundary_count + radial_count > 0
    if a1.dimension == A1Dimension.EMPTY and (
        not merged_closure.is_empty or not expanded_closure.is_empty or all_near
    ):
        failures.append("EMPTY A1 must have empty closures and is not all_near")
    if a1.dimension != A1Dimension.EMPTY and not has_actual_sample and not all_near:
        failures.append("nonempty A1 produced no verifier samples without all_near")
    if has_actual_sample and merged_closure.is_empty:
        failures.append("nonempty sampled direction set was reported empty")
    if all_near and (not merged_closure.is_empty or not expanded_closure.is_empty):
        failures.append("all_near must have empty raw and expanded closures")

    expected_expanded = merged_closure.dilated(math.radians(1.0))
    if expected_expanded != expanded_closure:
        failures.append("expanded closure is not exactly the frozen one-degree dilation")
    independent_truth = _independent_truth_union(a1, station2)
    if _closed_unions_disagree(merged_closure, independent_truth):
        failures.append("claimed raw closure differs from independent critical-cell oracle")
    if _closed_unions_disagree(
        expanded_closure, independent_truth.dilated(math.radians(1.0))
    ):
        failures.append("claimed expanded closure differs from independent one-degree oracle")
    if all_near != (a1.dimension != A1Dimension.EMPTY and independent_truth.is_empty):
        failures.append("all_near disagrees with independent critical-cell oracle")
    endpoint_disagreements = _endpoint_disagreements_against_truth(
        merged_closure, independent_truth
    )

    return AngularVerificationReport(
        passed=not failures,
        boundary_points_checked=boundary_count,
        radial_points_checked=radial_count,
        expanded_error_checks=error_count,
        max_missing_angle_rad=max(missing, default=0.0),
        max_endpoint_disagreement_rad=max(endpoint_disagreements, default=0.0),
        failures=tuple(dict.fromkeys(failures)),
    )


def _independent_radial_interval(a1: A1Region, theta: float) -> tuple[float, float] | None:
    direction = Point2(math.cos(theta), math.sin(theta))
    displacement = a1.observation.station - a1.omega_center
    projection = displacement.dot(direction)
    discriminant = projection**2 - (displacement.dot(displacement) - a1.omega_radius_m**2)
    if discriminant < -1e-8:
        return None
    root = math.sqrt(max(0.0, discriminant))
    lo = max(INNER_RADIUS_M, -projection - root)
    hi = min(OUTER_RADIUS_M, -projection + root)
    return None if hi < lo - 1e-9 else (lo, hi)


def _independent_ray_has_actual_target(a1: A1Region, station2: Point2, angle: float) -> bool:
    if a1.dimension == A1Dimension.EMPTY:
        return False
    if a1.dimension == A1Dimension.POINT:
        return any(
            piece.curve.point.distance_to(station2) > NEAR_RADIUS_M
            and _circular_distance(
                math.atan2(piece.curve.point.y - station2.y, piece.curve.point.x - station2.x),
                angle,
            ) < 2e-10
            for piece in a1.boundary.point_pieces
        )

    direction = Point2(math.cos(angle), math.sin(angle))
    lo, hi = NEAR_RADIUS_M, math.inf
    for center, radius in (
        (a1.omega_center, a1.omega_radius_m),
        (a1.observation.station, OUTER_RADIUS_M),
    ):
        delta = station2 - center
        projection = delta.dot(direction)
        discriminant = projection**2 - (delta.dot(delta) - radius**2)
        if discriminant < -1e-9:
            return False
        root = math.sqrt(max(0.0, discriminant))
        lo = max(lo, -projection - root)
        hi = min(hi, -projection + root)
        if hi <= lo:
            return False

    relative = station2 - a1.observation.station
    lower, upper = a1.observation.wedge_limits_rad
    for boundary, want_positive in ((lower, True), (upper, False)):
        edge = Point2(math.cos(boundary), math.sin(boundary))
        offset = edge.x * relative.y - edge.y * relative.x
        slope = edge.x * direction.y - edge.y * direction.x
        sign = 1.0 if want_positive else -1.0
        offset, slope = sign * offset, sign * slope
        if abs(slope) <= 1e-14:
            if offset < -1e-9:
                return False
        else:
            root = -offset / slope
            if slope > 0.0:
                lo = max(lo, root)
            else:
                hi = min(hi, root)
        if hi <= lo:
            return False

    return max(
        (station2 + direction.scaled(t)).distance_to(a1.observation.station)
        for t in (lo, hi)
    ) > INNER_RADIUS_M


def _circular_distance(left: float, right: float) -> float:
    return abs((left - right + math.pi) % math.tau - math.pi)


def _independent_point_in_a1(a1: A1Region, point: Point2) -> bool:
    relative = point - a1.observation.station
    rho = relative.norm()
    if not (rho > INNER_RADIUS_M and rho <= OUTER_RADIUS_M):
        return False
    if point.distance_to(a1.omega_center) > a1.omega_radius_m:
        return False
    difference = _circular_distance(relative.angle_rad(), a1.observation.center_angle_rad)
    return difference <= a1.observation.epsilon_rad + 2e-13


def _endpoint_disagreements(
    a1: A1Region, station2: Point2, claimed: CircularIntervalUnion
) -> tuple[float, ...]:
    if claimed.is_empty or claimed.is_full:
        return ()
    result: list[float] = []
    endpoints = [
        endpoint % math.tau
        for interval in claimed.intervals
        for endpoint in (interval.start_rad, interval.end_rad)
    ]
    for endpoint in endpoints:
        step = 1e-6
        left = endpoint - step
        right = endpoint + step
        left_state = _independent_ray_has_actual_target(a1, station2, left)
        right_state = _independent_ray_has_actual_target(a1, station2, right)
        if left_state == right_state:
            continue
        false_side, true_side = (left, right) if not left_state else (right, left)
        for _ in range(48):
            middle = 0.5 * (false_side + true_side)
            if _independent_ray_has_actual_target(a1, station2, middle):
                true_side = middle
            else:
                false_side = middle
        recovered = 0.5 * (false_side + true_side)
        result.append(_circular_distance(endpoint, recovered))
    return tuple(result)


def _independent_truth_union(a1: A1Region, station2: Point2) -> CircularIntervalUnion:
    if a1.dimension == A1Dimension.EMPTY:
        return CircularIntervalUnion.empty()
    if a1.dimension == A1Dimension.POINT:
        return CircularIntervalUnion.from_intervals(
            (
                (angle, angle)
                for piece in a1.boundary.point_pieces
                if piece.curve.point.distance_to(station2) > NEAR_RADIUS_M
                for angle in (
                    math.atan2(
                        piece.curve.point.y - station2.y,
                        piece.curve.point.x - station2.x,
                    )
                    % math.tau,
                )
            )
        )

    cuts = _independent_critical_angles(a1, station2)
    unwrapped = [*cuts, cuts[0] + math.tau]
    result = CircularIntervalUnion.empty()
    for start, end in zip(unwrapped, unwrapped[1:]):
        if _independent_ray_has_actual_target(a1, station2, 0.5 * (start + end)):
            result = result.union(CircularIntervalUnion.from_intervals(((start, end),)))
    for angle in cuts:
        if _independent_ray_has_actual_target(a1, station2, angle) or any(
            _independent_ray_has_actual_target(a1, station2, angle + offset)
            for offset in (-1e-10, 1e-10)
        ):
            result = result.union(CircularIntervalUnion.from_intervals(((angle, angle),)))
    return result


def _independent_critical_angles(a1: A1Region, station2: Point2) -> tuple[float, ...]:
    angles = [0.0]
    for piece in a1.boundary.pieces:
        curve = piece.curve
        if isinstance(curve, BoundaryPoint):
            points = [curve.point]
        elif isinstance(curve, LineSegment):
            points = [curve.start, curve.end]
            points.extend(_independent_segment_circle_points(curve, station2, NEAR_RADIUS_M))
        else:
            points = [*curve.endpoints]
            points.extend(_independent_arc_tangencies(curve, station2))
            points.extend(_independent_arc_circle_points(curve, station2, NEAR_RADIUS_M))
        for point in points:
            if point.distance_to(station2) > 1e-12:
                angles.append(
                    math.atan2(point.y - station2.y, point.x - station2.x) % math.tau
                )
    angles.sort()
    unique: list[float] = []
    for angle in angles:
        if not unique or angle - unique[-1] > 1e-13:
            unique.append(angle)
    return tuple(unique)


def _independent_segment_circle_points(
    segment: LineSegment, center: Point2, radius: float
) -> tuple[Point2, ...]:
    direction = segment.end - segment.start
    relative = segment.start - center
    length_sq = direction.dot(direction)
    projection = -relative.dot(direction) / length_sq
    closest = segment.start + direction.scaled(projection)
    height_sq_m = radius**2 - closest.distance_to(center) ** 2
    if height_sq_m < 0.0:
        return ()
    if height_sq_m == 0.0:
        params = (projection,)
    else:
        offset = math.sqrt(height_sq_m / length_sq)
        params = (projection - offset, projection + offset)
    return tuple(segment.point_at(min(1.0, max(0.0, value))) for value in params if 0.0 <= value <= 1.0)


def _independent_arc_circle_points(
    arc: CircularArc, center: Point2, radius: float
) -> tuple[Point2, ...]:
    delta = center - arc.center
    distance = delta.norm()
    if distance <= 1e-12 or distance > arc.radius + radius + 1e-9:
        return ()
    if distance < abs(arc.radius - radius) - 1e-9:
        return ()
    along = (arc.radius**2 - radius**2 + distance**2) / (2.0 * distance)
    height_sq = arc.radius**2 - along**2
    if height_sq < -1e-9:
        return ()
    axis = delta.scaled(1.0 / distance)
    base = arc.center + axis.scaled(along)
    normal = Point2(-axis.y, axis.x)
    height = math.sqrt(max(0.0, height_sq))
    candidates = (base + normal.scaled(height), base - normal.scaled(height))
    return tuple(point for point in candidates if _independent_point_on_arc(arc, point))


def _independent_arc_tangencies(arc: CircularArc, observer: Point2) -> tuple[Point2, ...]:
    delta = observer - arc.center
    distance = delta.norm()
    if distance <= arc.radius:
        return ()
    unit = delta.scaled(1.0 / distance)
    base = arc.center + unit.scaled(arc.radius**2 / distance)
    perpendicular = Point2(-unit.y, unit.x)
    height = arc.radius * math.sqrt(1.0 - (arc.radius / distance) ** 2)
    candidates = (base + perpendicular.scaled(height), base - perpendicular.scaled(height))
    return tuple(point for point in candidates if _independent_point_on_arc(arc, point))


def _independent_point_on_arc(arc: CircularArc, point: Point2) -> bool:
    angle = (point - arc.center).angle_rad()
    return any(
        arc.start_angle_rad - 2e-12 <= angle + shift <= arc.end_angle_rad + 2e-12
        for shift in (-math.tau, 0.0, math.tau)
    )


def _closed_unions_disagree(
    left: CircularIntervalUnion, right: CircularIntervalUnion
) -> bool:
    cuts = [0.0, math.tau]
    for union in (left, right):
        cuts.extend(
            endpoint
            for interval in union.intervals
            for endpoint in (interval.start_rad, interval.end_rad)
        )
    cuts = sorted(set(cuts))
    probes = [*cuts, *(0.5 * (start + end) for start, end in zip(cuts, cuts[1:]))]
    return any(
        left.contains(angle, tolerance_rad=0.0)
        != right.contains(angle, tolerance_rad=0.0)
        for angle in probes
    )


def _endpoint_disagreements_against_truth(
    claimed: CircularIntervalUnion, truth: CircularIntervalUnion
) -> tuple[float, ...]:
    if claimed.is_empty and truth.is_empty or claimed.is_full and truth.is_full:
        return ()
    claimed_endpoints = [
        endpoint % math.tau
        for interval in claimed.intervals
        for endpoint in (interval.start_rad, interval.end_rad)
    ]
    truth_endpoints = [
        endpoint % math.tau
        for interval in truth.intervals
        for endpoint in (interval.start_rad, interval.end_rad)
    ]
    if not claimed_endpoints or not truth_endpoints:
        return (math.pi,)
    return tuple(
        min(_circular_distance(endpoint, truth_endpoint) for truth_endpoint in truth_endpoints)
        for endpoint in claimed_endpoints
    )
