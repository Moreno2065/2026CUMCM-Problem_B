"""Distance-driven near-parallel endpoint densification (Prompt v2 sections 7.1, 7.3).

The 3*epsilon admissibility gate excludes the exact same-side E3 events
``beta = theta1 +- 2*epsilon`` from an admissible expanded bearing set, but it
gives no uniform positive margin: an allowed interval endpoint can sit
arbitrarily close to an event that is still strictly outside the interval.  The
densification condition must therefore be the circular distance between the
event and the interval, not exact event membership.
"""

from __future__ import annotations

import math

import pytest

from src.q2.code.geometry.a1 import FirstObservation, build_a1
from src.q2.code.geometry.angular_image import build_angular_image
from src.q2.code.geometry.circular_intervals import CircularIntervalUnion
from src.q2.code.geometry.primitives import Point2
from src.q2.code.model.q1_adapter import evaluate_q1
from src.q2.code.solver.inner_max import maximize_inner
from src.q2.code.solver.q2_point import evaluate_q2_point
from src.q2.code.verifier.verify_inner import (
    PARALLEL_EVENT_FRACTION_OF_EPSILON,
    _independent_scan_samples,
    default_endpoint_densification_distance_rad,
    verify_inner_max_independent,
)

S1 = Point2(0.0, 0.0)
THETA1 = 0.0
EPSILON = 1.0
DEFAULT_GATE_RAD = default_endpoint_densification_distance_rad(EPSILON)
# theta1, theta1 +- 2*epsilon, theta1 + pi and theta1 + pi +- 2*epsilon, restated
# here independently of the module under test.
_PARALLEL_EVENT_DEGREES = (
    THETA1 - 2.0 * EPSILON,
    THETA1,
    THETA1 + 2.0 * EPSILON,
    THETA1 + 180.0 - 2.0 * EPSILON,
    THETA1 + 180.0,
    THETA1 + 180.0 + 2.0 * EPSILON,
)
PARALLEL_EVENTS_RAD = tuple(
    sorted(math.radians(angle) % math.tau for angle in _PARALLEL_EVENT_DEGREES)
)
# A station on the centre ray just inside the 3*epsilon gate: its expanded
# bearing interval endpoint sits 4.0e-7 rad from the theta1 - 2*epsilon event,
# far below the default gate of 1e-3 * radians(epsilon).
NEAR_GATE_POINT = Point2(600.0, 73.334)
FAR_FROM_EVENTS_POINT = Point2(750.0, 500.0)


def _circular_distance(left: float, right: float) -> float:
    return abs((left - right + math.pi) % math.tau - math.pi)


def _allowed(point: Point2) -> CircularIntervalUnion:
    a1 = build_a1(FirstObservation(S1, THETA1, EPSILON))
    return build_angular_image(a1, point).expanded_closure


def _min_endpoint_event_distance(allowed: CircularIntervalUnion) -> float:
    return min(
        _circular_distance(endpoint, event)
        for interval in allowed.intervals
        for endpoint in (interval.start_rad, interval.end_rad % math.tau)
        for event in PARALLEL_EVENTS_RAD
    )


def _events_inside(allowed: CircularIntervalUnion) -> tuple[float, ...]:
    return tuple(
        event
        for event in PARALLEL_EVENTS_RAD
        if allowed.contains(event, tolerance_rad=0.0)
    )


def _scan(allowed, bands: int = 5, gate: float | None = None):
    return _independent_scan_samples(
        allowed, THETA1, EPSILON, 65, bands, gate
    )


def test_default_gate_is_a_declared_fraction_of_epsilon() -> None:
    assert math.isclose(
        DEFAULT_GATE_RAD,
        PARALLEL_EVENT_FRACTION_OF_EPSILON * math.radians(EPSILON),
        rel_tol=1e-12,
    )
    assert math.isclose(DEFAULT_GATE_RAD, 1.7453292519943295e-05, rel_tol=1e-9)


def test_legal_point_with_endpoint_near_the_parallel_event_triggers_densification() -> None:
    """(a) admissible point, endpoint-to-event distance below the gate."""
    result = evaluate_q2_point(S1, THETA1, NEAR_GATE_POINT, EPSILON)
    assert result.in_crec is True
    assert result.all_near is False
    assert result.admissible is True, result.worst_candidate_type

    allowed = _allowed(NEAR_GATE_POINT)
    distance = _min_endpoint_event_distance(allowed)
    assert distance < DEFAULT_GATE_RAD, (distance, DEFAULT_GATE_RAD)

    # The exact same-side event is still excluded from the expanded set: the
    # endpoint merely comes numerically close to it.
    near_event = math.radians(THETA1 - 2.0 * EPSILON) % math.tau
    assert allowed.contains(near_event, tolerance_rad=0.0) is False
    assert _circular_distance(allowed.intervals[-1].end_rad, near_event) < DEFAULT_GATE_RAD

    samples, bands, base_count, densified_count, nearest = _scan(allowed)
    assert bands > 0
    assert densified_count > 0
    assert nearest < DEFAULT_GATE_RAD
    assert base_count >= 65
    assert all(allowed.contains(beta, tolerance_rad=0.0) for beta in samples)
    assert min(samples) >= allowed.intervals[0].start_rad
    assert max(samples) <= allowed.intervals[-1].end_rad

    # The gate is genuinely the numerical trigger: a much smaller explicit gate
    # on the same geometry produces no densified sample.
    _, tight_bands, _, tight_densified, _ = _scan(allowed, gate=1e-12)
    assert tight_bands == 0
    assert tight_densified == 0

    verification = verify_inner_max_independent(
        S1,
        THETA1,
        NEAR_GATE_POINT,
        allowed,
        EPSILON,
        q_main=result.Q,
        beta_main_deg=result.worst_beta,
    )
    assert verification.near_parallel_bands > 0
    assert verification.nearest_event_distance_rad < DEFAULT_GATE_RAD
    assert math.isclose(
        verification.endpoint_densification_distance_rad, DEFAULT_GATE_RAD, rel_tol=1e-12
    )
    assert not verification.failures, verification.failures


def test_legal_point_far_from_every_event_does_not_densify() -> None:
    """(b) legal point whose interval stays far from all parallel events."""
    allowed = _allowed(FAR_FROM_EVENTS_POINT)
    distance = _min_endpoint_event_distance(allowed)
    assert distance > DEFAULT_GATE_RAD
    assert _events_inside(allowed) == ()

    samples, bands, base_count, densified_count, nearest = _scan(allowed)
    assert bands == 0
    assert densified_count == 0
    assert nearest > DEFAULT_GATE_RAD
    assert base_count >= 65
    assert all(allowed.contains(beta, tolerance_rad=0.0) for beta in samples)

    main = maximize_inner(S1, THETA1, FAR_FROM_EVENTS_POINT, allowed, EPSILON)
    verification = verify_inner_max_independent(
        S1,
        THETA1,
        FAR_FROM_EVENTS_POINT,
        allowed,
        EPSILON,
        q_main=main.Q,
        beta_main_deg=main.worst_beta_deg,
    )
    assert verification.near_parallel_bands == 0
    assert verification.nearest_event_distance_rad > DEFAULT_GATE_RAD
    assert not verification.failures, verification.failures
    assert math.isfinite(verification.q_verify)


def test_event_outside_the_interval_endpoint_is_densified_from_inside() -> None:
    """An antiparallel event just outside an endpoint is not a hard exclusion."""
    event = math.radians(THETA1 + 180.0 + 2.0 * EPSILON) % math.tau
    end = event - 0.25 * DEFAULT_GATE_RAD
    allowed = CircularIntervalUnion.from_intervals(((math.pi - 0.5, end),))
    assert allowed.contains(event, tolerance_rad=0.0) is False
    assert _circular_distance(end, event) < DEFAULT_GATE_RAD

    samples, bands, _, densified_count, _ = _scan(allowed)
    assert bands >= 1
    assert densified_count > 0
    assert all(allowed.contains(beta, tolerance_rad=0.0) for beta in samples)
    assert max(beta for beta in samples) <= end
    # Densification approaches the event from inside without ever reaching it.
    assert max(beta for beta in samples) < event
    assert not allowed.contains(event, tolerance_rad=0.0)


def test_densification_never_leaves_a_multi_component_or_wrapped_union() -> None:
    """(d) overflow check across components, wrap-around and narrow intervals."""
    unions = (
        CircularIntervalUnion.from_intervals(((0.10, 0.20), (1.00, 1.40))),
        CircularIntervalUnion.from_intervals(((math.pi - 0.2, math.pi + 0.2),)),
        CircularIntervalUnion.from_intervals(((6.0, 6.6 + 0.5),)),
        CircularIntervalUnion.from_intervals(
            ((math.tau - 1e-6, math.tau), (0.0, 1e-6))
        ),
        CircularIntervalUnion.from_intervals(((3.0, 3.0), (5.0, 6.0))),
    )
    for allowed in unions:
        samples, bands, base_count, densified_count, nearest = _scan(allowed)
        assert samples, allowed
        assert base_count > 0
        assert math.isfinite(nearest)
        for beta in samples:
            assert allowed.contains(beta, tolerance_rad=0.0), (beta, allowed)
        # Densification must add samples when a band is detected, and the level
        # count is a budget rather than a trigger.
        _, zero_bands, _, zero_densified, _ = _scan(allowed, bands=0)
        assert zero_bands == bands
        assert zero_densified <= densified_count


def test_antiparallel_event_directions_stay_bounded_but_degraded() -> None:
    """(c) theta1 + pi and theta1 + pi +- 2*epsilon are bounded, not excluded."""
    station = Point2(950.0, 120.0)
    line_bearing = math.degrees(math.atan2(station.y, station.x))

    antiparallel = evaluate_q1(S1, THETA1, station, (line_bearing + 180.0) % 360.0, EPSILON)
    other = evaluate_q1(S1, THETA1, station, 270.0, EPSILON)
    assert antiparallel.unbounded is False
    assert antiparallel.status == "OK"
    assert antiparallel.diameter is not None and math.isfinite(antiparallel.diameter)
    assert other.unbounded is False
    assert other.diameter is not None and math.isfinite(other.diameter)
    # Only the ordering is asserted; no deterioration factor is hard-coded.
    assert antiparallel.diameter > other.diameter

    for offset in (-2.0 * EPSILON, 0.0, 2.0 * EPSILON):
        event = (line_bearing + 180.0 + offset) % 360.0
        result = evaluate_q1(S1, THETA1, station, event, EPSILON)
        assert result.unbounded is False, event
        assert result.diameter is None or math.isfinite(result.diameter), event
    # And the 3*epsilon gate is not a 180-degree exclusion: an interval may
    # legally contain the antiparallel direction.
    assert math.radians(THETA1 + 180.0) % math.tau in PARALLEL_EVENTS_RAD
    straddling = CircularIntervalUnion.from_intervals(
        ((math.pi - 0.2, math.pi + 0.2),)
    )
    assert straddling.contains(math.radians(THETA1 + 180.0), tolerance_rad=0.0)
    _, bands, _, densified_count, _ = _scan(straddling)
    assert bands >= 1
    assert densified_count > 0


def test_report_exposes_the_7_3_vocabulary() -> None:
    allowed = _allowed(FAR_FROM_EVENTS_POINT)
    main = maximize_inner(S1, THETA1, FAR_FROM_EVENTS_POINT, allowed, EPSILON)

    verification = verify_inner_max_independent(
        S1,
        THETA1,
        FAR_FROM_EVENTS_POINT,
        allowed,
        EPSILON,
        q_main=main.Q,
        beta_main_deg=main.worst_beta_deg,
    )

    assert verification.q_main_raw == verification.q_main == main.Q
    assert math.isclose(
        verification.gap_before_promotion, verification.abs_gap, rel_tol=0.0, abs_tol=0.0
    )
    assert verification.promoted is False
    assert verification.q_returned == main.Q
    assert dict(verification.sampling_levels)["base_uniform"] >= 3
    assert dict(verification.sampling_levels)["golden_refinement"] > 0
    assert "event_densification" in dict(verification.sampling_levels)
    assert isinstance(verification.convergence_diagnostic, str)
    assert "lower estimate" in verification.convergence_diagnostic
    assert "global" in verification.convergence_diagnostic
    assert math.isfinite(verification.nearest_event_distance_rad)
    # The existing field names keep their meaning.
    assert verification.refinement_rounds > 0
    assert verification.sample_count > 0
    assert verification.relative_gap == verification.abs_gap / max(1.0, abs(main.Q))


def test_promotion_bookkeeping_uses_a_synthetic_raw_main_value() -> None:
    """The promotion vocabulary is exercised with a deliberately low raw value.

    This is bookkeeping for the reported fields, not a production claim: the
    synthetic ``q_main_raw`` sits 10 m below the scan maximum.
    """
    allowed = _allowed(FAR_FROM_EVENTS_POINT)
    probe = verify_inner_max_independent(
        S1, THETA1, FAR_FROM_EVENTS_POINT, allowed, EPSILON
    )
    raw_main = probe.q_verify - 10.0

    verification = verify_inner_max_independent(
        S1,
        THETA1,
        FAR_FROM_EVENTS_POINT,
        allowed,
        EPSILON,
        q_main=raw_main,
        beta_main_deg=0.0,
    )

    assert verification.promoted is True
    assert verification.q_returned == verification.q_verify
    assert verification.q_main_raw == raw_main
    assert math.isclose(
        verification.gap_before_promotion,
        verification.q_verify - raw_main,
        rel_tol=1e-12,
    )
    assert verification.failures


def test_scan_rejects_an_invalid_densification_gate() -> None:
    allowed = _allowed(FAR_FROM_EVENTS_POINT)
    with pytest.raises(ValueError):
        verify_inner_max_independent(
            S1,
            THETA1,
            FAR_FROM_EVENTS_POINT,
            allowed,
            EPSILON,
            endpoint_densification_distance_rad=-1.0,
        )
    with pytest.raises(ValueError):
        verify_inner_max_independent(
            S1,
            THETA1,
            FAR_FROM_EVENTS_POINT,
            allowed,
            EPSILON,
            endpoint_densification_distance_rad=math.inf,
        )
    with pytest.raises(ValueError):
        _independent_scan_samples(allowed, THETA1, EPSILON, 65, 5, -1.0)
