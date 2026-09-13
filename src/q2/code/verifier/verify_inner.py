"""Independent dense and event-refined verification for Gate E inner maxima."""

from __future__ import annotations

from dataclasses import dataclass
import math

from src.q2.code.geometry.circular_intervals import CircularIntervalUnion
from src.q2.code.geometry.primitives import Point2
from src.q2.code.model.q1_adapter import evaluate_q1


# The E3 parallel boundary events are theta1, theta1 +- 2*epsilon, theta1 + pi
# and theta1 + pi +- 2*epsilon.  The 3*epsilon admissibility gate excludes the
# exact same-side events from the expanded bearing set, but it provides no
# uniform positive margin: an allowed interval endpoint may sit arbitrarily close
# to an event that is still outside the interval.  The densification gate below
# is therefore the circular distance between an event and each allowed interval,
# not exact event membership.
PARALLEL_EVENT_FRACTION_OF_EPSILON = 1e-3
# Roundoff floor for the gate when epsilon degenerates; a machine-precision
# guard rather than a physical margin.
ENDPOINT_DENSIFICATION_FLOOR_RAD = 1e-12


def default_endpoint_densification_distance_rad(epsilon: float) -> float:
    """Default numeric gate on the event-to-allowed-interval circular distance."""
    epsilon_rad = abs(math.radians(float(epsilon)))
    return max(
        PARALLEL_EVENT_FRACTION_OF_EPSILON * epsilon_rad, ENDPOINT_DENSIFICATION_FLOOR_RAD
    )


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


@dataclass(frozen=True)
class IndependentInnerVerification:
    """Outcome of a scan that shares no root-isolation code with the main path.

    The independent ingredient is the search path over beta, not the Q1 polygon
    algorithm, which is shared through the adapter.  The 7.3 vocabulary is
    reported explicitly: ``q_main_raw`` is the main-path value before any
    promotion, ``q_verify`` is this scan's own maximum, ``q_returned`` is the
    value this report would return under its promotion rule, and
    ``gap_before_promotion`` is ``q_verify - q_main_raw``.  ``sampling_levels``
    lists ``(stage, generated sample count)`` for the ``base_uniform``,
    ``event_densification`` and ``golden_refinement`` stages, counted before
    canonical deduplication.  A finite scan, even with a zero gap, is a lower
    estimate over sampled bearings, never a global upper bound or a
    global-optimality certificate.
    """

    q_verify: float
    beta_verify_deg: float
    q_main: float
    beta_main_deg: float
    abs_gap: float
    relative_gap: float
    sample_count: int
    refinement_rounds: int
    converged: bool
    near_parallel_bands: int
    failures: tuple[str, ...]
    q_main_raw: float = math.nan
    q_returned: float = math.nan
    gap_before_promotion: float = math.nan
    promoted: bool = False
    sampling_levels: tuple[tuple[str, int], ...] = ()
    convergence_diagnostic: str = ""
    endpoint_densification_distance_rad: float = 0.0
    nearest_event_distance_rad: float = math.inf


def verify_inner_max_independent(
    S1: Point2,
    theta1: float,
    S2: Point2,
    allowed_beta: CircularIntervalUnion,
    epsilon: float,
    *,
    base_samples_per_interval: int = 65,
    peak_seeds: int = 2,
    refinement_iterations: int = 20,
    near_parallel_bands: int = 5,
    q_main: float | None = None,
    beta_main_deg: float | None = None,
    tolerance_m: float | None = None,
    endpoint_densification_distance_rad: float | None = None,
) -> IndependentInnerVerification:
    """Independently maximize D_Q1 over the allowed bearing set.

    Only the Q1 adapter is used; no production candidate-construction or
    root-isolation helper is imported or called (the Gate E structural guard
    enforces this).  The purpose is a structurally different second estimate of
    ``sup_beta D_Q1(S2, beta)``.  Each circular interval is uniformly sampled,
    intervals that come within the numeric gate of an E3 parallel event are
    densified on the event side of that endpoint, and the strongest local sample
    peaks are then refined one-dimensionally.
    """
    if not isinstance(allowed_beta, CircularIntervalUnion):
        raise TypeError("allowed_beta must be a CircularIntervalUnion.")
    if allowed_beta.is_empty:
        raise ValueError("Cannot independently verify an empty bearing set.")
    if base_samples_per_interval < 3:
        raise ValueError("base_samples_per_interval must be at least three.")
    if peak_seeds < 1 or refinement_iterations < 1 or near_parallel_bands < 0:
        raise ValueError("Independent scan refinement parameters are invalid.")
    if tolerance_m is None:
        scale = 1.0 if q_main is None or not math.isfinite(q_main) else max(1.0, abs(q_main))
        tolerance_m = max(1e-6, 1e-8 * scale)
    if endpoint_densification_distance_rad is None:
        densification_distance = default_endpoint_densification_distance_rad(epsilon)
    else:
        densification_distance = float(endpoint_densification_distance_rad)
        if not (math.isfinite(densification_distance) and densification_distance >= 0.0):
            raise ValueError(
                "endpoint_densification_distance_rad must be finite and nonnegative."
            )

    intervals = tuple(
        (interval.start_rad, interval.end_rad) for interval in allowed_beta.intervals
    )
    (
        samples,
        band_count,
        base_sample_count,
        densified_sample_count,
        nearest_event_distance,
    ) = _independent_scan_samples(
        allowed_beta,
        theta1,
        epsilon,
        base_samples_per_interval,
        near_parallel_bands,
        densification_distance,
    )
    if not samples:
        raise ValueError("Independent scan produced no bearing samples.")

    q_scan = -math.inf
    beta_scan = samples[0]
    sample_count = 0
    for beta in samples:
        value = _diameter_at(S1, theta1, S2, beta, epsilon)
        sample_count += 1
        if value > q_scan:
            q_scan, beta_scan = value, beta

    q_verify, beta_verify, refinement_evaluations, converged = _refine_sample_peaks(
        S1, theta1, S2, samples, intervals, epsilon, peak_seeds, refinement_iterations
    )
    sample_count += refinement_evaluations
    if q_verify < q_scan:
        q_verify, beta_verify = q_scan, beta_scan

    if q_main is None:
        abs_gap = math.nan
        relative_gap = math.nan
        failures: tuple[str, ...] = ()
    else:
        abs_gap = _safe_difference(q_verify, q_main)
        scale = 1.0 if not math.isfinite(q_main) else max(1.0, abs(q_main))
        relative_gap = abs_gap / scale if math.isfinite(abs_gap) else math.inf
        failures = (
            (
                "independent scan exceeds the production maximum by "
                f"{abs_gap:.6g} m (tolerance {tolerance_m:.3g} m)"
            ),
        ) if abs_gap > tolerance_m else ()

    q_main_raw = math.nan if q_main is None else q_main
    promoted = bool(math.isfinite(abs_gap) and abs_gap > tolerance_m)
    if q_main is None:
        q_returned = math.nan
    else:
        q_returned = q_verify if promoted else q_main
    sampling_levels = (
        ("base_uniform", base_sample_count),
        ("event_densification", densified_sample_count),
        ("golden_refinement", refinement_evaluations),
    )

    return IndependentInnerVerification(
        q_verify=q_verify,
        beta_verify_deg=math.degrees(beta_verify) % 360.0,
        q_main=q_main_raw,
        beta_main_deg=math.nan if beta_main_deg is None else beta_main_deg % 360.0,
        abs_gap=abs_gap,
        relative_gap=relative_gap,
        sample_count=sample_count,
        refinement_rounds=refinement_iterations,
        converged=converged,
        near_parallel_bands=band_count,
        failures=failures,
        q_main_raw=q_main_raw,
        q_returned=q_returned,
        gap_before_promotion=abs_gap,
        promoted=promoted,
        sampling_levels=sampling_levels,
        convergence_diagnostic=_convergence_diagnostic(
            q_verify=q_verify,
            converged=converged,
            sampled_bearings=len(samples),
            sample_count=sample_count,
            nearest_event_distance=nearest_event_distance,
            densification_distance=densification_distance,
            band_count=band_count,
        ),
        endpoint_densification_distance_rad=densification_distance,
        nearest_event_distance_rad=nearest_event_distance,
    )


def _convergence_diagnostic(
    *,
    q_verify: float,
    converged: bool,
    sampled_bearings: int,
    sample_count: int,
    nearest_event_distance: float,
    densification_distance: float,
    band_count: int,
) -> str:
    if not converged:
        status = (
            "not converged: no interior sample peak was bracketed for golden-section "
            "refinement, so the reported value is a finite-sample lower estimate"
        )
    elif math.isinf(q_verify):
        status = (
            "stopped at an unbounded Q1 branch; the scan value is exact only for that "
            "unbounded branch, not a certified global upper bound"
        )
    else:
        status = (
            "converged: golden-section refinement of the strongest sample peaks stalled "
            "within 1e-9 relative; a finite scan remains a lower estimate, not a "
            "global-optimality certificate"
        )
    return (
        f"{status}; {sampled_bearings} sampled bearings "
        f"({sample_count} Q1 evaluations), nearest parallel-event distance "
        f"{nearest_event_distance:.3e} rad vs gate {densification_distance:.3e} rad, "
        f"{band_count} densified event/interval pairs"
    )


def _diameter_at(S1: Point2, theta1: float, S2: Point2, beta_rad: float, epsilon: float) -> float:
    result = evaluate_q1(S1, theta1, S2, math.degrees(beta_rad), epsilon)
    if result.unbounded:
        return math.inf
    return float(result.diameter or 0.0)


def _parallel_events(theta1: float, epsilon: float) -> tuple[float, ...]:
    """The E3 parallel boundary directions, canonicalized and deduplicated."""
    theta_rad = math.radians(theta1)
    epsilon_rad = math.radians(epsilon)
    events: list[float] = []
    for first_side in (-1.0, 1.0):
        for second_side in (-1.0, 1.0):
            base = theta_rad + (first_side - second_side) * epsilon_rad
            events.extend((base, base + math.pi))
    unique: list[float] = []
    for event in sorted(value % math.tau for value in events):
        if not unique or _circular_distance(event, unique[-1]) > 1e-15:
            unique.append(event)
    return tuple(unique)


def _circular_distance(left: float, right: float) -> float:
    return abs((left - right + math.pi) % math.tau - math.pi)


def _event_interval_distance(
    event: float, start: float, end: float
) -> tuple[float, float | None]:
    """Circular distance from an event to a closed interval.

    The second element is the event unwrapped onto the interval's branch when it
    lies inside the interval, and ``None`` when the event is strictly outside.
    """
    canonical = event % math.tau
    for shift in (-math.tau, 0.0, math.tau):
        value = canonical + shift
        if start <= value <= end:
            return 0.0, value
    return (
        min(
            _circular_distance(canonical, start % math.tau),
            _circular_distance(canonical, end % math.tau),
        ),
        None,
    )


def _event_densification_samples(
    start: float,
    end: float,
    event: float,
    inside_value: float | None,
    window: float,
    levels: int,
) -> list[float]:
    """Multi-scale samples around an event, always kept inside [start, end]."""
    if inside_value is not None:
        anchor = min(end, max(start, inside_value))
        angles = [anchor]
        for exponent in range(levels):
            delta = window * (2.0 ** -(exponent + 1))
            angles.extend((anchor - delta, anchor + delta))
        return [min(end, max(start, angle)) for angle in angles]
    if _circular_distance(event % math.tau, start % math.tau) <= _circular_distance(
        event % math.tau, end % math.tau
    ):
        return [start] + [
            start + window * (2.0 ** -(exponent + 1)) for exponent in range(levels)
        ]
    return [end] + [
        end - window * (2.0 ** -(exponent + 1)) for exponent in range(levels)
    ]


def _independent_scan_samples(
    allowed: CircularIntervalUnion,
    theta1: float,
    epsilon: float,
    base_samples: int,
    near_parallel_bands: int,
    endpoint_densification_distance_rad: float | None = None,
) -> tuple[tuple[float, ...], int, int, int, float]:
    """Uniform per-interval samples plus distance-driven near-parallel densification.

    For every (allowed interval, E3 event) pair the circular distance between the
    event and the closed interval is measured.  When it falls below the numeric
    gate the interval is densified on the event side of the nearest endpoint with
    a geometric sequence of levels, or around the event itself when the event is
    inside the interval.  Generated samples are canonicalized and filtered through
    ``allowed.contains(beta, tolerance_rad=0.0)``, so densification never leaves
    the allowed bearing set.

    Returns ``(samples, band_count, base_sample_count, densified_sample_count,
    nearest_event_distance)``; the two sample counts are generated before
    canonical deduplication.
    """
    epsilon_rad = math.radians(epsilon)
    threshold = (
        default_endpoint_densification_distance_rad(epsilon)
        if endpoint_densification_distance_rad is None
        else float(endpoint_densification_distance_rad)
    )
    if not (math.isfinite(threshold) and threshold >= 0.0):
        raise ValueError(
            "endpoint_densification_distance_rad must be finite and nonnegative."
        )
    events = _parallel_events(theta1, epsilon)

    samples: list[float] = []
    base_sample_count = 0
    densified_sample_count = 0
    band_count = 0
    nearest_event_distance = math.inf
    for interval in allowed.intervals:
        start, end = interval.start_rad, interval.end_rad
        span = end - start
        if span <= 0.0:
            samples.append(start)
            base_sample_count += 1
            continue
        uniform = [
            start + span * index / (base_samples - 1) for index in range(base_samples)
        ]
        samples.extend(uniform)
        base_sample_count += len(uniform)
        window = min(span, 2.0 * epsilon_rad) if epsilon_rad > 0.0 else span
        for event in events:
            distance, inside_value = _event_interval_distance(event, start, end)
            nearest_event_distance = min(nearest_event_distance, distance)
            if not distance < threshold:
                continue
            band_count += 1
            for beta in _event_densification_samples(
                start, end, event, inside_value, window, near_parallel_bands
            ):
                if start <= beta <= end:
                    samples.append(beta)
                    densified_sample_count += 1
    return (
        _sorted_unique(
            [
                beta % math.tau
                for beta in samples
                if allowed.contains(beta % math.tau, tolerance_rad=0.0)
            ]
        ),
        band_count,
        base_sample_count,
        densified_sample_count,
        nearest_event_distance,
    )


def _refine_sample_peaks(
    S1: Point2,
    theta1: float,
    S2: Point2,
    samples: tuple[float, ...],
    intervals: tuple[tuple[float, float], ...],
    epsilon: float,
    peak_seeds: int,
    iterations: int,
) -> tuple[float, float, int, bool]:
    evaluations = 0
    best_value = -math.inf
    best_beta = samples[0]
    converged = True
    refined_any = False
    for start, end in intervals:
        local = [beta for beta in samples if start <= beta <= end]
        if len(local) < 3:
            continue
        values = [_diameter_at(S1, theta1, S2, beta, epsilon) for beta in local]
        evaluations += len(local)
        peaks = [
            index
            for index in range(1, len(local) - 1)
            if values[index] >= values[index - 1] and values[index] >= values[index + 1]
        ]
        peaks.sort(key=lambda index: values[index], reverse=True)
        for index in peaks[:peak_seeds]:
            value, beta, trace = _golden_max(
                lambda angle: _diameter_at(S1, theta1, S2, angle, epsilon),
                local[index - 1],
                local[index + 1],
                iterations,
            )
            evaluations += 2 * iterations + 2
            refined_any = True
            if value > best_value:
                best_value, best_beta = value, beta
            if len(trace) >= 4:
                improvement = trace[-1] - trace[-4]
                converged = converged and improvement <= 1e-9 * max(1.0, abs(trace[-1]))
    if not refined_any:
        best_value, best_beta = max(
            (
                (_diameter_at(S1, theta1, S2, beta, epsilon), beta)
                for beta in samples
            ),
            key=lambda item: item[0],
        )
        evaluations += len(samples)
        converged = False
    return best_value, best_beta, evaluations, converged


def _golden_max(function, left: float, right: float, iterations: int):
    inverse_phi = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = left, right
    c = b - inverse_phi * (b - a)
    d = a + inverse_phi * (b - a)
    fc, fd = function(c), function(d)
    best_seen = max(fc, fd)
    trace: list[float] = [best_seen]
    for _ in range(iterations):
        if b - a <= 1e-12:
            break
        if fc >= fd:
            b, d, fd = d, c, fc
            c = b - inverse_phi * (b - a)
            fc = function(c)
        else:
            a, c, fc = c, d, fd
            d = a + inverse_phi * (b - a)
            fd = function(d)
        best_seen = max(best_seen, fc, fd)
        trace.append(best_seen)
    candidates = ((fc, c), (fd, d), (function(a), a), (function(b), b))
    value, beta = max(candidates, key=lambda item: item[0])
    return value, beta, trace


def _sorted_unique(values: list[float]) -> tuple[float, ...]:
    unique: list[float] = []
    for value in sorted(values):
        if not unique or value - unique[-1] > 1e-15:
            unique.append(value)
    return tuple(unique)


def _safe_difference(candidate: float, reference: float) -> float:
    if math.isinf(candidate) and math.isinf(reference):
        return 0.0
    if math.isinf(candidate):
        return math.inf
    if math.isinf(reference):
        return -math.inf
    return candidate - reference
