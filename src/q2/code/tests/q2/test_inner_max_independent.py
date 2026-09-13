"""Independent inner-max scan: no underestimation, degeneracies and E4/E5 paths."""

from __future__ import annotations

import math

import pytest

from src.q2.code.geometry.a1 import FirstObservation, build_a1
from src.q2.code.geometry.angular_image import build_angular_image
from src.q2.code.geometry.circular_intervals import CircularIntervalUnion
from src.q2.code.geometry.primitives import Point2
from src.q2.code.model.q1_adapter import evaluate_q1
from src.q2.code.solver.inner_max import (
    InnerVerificationConfig,
    _active_vertices,
    _bracket_roots,
    _pair_derivative,
    construct_inner_candidates,
    maximize_inner,
    maximize_inner_verified,
)
from src.q2.code.solver.q2_point import evaluate_q2_point
from src.q2.code.verifier.verify_inner import verify_inner_max_independent


S1 = Point2(0.0, 0.0)
THETA1 = 0.0
REPRESENTATIVE_POINTS = (
    Point2(750.0, 500.0),
    Point2(400.0, 300.0),
    Point2(1120.0, -650.0),
    Point2(-300.0, 600.0),
)


def _allowed(point: Point2, theta1: float = THETA1) -> CircularIntervalUnion:
    a1 = build_a1(FirstObservation(S1, theta1, 1.0))
    return build_angular_image(a1, point).expanded_closure


def test_independent_scan_never_reports_a_maximum_above_the_main_candidate_set() -> None:
    """The verifier is a coarser lower estimate: the guarantee is one-sided.

    A dense finite scan may legitimately miss the true peak, so it can sit below
    the production value.  What must never happen is the reverse: the verifier
    must not find a materially larger diameter than the candidate set.  Measured
    gaps (including negative ones where the scan under-shoots) are reported.
    """
    for point in REPRESENTATIVE_POINTS:
        allowed = _allowed(point)
        if allowed.is_empty:
            continue
        main = maximize_inner(S1, THETA1, point, allowed, 1.0)
        verification = verify_inner_max_independent(
            S1,
            THETA1,
            point,
            allowed,
            1.0,
            q_main=main.Q,
            beta_main_deg=main.worst_beta_deg,
        )

        assert verification.sample_count > 0
        assert verification.refinement_rounds > 0
        assert not verification.failures, verification.failures
        assert math.isfinite(verification.q_verify)
        assert verification.q_verify > 0.0
        assert verification.q_verify <= main.Q + 1e-4
        assert math.isfinite(verification.relative_gap)
        assert allowed.contains(
            math.radians(verification.beta_verify_deg), tolerance_rad=1e-12
        )


def test_verified_facade_returns_the_main_result_when_no_promotion_is_needed() -> None:
    point = Point2(750.0, 500.0)
    allowed = _allowed(point)

    main = maximize_inner(S1, THETA1, point, allowed, 1.0)
    verified = maximize_inner_verified(S1, THETA1, point, allowed, 1.0)

    assert verified.Q == main.Q
    assert verified.candidate_type == main.candidate_type
    assert verified.worst_beta_deg == main.worst_beta_deg


def test_near_parallel_boundaries_are_explicitly_densified() -> None:
    point = Point2(750.0, 500.0)
    # The 3*epsilon gate structurally excludes the parallel events from any
    # admissible expanded bearing set, so the densification mechanism is
    # exercised on an interval that deliberately straddles theta1 + 180 deg.
    allowed = CircularIntervalUnion.from_intervals(
        ((math.pi - 0.2, math.pi + 0.2),)
    )

    without = verify_inner_max_independent(
        S1, THETA1, point, allowed, 1.0, near_parallel_bands=0
    )
    with_bands = verify_inner_max_independent(
        S1, THETA1, point, allowed, 1.0, near_parallel_bands=6
    )

    assert without.near_parallel_bands >= 3
    assert with_bands.near_parallel_bands == without.near_parallel_bands
    assert with_bands.sample_count > without.sample_count
    assert not with_bands.failures, with_bands.failures


def test_admissible_bearing_sets_structurally_exclude_the_parallel_events() -> None:
    """For admissible stations the 3*epsilon gate puts beta = theta1 +- 2*eps
    strictly outside the expanded set, so no densification band is created."""
    point = Point2(600.0, 76.0)
    allowed = _allowed(point)
    main = maximize_inner(S1, THETA1, point, allowed, 1.0)
    verification = verify_inner_max_independent(
        S1,
        THETA1,
        point,
        allowed,
        1.0,
        q_main=main.Q,
        beta_main_deg=main.worst_beta_deg,
    )
    assert verification.near_parallel_bands == 0
    assert not verification.failures, verification.failures


@pytest.mark.parametrize("theta1", [359.5, 0.5, 0.0])
def test_theta1_wrap_is_supported_by_main_and_independent_paths(theta1: float) -> None:
    point = Point2(750.0, 500.0)
    allowed = _allowed(point, theta1)

    main = maximize_inner(S1, theta1, point, allowed, 1.0)
    verification = verify_inner_max_independent(
        S1,
        theta1,
        point,
        allowed,
        1.0,
        q_main=main.Q,
        beta_main_deg=main.worst_beta_deg,
    )

    assert not verification.failures, verification.failures


def test_multi_interval_allowed_beta_is_fully_sampled() -> None:
    point = Point2(750.0, 500.0)
    allowed = CircularIntervalUnion.from_intervals(((0.10, 0.20), (1.00, 1.40)))

    main = maximize_inner(S1, THETA1, point, allowed, 1.0)
    verification = verify_inner_max_independent(
        S1,
        THETA1,
        point,
        allowed,
        1.0,
        q_main=main.Q,
        beta_main_deg=main.worst_beta_deg,
    )

    assert not verification.failures, verification.failures
    assert verification.q_verify >= main.Q - 1e-9


def test_three_epsilon_gate_first_degrades_q_then_blocks_the_station() -> None:
    admissible_values: list[float] = []
    for y in (120.0, 90.0, 80.0, 76.0, 75.0):
        result = evaluate_q2_point(S1, THETA1, Point2(600.0, y), 1.0)
        assert result.admissible is True
        assert result.Q is not None and math.isfinite(result.Q)
        admissible_values.append(float(result.Q))

    # Approaching the 3*epsilon boundary makes the worst-case diameter explode.
    assert all(
        later > earlier
        for earlier, later in zip(admissible_values, admissible_values[1:])
    ), admissible_values

    blocked = evaluate_q2_point(S1, THETA1, Point2(600.0, 70.0), 1.0)
    assert blocked.admissible is False
    assert blocked.worst_candidate_type == "INADMISSIBLE"
    assert blocked.Q is None


def test_antiparallel_sight_lines_are_bounded_but_much_worse_than_orthogonal() -> None:
    station = Point2(950.0, 120.0)

    antiparallel = evaluate_q1(S1, THETA1, station, 187.2, 1.0)
    orthogonal = evaluate_q1(S1, THETA1, station, 270.0, 1.0)

    assert not antiparallel.unbounded
    assert antiparallel.diameter is not None and math.isfinite(antiparallel.diameter)
    assert not orthogonal.unbounded
    assert orthogonal.diameter is not None and math.isfinite(orthogonal.diameter)
    # Only the real ordering is asserted; no fixed deterioration factor is
    # hard-coded.  The measured values are reported for the paper.
    assert antiparallel.diameter > orthogonal.diameter
    assert antiparallel.status == "OK"


def test_e5_envelope_switch_dominated_case_is_independently_confirmed() -> None:
    # Solver-level fixture: this station is outside Crec, and the bearing set is
    # built directly from its angular image, so it exercises the inner maximizer
    # rather than an admissible production point.
    point = Point2(1120.0, -650.0)
    allowed = _allowed(point)

    main = maximize_inner(S1, THETA1, point, allowed, 1.0)
    assert main.candidate_type == "E5"

    verification = verify_inner_max_independent(
        S1,
        THETA1,
        point,
        allowed,
        1.0,
        q_main=main.Q,
        beta_main_deg=main.worst_beta_deg,
    )
    # The envelope-switch (E5) maximum must not be beaten by the independent
    # scan; the scan is allowed to under-shoot it, and the measured gap is kept
    # in the report rather than asserted away.
    assert not verification.failures, verification.failures
    assert verification.q_verify <= main.Q + 1e-4
    assert verification.abs_gap <= 0.0 or math.isclose(
        verification.q_verify, main.Q, rel_tol=1e-6, abs_tol=1e-4
    )


def test_all_matching_event_types_reports_ties_and_contains_the_selected_type() -> None:
    """The selected type and every tying type are reported separately.

    On the ``(1120, -650)`` fixture the envelope-switch candidate wins the
    enumeration, but the apex event (E2) reaches the same worst value to within
    the tie window: the two betas differ by about 7e-14 rad and the diameters by
    about 1.7e-10 m.  The tie must be reported as a tie, and the winner must stay
    a member of the matching set.  Enumeration order decides only which type is
    named in ``candidate_type``; it is not evidence that E5 is the sole geometric
    mechanism at work (work order section 7.2).

    The fixture is the synthetic bearing set built from the angular image of a
    station that is itself outside Crec, so this is a solver-level tie.  In the
    fixed-seed 500-station admissible family used by Gate E (``random.Random``
    seed 20260911) no tie was observed: every matching set there was the
    singleton ``("E1",)``, and a 0.25-degree ray at x=600 toward the
    3*epsilon boundary behaved the same.
    """
    point = Point2(1120.0, -650.0)
    allowed = _allowed(point)
    main = maximize_inner(S1, THETA1, point, allowed, 1.0)

    matching = main.all_matching_event_types
    assert isinstance(matching, tuple)
    assert matching and all(isinstance(kind, str) for kind in matching)
    assert main.candidate_type in matching
    assert matching[0] == main.candidate_type
    assert len(set(matching)) == len(matching)

    # The set is exactly the types whose candidate value ties the worst value
    # within the reported window: it is derived, not copied from enumeration.
    values: list[float] = []
    for candidate in main.candidates:
        evaluated = evaluate_q1(
            S1, THETA1, point, math.degrees(candidate.beta_rad), 1.0
        )
        values.append(
            math.inf if evaluated.unbounded else float(evaluated.diameter or 0.0)
        )
    reaching = {
        candidate.candidate_type
        for candidate, value in zip(main.candidates, values)
        if abs(value - main.Q) <= main.matching_tolerance_m
    }
    assert set(matching) == reaching

    # Measured on this fixture: the winner was enumerated as E5 while E2 ties it.
    assert set(matching) == {"E5", "E2"}
    tied = [
        (candidate, value)
        for candidate, value in zip(main.candidates, values)
        if abs(value - main.Q) <= main.matching_tolerance_m
    ]
    assert len(tied) == 2
    assert sorted(candidate.candidate_type for candidate, _ in tied) == ["E2", "E5"]
    tied_betas = sorted(candidate.beta_rad for candidate, _ in tied)
    assert 0.0 < tied_betas[1] - tied_betas[0] < 1e-12
    assert 0.0 < abs(tied[0][1] - tied[1][1]) < main.matching_tolerance_m

    # Control: the endpoint-dominated fixture is not multi-labelled, so the field
    # is not simply "all five event types".
    endpoint = Point2(750.0, 500.0)
    endpoint_main = maximize_inner(S1, THETA1, endpoint, _allowed(endpoint), 1.0)
    assert endpoint_main.all_matching_event_types == ("E1",)


def test_verified_result_exposes_the_section_7_3_diagnostic_split() -> None:
    """q_main_raw / q_verify / q_returned / gap_before_promotion stay distinct."""
    point = Point2(1120.0, -650.0)
    allowed = _allowed(point)

    raw = maximize_inner(S1, THETA1, point, allowed, 1.0)
    verified = maximize_inner_verified(S1, THETA1, point, allowed, 1.0)

    # The raw candidate path has no independent scan, so those diagnostics stay
    # unset rather than silently reusing the candidate maximum as "verified".
    assert raw.q_main_raw == raw.Q
    assert raw.q_returned == raw.Q
    assert raw.promoted is False
    assert math.isnan(raw.q_verify)
    assert math.isnan(raw.gap_before_promotion)
    assert raw.verification_failures == ()

    assert verified.q_main_raw == raw.Q
    assert verified.q_returned == verified.Q
    assert math.isfinite(verified.q_verify)
    assert verified.promoted is False
    assert verified.matching_tolerance_m > 0.0
    assert verified.verification_sample_count > 0
    assert isinstance(verified.verification_converged, bool)
    assert verified.verification_failures == ()
    assert math.isclose(
        verified.gap_before_promotion,
        verified.q_verify - verified.q_main_raw,
        rel_tol=0.0,
        abs_tol=0.0,
    )
    # On this fixture the independent scan under-shoots slightly (measured
    # 87.419691781922 m vs 87.419773460162 m, gap -8.2e-05 m): it is below the
    # 1e-4 m promotion tolerance, so the candidate value is returned unchanged.
    assert verified.gap_before_promotion < 0.0
    assert verified.Q == verified.q_main_raw
    # A zero gap would not certify a global optimum either; only the one-sided
    # "scan must not exceed the candidate maximum" statement is asserted.
    assert verified.q_verify <= verified.q_main_raw + 1e-4


def test_fixed_topology_roots_exist_and_candidate_values_are_compared_correctly() -> None:
    """Fixed-topology segment: roots exist, values are compared, scan agrees.

    Three separate claims are checked and kept separate:

    (i) interior stationary roots of the pair distance really do exist on a
        fixed-topology segment;
    (ii) the reported worst value equals the maximum over *all* candidate
        evaluations, and the reported event type is a member of the set of
        types that actually reach that value;
    (iii) the independent scan finds no out-of-tolerance omission.

    What is deliberately NOT claimed: on this fixture the winner is the
    interval endpoint (E1), so E4 does not win here.  Per work order section
    7.2 an unobserved E4 win is a finite-test result only.  It does not prove
    that E4 is globally redundant, so the interior stationary events remain in
    the candidate set; this finite family simply never selects one as winner.
    """
    point = Point2(750.0, 500.0)
    allowed = _allowed(point)
    interval = allowed.intervals[0]
    start, end = interval.start_rad, interval.end_rad
    midpoint = 0.5 * (start + end)
    labels = [
        vertex.label
        for vertex in _active_vertices(S1, THETA1, point, midpoint, 1.0)
    ]
    pairs = [
        (labels[i], labels[j])
        for i in range(len(labels))
        for j in range(i + 1, len(labels))
    ]
    roots_found = 0
    for pair in pairs:
        roots = _bracket_roots(
            lambda beta, pair=pair: _pair_derivative(
                S1, THETA1, point, beta, 1.0, pair
            ),
            start,
            end,
        )
        roots_found += len(roots)
    # (i) The E4 stationarity machinery is live: interior roots of the
    # fixed-topology pair distance do exist on this segment.
    assert roots_found > 0

    # (ii) The worst value is the maximum over every candidate evaluation, not
    # just over the sub-family that happened to be enumerated first.
    main = maximize_inner(S1, THETA1, point, allowed, 1.0)
    values: list[float] = []
    for candidate in main.candidates:
        evaluated = evaluate_q1(
            S1, THETA1, point, math.degrees(candidate.beta_rad), 1.0
        )
        values.append(
            math.inf if evaluated.unbounded else float(evaluated.diameter or 0.0)
        )
    assert math.isfinite(main.Q)
    assert main.Q == max(values)
    assert main.candidate_type in main.all_matching_event_types
    reaching = {
        candidate.candidate_type
        for candidate, value in zip(main.candidates, values)
        if abs(value - main.Q) <= main.matching_tolerance_m
    }
    assert reaching
    assert set(main.all_matching_event_types) == reaching

    # (iii) The independent scan must agree: it may under-shoot but must not
    # exceed the candidate maximum beyond the promotion tolerance.
    assert main.candidate_type == "E1"
    verification = verify_inner_max_independent(
        S1,
        THETA1,
        point,
        allowed,
        1.0,
        q_main=main.Q,
        beta_main_deg=main.worst_beta_deg,
    )
    assert not verification.failures, verification.failures
    assert verification.abs_gap <= 1e-4


def test_verification_config_rejects_invalid_budgets() -> None:
    with pytest.raises(ValueError):
        InnerVerificationConfig(base_samples_per_interval=2)
    with pytest.raises(ValueError):
        InnerVerificationConfig(peak_seeds=0)
    with pytest.raises(ValueError):
        InnerVerificationConfig(promotion_tolerance_m=-1.0)
