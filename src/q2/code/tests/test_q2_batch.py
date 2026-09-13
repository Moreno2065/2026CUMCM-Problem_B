"""Regression tests for the optional candidate-point batch backend."""

from __future__ import annotations

import pytest

from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver.q2_point import evaluate_q2_point


def _representative_points() -> tuple[Point2, ...]:
    return (
        Point2(0.0, 0.0),
        Point2(502.49961923789095, -98.25475935627162),
        Point2(792.3025077759607, -616.4786501226868),
        Point2(792.3025077759607, 616.4786501226868),
        Point2(673.8963210702341, 743.3557100464799),
        Point2(752.5, 752.5),
        Point2(1500.0, 0.0),
        Point2(-1000.0, -800.0),
    )


def test_workers_one_is_the_authoritative_serial_reference() -> None:
    from src.q2.code.solver.batch import evaluate_q2_points_batch

    points = _representative_points()
    expected = [evaluate_q2_point(Point2(0.0, 0.0), 0.0, point) for point in points]
    assert evaluate_q2_points_batch(Point2(0.0, 0.0), 0.0, points, workers=1) == expected


def test_parallel_batch_is_exact_and_preserves_input_order() -> None:
    from src.q2.code.solver.batch import evaluate_q2_points_batch

    points = _representative_points()
    expected = [evaluate_q2_point(Point2(0.0, 0.0), 0.0, point) for point in points]
    actual = evaluate_q2_points_batch(Point2(0.0, 0.0), 0.0, points, workers=2)
    assert actual == expected
    assert [result.S2 for result in actual] == list(points)


def test_batch_rejects_invalid_worker_count() -> None:
    from src.q2.code.solver.batch import evaluate_q2_points_batch

    with pytest.raises(ValueError, match="workers"):
        evaluate_q2_points_batch(Point2(0.0, 0.0), 0.0, (), workers=0)


def test_empty_batch_does_not_start_worker_processes() -> None:
    from src.q2.code.solver.batch import evaluate_q2_points_batch

    assert evaluate_q2_points_batch(Point2(0.0, 0.0), 0.0, (), workers=2) == []


def test_adaptive_candidate_batch_backend_matches_serial_surface() -> None:
    from src.q2.code.geometry.a1 import FirstObservation, build_a1
    from src.q2.code.geometry.crec import build_crec
    from src.q2.code.solver.batch import Q2PointBatchExecutor
    from src.q2.code.solver.candidate_regions import (
        CandidateRegionConfig,
        build_adaptive_candidate_regions,
    )
    from src.q2.code.solver.outer_search import derive_search_bounds

    s1 = Point2(0.0, 0.0)
    a1 = build_a1(FirstObservation(s1, 0.0, 1.0))
    bounds = derive_search_bounds(a1, build_crec(a1))
    hero = evaluate_q2_point(s1, 0.0, Point2(792.3025077759607, -616.4786501226868))
    config = CandidateRegionConfig(
        base_resolution=5,
        max_refinement_depth=1,
        target_boundary_resolution_m=25.0,
        max_refined_cells_per_level=2,
    )
    serial = build_adaptive_candidate_regions(
        s1, 0.0, 1.0, bounds, hero, etas=(0.05,), config=config
    )
    with Q2PointBatchExecutor(s1, 0.0, 1.0, workers=2) as batch:
        parallel = build_adaptive_candidate_regions(
            s1,
            0.0,
            1.0,
            bounds,
            hero,
            etas=(0.05,),
            config=config,
            batch_evaluator=batch.evaluate,
        )
    assert parallel.surface == serial.surface
    assert parallel.all_evaluated_results == serial.all_evaluated_results
    assert parallel.regions == serial.regions
    assert parallel.cells == serial.cells


def test_outer_search_parallel_backend_matches_serial_reduction() -> None:
    from dataclasses import replace

    from src.q2.code.solver.outer_search import OuterSearchConfig, search_outer

    serial = search_outer(
        Point2(0.0, 0.0),
        0.0,
        config=OuterSearchConfig(
            coarse_resolution=3,
            subdivision_depth=0,
            local_iterations=1,
            parallel_workers=1,
        ),
    )
    parallel = search_outer(
        Point2(0.0, 0.0),
        0.0,
        config=replace(serial.config, parallel_workers=2),
    )
    assert parallel.recommended == serial.recommended
    assert parallel.history == serial.history
    assert parallel.evaluated_count == serial.evaluated_count
