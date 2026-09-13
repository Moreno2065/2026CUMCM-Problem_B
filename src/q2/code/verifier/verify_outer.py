"""Independent local verification of a Gate F spatial-search recommendation."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol

from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver.q2_point import Q2PointResult, evaluate_q2_point


@dataclass(frozen=True)
class OuterVerificationReport:
    passed: bool
    recomputed: Q2PointResult
    q_agrees: bool
    checked_points: int
    valid_points: int
    best_local_point: Point2
    best_local_Q: float
    no_better_local_point: bool
    tolerance_m: float
    failures: tuple[str, ...]


class SearchRecommendation(Protocol):
    recommended: Q2PointResult
    certified_global_optimum: bool


def verify_outer(
    S1: Point2,
    theta1: float,
    epsilon: float,
    search_result: SearchRecommendation,
    *,
    mesh_radius_m: float = 10.0,
    mesh_resolution: int = 9,
) -> OuterVerificationReport:
    """Recompute the incumbent and inspect an independent deterministic neighborhood."""
    if not (math.isfinite(mesh_radius_m) and mesh_radius_m > 0.0):
        raise ValueError("mesh_radius_m must be finite and positive.")
    if mesh_resolution < 3:
        raise ValueError("mesh_resolution must be at least three.")
    recommended = search_result.recommended
    recomputed = evaluate_q2_point(S1, theta1, recommended.S2, epsilon)
    scale = max(1.0, float(recomputed.Q or 0.0), float(recommended.Q or 0.0))
    tolerance = max(1e-5, 2e-7 * scale)
    q_agrees = recomputed == recommended
    failures: list[str] = []
    if not q_agrees:
        failures.append("fresh Q2 recomputation disagrees with the stored recommendation")
    if search_result.certified_global_optimum is not False:
        failures.append("Gate F must not claim a global-optimum certificate")

    points = _local_points(recommended.S2, mesh_radius_m, mesh_resolution)
    evaluations = [evaluate_q2_point(S1, theta1, point, epsilon) for point in points]
    valid = [result for result in evaluations if _is_valid(result)]
    if not valid:
        failures.append("independent local mesh found no valid points")
        best = recomputed
    else:
        best = min(valid, key=lambda result: (float(result.Q), result.S2.x, result.S2.y))
    best_q = math.inf if best.Q is None else float(best.Q)
    recomputed_q = math.inf if recomputed.Q is None else float(recomputed.Q)
    no_better = best_q >= recomputed_q - tolerance
    if not no_better:
        failures.append("independent local mesh found a materially better valid point")

    return OuterVerificationReport(
        passed=not failures,
        recomputed=recomputed,
        q_agrees=q_agrees,
        checked_points=len(points),
        valid_points=len(valid),
        best_local_point=best.S2,
        best_local_Q=best_q,
        no_better_local_point=no_better,
        tolerance_m=tolerance,
        failures=tuple(failures),
    )


def _local_points(center: Point2, radius: float, resolution: int) -> tuple[Point2, ...]:
    points = {
        Point2(
            center.x - radius + 2.0 * radius * ix / (resolution - 1),
            center.y - radius + 2.0 * radius * iy / (resolution - 1),
        )
        for ix in range(resolution)
        for iy in range(resolution)
    }
    directions = tuple(
        Point2(math.cos(index * math.pi / 8.0), math.sin(index * math.pi / 8.0))
        for index in range(16)
    )
    for distance in (1e-6, 1e-3, 0.1, 1.0, radius):
        for direction in directions:
            points.add(
                Point2(
                    center.x + direction.x * distance,
                    center.y + direction.y * distance,
                )
            )
    return tuple(sorted(points))


def _same_value(left: float | None, right: float | None, tolerance: float) -> bool:
    if left is None or right is None:
        return left is right
    if math.isinf(left) or math.isinf(right):
        return left == right
    return abs(left - right) <= tolerance


def _is_valid(result: Q2PointResult) -> bool:
    return result.in_crec and result.admissible and result.Q is not None
