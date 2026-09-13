"""Centered-case symmetry report used as a minimal special-case verifier.

Only the frozen centered case ``S1 = (0, 0)`` with first bearing ``0 deg`` is
claimed to be mirror-symmetric.  The mirror symmetry is used as a *special-case
verifier* for the Hero point and the numerical candidate region; it is not
promoted to a general theorem about the candidate region.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver.candidate_regions import AdaptiveCandidateResult
from src.q2.code.solver.q2_point import Q2PointResult, evaluate_q2_point


@dataclass(frozen=True)
class SymmetryReport:
    applicable: bool
    S1: tuple[float, float]
    theta1_deg: float
    hero_S2: tuple[float, float]
    mirror_S2: tuple[float, float]
    hero_Q_m: float
    mirror_Q_m: float
    abs_Q_difference_m: float
    both_crec_feasible: bool
    both_admissible: bool
    tolerance_m: float
    mirror_paired_points: int
    unpaired_points: int
    area_plus_m2: float
    area_minus_m2: float
    area_relative_difference: float
    passed: bool
    notes: tuple[str, ...]


def build_symmetry_report(
    S1: Point2,
    theta1_deg: float,
    hero: Q2PointResult,
    *,
    epsilon_deg: float = 1.0,
    adaptive: AdaptiveCandidateResult | None = None,
    eta: float = 0.05,
    tolerance_m: float = 1e-7,
) -> SymmetryReport:
    """Mirror-check the Hero point and (optionally) the candidate region."""
    applicable = S1 == Point2(0.0, 0.0) and math.isclose(
        theta1_deg % 360.0, 0.0, abs_tol=1e-12
    )
    if not applicable:
        return SymmetryReport(
            applicable=False,
            S1=(S1.x, S1.y),
            theta1_deg=theta1_deg,
            hero_S2=(hero.S2.x, hero.S2.y),
            mirror_S2=(hero.S2.x, -hero.S2.y),
            hero_Q_m=math.nan if hero.Q is None else float(hero.Q),
            mirror_Q_m=math.nan,
            abs_Q_difference_m=math.nan,
            both_crec_feasible=False,
            both_admissible=False,
            tolerance_m=tolerance_m,
            mirror_paired_points=0,
            unpaired_points=0,
            area_plus_m2=0.0,
            area_minus_m2=0.0,
            area_relative_difference=math.nan,
            passed=False,
            notes=("mirror symmetry is only claimed for the centered case S1=(0,0), theta1=0",),
        )

    mirror = Point2(hero.S2.x, -hero.S2.y)
    mirror_result = evaluate_q2_point(S1, theta1_deg, mirror, epsilon_deg)
    if hero.Q is None or mirror_result.Q is None:
        raise ValueError("A symmetric centered case must have finite Hero Q values.")
    difference = abs(float(hero.Q) - float(mirror_result.Q))
    both_crec = hero.in_crec and mirror_result.in_crec
    both_admissible = hero.admissible and mirror_result.admissible

    paired = 0
    unpaired = 0
    area_plus = 0.0
    area_minus = 0.0
    if adaptive is not None:
        lookup = {
            (round(result.S2.x, 6), round(result.S2.y, 6))
            for result in adaptive.surface
        }
        for result in adaptive.surface:
            if result.S2.y > 0.0:
                if (round(result.S2.x, 6), round(-result.S2.y, 6)) in lookup:
                    paired += 1
                else:
                    unpaired += 1
        for cell in adaptive.cells[eta]:
            if cell.center.y > 0.0:
                area_plus += cell.area
            elif cell.center.y < 0.0:
                area_minus += cell.area
    area_relative = (
        abs(area_plus - area_minus) / max(1e-12, max(area_plus, area_minus))
        if adaptive is not None
        else math.nan
    )
    region_ok = adaptive is None or unpaired == 0
    passed = (
        both_crec
        and both_admissible
        and difference <= tolerance_m
        and region_ok
    )
    notes = [
        "mirror symmetry is a special-case verifier for the centered case only",
        "Hero and its mirror are evaluated through the same frozen evaluator",
    ]
    if adaptive is not None:
        notes.append(
            "candidate-region mirror pairing counts sampled surface points only"
        )
    return SymmetryReport(
        applicable=True,
        S1=(S1.x, S1.y),
        theta1_deg=theta1_deg,
        hero_S2=(hero.S2.x, hero.S2.y),
        mirror_S2=(mirror.x, mirror.y),
        hero_Q_m=float(hero.Q),
        mirror_Q_m=float(mirror_result.Q),
        abs_Q_difference_m=difference,
        both_crec_feasible=both_crec,
        both_admissible=both_admissible,
        tolerance_m=tolerance_m,
        mirror_paired_points=paired,
        unpaired_points=unpaired,
        area_plus_m2=area_plus,
        area_minus_m2=area_minus,
        area_relative_difference=area_relative,
        passed=passed,
        notes=tuple(notes),
    )
