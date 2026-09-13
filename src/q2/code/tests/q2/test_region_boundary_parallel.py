"""Boundary clipping may batch independent bisection probes without changing rings."""

from __future__ import annotations

import inspect

from src.q2.code.geometry.circular_intervals import CircularIntervalUnion
from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver import region_boundary
from src.q2.code.solver.candidate_regions import (
    CandidateRegionConfig,
    build_adaptive_candidate_regions,
)
from src.q2.code.solver.outer_search import SearchBounds
from src.q2.code.solver.q2_point import Q2PointResult


EMPTY = CircularIntervalUnion.empty()


def _result(point: Point2) -> Q2PointResult:
    return Q2PointResult(
        point,
        True,
        1.0,
        False,
        EMPTY,
        EMPTY,
        True,
        0.0 if point.x + point.y <= 0.0 else 2.0,
        0.0,
        "E1",
        None,
        (),
        None,
        (),
    )


def _extract(*, batched: bool):
    corners = (
        Point2(-1.0, -1.0),
        Point2(1.0, -1.0),
        Point2(1.0, 1.0),
        Point2(-1.0, 1.0),
    )
    cache: dict[Point2, Q2PointResult] = {}
    batch_sizes: list[int] = []

    def probe(point: Point2) -> Q2PointResult:
        return _result(point)

    def probe_many(points: tuple[Point2, ...]) -> list[Q2PointResult]:
        batch_sizes.append(len(points))
        return [_result(point) for point in points]

    kwargs = {}
    if batched:
        kwargs["probe_many"] = probe_many
    result = region_boundary.extract_mixed_cell_boundary(
        corners,
        Point2(0.0, 0.0),
        cache,
        1.0,
        probe,
        config=region_boundary.BoundaryExtractionConfig(
            bisection_steps=4,
            max_subdivision_depth=0,
        ),
        **kwargs,
    )
    return result, batch_sizes


def test_boundary_clip_batches_same_round_bisection_probes_in_input_order() -> None:
    assert "probe_many" in inspect.signature(
        region_boundary.extract_mixed_cell_boundary
    ).parameters

    serial, _ = _extract(batched=False)
    batched, batch_sizes = _extract(batched=True)

    assert batched == serial
    assert batch_sizes
    assert max(batch_sizes) >= 2


def test_candidate_boundary_probes_reuse_the_existing_batch_backend() -> None:
    bounds = SearchBounds(0.0, 1.0, 0.0, 1.0, "synthetic_test_box")

    def field(point: Point2) -> Q2PointResult:
        return Q2PointResult(
            point,
            True,
            1.0,
            False,
            EMPTY,
            EMPTY,
            True,
            0.0 if point.x <= 0.6 else 2.0,
            0.0,
            "E1",
            None,
            (),
            None,
            (),
        )

    hero = field(Point2(0.5, 0.5))
    config = CandidateRegionConfig(
        base_resolution=4,
        max_refinement_depth=0,
        target_boundary_resolution_m=0.1,
        max_refined_cells_per_level=1,
        boundary_max_cells=64,
        boundary_max_probes=512,
        boundary_bisection_steps=4,
        boundary_max_subdivision_depth=0,
    )
    serial = build_adaptive_candidate_regions(
        Point2(0.0, 0.0),
        0.0,
        1.0,
        bounds,
        hero,
        etas=(0.0,),
        config=config,
        evaluator=field,
    )
    batch_sizes: list[int] = []

    def batch_evaluator(points: tuple[Point2, ...]) -> list[Q2PointResult]:
        batch_sizes.append(len(points))
        return [field(point) for point in points]

    parallel = build_adaptive_candidate_regions(
        Point2(0.0, 0.0),
        0.0,
        1.0,
        bounds,
        hero,
        etas=(0.0,),
        config=config,
        batch_evaluator=batch_evaluator,
    )

    assert parallel.boundary_polygons == serial.boundary_polygons
    assert parallel.diagnostics == serial.diagnostics
    assert 2 in batch_sizes
    diagnostics = parallel.diagnostics[0.0]
    assert diagnostics.parallel_workers == 1
    assert diagnostics.boundary_batch_call_count > 0
    assert diagnostics.boundary_batch_point_count > 0
    assert diagnostics.boundary_batch_max_size >= 2
    assert parallel.refinement_history[-1]["parallel_workers"] == 1
