"""Independent dense cross-check of RADIAL_DEPTH Crec Omega-arc witnesses.

The production Crec arc witness maximizes the raw reception violation with an
analytic stationary-point solve (an up-to-sixth-degree polynomial followed by an
unsquared-derivative recheck).  That is a strong candidate generator but not a
proof, so this module re-maximizes the *same raw objective* on every deep arc by
dense sampling plus a golden-section local refinement and reports every arc
where the production candidates were beaten.

If an independent scan finds a larger violation, the production value must not
be used unchanged: :func:`verified_in_crec` adopts the larger violation and
fails closed whenever the two verdicts disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from src.q2.code.geometry.crec import (
    CREC_TOL_M,
    CompatibleRadiusMode,
    CrecEvaluation,
    CrecRegion,
    _arc_candidates,
)
from src.q2.code.geometry.primitives import CircularArc, Point2


class CrecUnderestimateError(RuntimeError):
    """The independent deep-arc scan beat the analytic Crec witness value."""


@dataclass(frozen=True)
class DeepArcWitnessRow:
    label: str
    source: str
    arc_start_rad: float
    arc_end_rad: float
    base_samples: int
    main_max_violation_m: float
    main_active_angle_rad: float
    scan_max_violation_m: float
    scan_active_angle_rad: float
    refined_max_violation_m: float
    refined_active_angle_rad: float
    gap_m: float
    passed: bool


@dataclass(frozen=True)
class CrecWitnessVerification:
    rows: tuple[DeepArcWitnessRow, ...]
    checked_arc_count: int
    max_gap_m: float
    passed: bool
    failures: tuple[str, ...]


def verify_crec_deep_arc_witnesses(
    crec: CrecRegion,
    second_station: Point2,
    *,
    base_samples: int = 2049,
    refinement_iterations: int = 80,
    tolerance_m: float = 1e-6,
) -> CrecWitnessVerification:
    """Compare production deep-arc candidates against an independent scan."""
    if base_samples < 3:
        raise ValueError("base_samples must be at least three.")
    if refinement_iterations < 1:
        raise ValueError("refinement_iterations must be positive.")
    first_station = crec.a1.observation.station
    rows: list[DeepArcWitnessRow] = []
    failures: list[str] = []

    for piece in crec.witnesses.pieces:
        if piece.radius_mode != CompatibleRadiusMode.RADIAL_DEPTH:
            continue
        arc = piece.curve
        if not isinstance(arc, CircularArc):
            continue

        main_points = _arc_candidates(piece, second_station, first_station)
        main_values = [
            (_violation(second_station, point, first_station), point)
            for point in main_points
        ]
        if main_values:
            main_max, main_point = max(main_values, key=lambda item: item[0])
            main_angle = _arc_angle(main_point, arc)
        else:
            main_max, main_angle = -math.inf, math.nan

        scan_max, scan_angle = _dense_arc_scan(
            arc, second_station, first_station, base_samples
        )
        refined_max, refined_angle = _refine_arc_max(
            arc, second_station, first_station, scan_angle, refinement_iterations
        )
        independent_max = max(scan_max, refined_max)
        if math.isfinite(main_max):
            gap = independent_max - main_max
        else:
            gap = math.inf
        passed = gap <= tolerance_m
        if not passed:
            failures.append(
                f"{piece.label.value} deep arc [{arc.start_angle_rad:.9g}, "
                f"{arc.end_angle_rad:.9g}] rad: independent {independent_max:.9g} m "
                f"beats analytic {main_max:.9g} m by {gap:.6g} m"
            )
        rows.append(
            DeepArcWitnessRow(
                label=piece.label.value,
                source=piece.source,
                arc_start_rad=arc.start_angle_rad,
                arc_end_rad=arc.end_angle_rad,
                base_samples=base_samples,
                main_max_violation_m=main_max,
                main_active_angle_rad=main_angle,
                scan_max_violation_m=scan_max,
                scan_active_angle_rad=scan_angle,
                refined_max_violation_m=refined_max,
                refined_active_angle_rad=refined_angle,
                gap_m=gap,
                passed=passed,
            )
        )

    return CrecWitnessVerification(
        rows=tuple(rows),
        checked_arc_count=len(rows),
        max_gap_m=max((row.gap_m for row in rows if math.isfinite(row.gap_m)), default=0.0),
        passed=not failures,
        failures=tuple(failures),
    )


def verified_in_crec(
    crec: CrecRegion,
    second_station: Point2,
    *,
    base_samples: int = 2049,
    tolerance_m: float = 1e-6,
) -> CrecEvaluation:
    """Membership decision that never returns an underestimated violation.

    The fast production evaluation is kept when the independent deep-arc scan
    agrees.  When the independent scan sees a larger violation, the larger value
    is adopted; if that also changes the membership verdict, the caller receives
    the corrected (fail-closed) evaluation instead of the stale one.
    """
    evaluation = crec.is_in_crec(second_station)
    verification = verify_crec_deep_arc_witnesses(
        crec,
        second_station,
        base_samples=base_samples,
        tolerance_m=tolerance_m,
    )
    if verification.passed:
        return evaluation
    if any(not math.isfinite(row.gap_m) for row in verification.rows):
        raise CrecUnderestimateError(
            "independent deep-arc scan produced an unbounded violation"
        )
    independent_max = evaluation.max_violation_m + max(
        row.gap_m for row in verification.rows
    )
    if independent_max <= CREC_TOL_M + tolerance_m:
        return evaluation
    active = max(
        verification.rows,
        key=lambda row: row.main_max_violation_m + row.gap_m,
    )
    return CrecEvaluation(
        in_crec=False,
        max_violation_m=independent_max,
        margin_m=-independent_max,
        active_witness_point=evaluation.active_witness_point,
        active_witness_type=evaluation.active_witness_type,
        active_witness_source=f"independent_deep_arc_scan:{active.source}",
        checked_candidate_count=evaluation.checked_candidate_count,
        a1_dimension=evaluation.a1_dimension,
    )


def _violation(second_station: Point2, target: Point2, first_station: Point2) -> float:
    return second_station.distance_to(target) - max(1000.0, target.distance_to(first_station))


def _point_on_arc(arc: CircularArc, angle: float) -> Point2:
    return arc.center + Point2(math.cos(angle), math.sin(angle)).scaled(arc.radius)


def _arc_angle(point: Point2, arc: CircularArc) -> float:
    delta = point - arc.center
    angle = delta.angle_rad() if delta.norm() > CREC_TOL_M else arc.start_angle_rad
    central = 0.5 * (arc.start_angle_rad + arc.end_angle_rad)
    return angle + math.tau * round((central - angle) / math.tau)


def _dense_arc_scan(
    arc: CircularArc,
    second_station: Point2,
    first_station: Point2,
    samples: int,
) -> tuple[float, float]:
    best_value = -math.inf
    best_angle = arc.start_angle_rad
    for index in range(samples):
        angle = arc.start_angle_rad + arc.angle_span_rad * index / (samples - 1)
        value = _violation(second_station, _point_on_arc(arc, angle), first_station)
        if value > best_value:
            best_value, best_angle = value, angle
    return best_value, best_angle


def _refine_arc_max(
    arc: CircularArc,
    second_station: Point2,
    first_station: Point2,
    seed_angle: float,
    iterations: int,
) -> tuple[float, float]:
    window = max(arc.angle_span_rad / 64.0, 1e-9)
    left = max(arc.start_angle_rad, seed_angle - window)
    right = min(arc.end_angle_rad, seed_angle + window)

    def value(angle: float) -> float:
        return _violation(second_station, _point_on_arc(arc, angle), first_station)

    if right - left <= 0.0:
        return value(seed_angle), seed_angle

    inverse_phi = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = left, right
    c = b - inverse_phi * (b - a)
    d = a + inverse_phi * (b - a)
    fc, fd = value(c), value(d)
    for _ in range(iterations):
        if b - a <= 1e-13:
            break
        if fc >= fd:
            b, d, fd = d, c, fc
            c = b - inverse_phi * (b - a)
            fc = value(c)
        else:
            a, c, fc = c, d, fd
            d = a + inverse_phi * (b - a)
            fd = value(d)
    candidates = ((fc, c), (fd, d), (value(a), a), (value(b), b))
    return max(candidates, key=lambda item: item[0])
