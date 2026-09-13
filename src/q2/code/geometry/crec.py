"""Exact robust reception geometry for Q2 Gate B.

This module owns reception witnesses only.  It deliberately does not import,
accept, or reinterpret A1 active-boundary labels as reception labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

import numpy as np

from .a1 import (
    A1BoundaryRegistry,
    A1Dimension,
    A1Region,
    INNER_RADIUS_M,
    OUTER_RADIUS_M,
)
from .primitives import BoundaryPoint, CircularArc, LineSegment, Point2


MIN_RECEPTION_RADIUS_M = 1000.0
CREC_TOL_M = 1e-9


class InvalidFirstObservationGeometry(ValueError):
    """The first successful observation produced no legal target geometry."""


class UnsupportedA1Dimension(ValueError):
    """Gate B cannot silently reinterpret an unsupported A1 dimension."""


class CrecWitnessLabel(str, Enum):
    RHO_LO = "crec_rho_lo"
    RHO_1000 = "crec_rho_1000"
    OMEGA_TRUNCATED_RHO_LO = "crec_omega_truncated_rho_lo"
    OMEGA_TRUNCATED_RHO_HI_BELOW_1000 = "crec_omega_truncated_rho_hi_below_1000"
    DEGENERATE_POINT = "crec_degenerate_point"
    RHO_1500_AS_DEEP_END_WITNESS = "crec_forbidden_rho_1500_deep_end"


class CompatibleRadiusMode(str, Enum):
    FIXED_1000 = "fixed_1000"
    RADIAL_DEPTH = "radial_depth"


@dataclass(frozen=True)
class CrecWitnessPiece:
    label: CrecWitnessLabel
    curve: LineSegment | CircularArc | BoundaryPoint
    radius_mode: CompatibleRadiusMode
    source: str


@dataclass(frozen=True)
class CrecWitnessRegistry:
    """Nominal registry whose labels encode reception worst-case semantics."""

    pieces: tuple[CrecWitnessPiece, ...]
    first_station: Point2
    omega_center: Point2
    omega_radius_m: float

    def __post_init__(self) -> None:
        if not (math.isfinite(self.omega_radius_m) and self.omega_radius_m > 0.0):
            raise ValueError("Crec registry Omega radius must be finite and positive.")
        for piece in self.pieces:
            if piece.label == CrecWitnessLabel.RHO_1500_AS_DEEP_END_WITNESS:
                raise ValueError("rho=1500 cannot be a deep-end Crec witness.")
            if piece.label in {
                CrecWitnessLabel.RHO_LO,
                CrecWitnessLabel.RHO_1000,
                CrecWitnessLabel.OMEGA_TRUNCATED_RHO_HI_BELOW_1000,
            } and piece.radius_mode != CompatibleRadiusMode.FIXED_1000:
                raise ValueError(
                    f"{piece.label.value} requires compatible radius mode fixed_1000."
                )
            if piece.label == CrecWitnessLabel.DEGENERATE_POINT:
                if not isinstance(piece.curve, BoundaryPoint):
                    raise TypeError("A degenerate Crec witness must be a BoundaryPoint.")
                continue
            if not isinstance(piece.curve, CircularArc):
                raise TypeError("Nondegenerate Crec witness families must be CircularArc values.")
            if piece.label == CrecWitnessLabel.RHO_LO and (
                piece.curve.center.distance_to(self.first_station) > CREC_TOL_M
                or not math.isclose(piece.curve.radius, 5.0, abs_tol=CREC_TOL_M)
            ):
                raise ValueError("rho_lo station arcs must coincide with rho=5.")
            if piece.label == CrecWitnessLabel.RHO_1000 and (
                piece.curve.center.distance_to(self.first_station) > CREC_TOL_M
                or not math.isclose(
                    piece.curve.radius, MIN_RECEPTION_RADIUS_M, abs_tol=CREC_TOL_M
                )
            ):
                raise ValueError("rho_1000 witness arcs must coincide with rho=1000.")
            if piece.label in {
                CrecWitnessLabel.OMEGA_TRUNCATED_RHO_LO,
                CrecWitnessLabel.OMEGA_TRUNCATED_RHO_HI_BELOW_1000,
            } and (
                piece.curve.center.distance_to(self.omega_center) > CREC_TOL_M
                or not math.isclose(
                    piece.curve.radius, self.omega_radius_m, abs_tol=CREC_TOL_M
                )
            ):
                raise ValueError("Omega-truncated witnesses must lie on the frozen Omega circle.")


@dataclass(frozen=True)
class CrecEvaluation:
    in_crec: bool
    max_violation_m: float
    margin_m: float
    active_witness_point: Point2
    active_witness_type: CrecWitnessLabel
    active_witness_source: str
    checked_candidate_count: int
    a1_dimension: A1Dimension


@dataclass(frozen=True)
class CrecRegion:
    a1: A1Region
    witnesses: CrecWitnessRegistry

    def __post_init__(self) -> None:
        if not isinstance(self.witnesses, CrecWitnessRegistry):
            raise TypeError("CrecRegion requires a CrecWitnessRegistry.")
        if (
            self.witnesses.first_station.distance_to(self.a1.observation.station)
            > CREC_TOL_M
            or self.witnesses.omega_center.distance_to(self.a1.omega_center)
            > CREC_TOL_M
            or not math.isclose(
                self.witnesses.omega_radius_m,
                self.a1.omega_radius_m,
                abs_tol=CREC_TOL_M,
            )
        ):
            raise ValueError("Crec registry metadata does not match its A1 geometry.")

    def is_in_crec(self, second_station: Point2) -> CrecEvaluation:
        """Evaluate Phi at a second station and return the active witness provenance."""
        candidates: list[tuple[Point2, CrecWitnessPiece]] = []
        for piece in self.witnesses.pieces:
            if isinstance(piece.curve, BoundaryPoint):
                _append_unique_candidate(candidates, piece.curve.point, piece)
            elif isinstance(piece.curve, CircularArc):
                for point in _arc_candidates(
                    piece, second_station, self.a1.observation.station
                ):
                    _append_unique_candidate(candidates, point, piece)
            else:
                raise TypeError("Crec witness registry contains an unsupported curve type.")
        if not candidates:
            raise InvalidFirstObservationGeometry("A nonempty A1 produced no Crec witnesses.")

        active_point, active_piece = max(
            candidates,
            key=lambda item: _violation(second_station, item[0], self.a1.observation.station),
        )
        maximum = _violation(second_station, active_point, self.a1.observation.station)
        return CrecEvaluation(
            in_crec=maximum <= CREC_TOL_M,
            max_violation_m=maximum,
            margin_m=-maximum,
            active_witness_point=active_point,
            active_witness_type=active_piece.label,
            active_witness_source=active_piece.source,
            checked_candidate_count=len(candidates),
            a1_dimension=self.a1.dimension,
        )


def build_crec(a1: A1Region) -> CrecRegion:
    """Build the exact robust reception object from a validated Gate A region."""
    if not isinstance(a1, A1Region) or not isinstance(a1.boundary, A1BoundaryRegistry):
        raise TypeError("build_crec requires an A1Region with an A1BoundaryRegistry.")
    if a1.dimension == A1Dimension.EMPTY:
        raise InvalidFirstObservationGeometry(
            "A successful first observation cannot define EMPTY A1; Crec is invalid."
        )
    if a1.dimension == A1Dimension.SEGMENT:
        raise UnsupportedA1Dimension(
            "One-dimensional A1 is explicitly blocked until an exact segment witness proof exists."
        )
    if a1.dimension == A1Dimension.POINT:
        point_pieces = a1.boundary.point_pieces
        if not point_pieces:
            raise InvalidFirstObservationGeometry("POINT A1 has no registered BoundaryPoint.")
        pieces = tuple(
            CrecWitnessPiece(
                label=CrecWitnessLabel.DEGENERATE_POINT,
                curve=BoundaryPoint(piece.curve.point),
                radius_mode=(
                    CompatibleRadiusMode.FIXED_1000
                    if piece.curve.point.distance_to(a1.observation.station)
                    <= MIN_RECEPTION_RADIUS_M + CREC_TOL_M
                    else CompatibleRadiusMode.RADIAL_DEPTH
                ),
                source="a1_tangent_singleton",
            )
            for piece in point_pieces
        )
    elif a1.dimension == A1Dimension.AREA:
        pieces = _build_area_witnesses(a1)
        if not pieces:
            raise InvalidFirstObservationGeometry(
                "AREA A1 produced no reception witness families."
            )
    else:
        raise UnsupportedA1Dimension(f"Unsupported A1 dimension: {a1.dimension!r}")

    registry = CrecWitnessRegistry(
        pieces=pieces,
        first_station=a1.observation.station,
        omega_center=a1.omega_center,
        omega_radius_m=a1.omega_radius_m,
    )
    return CrecRegion(a1=a1, witnesses=registry)


def is_in_crec(crec: CrecRegion, second_station: Point2) -> CrecEvaluation:
    """Functional facade for callers that prefer an explicit evaluator."""
    if not isinstance(crec, CrecRegion):
        raise TypeError("is_in_crec requires a CrecRegion, not a physical A1 registry.")
    return crec.is_in_crec(second_station)


def _violation(second_station: Point2, target: Point2, first_station: Point2) -> float:
    compatible_radius = max(MIN_RECEPTION_RADIUS_M, target.distance_to(first_station))
    return second_station.distance_to(target) - compatible_radius


def _build_area_witnesses(a1: A1Region) -> tuple[CrecWitnessPiece, ...]:
    """Apply the frozen three-branch radial reduction on analytic angular cells."""
    cuts = _witness_angular_cuts(a1)
    pieces: list[CrecWitnessPiece] = []
    for start, end in zip(cuts, cuts[1:]):
        if end - start <= 1e-12:
            continue
        midpoint = 0.5 * (start + end)
        radial = a1.radial_interval(midpoint)
        if radial is None:
            continue
        lo, hi = radial
        if hi <= MIN_RECEPTION_RADIUS_M + CREC_TOL_M:
            selectors = ("lo", "hi")
        elif lo < MIN_RECEPTION_RADIUS_M - CREC_TOL_M:
            selectors = ("lo", "rho_1000")
        else:
            selectors = ("lo",)
        for selector in selectors:
            piece = _witness_piece_for_cell(a1, start, end, midpoint, selector)
            if piece is not None:
                pieces.append(piece)
    return tuple(pieces)


def _witness_angular_cuts(a1: A1Region) -> list[float]:
    lower, upper = a1.observation.wedge_limits_rad
    cuts = [lower, upper]
    station = a1.observation.station
    center_delta = a1.omega_center - station
    center_distance = center_delta.norm()
    if center_distance > a1.omega_radius_m + CREC_TOL_M:
        center_angle = center_delta.angle_rad()
        tangent_offset = math.asin(min(1.0, a1.omega_radius_m / center_distance))
        cuts.extend((center_angle - tangent_offset, center_angle + tangent_offset))
    for radius_m in (INNER_RADIUS_M, MIN_RECEPTION_RADIUS_M, OUTER_RADIUS_M):
        for point in _circle_circle_intersections(
            station, radius_m, a1.omega_center, a1.omega_radius_m
        ):
            cuts.append((point - station).angle_rad())
    return _unwrapped_cuts(cuts, lower, upper)


def _witness_piece_for_cell(
    a1: A1Region,
    start: float,
    end: float,
    midpoint: float,
    selector: str,
) -> CrecWitnessPiece | None:
    radial = a1.radial_interval(midpoint)
    if radial is None:
        return None
    lo, hi = radial
    station = a1.observation.station
    if selector == "rho_1000":
        return CrecWitnessPiece(
            CrecWitnessLabel.RHO_1000,
            CircularArc(station, MIN_RECEPTION_RADIUS_M, start, end),
            CompatibleRadiusMode.FIXED_1000,
            "radial_transition_rho_1000",
        )
    if selector == "lo" and math.isclose(lo, INNER_RADIUS_M, abs_tol=1e-7):
        return CrecWitnessPiece(
            CrecWitnessLabel.RHO_LO,
            CircularArc(station, INNER_RADIUS_M, start, end),
            CompatibleRadiusMode.FIXED_1000,
            "radial_lower_rho_5",
        )

    root_index = 0 if selector == "lo" else 1
    omega_arc = _omega_arc_for_ray_cell(a1, start, end, root_index)
    if omega_arc is None:
        return None
    if selector == "hi":
        return CrecWitnessPiece(
            CrecWitnessLabel.OMEGA_TRUNCATED_RHO_HI_BELOW_1000,
            omega_arc,
            CompatibleRadiusMode.FIXED_1000,
            "omega_exit_below_rho_1000",
        )
    radius_mode = (
        CompatibleRadiusMode.FIXED_1000
        if lo <= MIN_RECEPTION_RADIUS_M + CREC_TOL_M
        else CompatibleRadiusMode.RADIAL_DEPTH
    )
    return CrecWitnessPiece(
        CrecWitnessLabel.OMEGA_TRUNCATED_RHO_LO,
        omega_arc,
        radius_mode,
        "omega_entry_fixed_1000"
        if radius_mode == CompatibleRadiusMode.FIXED_1000
        else "omega_entry_deep_radial",
    )


def _omega_arc_for_ray_cell(
    a1: A1Region, start: float, end: float, root_index: int
) -> CircularArc | None:
    endpoints: list[Point2] = []
    for angle in (start, end):
        roots = _ray_circle_roots(
            a1.observation.station, angle, a1.omega_center, a1.omega_radius_m
        )
        if roots is None:
            return None
        endpoints.append(_point_on_ray(a1.observation.station, angle, roots[root_index]))
    psi0 = (endpoints[0] - a1.omega_center).angle_rad()
    psi1 = (endpoints[1] - a1.omega_center).angle_rad()
    delta = (psi1 - psi0 + math.pi) % math.tau - math.pi
    if abs(delta) <= 1e-12:
        return None
    if delta > 0.0:
        return CircularArc(a1.omega_center, a1.omega_radius_m, psi0, psi0 + delta)
    return CircularArc(a1.omega_center, a1.omega_radius_m, psi0 + delta, psi0)


def _arc_candidates(
    piece: CrecWitnessPiece, second_station: Point2, first_station: Point2
) -> tuple[Point2, ...]:
    arc = piece.curve
    if not isinstance(arc, CircularArc):
        return ()
    candidates = list(arc.endpoints)
    if piece.radius_mode == CompatibleRadiusMode.FIXED_1000:
        displacement = second_station - arc.center
        if displacement.norm() <= CREC_TOL_M:
            return tuple(candidates)
        antipode = arc.center - displacement.scaled(arc.radius / displacement.norm())
        if _point_on_arc(antipode, arc):
            candidates.append(antipode)
    else:
        candidates.extend(
            _deep_arc_stationary_points(arc, second_station, first_station)
        )
    return tuple(candidates)


def _deep_arc_stationary_points(
    arc: CircularArc, second_station: Point2, first_station: Point2
) -> tuple[Point2, ...]:
    """Finite stationary set for distance(X,G)-distance(S1,G) on an Omega arc.

    With t=tan(psi/2), squaring the derivative equation yields a polynomial
    of degree at most six.  Every real in-arc root is checked again against
    the original unsquared derivative, so sign-flipped algebraic roots cannot
    become witnesses.
    """
    relative_x = second_station - arc.center
    relative_s = first_station - arc.center
    radius = arc.radius

    def derivative_linear(vector: Point2) -> np.ndarray:
        return np.array((-vector.y, 2.0 * vector.x, vector.y), dtype=float)

    def distance_squared(vector: Point2) -> np.ndarray:
        constant = radius * radius + vector.dot(vector)
        return np.array(
            (
                constant - 2.0 * radius * vector.x,
                -4.0 * radius * vector.y,
                constant + 2.0 * radius * vector.x,
            ),
            dtype=float,
        )

    px = derivative_linear(relative_x)
    ps = derivative_linear(relative_s)
    nx = distance_squared(relative_x)
    ns = distance_squared(relative_s)
    polynomial = np.polynomial.polynomial.polysub(
        np.polynomial.polynomial.polymul(
            np.polynomial.polynomial.polymul(px, px), ns
        ),
        np.polynomial.polynomial.polymul(
            np.polynomial.polynomial.polymul(ps, ps), nx
        ),
    )
    scale = max(1.0, float(np.max(np.abs(polynomial))))
    while len(polynomial) > 1 and abs(polynomial[-1]) <= 1e-13 * scale:
        polynomial = polynomial[:-1]

    angles: list[float] = []
    if len(polynomial) > 1:
        for root in np.roots(polynomial[::-1]):
            if abs(float(root.imag)) > 1e-7 * max(1.0, abs(float(root.real))):
                continue
            base = 2.0 * math.atan(float(root.real))
            for angle in _angle_shifts_in_arc(base, arc):
                if _deep_arc_derivative_abs(
                    arc, angle, second_station, first_station
                ) <= 2e-5:
                    angles.append(angle)

    for angle in _angle_shifts_in_arc(math.pi, arc):
        if _deep_arc_derivative_abs(arc, angle, second_station, first_station) <= 2e-5:
            angles.append(angle)

    points: list[Point2] = []
    for angle in sorted(angles):
        point = arc.center + Point2(math.cos(angle), math.sin(angle)).scaled(radius)
        if all(point.distance_to(existing) > 1e-7 for existing in points):
            points.append(point)
    return tuple(points)


def _deep_arc_derivative_abs(
    arc: CircularArc,
    angle: float,
    second_station: Point2,
    first_station: Point2,
) -> float:
    point = arc.center + Point2(math.cos(angle), math.sin(angle)).scaled(arc.radius)
    tangent = Point2(-math.sin(angle), math.cos(angle)).scaled(arc.radius)
    to_x = point - second_station
    to_s = point - first_station
    distance_x = to_x.norm()
    distance_s = to_s.norm()
    if distance_x <= CREC_TOL_M:
        return math.inf
    if distance_s <= CREC_TOL_M:
        return math.inf
    return abs(to_x.dot(tangent) / distance_x - to_s.dot(tangent) / distance_s)


def _angle_shifts_in_arc(base: float, arc: CircularArc) -> tuple[float, ...]:
    candidates: list[float] = []
    central_shift = round((0.5 * (arc.start_angle_rad + arc.end_angle_rad) - base) / math.tau)
    for offset in (-1, 0, 1):
        angle = base + (central_shift + offset) * math.tau
        if arc.start_angle_rad - 1e-11 <= angle <= arc.end_angle_rad + 1e-11:
            candidates.append(angle)
    return tuple(candidates)


def _append_unique_candidate(
    candidates: list[tuple[Point2, CrecWitnessPiece]],
    point: Point2,
    piece: CrecWitnessPiece,
) -> None:
    if all(point.distance_to(existing) > 1e-7 for existing, _ in candidates):
        candidates.append((point, piece))


def _point_on_arc(point: Point2, arc: CircularArc) -> bool:
    if not math.isclose(point.distance_to(arc.center), arc.radius, abs_tol=1e-7):
        return False
    angle = (point - arc.center).angle_rad()
    for shift in (-math.tau, 0.0, math.tau):
        candidate = angle + shift
        if arc.start_angle_rad - 1e-12 <= candidate <= arc.end_angle_rad + 1e-12:
            return True
    return False


def _point_on_ray(station: Point2, angle: float, radius: float) -> Point2:
    return station + Point2(math.cos(angle), math.sin(angle)).scaled(radius)


def _ray_circle_roots(
    station: Point2, angle: float, center: Point2, radius: float
) -> tuple[float, float] | None:
    direction = Point2(math.cos(angle), math.sin(angle))
    delta = station - center
    projection = delta.dot(direction)
    discriminant = projection * projection - (delta.dot(delta) - radius * radius)
    if discriminant < -CREC_TOL_M:
        return None
    root = math.sqrt(max(0.0, discriminant))
    return -projection - root, -projection + root


def _circle_circle_intersections(
    c0: Point2, r0: float, c1: Point2, r1: float
) -> tuple[Point2, ...]:
    delta = c1 - c0
    distance = delta.norm()
    if distance <= CREC_TOL_M:
        return ()
    if distance > r0 + r1 + CREC_TOL_M or distance < abs(r0 - r1) - CREC_TOL_M:
        return ()
    along = (r0 * r0 - r1 * r1 + distance * distance) / (2.0 * distance)
    height_sq = r0 * r0 - along * along
    if height_sq < -CREC_TOL_M:
        return ()
    height = math.sqrt(max(0.0, height_sq))
    axis = delta.scaled(1.0 / distance)
    base = c0 + axis.scaled(along)
    normal = Point2(-axis.y, axis.x)
    first = base + normal.scaled(height)
    if height <= CREC_TOL_M:
        return (first,)
    return first, base - normal.scaled(height)


def _unwrapped_cuts(values: list[float], lower: float, upper: float) -> list[float]:
    accepted = [lower, upper]
    for raw in values:
        base = raw % math.tau
        for shift in (-math.tau, 0.0, math.tau):
            candidate = base + shift
            if lower + 1e-12 < candidate < upper - 1e-12:
                accepted.append(candidate)
    accepted.sort()
    unique: list[float] = []
    for value in accepted:
        if not unique or value - unique[-1] > 1e-12:
            unique.append(value)
    return unique
