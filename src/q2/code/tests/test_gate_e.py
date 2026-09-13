"""Gate E contracts for the fixed-station Q2 inner maximizer."""

from __future__ import annotations

import inspect
import math
import random

import pytest

from src.q2.code.geometry.a1 import FirstObservation, build_a1
from src.q2.code.geometry.angular_image import build_angular_image
from src.q2.code.geometry.circular_intervals import CircularIntervalUnion
from src.q2.code.geometry.crec import build_crec
from src.q2.code.geometry.primitives import Point2
from src.q2.code.model.q1_adapter import evaluate_q1
from src.q2.code.solver.inner_max import (
    _bracket_roots,
    construct_inner_candidates,
    maximize_inner,
)
from src.q2.code.solver.q2_point import evaluate_q2_point
from src.q2.code.verifier.verify_inner import _independent_samples, verify_inner


def test_q2_point_reports_complete_provenance_and_endpoint_maximum() -> None:
    result = evaluate_q2_point(Point2(0.0, 0.0), 0.0, Point2(750.0, 500.0), 1.0)

    assert result.in_crec
    assert result.crec_margin > 0.0
    assert not result.all_near
    assert result.admissible
    assert not result.raw_theta_intervals.is_empty
    assert not result.expanded_theta_intervals.is_empty
    assert result.Q is not None and 160.0 < result.Q < 170.0
    assert result.worst_candidate_type == "E1"
    assert result.worst_Q1_status == "OK"
    assert result.worst_beta is not None
    assert result.worst_Q1_polygon
    assert result.diameter_witness_pair is not None
    assert result.active_geometry_labels
    assert "a1_rho_5" not in result.active_geometry_labels
    assert "a1_wedge_lower" not in result.active_geometry_labels


def test_all_near_bypasses_admissibility_and_has_zero_loss() -> None:
    tangent = Point2(1620.0, 784.6018098373212)
    result = evaluate_q2_point(
        Point2(2000.0, 0.0),
        114.84193276316712,
        tangent,
        1.0,
    )

    assert result.in_crec
    assert result.all_near
    assert result.admissible
    assert result.Q == 0.0
    assert result.raw_theta_intervals.is_empty
    assert result.expanded_theta_intervals.is_empty
    assert result.worst_beta is None
    assert result.worst_candidate_type == "ALL_NEAR"


def test_outside_crec_is_rejected_before_angular_or_inner_optimization() -> None:
    result = evaluate_q2_point(Point2(0.0, 0.0), 0.0, Point2(-2000.0, 0.0), 1.0)

    assert not result.in_crec
    assert not result.admissible
    assert result.Q is None
    assert result.raw_theta_intervals.is_empty
    assert result.expanded_theta_intervals.is_empty
    assert result.worst_candidate_type == "OUTSIDE_CREC"


def test_strict_three_epsilon_gate_rejects_equal_or_nearer_image() -> None:
    result = evaluate_q2_point(Point2(0.0, 0.0), 0.0, Point2(0.0, 0.0), 1.0)

    assert result.in_crec
    assert not result.all_near
    assert not result.admissible
    assert result.Q is None
    assert result.worst_candidate_type == "INADMISSIBLE"


def test_inner_unbounded_bearing_returns_positive_infinity() -> None:
    allowed = CircularIntervalUnion.from_degrees(((0.0, 0.0),))
    result = maximize_inner(
        Point2(0.0, 0.0), 0.0, Point2(0.0, 10.0), allowed, 1.0
    )

    assert math.isinf(result.Q)
    assert result.worst_q1.status == "UNBOUNDED"


def test_candidate_construction_retains_e1_e2_e3_e4_e5_and_wraparound() -> None:
    allowed = CircularIntervalUnion.from_degrees(((170.0, 350.0), (350.0, 370.0)))
    candidates = construct_inner_candidates(
        Point2(0.0, 0.0), 0.0, Point2(750.0, 500.0), allowed, 1.0
    )

    kinds = {candidate.candidate_type for candidate in candidates}
    assert {"E1", "E2", "E3", "E4", "E5"} <= kinds
    assert any(candidate.beta_rad < math.radians(10.1) for candidate in candidates)


def test_apex_and_legal_one_sided_parallel_fixtures_are_deterministic() -> None:
    apex_interval = CircularIntervalUnion.from_degrees(
        ((113.11858929568301, 180.56982546672263),)
    )
    apex = maximize_inner(
        Point2(0.0, 0.0),
        0.0,
        Point2(251.4671164747374, -12.249266026209511),
        apex_interval,
        1.0,
    )
    assert apex.candidate_type == "E2"
    assert apex.Q == pytest.approx(132.97167363404972, rel=2e-10)

    parallel_interval = CircularIntervalUnion.from_degrees(((170.0, 190.0),))
    first = construct_inner_candidates(
        Point2(0.0, 0.0), 0.0, Point2(1000.0, -100.0), parallel_interval, 1.0
    )
    second = construct_inner_candidates(
        Point2(0.0, 0.0), 0.0, Point2(1000.0, -100.0), parallel_interval, 1.0
    )
    assert first == second
    assert {candidate.side for candidate in first if candidate.candidate_type == "E3"} >= {
        "exact",
        "left",
        "right",
    }
    assert all(
        parallel_interval.contains(candidate.beta_rad, tolerance_rad=0.0)
        for candidate in first
        if candidate.candidate_type == "E3" and candidate.side in {"left", "right"}
    )

    divergent_station = Point2(-1048.1414916324345, 176.91690118380757)
    divergent_allowed = CircularIntervalUnion.from_degrees(((-5.0, 5.0),))
    divergent = construct_inner_candidates(
        Point2(0.0, 0.0), 0.0, divergent_station, divergent_allowed, 1.0
    )
    flagged = [candidate for candidate in divergent if candidate.limit_unbounded]
    assert flagged
    assert all(candidate.side in {"left", "right"} for candidate in flagged)
    assert all(divergent_allowed.contains(candidate.beta_rad) for candidate in flagged)
    flagged_results = [
        evaluate_q1(
            Point2(0.0, 0.0),
            0.0,
            divergent_station,
            math.degrees(candidate.beta_rad),
            1.0,
        )
        for candidate in flagged
    ]
    assert all(
        result.unbounded
        or (result.diameter is not None and result.diameter > 1e8)
        for result in flagged_results
    )


def test_adaptive_root_isolation_finds_clustered_even_and_near_endpoint_roots() -> None:
    clustered = _bracket_roots(lambda value: (value - 0.201) * (value - 0.202), 0.0, 1.0)
    even = _bracket_roots(lambda value: (value - 0.4137) ** 2, 0.0, 1.0)
    near_endpoint = _bracket_roots(lambda value: value - 1e-10, 0.0, 1.0)

    assert any(abs(root - 0.201) < 1e-7 for root in clustered)
    assert any(abs(root - 0.202) < 1e-7 for root in clustered)
    assert any(abs(root - 0.4137) < 1e-7 for root in even)
    assert any(abs(root - 1e-10) < 1e-11 for root in near_endpoint)


def test_independent_verifier_dense_oracle_cannot_be_generated_by_production() -> None:
    source = inspect.getsource(__import__(verify_inner.__module__, fromlist=["*"]))
    assert "maximize_inner" not in source
    assert "construct_inner_candidates" not in source

    station1 = Point2(0.0, 0.0)
    station2 = Point2(750.0, 500.0)
    image = build_angular_image(build_a1(FirstObservation(station1, 0.0)), station2)
    candidate = maximize_inner(
        station1, 0.0, station2, image.expanded_closure, 1.0
    )
    report = verify_inner(
        station1,
        0.0,
        station2,
        image.expanded_closure,
        candidate,
        1.0,
        samples_per_component=257,
    )

    assert report.passed, report.failures
    assert report.checked_beta_count >= 257
    assert candidate.Q + report.tolerance_m >= report.dense_observed_max


def test_fixed_seed_500_valid_stations_never_underestimate_dense_observation() -> None:
    rng = random.Random(20260911)
    station1 = Point2(0.0, 0.0)
    a1 = build_a1(FirstObservation(station1, 0.0))
    crec = build_crec(a1)
    checked = 0

    while checked < 500:
        station2 = Point2(rng.uniform(0.0, 1000.0), rng.uniform(-850.0, 850.0))
        if not crec.is_in_crec(station2).in_crec:
            continue
        image = build_angular_image(a1, station2)
        if image.all_near or image.merged_closure.distance_to_angle(0.0) <= math.radians(3.0):
            continue
        candidate = maximize_inner(
            station1, 0.0, station2, image.expanded_closure, 1.0
        )
        report = verify_inner(
            station1,
            0.0,
            station2,
            image.expanded_closure,
            candidate,
            1.0,
            samples_per_component=17,
        )
        assert candidate.Q + report.tolerance_m >= report.dense_observed_max
        assert report.passed, report.failures
        assert image.expanded_closure.contains(math.radians(candidate.worst_beta_deg))
        direct = evaluate_q1(
            station1, 0.0, station2, candidate.worst_beta_deg, 1.0
        )
        assert direct.status == candidate.worst_q1.status
        assert direct.diameter == pytest.approx(candidate.worst_q1.diameter)
        checked += 1

    assert checked == 500


def test_verifier_refinement_never_crosses_disconnected_wrap_gap() -> None:
    station1 = Point2(505.34372748944406, 1844.7948872935394)
    theta1 = 548.7487532975065
    station2 = Point2(-538.6481716855972, -713.6830160537354)
    allowed = CircularIntervalUnion.from_degrees(
        ((270.10867603837596, 426.7160974748844),)
    )
    production = maximize_inner(station1, theta1, station2, allowed, 1.0)

    samples = _independent_samples(
        station1, theta1, station2, allowed, 1.0, 17
    )
    assert production.Q == 0.0
    assert all(allowed.contains(beta, tolerance_rad=0.0) for beta in samples)
    assert all(abs(math.degrees(beta) - 181.13) > 1.0 for beta in samples)

    report = verify_inner(
        station1,
        theta1,
        station2,
        allowed,
        production,
        1.0,
        samples_per_component=17,
    )
    assert report.passed, report.failures
    assert report.dense_observed_max == 0.0


@pytest.mark.parametrize("epsilon", [0.0, -1.0, 2.0])
def test_q2_point_rejects_non_frozen_epsilon(epsilon: float) -> None:
    with pytest.raises(ValueError, match="frozen"):
        evaluate_q2_point(Point2(0.0, 0.0), 0.0, Point2(750.0, 500.0), epsilon)
