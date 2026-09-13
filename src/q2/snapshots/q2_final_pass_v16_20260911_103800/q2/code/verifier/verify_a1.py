"""Independent boundary-sampling verifier for the frozen A1 geometry."""

from __future__ import annotations

from dataclasses import dataclass
import math

from ..geometry.a1 import (
    A1BoundaryLabel,
    A1Region,
    INNER_RADIUS_M,
    OUTER_RADIUS_M,
)
from ..geometry.primitives import BoundaryPoint, CircularArc, LineSegment, Point2


@dataclass(frozen=True)
class A1BoundaryVerification:
    passed: bool
    checked_points: int
    completeness_checked: bool
    failures: tuple[str, ...]


def verify_a1_boundary(
    a1: A1Region, *, samples_per_piece: int = 17, tolerance_m: float = 2e-7
) -> A1BoundaryVerification:
    """Sample every registered boundary piece against an independently derived predicate."""
    if samples_per_piece < 2:
        raise ValueError("samples_per_piece must be at least two.")

    failures: list[str] = []
    checked = 0
    for index, piece in enumerate(a1.boundary.pieces):
        _check_piece_label_geometry(piece.label, piece.curve, a1, index, failures, tolerance_m)
        for sample in range(samples_per_piece):
            point = piece.curve.point_at(sample / (samples_per_piece - 1))
            checked += 1
            if not _independent_closure_contains(a1, point, tolerance_m):
                failures.append(
                    f"piece={index} label={piece.label.value} sample={sample} violates closure(A1)"
                )
    completeness_checked, completeness_failures = _independent_completeness_check(
        a1, tolerance_m
    )
    failures.extend(completeness_failures)
    if a1.dimension.value >= 0 and checked == 0:
        failures.append("nonempty A1 has no registered boundary samples")
    if a1.dimension.value < 0:
        failures.append("EMPTY A1 requires a separate independent emptiness proof")
    return A1BoundaryVerification(
        not failures, checked, completeness_checked, tuple(failures)
    )


def _independent_closure_contains(a1: A1Region, point: Point2, tolerance_m: float) -> bool:
    """Directly evaluate the frozen inequalities without calling A1Region predicates."""
    delta = point - a1.observation.station
    rho = math.hypot(delta.x, delta.y)
    if rho < INNER_RADIUS_M - tolerance_m or rho > OUTER_RADIUS_M + tolerance_m:
        return False
    if math.hypot(point.x - a1.omega_center.x, point.y - a1.omega_center.y) > (
        a1.omega_radius_m + tolerance_m
    ):
        return False
    bearing = math.atan2(delta.y, delta.x)
    center = math.radians(a1.observation.bearing_deg % 360.0)
    angle_distance = abs((bearing - center + math.pi) % math.tau - math.pi)
    return angle_distance <= math.radians(a1.observation.epsilon_deg) + 1e-11


def _check_piece_label_geometry(
    label: A1BoundaryLabel,
    curve: LineSegment | CircularArc | BoundaryPoint,
    a1: A1Region,
    index: int,
    failures: list[str],
    tolerance_m: float,
) -> None:
    if label == A1BoundaryLabel.DEGENERATE_POINT:
        if not isinstance(curve, BoundaryPoint):
            failures.append(f"piece={index} degenerate boundary is not a BoundaryPoint")
        return
    if label in {A1BoundaryLabel.WEDGE_LOWER, A1BoundaryLabel.WEDGE_UPPER}:
        if not isinstance(curve, LineSegment):
            failures.append(f"piece={index} {label.value} is not a line segment")
            return
        expected = a1.observation.wedge_limits_rad[
            0 if label == A1BoundaryLabel.WEDGE_LOWER else 1
        ]
        direction = curve.end - curve.start
        actual = math.atan2(direction.y, direction.x)
        if abs((actual - expected + math.pi) % math.tau - math.pi) > 1e-10:
            failures.append(f"piece={index} {label.value} is not on its first-wedge side")
        return

    if not isinstance(curve, CircularArc):
        failures.append(f"piece={index} {label.value} is not a circular arc")
        return
    if label == A1BoundaryLabel.RHO_INNER and not math.isclose(
        curve.radius, INNER_RADIUS_M, abs_tol=tolerance_m
    ):
        failures.append(f"piece={index} inner arc does not have rho=5")
    elif label == A1BoundaryLabel.RHO_OUTER and not math.isclose(
        curve.radius, OUTER_RADIUS_M, abs_tol=tolerance_m
    ):
        failures.append(f"piece={index} outer arc does not have rho=1500")
    elif label == A1BoundaryLabel.OMEGA:
        if curve.center.distance_to(a1.omega_center) > tolerance_m or not math.isclose(
            curve.radius, a1.omega_radius_m, abs_tol=tolerance_m
        ):
            failures.append(f"piece={index} omega arc does not coincide with dOmega")


def _independent_completeness_check(
    a1: A1Region, tolerance_m: float
) -> tuple[bool, list[str]]:
    """Reverse-check independently derived ray-boundary samples against the registry.

    This deliberately does not call A1's active-boundary constructors.  It is a
    dense deterministic oracle rather than a certificate for all real points;
    it includes both wedge endpoints, so tangent singleton cases are mandatory
    coverage targets rather than a measure-zero blind spot.
    """
    if a1.dimension.value < 0:
        return False, []

    lower, upper = a1.observation.wedge_limits_rad
    failures: list[str] = []
    expected = 0
    for index in range(101):
        angle = lower + (upper - lower) * index / 100.0
        radial = _independent_radial_interval(a1, angle, tolerance_m)
        if radial is None:
            continue
        lo, hi = radial
        if hi - lo <= tolerance_m:
            point = _independent_point_on_ray(a1.observation.station, angle, lo)
            if _independent_strict_contains(a1, point, tolerance_m):
                expected += 1
                if not _covered_by_registered_boundary(a1, point, tolerance_m):
                    failures.append(f"unregistered singleton boundary sample at ray={index}")
            continue

        for radius in (lo, hi):
            point = _independent_point_on_ray(a1.observation.station, angle, radius)
            expected += 1
            if not _covered_by_registered_boundary(a1, point, tolerance_m):
                failures.append(f"unregistered radial boundary sample at ray={index}")
        if index in {0, 100}:
            point = _independent_point_on_ray(a1.observation.station, angle, 0.5 * (lo + hi))
            expected += 1
            if not _covered_by_registered_boundary(a1, point, tolerance_m):
                failures.append(f"unregistered wedge-side boundary sample at ray={index}")

    if expected == 0:
        failures.append("independent completeness oracle found no nonempty A1 witness")
    return True, failures


def _independent_radial_interval(
    a1: A1Region, angle: float, tolerance_m: float
) -> tuple[float, float] | None:
    ux, uy = math.cos(angle), math.sin(angle)
    dx = a1.observation.station.x - a1.omega_center.x
    dy = a1.observation.station.y - a1.omega_center.y
    projection = dx * ux + dy * uy
    discriminant = a1.omega_radius_m * a1.omega_radius_m - (dx * dx + dy * dy) + projection * projection
    if discriminant < -tolerance_m:
        return None
    root = math.sqrt(max(0.0, discriminant))
    lo = max(INNER_RADIUS_M, -projection - root)
    hi = min(OUTER_RADIUS_M, -projection + root)
    return None if hi < lo - tolerance_m else (lo, hi)


def _independent_point_on_ray(station: Point2, angle: float, radius: float) -> Point2:
    return Point2(station.x + radius * math.cos(angle), station.y + radius * math.sin(angle))


def _independent_strict_contains(a1: A1Region, point: Point2, tolerance_m: float) -> bool:
    delta = point - a1.observation.station
    rho = math.hypot(delta.x, delta.y)
    if rho <= INNER_RADIUS_M + tolerance_m or rho > OUTER_RADIUS_M + tolerance_m:
        return False
    if point.distance_to(a1.omega_center) > a1.omega_radius_m + tolerance_m:
        return False
    bearing = math.atan2(delta.y, delta.x)
    center = math.radians(a1.observation.bearing_deg % 360.0)
    return abs((bearing - center + math.pi) % math.tau - math.pi) <= math.radians(
        a1.observation.epsilon_deg
    ) + 1e-11


def _covered_by_registered_boundary(a1: A1Region, point: Point2, tolerance_m: float) -> bool:
    for piece in a1.boundary.pieces:
        curve = piece.curve
        if isinstance(curve, BoundaryPoint):
            if curve.point.distance_to(point) <= tolerance_m:
                return True
        elif isinstance(curve, LineSegment):
            if _distance_to_segment(point, curve) <= tolerance_m:
                return True
        elif isinstance(curve, CircularArc) and _point_on_arc(point, curve, tolerance_m):
            return True
    return False


def _distance_to_segment(point: Point2, segment: LineSegment) -> float:
    direction = segment.end - segment.start
    length_squared = direction.dot(direction)
    fraction = 0.0 if length_squared == 0.0 else (point - segment.start).dot(direction) / length_squared
    fraction = min(1.0, max(0.0, fraction))
    closest = segment.start + direction.scaled(fraction)
    return point.distance_to(closest)


def _point_on_arc(point: Point2, arc: CircularArc, tolerance_m: float) -> bool:
    if not math.isclose(point.distance_to(arc.center), arc.radius, abs_tol=tolerance_m):
        return False
    angle = math.atan2(point.y - arc.center.y, point.x - arc.center.x)
    for shift in (-math.tau, 0.0, math.tau):
        candidate = angle + shift
        if arc.start_angle_rad - 1e-11 <= candidate <= arc.end_angle_rad + 1e-11:
            return True
    return False
