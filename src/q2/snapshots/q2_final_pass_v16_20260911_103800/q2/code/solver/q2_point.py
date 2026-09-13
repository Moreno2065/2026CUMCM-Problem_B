"""Structured evaluation of the frozen Q2 objective at one second station."""

from __future__ import annotations

from dataclasses import dataclass
import math

from src.q2.code.geometry.a1 import EPSILON_DEG, FirstObservation, build_a1
from src.q2.code.geometry.angular_image import build_angular_image
from src.q2.code.geometry.circular_intervals import CircularIntervalUnion
from src.q2.code.geometry.crec import build_crec, is_in_crec
from src.q2.code.geometry.primitives import Point2
from src.q2.code.model.q1_adapter import Q1AdapterPoint
from src.q2.code.solver.inner_max import maximize_inner


@dataclass(frozen=True)
class Q2PointResult:
    S2: Point2
    in_crec: bool
    crec_margin: float
    all_near: bool
    raw_theta_intervals: CircularIntervalUnion
    expanded_theta_intervals: CircularIntervalUnion
    admissible: bool
    Q: float | None
    worst_beta: float | None
    worst_candidate_type: str
    worst_Q1_status: str | None
    worst_Q1_polygon: tuple[Q1AdapterPoint, ...]
    diameter_witness_pair: tuple[Q1AdapterPoint, Q1AdapterPoint] | None
    active_geometry_labels: tuple[str, ...]


def evaluate_q2_point(
    S1: Point2,
    theta1: float,
    S2: Point2,
    epsilon: float = EPSILON_DEG,
) -> Q2PointResult:
    """Evaluate Crec, near-aware admissibility, and the exact inner objective."""
    if not isinstance(S1, Point2) or not isinstance(S2, Point2):
        raise TypeError("S1 and S2 must be Point2 values.")
    values = (float(theta1), float(epsilon))
    if not all(math.isfinite(value) for value in values):
        raise ValueError("theta1 and epsilon must be finite.")
    if epsilon != EPSILON_DEG:
        raise ValueError("Gate E uses the frozen one-degree epsilon.")

    a1 = build_a1(FirstObservation(S1, theta1, epsilon))
    crec_evaluation = is_in_crec(build_crec(a1), S2)
    crec_label = crec_evaluation.active_witness_type.value
    empty = CircularIntervalUnion.empty()
    if not crec_evaluation.in_crec:
        return Q2PointResult(
            S2, False, crec_evaluation.margin_m, False, empty, empty, False,
            None, None, "OUTSIDE_CREC", None, (), None, (crec_label,),
        )

    angular = build_angular_image(a1, S2)
    angular_labels = tuple(
        sorted({event.source_label for event in angular.boundary_events})
    )
    active_labels = tuple(dict.fromkeys((crec_label,) + angular_labels))
    if angular.all_near:
        return Q2PointResult(
            S2, True, crec_evaluation.margin_m, True,
            angular.merged_closure, angular.expanded_closure, True,
            0.0, None, "ALL_NEAR", None, (), None, active_labels,
        )

    separation = angular.merged_closure.distance_to_angle(math.radians(theta1))
    admissible = separation > 3.0 * math.radians(epsilon)
    if not admissible:
        return Q2PointResult(
            S2, True, crec_evaluation.margin_m, False,
            angular.merged_closure, angular.expanded_closure, False,
            None, None, "INADMISSIBLE", None, (), None, active_labels,
        )

    inner = maximize_inner(
        S1, theta1, S2, angular.expanded_closure, epsilon
    )
    worst_sources = next(
        (
            candidate.source_labels
            for candidate in inner.candidates
            if candidate.candidate_type == inner.candidate_type
            and abs(
                (math.degrees(candidate.beta_rad) - inner.worst_beta_deg + 180.0)
                % 360.0
                - 180.0
            )
            <= 1e-9
        ),
        (),
    )
    winner_geometry: tuple[str, ...] = ()
    if inner.candidate_type == "E1":
        epsilon_rad = math.radians(epsilon)
        raw_angles: list[float] = []
        if "interval_start" in worst_sources:
            raw_angles.append(math.radians(inner.worst_beta_deg) + epsilon_rad)
        if "interval_end" in worst_sources:
            raw_angles.append(math.radians(inner.worst_beta_deg) - epsilon_rad)
        winner_geometry = tuple(
            sorted(
                {
                    witness.source_label
                    for witness in angular.extrema_witnesses
                    if any(
                        abs((witness.angle_rad - angle + math.pi) % math.tau - math.pi)
                        <= 1e-9
                        for angle in raw_angles
                    )
                }
            )
        )
    active_labels = tuple(
        dict.fromkeys(
            (crec_label,)
            + winner_geometry
            + (f"inner_{inner.candidate_type}",)
            + worst_sources
        )
    )
    return Q2PointResult(
        S2=S2,
        in_crec=True,
        crec_margin=crec_evaluation.margin_m,
        all_near=False,
        raw_theta_intervals=angular.merged_closure,
        expanded_theta_intervals=angular.expanded_closure,
        admissible=True,
        Q=inner.Q,
        worst_beta=inner.worst_beta_deg,
        worst_candidate_type=inner.candidate_type,
        worst_Q1_status=inner.worst_q1.status,
        worst_Q1_polygon=inner.worst_q1.ordered_vertices,
        diameter_witness_pair=inner.worst_q1.diameter_witness_pair,
        active_geometry_labels=active_labels,
    )
