"""Independent dense and event-refined verification for Gate E inner maxima."""

from __future__ import annotations

from dataclasses import dataclass
import math

from src.q2.code.geometry.circular_intervals import CircularIntervalUnion
from src.q2.code.geometry.primitives import Point2
from src.q2.code.model.q1_adapter import evaluate_q1


@dataclass(frozen=True)
class InnerVerificationReport:
    passed: bool
    dense_observed_max: float
    dense_worst_beta_deg: float
    checked_beta_count: int
    tolerance_m: float
    analytic_minus_dense_m: float
    failures: tuple[str, ...]


def verify_inner(
    S1: Point2,
    theta1: float,
    S2: Point2,
    allowed_beta: CircularIntervalUnion,
    candidate,
    epsilon: float,
    *,
    samples_per_component: int = 1025,
) -> InnerVerificationReport:
    """Cross-check a claimed maximum without invoking the production candidate path."""
    if samples_per_component < 3:
        raise ValueError("samples_per_component must be at least three.")
    samples = _independent_samples(
        S1, theta1, S2, allowed_beta, epsilon, samples_per_component
    )
    if not samples:
        raise ValueError("Cannot verify an empty bearing set.")

    observations: list[tuple[float, float, str]] = []
    for beta in samples:
        result = evaluate_q1(S1, theta1, S2, math.degrees(beta), epsilon)
        value = math.inf if result.unbounded else float(result.diameter or 0.0)
        observations.append((value, beta, result.status))
    dense_value, dense_beta, _ = max(observations, key=lambda row: row[0])
    claimed = float(candidate.Q)
    scale = max(
        1.0,
        0.0 if not math.isfinite(claimed) else claimed,
        0.0 if not math.isfinite(dense_value) else dense_value,
    )
    tolerance = max(5e-6, 2e-8 * scale)
    failures: list[str] = []
    if math.isfinite(dense_value):
        if not math.isfinite(claimed) and not _independent_infinite_evidence(observations):
            failures.append("infinite analytic claim has no independent unbounded or divergent evidence")
        elif math.isfinite(claimed) and claimed + tolerance < dense_value:
            failures.append("analytic candidate set underestimates the independent dense observation")
    elif not math.isinf(claimed):
        failures.append("independent oracle found an unbounded bearing")

    beta_rad = math.radians(float(candidate.worst_beta_deg))
    if not allowed_beta.contains(beta_rad, tolerance_rad=2e-12):
        failures.append("claimed worst beta is outside the expanded bearing set")
    reevaluated = evaluate_q1(S1, theta1, S2, candidate.worst_beta_deg, epsilon)
    reevaluated_value = math.inf if reevaluated.unbounded else float(reevaluated.diameter or 0.0)
    if math.isfinite(claimed) and abs(reevaluated_value - claimed) > tolerance:
        failures.append("claimed Q does not equal a direct pure-Q1 reevaluation")

    difference = (
        math.nan
        if math.isinf(claimed) and math.isinf(dense_value)
        else claimed - dense_value
    )
    return InnerVerificationReport(
        passed=not failures,
        dense_observed_max=dense_value,
        dense_worst_beta_deg=math.degrees(dense_beta) % 360.0,
        checked_beta_count=len(samples),
        tolerance_m=tolerance,
        analytic_minus_dense_m=difference,
        failures=tuple(failures),
    )


def _independent_samples(
    S1: Point2,
    theta1: float,
    S2: Point2,
    allowed: CircularIntervalUnion,
    epsilon: float,
    count: int,
) -> tuple[float, ...]:
    samples: list[float] = []
    for interval in allowed.intervals:
        span = interval.end_rad - interval.start_rad
        if span == 0.0:
            samples.append(interval.start_rad)
            continue
        samples.extend(
            interval.start_rad + span * index / (count - 1)
            for index in range(count)
        )

    epsilon_rad = math.radians(epsilon)
    apex = math.atan2(S1.y - S2.y, S1.x - S2.x)
    events = [apex - epsilon_rad, apex + epsilon_rad]
    theta_rad = math.radians(theta1)
    for first_side in (-1.0, 1.0):
        for second_side in (-1.0, 1.0):
            base = theta_rad + first_side * epsilon_rad - second_side * epsilon_rad
            events.extend((base, base + math.pi))
    for event in events:
        for delta in (0.0, 1e-3, -1e-3, 1e-5, -1e-5, 1e-7, -1e-7):
            beta = (event + delta) % math.tau
            if allowed.contains(beta, tolerance_rad=0.0):
                samples.append(beta)

    # Refine local maxima separately on each canonical component. Combining the
    # globally sorted samples would interpolate straight across a circular gap.
    refinement: list[float] = []
    for interval in allowed.intervals:
        coarse = sorted(
            {
                beta
                for beta in samples
                if interval.start_rad <= beta <= interval.end_rad
            }
        )
        if len(coarse) < 3:
            continue
        values = []
        for beta in coarse:
            result = evaluate_q1(S1, theta1, S2, math.degrees(beta), epsilon)
            values.append(math.inf if result.unbounded else float(result.diameter or 0.0))
        for index in range(1, len(coarse) - 1):
            if values[index] >= values[index - 1] and values[index] >= values[index + 1]:
                left, right = coarse[index - 1], coarse[index + 1]
                refinement.extend(
                    left + (right - left) * step / 16.0 for step in range(1, 16)
                )
    samples.extend(refinement)
    return tuple(
        sorted(
            {
                beta % math.tau
                for beta in samples
                if allowed.contains(beta, tolerance_rad=0.0)
            }
        )
    )


def _independent_infinite_evidence(
    observations: list[tuple[float, float, str]],
) -> bool:
    if any(math.isinf(value) or status == "UNBOUNDED" for value, _, status in observations):
        return True
    finite = sorted((value for value, _, _ in observations if math.isfinite(value)), reverse=True)
    return len(finite) >= 3 and finite[0] > 1e8 and finite[0] > 20.0 * finite[2]
