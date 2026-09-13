"""Deterministic E1--E5 maximization of the fixed-station Q2 objective."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable

from src.q2.code.geometry.circular_intervals import CircularIntervalUnion
from src.q2.code.geometry.primitives import Point2
from src.q2.code.model.q1_adapter import Q1AdapterResult, evaluate_q1


ROOT_TOL_RAD = 2e-13
MAX_ROOT_ISOLATION_DEPTH = 24
CURVATURE_REFINEMENT_RATIO = 1e-1


@dataclass(frozen=True)
class InnerCandidate:
    beta_rad: float
    candidate_type: str
    source_labels: tuple[str, ...]
    side: str | None = None
    limit_unbounded: bool = False


@dataclass(frozen=True)
class InnerMaxResult:
    Q: float
    worst_beta_deg: float
    candidate_type: str
    worst_q1: Q1AdapterResult
    candidates: tuple[InnerCandidate, ...]


@dataclass(frozen=True)
class _Line:
    a: float
    b: float
    c: float
    angle_rad: float


@dataclass(frozen=True)
class _AnalyticVertex:
    label: str
    point: Point2
    derivative: Point2


def construct_inner_candidates(
    S1: Point2,
    theta1: float,
    S2: Point2,
    allowed_beta: CircularIntervalUnion,
    epsilon: float,
) -> tuple[InnerCandidate, ...]:
    """Construct all finite E1--E5 candidates on analytic beta segments."""
    _validate_inputs(S1, theta1, S2, allowed_beta, epsilon)
    if allowed_beta.is_empty:
        return ()

    candidates: list[InnerCandidate] = []
    seen: set[tuple[str, int, str | None]] = set()

    def add(
        beta: float,
        kind: str,
        labels: tuple[str, ...],
        side: str | None = None,
        limit_unbounded: bool = False,
    ) -> None:
        canonical = beta % math.tau
        key = (kind, round(canonical / ROOT_TOL_RAD), side)
        if key not in seen and allowed_beta.contains(canonical, tolerance_rad=ROOT_TOL_RAD):
            seen.add(key)
            candidates.append(
                InnerCandidate(canonical, kind, labels, side, limit_unbounded)
            )

    intervals = tuple(
        (interval.start_rad, interval.end_rad) for interval in allowed_beta.intervals
    )
    for start, end in intervals:
        add(start, "E1", ("interval_start",))
        add(end, "E1", ("interval_end",))

    epsilon_rad = math.radians(epsilon)
    apex_direction = math.atan2(S1.y - S2.y, S1.x - S2.x)
    e2_events = _events_in_intervals(
        (apex_direction - epsilon_rad, apex_direction + epsilon_rad), intervals
    )
    for event in e2_events:
        add(event, "E2", ("second_wedge_apex",))

    parallel_bases: list[float] = []
    theta_rad = math.radians(theta1)
    for first_side in (-1.0, 1.0):
        for second_side in (-1.0, 1.0):
            base = theta_rad + first_side * epsilon_rad - second_side * epsilon_rad
            parallel_bases.extend((base, base + math.pi))
    e3_events = _events_in_intervals(tuple(parallel_bases), intervals)
    for event in e3_events:
        add(event, "E3", ("parallel_boundary",), "exact")

    break_events = e2_events + e3_events
    for start, end in intervals:
        cuts = [start, end]
        for event in break_events:
            unwrapped = _unwrap_into(event, start, end)
            if unwrapped is not None and start + ROOT_TOL_RAD < unwrapped < end - ROOT_TOL_RAD:
                cuts.append(unwrapped)
        cuts = _unique_sorted(cuts)
        for left, right in zip(cuts, cuts[1:]):
            if right - left <= 10.0 * ROOT_TOL_RAD:
                continue
            midpoint = 0.5 * (left + right)
            labels = tuple(vertex.label for vertex in _active_vertices(S1, theta1, S2, midpoint, epsilon))
            pairs = tuple(
                (labels[i], labels[j])
                for i in range(len(labels))
                for j in range(i + 1, len(labels))
            )

            for pair in pairs:
                def derivative(beta: float, pair=pair) -> float:
                    return _pair_derivative(S1, theta1, S2, beta, epsilon, pair)

                for root in _bracket_roots(derivative, left, right):
                    active = _active_pair_values(S1, theta1, S2, root, epsilon)
                    value = active.get(pair)
                    if value is not None and value >= max(active.values(), default=value) - 1e-6:
                        add(root, "E4", pair)

            for index, first in enumerate(pairs):
                for second in pairs[index + 1 :]:
                    def difference(beta: float, first=first, second=second) -> float:
                        return _pair_value(
                            S1, theta1, S2, beta, epsilon, first
                        ) - _pair_value(S1, theta1, S2, beta, epsilon, second)

                    for root in _bracket_roots(difference, left, right):
                        active = _active_pair_values(S1, theta1, S2, root, epsilon)
                        first_value = active.get(first)
                        second_value = active.get(second)
                        if first_value is None or second_value is None:
                            continue
                        envelope = max(active.values(), default=0.0)
                        tolerance = max(1e-5, 2e-9 * envelope)
                        if abs(first_value - second_value) <= tolerance and first_value >= envelope - tolerance:
                            add(root, "E5", first + second)

        for event in e3_events:
            event_unwrapped = _unwrap_into(event, start, end)
            if event_unwrapped is None:
                continue
            for sign, side, bound in ((-1.0, "left", start), (1.0, "right", end)):
                available = (event_unwrapped - bound) if sign < 0.0 else (bound - event_unwrapped)
                if available <= 10.0 * ROOT_TOL_RAD:
                    continue
                offset = min(available * 0.25, max(1e-8, available * 1e-6))
                probe = event_unwrapped + sign * offset
                divergent = _has_parallel_divergence(
                    S1, theta1, S2, event_unwrapped, probe, epsilon
                )
                add(probe, "E3", ("parallel_boundary", side), side, divergent)

    return tuple(candidates)


def maximize_inner(
    S1: Point2,
    theta1: float,
    S2: Point2,
    allowed_beta: CircularIntervalUnion,
    epsilon: float,
) -> InnerMaxResult:
    """Evaluate the Q1 diameter only at deterministic E1--E5 candidates."""
    candidates = construct_inner_candidates(S1, theta1, S2, allowed_beta, epsilon)
    if not candidates:
        raise ValueError("The expanded bearing set must be nonempty.")

    best_candidate: InnerCandidate | None = None
    best_q1: Q1AdapterResult | None = None
    best_value = -math.inf
    for candidate in candidates:
        q1 = evaluate_q1(S1, theta1, S2, math.degrees(candidate.beta_rad), epsilon)
        value = math.inf if q1.unbounded or candidate.limit_unbounded else float(q1.diameter or 0.0)
        if best_candidate is None or value > best_value:
            best_candidate = candidate
            best_q1 = q1
            best_value = value

    assert best_candidate is not None and best_q1 is not None
    return InnerMaxResult(
        Q=best_value,
        worst_beta_deg=math.degrees(best_candidate.beta_rad) % 360.0,
        candidate_type=best_candidate.candidate_type,
        worst_q1=best_q1,
        candidates=candidates,
    )


def _validate_inputs(S1, theta1, S2, allowed_beta, epsilon) -> None:
    if not isinstance(S1, Point2) or not isinstance(S2, Point2):
        raise TypeError("S1 and S2 must be Point2 values.")
    if not isinstance(allowed_beta, CircularIntervalUnion):
        raise TypeError("allowed_beta must be a CircularIntervalUnion.")
    if not all(math.isfinite(float(value)) for value in (theta1, epsilon)):
        raise ValueError("theta1 and epsilon must be finite.")
    if not 0.0 < float(epsilon) < 90.0:
        raise ValueError("epsilon must lie in (0, 90) degrees.")


def _events_in_intervals(
    bases: tuple[float, ...], intervals: tuple[tuple[float, float], ...]
) -> list[float]:
    events: list[float] = []
    for base in bases:
        for start, end in intervals:
            first_shift = math.floor((start - base) / math.tau) - 1
            for shift in range(first_shift, first_shift + 4):
                value = base + shift * math.tau
                if start - ROOT_TOL_RAD <= value <= end + ROOT_TOL_RAD:
                    events.append(value % math.tau)
    return _unique_circular(events)


def _unwrap_into(angle: float, start: float, end: float) -> float | None:
    canonical = angle % math.tau
    for shift in (-math.tau, 0.0, math.tau):
        value = canonical + shift
        if start - ROOT_TOL_RAD <= value <= end + ROOT_TOL_RAD:
            return min(end, max(start, value))
    return None


def _unique_sorted(values: list[float]) -> list[float]:
    result: list[float] = []
    for value in sorted(values):
        if not result or value - result[-1] > ROOT_TOL_RAD:
            result.append(value)
    return result


def _unique_circular(values: list[float]) -> list[float]:
    result: list[float] = []
    for value in sorted(value % math.tau for value in values):
        if not result or value - result[-1] > ROOT_TOL_RAD:
            result.append(value)
    return result


def _lines(S1: Point2, theta1: float, S2: Point2, beta_rad: float, epsilon: float) -> dict[str, _Line]:
    epsilon_rad = math.radians(epsilon)
    theta_rad = math.radians(theta1)
    result: dict[str, _Line] = {}
    for prefix, station, center in (("A", S1, theta_rad), ("B", S2, beta_rad)):
        for index, (angle, orientation) in enumerate(
            ((center - epsilon_rad, 1.0), (center + epsilon_rad, -1.0))
        ):
            a = orientation * math.sin(angle)
            b = -orientation * math.cos(angle)
            result[f"{prefix}{index}"] = _Line(a, b, a * station.x + b * station.y, angle)
    return result


def _active_vertices(
    S1: Point2, theta1: float, S2: Point2, beta_rad: float, epsilon: float
) -> tuple[_AnalyticVertex, ...]:
    lines = _lines(S1, theta1, S2, beta_rad, epsilon)
    definitions = (
        ("S1", "A0", "A1"),
        ("S2", "B0", "B1"),
        ("A0B0", "A0", "B0"),
        ("A0B1", "A0", "B1"),
        ("A1B0", "A1", "B0"),
        ("A1B1", "A1", "B1"),
    )
    vertices: list[_AnalyticVertex] = []
    for label, left, right in definitions:
        vertex = _vertex(S1, theta1, S2, beta_rad, epsilon, label)
        if vertex is None:
            continue
        scale = max(1.0, abs(vertex.point.x), abs(vertex.point.y), *(abs(line.c) for line in lines.values()))
        tolerance = 1e-9 + 2e-14 * scale
        if all(
            line.a * vertex.point.x + line.b * vertex.point.y <= line.c + tolerance
            for line in lines.values()
        ):
            vertices.append(vertex)
    return tuple(vertices)


def _vertex(
    S1: Point2, theta1: float, S2: Point2, beta_rad: float, epsilon: float, label: str
) -> _AnalyticVertex | None:
    if label == "S1":
        return _AnalyticVertex(label, S1, Point2(0.0, 0.0))
    if label == "S2":
        return _AnalyticVertex(label, S2, Point2(0.0, 0.0))
    first_index = int(label[1])
    second_index = int(label[3])
    first_angle = math.radians(theta1) + (-1.0 if first_index == 0 else 1.0) * math.radians(epsilon)
    second_angle = beta_rad + (-1.0 if second_index == 0 else 1.0) * math.radians(epsilon)
    ux, uy = math.cos(first_angle), math.sin(first_angle)
    vx, vy = math.cos(second_angle), math.sin(second_angle)
    dx, dy = S2.x - S1.x, S2.y - S1.y
    numerator = dx * vy - dy * vx
    denominator = ux * vy - uy * vx
    if abs(denominator) <= 1e-15:
        return None
    numerator_derivative = dx * vx + dy * vy
    denominator_derivative = ux * vx + uy * vy
    t = numerator / denominator
    derivative_t = (
        numerator_derivative * denominator - numerator * denominator_derivative
    ) / (denominator * denominator)
    return _AnalyticVertex(
        label,
        Point2(S1.x + t * ux, S1.y + t * uy),
        Point2(derivative_t * ux, derivative_t * uy),
    )


def _pair_value(S1, theta1, S2, beta, epsilon, pair: tuple[str, str]) -> float:
    first = _vertex(S1, theta1, S2, beta, epsilon, pair[0])
    second = _vertex(S1, theta1, S2, beta, epsilon, pair[1])
    if first is None or second is None:
        return math.nan
    dx = first.point.x - second.point.x
    dy = first.point.y - second.point.y
    return dx * dx + dy * dy


def _pair_derivative(S1, theta1, S2, beta, epsilon, pair: tuple[str, str]) -> float:
    first = _vertex(S1, theta1, S2, beta, epsilon, pair[0])
    second = _vertex(S1, theta1, S2, beta, epsilon, pair[1])
    if first is None or second is None:
        return math.nan
    dx = first.point.x - second.point.x
    dy = first.point.y - second.point.y
    ddx = first.derivative.x - second.derivative.x
    ddy = first.derivative.y - second.derivative.y
    return 2.0 * (dx * ddx + dy * ddy)


def _active_pair_values(S1, theta1, S2, beta, epsilon) -> dict[tuple[str, str], float]:
    vertices = _active_vertices(S1, theta1, S2, beta, epsilon)
    values: dict[tuple[str, str], float] = {}
    for i, first in enumerate(vertices):
        for second in vertices[i + 1 :]:
            pair = (first.label, second.label)
            values[pair] = _pair_value(S1, theta1, S2, beta, epsilon, pair)
    return values


def _bracket_roots(function: Callable[[float], float], start: float, end: float) -> tuple[float, ...]:
    if end < start or end - start <= ROOT_TOL_RAD:
        return ()
    cache: dict[float, float] = {}

    def value_at(point: float) -> float:
        if point not in cache:
            cache[point] = function(point)
        return cache[point]

    roots: list[float] = []

    def register(point: float) -> None:
        if start - ROOT_TOL_RAD <= point <= end + ROOT_TOL_RAD:
            roots.append(min(end, max(start, point)))

    def visit(left: float, right: float, left_value: float, right_value: float, depth: int) -> None:
        if not (math.isfinite(left_value) and math.isfinite(right_value)):
            return
        midpoint = 0.5 * (left + right)
        middle_value = value_at(midpoint)
        if not math.isfinite(middle_value):
            if depth < MAX_ROOT_ISOLATION_DEPTH:
                visit(left, midpoint, left_value, value_at(math.nextafter(midpoint, left)), depth + 1)
                visit(midpoint, right, value_at(math.nextafter(midpoint, right)), right_value, depth + 1)
            return

        scale = max(1.0, abs(left_value), abs(middle_value), abs(right_value))
        for point, value in (
            (left, left_value),
            (midpoint, middle_value),
            (right, right_value),
        ):
            if abs(value) <= 1e-13 * scale:
                register(point)

        left_crossing = left_value * middle_value < 0.0
        right_crossing = middle_value * right_value < 0.0
        if left_crossing:
            register(_bisect(function, left, midpoint, left_value))
        if right_crossing:
            register(_bisect(function, midpoint, right, middle_value))

        width = right - left
        if depth >= MAX_ROOT_ISOLATION_DEPTH or width <= ROOT_TOL_RAD:
            return
        half_width = 0.5 * width
        left_slope = (middle_value - left_value) / half_width
        right_slope = (right_value - middle_value) / half_width
        turning = left_slope * right_slope <= 0.0
        curvature = abs(right_slope - left_slope) * width
        shape_scale = max(
            abs(left_value), abs(middle_value), abs(right_value), 1e-300
        )
        nonlinear = curvature > CURVATURE_REFINEMENT_RATIO * shape_scale

        if turning:
            minimizer = _minimize_abs(function, left, right)
            minimum = function(minimizer)
            if math.isfinite(minimum) and abs(minimum) <= 1e-11 * scale:
                register(minimizer)

        # Sign-changing halves already contain one isolated simple root. Recurse
        # only when curvature or a turning point indicates another root may be
        # hidden in the same half.
        if turning or nonlinear:
            visit(left, midpoint, left_value, middle_value, depth + 1)
            visit(midpoint, right, middle_value, right_value, depth + 1)

    start_value = value_at(start)
    end_value = value_at(end)
    visit(start, end, start_value, end_value, 0)

    verified: list[float] = []
    for root in _unique_sorted(roots):
        root_value = function(root)
        delta = min(1e-7, max(ROOT_TOL_RAD, (end - start) * 1e-8))
        neighbour_scale = max(
            1.0,
            abs(function(max(start, root - delta))),
            abs(function(min(end, root + delta))),
        )
        if math.isfinite(root_value) and abs(root_value) <= 1e-7 * neighbour_scale:
            verified.append(root)
    return tuple(_unique_sorted(verified))


def _minimize_abs(function: Callable[[float], float], left: float, right: float) -> float:
    inverse_phi = (math.sqrt(5.0) - 1.0) / 2.0
    first = right - inverse_phi * (right - left)
    second = left + inverse_phi * (right - left)
    first_value = abs(function(first))
    second_value = abs(function(second))
    for _ in range(80):
        if right - left <= ROOT_TOL_RAD:
            break
        if first_value <= second_value:
            right, second, second_value = second, first, first_value
            first = right - inverse_phi * (right - left)
            first_value = abs(function(first))
        else:
            left, first, first_value = first, second, second_value
            second = left + inverse_phi * (right - left)
            second_value = abs(function(second))
    return first if first_value <= second_value else second


def _bisect(function: Callable[[float], float], left: float, right: float, left_value: float) -> float:
    for _ in range(64):
        midpoint = 0.5 * (left + right)
        value = function(midpoint)
        if right - left <= ROOT_TOL_RAD or value == 0.0:
            return midpoint
        if not math.isfinite(value):
            right = midpoint
        elif left_value * value <= 0.0:
            right = midpoint
        else:
            left, left_value = midpoint, value
    return 0.5 * (left + right)


def _has_parallel_divergence(S1, theta1, S2, event, probe, epsilon) -> bool:
    active = _active_vertices(S1, theta1, S2, probe, epsilon)
    if len(active) < 2:
        return False
    epsilon_rad = math.radians(epsilon)
    theta_rad = math.radians(theta1)
    divergent: list[str] = []
    for vertex in active:
        if not vertex.label.startswith("A") or "B" not in vertex.label:
            continue
        first_index = int(vertex.label[1])
        second_index = int(vertex.label[3])
        first_angle = theta_rad + (-1.0 if first_index == 0 else 1.0) * epsilon_rad
        second_angle = event + (-1.0 if second_index == 0 else 1.0) * epsilon_rad
        if abs(math.sin(second_angle - first_angle)) <= 1e-11:
            divergent.append(vertex.label)
    return bool(divergent) and any(vertex.label not in divergent for vertex in active)
