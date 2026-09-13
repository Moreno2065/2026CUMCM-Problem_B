"""Unified validity predicate, disclosed safe bounds and the fixed-centre check."""

from __future__ import annotations

from dataclasses import replace
import math

import pytest

from src.q2.code.geometry.a1 import FirstObservation, build_a1
from src.q2.code.geometry.circular_intervals import CircularIntervalUnion
from src.q2.code.geometry.crec import build_crec
from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver.batch import Q2PointBatchExecutor
from src.q2.code.solver.incumbent import is_valid_incumbent_result
from src.q2.code.solver.outer_search import (
    OuterSearchConfig,
    _is_valid as outer_is_valid,
    derive_search_bounds,
    search_outer,
)
from src.q2.code.solver.q2_point import Q2PointResult, evaluate_q2_point


FAST = OuterSearchConfig(coarse_resolution=4, subdivision_depth=1, local_iterations=3)


def _centered_result(**overrides: object) -> Q2PointResult:
    base = evaluate_q2_point(Point2(0.0, 0.0), 0.0, Point2(750.0, 500.0), 1.0)
    return replace(base, **overrides)


def test_outer_search_and_incumbent_share_one_finite_validity_predicate() -> None:
    valid = _centered_result()
    assert outer_is_valid(valid) is True
    assert outer_is_valid(valid) == is_valid_incumbent_result(valid)

    infinite = _centered_result(Q=math.inf)
    assert outer_is_valid(infinite) is False
    assert is_valid_incumbent_result(infinite) is False
    assert outer_is_valid(_centered_result(Q=None)) is False

    all_near = evaluate_q2_point(
        Point2(2000.0, 0.0),
        114.84193276316712,
        Point2(1620.0, 784.6018098373212),
        1.0,
    )
    assert all_near.all_near
    assert outer_is_valid(all_near) == is_valid_incumbent_result(all_near) is True


def test_search_bounds_are_a_disclosed_safe_superset_of_crec() -> None:
    for station, bearing in (
        (Point2(0.0, 0.0), 0.0),
        (Point2(1700.0, 0.0), 0.0),
        (Point2(3000.0, 0.0), 180.0),
    ):
        a1 = build_a1(FirstObservation(station, bearing))
        bounds = derive_search_bounds(a1, build_crec(a1))

        assert (
            bounds.derivation
            == "safe_superset_from_subset_of_mandatory_crec_disk_boxes"
        )
        # S1 is always a Crec member, so a genuine superset must contain it.
        assert bounds.contains(station, tolerance_m=1e-6)


def test_final_neighbour_check_probes_one_frozen_centre() -> None:
    result = search_outer(Point2(0.0, 0.0), 0.0, 1.0, config=FAST)

    assert result.no_known_better_neighbor is True
    assert result.recommended.Q is not None and math.isfinite(float(result.recommended.Q))
    step = 5.0 / (2**13)
    probes = [
        record
        for record in result.history
        if record.stage == "final_neighbor_check"
    ]
    assert probes

    centre = result.recommended.S2
    contiguous = 0
    for record in reversed(probes):
        if math.isclose(record.point.distance_to(centre), step, rel_tol=0.0, abs_tol=1e-9):
            contiguous += 1
        else:
            break
    assert contiguous >= 1


def test_parallel_workers_preserve_the_serial_validity_verdict() -> None:
    points = (
        Point2(750.0, 500.0),
        Point2(400.0, 300.0),
        Point2(2000.0, 2600.0),
    )
    serial = [evaluate_q2_point(Point2(0.0, 0.0), 0.0, point, 1.0) for point in points]
    with Q2PointBatchExecutor(Point2(0.0, 0.0), 0.0, 1.0, workers=2) as batch:
        parallel = batch.evaluate(points)

    assert parallel == serial
    assert [outer_is_valid(result) for result in parallel] == [
        outer_is_valid(result) for result in serial
    ]


def test_coarse_candidates_are_never_promoted_from_an_infinite_q() -> None:
    # An inadmissible point may be a raw grid member but must never be valid.
    inadmissible = evaluate_q2_point(Point2(0.0, 0.0), 0.0, Point2(600.0, 70.0), 1.0)
    assert inadmissible.Q is None
    assert outer_is_valid(inadmissible) is False
    assert not is_valid_incumbent_result(inadmissible)
    assert isinstance(inadmissible.raw_theta_intervals, CircularIntervalUnion)
