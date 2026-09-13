"""Independent dense verification chain for Q2 Gate B Crec.

This module intentionally does not import geometry.crec, call is_in_crec, or
read CrecWitnessRegistry.  It evaluates the frozen unreduced target objective
directly from the first observation and Omega geometry.
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
from ..geometry.primitives import Point2


@dataclass(frozen=True)
class CrecVerification:
    passed: bool
    sampled_target_count: int
    representative_max_violation_m: float
    dense_radial_max_violation_m: float
    analytic_max_violation_m: float
    analytic_minus_dense_m: float
    dense_active_target: Point2
    failures: tuple[str, ...]


def verify_crec(
    a1: A1Region,
    second_station: Point2,
    *,
    analytic_max_violation_m: float,
    analytic_in_crec: bool,
    angle_samples: int = 721,
    radial_samples: int = 257,
    tolerance_m: float = 2e-6,
) -> CrecVerification:
    """Run representative-target and independent dense-radial oracles."""
    if angle_samples < 3 or radial_samples < 3:
        raise ValueError("Verifier B needs at least three angular and radial samples.")
    if a1.dimension == A1Dimension.EMPTY:
        raise ValueError("Verifier B rejects EMPTY A1 as invalid first-observation geometry.")

    representative = _representative_targets(
        a1, angle_samples=angle_samples, radial_samples=min(radial_samples, 33)
    )
    if not representative:
        raise ValueError("Independent representative oracle found no A1 targets.")
    representative_values = [
        _direct_violation(second_station, target, a1.observation.station)
        for target in representative
    ]
    representative_max = max(representative_values)

    dense_max, dense_target, dense_count = _independent_dense_radial_max(
        a1,
        second_station,
        angle_samples=angle_samples,
        radial_samples=radial_samples,
    )
    failures: list[str] = []
    if analytic_in_crec:
        for index, value in enumerate(representative_values):
            if value > tolerance_m:
                failures.append(
                    f"analytic PASS violated by representative A1 target {index}: {value:.12g} m"
                )
                break
    if analytic_max_violation_m < dense_max - tolerance_m:
        failures.append(
            "analytic Phi underestimates independent dense Phi: "
            f"analytic={analytic_max_violation_m:.12g}, dense={dense_max:.12g}"
        )
    return CrecVerification(
        passed=not failures,
        sampled_target_count=max(len(representative), dense_count),
        representative_max_violation_m=representative_max,
        dense_radial_max_violation_m=dense_max,
        analytic_max_violation_m=analytic_max_violation_m,
        analytic_minus_dense_m=analytic_max_violation_m - dense_max,
        dense_active_target=dense_target,
        failures=tuple(failures),
    )


def _representative_targets(
    a1: A1Region, *, angle_samples: int, radial_samples: int
) -> tuple[Point2, ...]:
    if a1.dimension == A1Dimension.POINT:
        return _independent_singleton_targets(a1)
    lower, upper = a1.observation.wedge_limits_rad
    targets: list[Point2] = []
    seen: set[Point2] = set()
    for angle_index in range(angle_samples):
        angle = lower + (upper - lower) * angle_index / (angle_samples - 1)
        radial = _independent_radial_interval(a1, angle)
        if radial is None:
            continue
        lo, hi = radial
        radii = [lo, hi, 0.5 * (lo + hi)]
        if lo <= 1000.0 <= hi:
            radii.append(1000.0)
        for radial_index in range(radial_samples):
            radii.append(lo + (hi - lo) * radial_index / (radial_samples - 1))
        for radius in radii:
            point = _point_on_ray(a1.observation.station, angle, radius)
            if point not in seen:
                seen.add(point)
                targets.append(point)
    return tuple(targets)


def _independent_dense_radial_max(
    a1: A1Region,
    second_station: Point2,
    *,
    angle_samples: int,
    radial_samples: int,
) -> tuple[float, Point2, int]:
    if a1.dimension == A1Dimension.POINT:
        targets = _independent_singleton_targets(a1)
        if not targets:
            raise ValueError("Independent dense oracle could not recover POINT A1.")
        active = max(
            targets,
            key=lambda target: _direct_violation(
                second_station, target, a1.observation.station
            ),
        )
        return (
            _direct_violation(second_station, active, a1.observation.station),
            active,
            len(targets),
        )

    lower, upper = a1.observation.wedge_limits_rad
    maximum = -math.inf
    active: Point2 | None = None
    checked = 0
    for angle_index in range(angle_samples):
        angle = lower + (upper - lower) * angle_index / (angle_samples - 1)
        radial = _independent_radial_interval(a1, angle)
        if radial is None:
            continue
        lo, hi = radial
        radii = [lo + (hi - lo) * index / (radial_samples - 1) for index in range(radial_samples)]
        if lo < 1000.0 < hi:
            radii.append(1000.0)
        for radius in radii:
            target = _point_on_ray(a1.observation.station, angle, radius)
            value = _direct_violation(second_station, target, a1.observation.station)
            checked += 1
            if value > maximum:
                maximum = value
                active = target
    if active is None:
        raise ValueError("Independent dense radial oracle found no A1 target.")
    return maximum, active, checked


def _independent_singleton_targets(a1: A1Region) -> tuple[Point2, ...]:
    lower, upper = a1.observation.wedge_limits_rad
    targets: list[Point2] = []
    candidate_angles = [lower, upper]
    center_delta = a1.omega_center - a1.observation.station
    center_distance = center_delta.norm()
    if center_distance > a1.omega_radius_m + 1e-9:
        center_angle = center_delta.angle_rad()
        tangent_offset = math.asin(min(1.0, a1.omega_radius_m / center_distance))
        candidate_angles.extend(
            (center_angle - tangent_offset, center_angle + tangent_offset)
        )

    for angle in candidate_angles:
        radial = _independent_radial_interval(a1, angle)
        if radial is None:
            continue
        lo, hi = radial
        if hi - lo <= 2e-7 and lo > INNER_RADIUS_M + 1e-9:
            point = _point_on_ray(a1.observation.station, angle, 0.5 * (lo + hi))
            if _independent_a1_contains(a1, point):
                _append_unique(targets, point)

    for point in _circle_circle_intersections(
        a1.observation.station,
        OUTER_RADIUS_M,
        a1.omega_center,
        a1.omega_radius_m,
    ):
        if _independent_a1_contains(a1, point):
            _append_unique(targets, point)
    return tuple(targets)


def _circle_circle_intersections(
    c0: Point2, r0: float, c1: Point2, r1: float
) -> tuple[Point2, ...]:
    delta = c1 - c0
    distance = delta.norm()
    if distance <= 1e-9:
        return ()
    if distance > r0 + r1 + 1e-9 or distance < abs(r0 - r1) - 1e-9:
        return ()
    along = (r0 * r0 - r1 * r1 + distance * distance) / (2.0 * distance)
    height_squared = r0 * r0 - along * along
    if height_squared < -1e-9:
        return ()
    height = math.sqrt(max(0.0, height_squared))
    axis = delta.scaled(1.0 / distance)
    base = c0 + axis.scaled(along)
    normal = Point2(-axis.y, axis.x)
    first = base + normal.scaled(height)
    if height <= 1e-9:
        return (first,)
    return first, base - normal.scaled(height)


def _independent_radial_interval(
    a1: A1Region, angle: float
) -> tuple[float, float] | None:
    direction = Point2(math.cos(angle), math.sin(angle))
    delta = a1.observation.station - a1.omega_center
    projection = delta.dot(direction)
    discriminant = projection * projection - (
        delta.dot(delta) - a1.omega_radius_m * a1.omega_radius_m
    )
    if discriminant < -1e-9:
        return None
    root = math.sqrt(max(0.0, discriminant))
    lo = max(INNER_RADIUS_M, -projection - root)
    hi = min(OUTER_RADIUS_M, -projection + root)
    if hi < lo - 1e-9:
        return None
    return lo, hi


def _independent_closure_contains(a1: A1Region, point: Point2) -> bool:
    displacement = point - a1.observation.station
    rho = displacement.norm()
    if rho < INNER_RADIUS_M - 2e-7 or rho > OUTER_RADIUS_M + 2e-7:
        return False
    if point.distance_to(a1.omega_center) > a1.omega_radius_m + 2e-7:
        return False
    bearing = displacement.angle_rad()
    center = a1.observation.center_angle_rad
    distance = abs((bearing - center + math.pi) % math.tau - math.pi)
    return distance <= a1.observation.epsilon_rad + 1e-11


def _independent_a1_contains(a1: A1Region, point: Point2) -> bool:
    displacement = point - a1.observation.station
    rho = displacement.norm()
    if rho <= INNER_RADIUS_M + 1e-9 or rho > OUTER_RADIUS_M + 2e-7:
        return False
    if point.distance_to(a1.omega_center) > a1.omega_radius_m + 2e-7:
        return False
    bearing = displacement.angle_rad()
    center = a1.observation.center_angle_rad
    distance = abs((bearing - center + math.pi) % math.tau - math.pi)
    return distance <= a1.observation.epsilon_rad + 1e-11


def _direct_violation(
    second_station: Point2, target: Point2, first_station: Point2
) -> float:
    return second_station.distance_to(target) - max(
        1000.0, target.distance_to(first_station)
    )


def _point_on_ray(station: Point2, angle: float, radius: float) -> Point2:
    return station + Point2(math.cos(angle), math.sin(angle)).scaled(radius)


def _append_unique(points: list[Point2], point: Point2) -> None:
    if all(point.distance_to(existing) > 1e-7 for existing in points):
        points.append(point)
