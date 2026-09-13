"""Exact first-observation physical target set A1 and its boundary registry.

The registry belongs exclusively to the physical first-observation set and the
later near-aware angular-image calculation.  It must not be passed to Q1 or
reused as a reception-witness registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
import math
from typing import Optional

from .primitives import BoundaryPoint, CircularArc, LineSegment, Point2


EPSILON_DEG = 1.0
INNER_RADIUS_M = 5.0
OUTER_RADIUS_M = 1500.0
OMEGA_CENTER = Point2(0.0, 0.0)
OMEGA_RADIUS_M = 1800.0
GEOMETRY_TOL_M = 1e-9
GEOMETRY_TOL_RAD = 1e-12


class A1BoundaryLabel(str, Enum):
    WEDGE_LOWER = "a1_wedge_lower"
    WEDGE_UPPER = "a1_wedge_upper"
    RHO_INNER = "a1_rho_5"
    RHO_OUTER = "a1_rho_1500"
    OMEGA = "a1_omega"
    DEGENERATE_POINT = "a1_degenerate_point"


class A1Dimension(IntEnum):
    """Affine dimension of the physical A1 set, with EMPTY represented by -1."""

    EMPTY = -1
    POINT = 0
    SEGMENT = 1
    AREA = 2


class A1DimensionClassificationError(ValueError):
    """A degenerate A1 arrangement was rejected instead of being silently guessed."""


# Fail-closed interior-witness tolerances.  They are far below any representable
# problem-scale feature, so a witness is accepted only when a genuine
# two-dimensional neighbourhood of A1 is provably present.
INTERIOR_MARGIN_M = 1e-6
INTERIOR_MARGIN_RAD = 1e-9
INTERIOR_SCAN_SAMPLES = 513


@dataclass(frozen=True)
class FirstObservation:
    station: Point2
    bearing_deg: float
    epsilon_deg: float = EPSILON_DEG

    def __post_init__(self) -> None:
        if not math.isfinite(self.bearing_deg):
            raise ValueError("First bearing must be finite.")
        if not (0.0 < self.epsilon_deg < 90.0):
            raise ValueError("epsilon_deg must be in (0, 90).")

    @property
    def center_angle_rad(self) -> float:
        return math.radians(self.bearing_deg % 360.0)

    @property
    def epsilon_rad(self) -> float:
        return math.radians(self.epsilon_deg)

    @property
    def wedge_limits_rad(self) -> tuple[float, float]:
        return self.center_angle_rad - self.epsilon_rad, self.center_angle_rad + self.epsilon_rad


@dataclass(frozen=True)
class A1BoundaryPiece:
    label: A1BoundaryLabel
    curve: LineSegment | CircularArc | BoundaryPoint


@dataclass(frozen=True)
class A1BoundaryRegistry:
    """The sole active-boundary registry for A1 and angular-image geometry."""

    pieces: tuple[A1BoundaryPiece, ...]
    omega_center: Point2 = OMEGA_CENTER
    omega_radius_m: float = OMEGA_RADIUS_M

    def __post_init__(self) -> None:
        if not (math.isfinite(self.omega_radius_m) and self.omega_radius_m > 0.0):
            raise ValueError("Registry Omega radius must be finite and positive.")
        for piece in self.pieces:
            if piece.label in {A1BoundaryLabel.WEDGE_LOWER, A1BoundaryLabel.WEDGE_UPPER}:
                if not isinstance(piece.curve, LineSegment):
                    raise TypeError("A1 wedge boundaries must be line segments.")
            elif piece.label == A1BoundaryLabel.DEGENERATE_POINT:
                if not isinstance(piece.curve, BoundaryPoint):
                    raise TypeError("A1 degenerate boundary must be a BoundaryPoint.")
            else:
                if not isinstance(piece.curve, CircularArc):
                    raise TypeError("A1 radial and omega boundaries must be circular arcs.")
            if piece.label == A1BoundaryLabel.RHO_INNER and not math.isclose(
                piece.curve.radius, INNER_RADIUS_M, abs_tol=GEOMETRY_TOL_M
            ):
                raise ValueError("A1BoundaryRegistry permits only rho=5 for its inner arc.")
            if piece.label == A1BoundaryLabel.RHO_OUTER and not math.isclose(
                piece.curve.radius, OUTER_RADIUS_M, abs_tol=GEOMETRY_TOL_M
            ):
                raise ValueError("A1BoundaryRegistry permits only rho=1500 for its outer arc.")
            if isinstance(piece.curve, CircularArc) and math.isclose(
                piece.curve.radius, 1000.0, abs_tol=GEOMETRY_TOL_M
            ):
                raise ValueError("rho=1000 is not an A1 physical boundary.")
            if piece.label == A1BoundaryLabel.OMEGA and (
                piece.curve.center.distance_to(self.omega_center) > GEOMETRY_TOL_M
                or not math.isclose(
                    piece.curve.radius, self.omega_radius_m, abs_tol=GEOMETRY_TOL_M
                )
            ):
                raise ValueError("Omega arcs must match the registry Omega center and radius.")

    @property
    def line_pieces(self) -> tuple[A1BoundaryPiece, ...]:
        return tuple(piece for piece in self.pieces if isinstance(piece.curve, LineSegment))

    @property
    def arc_pieces(self) -> tuple[A1BoundaryPiece, ...]:
        return tuple(piece for piece in self.pieces if isinstance(piece.curve, CircularArc))

    @property
    def point_pieces(self) -> tuple[A1BoundaryPiece, ...]:
        return tuple(piece for piece in self.pieces if isinstance(piece.curve, BoundaryPoint))


@dataclass(frozen=True)
class A1Region:
    observation: FirstObservation
    omega_center: Point2
    omega_radius_m: float
    boundary: A1BoundaryRegistry
    dimension: A1Dimension

    def radial_interval(self, direction_angle_rad: float) -> Optional[tuple[float, float]]:
        """Closed radial interval in the closure of A1 along a wedge direction."""
        if not _angle_in_unwrapped_interval(
            direction_angle_rad, *self.observation.wedge_limits_rad
        ):
            return None
        return _radial_interval_in_omega(
            self.observation.station,
            direction_angle_rad,
            self.omega_center,
            self.omega_radius_m,
        )

    def contains(self, point: Point2, tol_m: float = GEOMETRY_TOL_M) -> bool:
        """Membership in A1 itself: the 5 m inner radius is strictly excluded."""
        displacement = point - self.observation.station
        rho = displacement.norm()
        if rho <= INNER_RADIUS_M + tol_m or rho > OUTER_RADIUS_M + tol_m:
            return False
        if point.distance_to(self.omega_center) > self.omega_radius_m + tol_m:
            return False
        return _circular_distance_rad(displacement.angle_rad(), self.observation.center_angle_rad) <= (
            self.observation.epsilon_rad + GEOMETRY_TOL_RAD
        )

    def closure_contains(self, point: Point2, tol_m: float = GEOMETRY_TOL_M) -> bool:
        """Membership in closure(A1), used for boundary-verifier checks."""
        displacement = point - self.observation.station
        rho = displacement.norm()
        if rho < INNER_RADIUS_M - tol_m or rho > OUTER_RADIUS_M + tol_m:
            return False
        if point.distance_to(self.omega_center) > self.omega_radius_m + tol_m:
            return False
        return _circular_distance_rad(displacement.angle_rad(), self.observation.center_angle_rad) <= (
            self.observation.epsilon_rad + GEOMETRY_TOL_RAD
        )


def build_a1(
    observation: FirstObservation,
    *,
    omega_center: Point2 = OMEGA_CENTER,
    omega_radius_m: float = OMEGA_RADIUS_M,
) -> A1Region:
    """Build the frozen physical A1 set and its exact active boundary pieces."""
    if not (math.isfinite(omega_radius_m) and omega_radius_m > 0.0):
        raise ValueError("Omega radius must be finite and positive.")

    lower, upper = observation.wedge_limits_rad
    pieces: list[A1BoundaryPiece] = []

    for angle, label in (
        (lower, A1BoundaryLabel.WEDGE_LOWER),
        (upper, A1BoundaryLabel.WEDGE_UPPER),
    ):
        radial = _radial_interval_in_omega(
            observation.station, angle, omega_center, omega_radius_m
        )
        if radial is not None and radial[1] - radial[0] > GEOMETRY_TOL_M:
            start = _point_on_ray(observation.station, angle, radial[0])
            end = _point_on_ray(observation.station, angle, radial[1])
            pieces.append(A1BoundaryPiece(label, LineSegment(start, end)))

    pieces.extend(
        _active_station_circle_arcs(
            observation, omega_center, omega_radius_m, INNER_RADIUS_M, A1BoundaryLabel.RHO_INNER
        )
    )
    pieces.extend(
        _active_station_circle_arcs(
            observation, omega_center, omega_radius_m, OUTER_RADIUS_M, A1BoundaryLabel.RHO_OUTER
        )
    )
    pieces.extend(_active_omega_arcs(observation, omega_center, omega_radius_m))

    if _strict_interior_witness(observation, omega_center, omega_radius_m) is not None:
        dimension = A1Dimension.AREA
    else:
        isolated = _isolated_a1_candidates(observation, omega_center, omega_radius_m)
        dimension = _degenerate_dimension(
            observation, omega_center, omega_radius_m, pieces, isolated
        )
        if dimension == A1Dimension.POINT:
            pieces = [
                A1BoundaryPiece(A1BoundaryLabel.DEGENERATE_POINT, BoundaryPoint(point))
                for point in isolated
            ]
        elif dimension == A1Dimension.EMPTY:
            pieces = []
        elif dimension == A1Dimension.SEGMENT:
            pieces = [
                piece
                for piece in pieces
                if _piece_has_positive_length(piece)
            ]

    registry = A1BoundaryRegistry(tuple(pieces), omega_center, omega_radius_m)
    return A1Region(observation, omega_center, omega_radius_m, registry, dimension)


def _strict_interior_witness(
    observation: FirstObservation,
    omega_center: Point2,
    omega_radius_m: float,
) -> Optional[Point2]:
    """Return a point provably interior to A1, or None when no witness is found.

    A witness is a full two-dimensional neighbourhood certificate: the radial
    interval must have positive width strictly inside 5 < rho < 1500, the point
    must lie strictly inside Omega, and its bearing must lie strictly inside the
    first-observation wedge.  Failure to find a witness is treated as "not
    AREA", never as an excuse to promote a degenerate arrangement to AREA.
    """
    lower, upper = observation.wedge_limits_rad
    if upper - lower <= 2.0 * INTERIOR_MARGIN_RAD:
        return None
    for angle in _interior_witness_angles(observation, omega_center, omega_radius_m):
        if not (lower + INTERIOR_MARGIN_RAD < angle < upper - INTERIOR_MARGIN_RAD):
            continue
        point = _strict_radial_witness(
            observation.station, angle, omega_center, omega_radius_m
        )
        if point is not None:
            return point
    return None


def _interior_witness_angles(
    observation: FirstObservation, omega_center: Point2, omega_radius_m: float
) -> tuple[float, ...]:
    """Analytic cell midpoints plus a dense uniform scan inside the open wedge."""
    lower, upper = observation.wedge_limits_rad
    cuts: list[float] = [lower, upper]
    for radius_m in (INNER_RADIUS_M, OUTER_RADIUS_M):
        for point in _circle_circle_intersections(
            omega_center, omega_radius_m, observation.station, radius_m
        ):
            cuts.append((point - observation.station).angle_rad())
    station_delta = observation.station - omega_center
    station_distance = station_delta.norm()
    if station_distance > omega_radius_m + GEOMETRY_TOL_M:
        # The tangent rays point from the external station *towards* the
        # circle.  ``station_delta`` points from the circle centre to the
        # station, so the ray-axis must be reversed by pi before applying the
        # tangent offset.  Omitting this reversal loses narrow positive-area
        # wedges just beyond an external tangency and can misclassify A1 as a
        # segment.
        center_angle = station_delta.angle_rad() + math.pi
        tangent_offset = math.asin(min(1.0, omega_radius_m / station_distance))
        cuts.extend((center_angle - tangent_offset, center_angle + tangent_offset))

    angles: list[float] = []
    boundaries = _unwrapped_cuts(cuts, lower, upper)
    for start, end in zip(boundaries, boundaries[1:]):
        if end - start > 2.0 * INTERIOR_MARGIN_RAD:
            angles.append(0.5 * (start + end))
    span = upper - lower
    angles.extend(
        lower + span * (index + 0.5) / INTERIOR_SCAN_SAMPLES
        for index in range(INTERIOR_SCAN_SAMPLES)
    )
    return tuple(angles)


def _strict_radial_witness(
    station: Point2,
    direction_angle_rad: float,
    omega_center: Point2,
    omega_radius_m: float,
) -> Optional[Point2]:
    direction = _unit(direction_angle_rad)
    delta = station - omega_center
    projection = delta.dot(direction)
    discriminant = projection * projection - (
        delta.dot(delta) - omega_radius_m * omega_radius_m
    )
    if discriminant <= 0.0:
        return None
    root = math.sqrt(discriminant)
    lo = max(INNER_RADIUS_M, -projection - root)
    hi = min(OUTER_RADIUS_M, -projection + root)
    if hi - lo <= 2.0 * INTERIOR_MARGIN_M:
        return None
    midpoint = 0.5 * (lo + hi)
    if not (
        INNER_RADIUS_M + INTERIOR_MARGIN_M
        < midpoint
        < OUTER_RADIUS_M - INTERIOR_MARGIN_M
    ):
        return None
    point = _point_on_ray(station, direction_angle_rad, midpoint)
    if point.distance_to(omega_center) >= omega_radius_m - INTERIOR_MARGIN_M:
        return None
    return point


def _degenerate_dimension(
    observation: FirstObservation,
    omega_center: Point2,
    omega_radius_m: float,
    pieces: list[A1BoundaryPiece],
    isolated: tuple[Point2, ...],
) -> A1Dimension:
    """Classify an A1 arrangement that has no certified interior witness.

    Positive-length boundary curves are only accepted as a genuine
    one-dimensional A1 when their own interior midpoints are themselves members
    of A1.  Any residual positive-length arrangement that cannot be certified
    raises instead of degrading silently.
    """
    genuine_one_dimensional = [
        piece
        for piece in pieces
        if _piece_has_positive_length(piece)
        and _piece_midpoint_in_a1(observation, omega_center, omega_radius_m, piece)
    ]
    if genuine_one_dimensional:
        return A1Dimension.SEGMENT
    if isolated:
        return A1Dimension.POINT
    if any(_piece_has_positive_length(piece) for piece in pieces):
        raise A1DimensionClassificationError(
            "A1 has no interior witness yet retains positive-length boundary pieces "
            "that could not be certified as members of A1; refusing to guess AREA."
        )
    return A1Dimension.EMPTY


def _piece_has_positive_length(piece: A1BoundaryPiece) -> bool:
    curve = piece.curve
    if isinstance(curve, LineSegment):
        return curve.length > GEOMETRY_TOL_M
    if isinstance(curve, CircularArc):
        return curve.angle_span_rad > GEOMETRY_TOL_RAD
    return False


def _piece_midpoint_in_a1(
    observation: FirstObservation,
    omega_center: Point2,
    omega_radius_m: float,
    piece: A1BoundaryPiece,
) -> bool:
    curve = piece.curve
    if not isinstance(curve, (LineSegment, CircularArc)):
        return False
    return _point_in_a1(
        observation, omega_center, omega_radius_m, curve.point_at(0.5)
    )


def _unit(angle_rad: float) -> Point2:
    return Point2(math.cos(angle_rad), math.sin(angle_rad))


def _point_on_ray(station: Point2, angle_rad: float, radius: float) -> Point2:
    return station + _unit(angle_rad).scaled(radius)


def _circular_distance_rad(a: float, b: float) -> float:
    return abs((a - b + math.pi) % math.tau - math.pi)


def _angle_in_unwrapped_interval(angle: float, lower: float, upper: float) -> bool:
    """Test periodic angle against a short unwrapped interval without min/max wrap bugs."""
    for shift in (-math.tau, 0.0, math.tau):
        candidate = angle + shift
        if lower - GEOMETRY_TOL_RAD <= candidate <= upper + GEOMETRY_TOL_RAD:
            return True
    return False


def _radial_interval_in_omega(
    station: Point2, direction_angle_rad: float, omega_center: Point2, omega_radius_m: float
) -> Optional[tuple[float, float]]:
    """Intersect one forward ray with Omega and the closed [5,1500] radial shell."""
    d = station - omega_center
    projection = d.dot(_unit(direction_angle_rad))
    discriminant = projection * projection - (d.dot(d) - omega_radius_m * omega_radius_m)
    if discriminant < -GEOMETRY_TOL_M:
        return None
    root = math.sqrt(max(0.0, discriminant))
    lo = max(INNER_RADIUS_M, -projection - root)
    hi = min(OUTER_RADIUS_M, -projection + root)
    if hi < lo - GEOMETRY_TOL_M:
        return None
    return lo, hi


def _unwrapped_cuts(cuts: list[float], lower: float, upper: float) -> list[float]:
    accepted = [lower, upper]
    for raw in cuts:
        base = raw % math.tau
        for shift in (-math.tau, 0.0, math.tau):
            candidate = base + shift
            if lower + GEOMETRY_TOL_RAD < candidate < upper - GEOMETRY_TOL_RAD:
                accepted.append(candidate)
    return _sorted_unique(accepted)


def _sorted_unique(values: list[float]) -> list[float]:
    values.sort()
    out: list[float] = []
    for value in values:
        if not out or value - out[-1] > GEOMETRY_TOL_RAD:
            out.append(value)
    return out


def _active_station_circle_arcs(
    observation: FirstObservation,
    omega_center: Point2,
    omega_radius_m: float,
    radius_m: float,
    label: A1BoundaryLabel,
) -> list[A1BoundaryPiece]:
    lower, upper = observation.wedge_limits_rad
    d = observation.station - omega_center
    distance = d.norm()
    cuts: list[float] = []
    if distance > GEOMETRY_TOL_M:
        cosine = (omega_radius_m * omega_radius_m - distance * distance - radius_m * radius_m) / (
            2.0 * radius_m * distance
        )
        if -1.0 < cosine < 1.0:
            offset = math.acos(cosine)
            direction = d.angle_rad()
            cuts.extend((direction - offset, direction + offset))

    pieces: list[A1BoundaryPiece] = []
    endpoints = _unwrapped_cuts(cuts, lower, upper)
    for start, end in zip(endpoints, endpoints[1:]):
        if end - start <= GEOMETRY_TOL_RAD:
            continue
        midpoint = _point_on_ray(observation.station, 0.5 * (start + end), radius_m)
        if midpoint.distance_to(omega_center) <= omega_radius_m + GEOMETRY_TOL_M:
            pieces.append(
                A1BoundaryPiece(label, CircularArc(observation.station, radius_m, start, end))
            )
    return pieces


def _circle_circle_intersections(
    c0: Point2, r0: float, c1: Point2, r1: float
) -> tuple[Point2, ...]:
    delta = c1 - c0
    distance = delta.norm()
    if distance <= GEOMETRY_TOL_M:
        return ()
    if distance > r0 + r1 + GEOMETRY_TOL_M or distance < abs(r0 - r1) - GEOMETRY_TOL_M:
        return ()
    along = (r0 * r0 - r1 * r1 + distance * distance) / (2.0 * distance)
    height_sq = r0 * r0 - along * along
    if height_sq < -GEOMETRY_TOL_M:
        return ()
    height = math.sqrt(max(0.0, height_sq))
    axis = delta.scaled(1.0 / distance)
    base = c0 + axis.scaled(along)
    normal = Point2(-axis.y, axis.x)
    first = base + normal.scaled(height)
    if height <= GEOMETRY_TOL_M:
        return (first,)
    return first, base - normal.scaled(height)


def _isolated_a1_candidates(
    observation: FirstObservation, omega_center: Point2, omega_radius_m: float
) -> tuple[Point2, ...]:
    """Find legal singleton A1 candidates when no positive-dimensional boundary exists."""
    candidates: list[Point2] = []
    for angle in observation.wedge_limits_rad:
        radial = _radial_interval_in_omega(
            observation.station, angle, omega_center, omega_radius_m
        )
        if radial is not None and radial[1] - radial[0] <= GEOMETRY_TOL_M:
            candidates.append(_point_on_ray(observation.station, angle, radial[0]))
    for radius_m in (INNER_RADIUS_M, OUTER_RADIUS_M):
        candidates.extend(
            _circle_circle_intersections(omega_center, omega_radius_m, observation.station, radius_m)
        )

    unique: list[Point2] = []
    for point in candidates:
        if not _point_in_a1(observation, omega_center, omega_radius_m, point):
            continue
        if all(point.distance_to(existing) > GEOMETRY_TOL_M for existing in unique):
            unique.append(point)
    return tuple(unique)


def _point_in_a1(
    observation: FirstObservation,
    omega_center: Point2,
    omega_radius_m: float,
    point: Point2,
) -> bool:
    displacement = point - observation.station
    rho = displacement.norm()
    if rho <= INNER_RADIUS_M + GEOMETRY_TOL_M or rho > OUTER_RADIUS_M + GEOMETRY_TOL_M:
        return False
    if point.distance_to(omega_center) > omega_radius_m + GEOMETRY_TOL_M:
        return False
    return _circular_distance_rad(displacement.angle_rad(), observation.center_angle_rad) <= (
        observation.epsilon_rad + GEOMETRY_TOL_RAD
    )


def _active_omega_arcs(
    observation: FirstObservation, omega_center: Point2, omega_radius_m: float
) -> list[A1BoundaryPiece]:
    """Return portions of dOmega that are boundary-active for closure(A1)."""
    cuts = [0.0, math.tau]
    for radius_m in (INNER_RADIUS_M, OUTER_RADIUS_M):
        for point in _circle_circle_intersections(
            omega_center, omega_radius_m, observation.station, radius_m
        ):
            cuts.append((point - omega_center).angle_rad() % math.tau)

    for ray_angle in observation.wedge_limits_rad:
        radial = _radial_interval_in_omega(
            observation.station, ray_angle, omega_center, omega_radius_m
        )
        if radial is None:
            continue
        for radius_m in radial:
            point = _point_on_ray(observation.station, ray_angle, radius_m)
            if math.isclose(point.distance_to(omega_center), omega_radius_m, abs_tol=1e-7):
                cuts.append((point - omega_center).angle_rad() % math.tau)

    pieces: list[A1BoundaryPiece] = []
    for start, end in zip(_sorted_unique(cuts), _sorted_unique(cuts)[1:]):
        if end - start <= GEOMETRY_TOL_RAD:
            continue
        midpoint = omega_center + _unit(0.5 * (start + end)).scaled(omega_radius_m)
        delta = midpoint - observation.station
        rho = delta.norm()
        active = (
            INNER_RADIUS_M - GEOMETRY_TOL_M <= rho <= OUTER_RADIUS_M + GEOMETRY_TOL_M
            and _circular_distance_rad(delta.angle_rad(), observation.center_angle_rad)
            <= observation.epsilon_rad + GEOMETRY_TOL_RAD
        )
        if active:
            pieces.append(
                A1BoundaryPiece(
                    A1BoundaryLabel.OMEGA,
                    CircularArc(omega_center, omega_radius_m, start, end),
                )
            )
    return pieces
