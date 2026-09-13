"""Candidate-region extraction: pointwise candidates vs whole-cell selection.

The regressions here pin the separation demanded by the candidate-region work
order: a legal Hero whose value equals the frozen reference is an accepted
sample for every nonnegative eta even when no cell is fully selected, a zero
area always carries a diagnostic reason, and the local boundary clip never
interpolates through masked samples or bridges two feasible branches.
"""

from __future__ import annotations

import math

import pytest

from src.q2.code.geometry.circular_intervals import CircularIntervalUnion
from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver.candidate_regions import (
    CANDIDATE_REGION_KIND,
    CLASSIFICATION_SAMPLES,
    REGION_STATUS_NO_INSIDE_CELLS,
    REGION_STATUS_POSITIVE_AREA,
    REGION_STATUS_UNRESOLVED_THIN,
    CandidateRegionConfig,
    build_adaptive_candidate_regions,
)
from src.q2.code.solver.outer_search import SearchBounds
from src.q2.code.solver.q2_point import Q2PointResult, evaluate_q2_point
from src.q2.code.solver.region_boundary import (
    REASON_MULTI_CROSSING,
    BoundaryExtractionConfig,
    extract_mixed_cell_boundary,
    is_inside_threshold,
    ring_area_m2,
)


EMPTY = CircularIntervalUnion.empty()
UNIT_BOUNDS = SearchBounds(0.0, 1.0, 0.0, 1.0, "synthetic_test_box")
HERO_POINT = Point2(0.5, 0.5)

ZERO_AREA_STATUSES = {
    REGION_STATUS_NO_INSIDE_CELLS,
    REGION_STATUS_UNRESOLVED_THIN,
}


def _sample(point: Point2, q: float | None, *, valid: bool = True) -> Q2PointResult:
    if not valid:
        return Q2PointResult(
            point, False, -1.0, False, EMPTY, EMPTY, False, None, None,
            "OUTSIDE_CREC", None, (), None, (),
        )
    return Q2PointResult(
        point, True, 1.0, False, EMPTY, EMPTY, True, q, 0.0, "E1", None, (), None, (),
    )


def _spike_evaluator(spike: Point2, far_value: float = 1000.0):
    def evaluator(point: Point2) -> Q2PointResult:
        return _sample(point, 0.0 if point == spike else far_value)

    return evaluator


def _invalid_evaluator(point: Point2) -> Q2PointResult:
    return _sample(point, None, valid=False)


def _infeasible_with_finite_q(point: Point2, q: float) -> Q2PointResult:
    """Finite Q but outside Crec: a degenerate hero the builder must still report."""
    return Q2PointResult(
        point, False, -1.0, False, EMPTY, EMPTY, False, q, None,
        "OUTSIDE_CREC", None, (), None, (),
    )


def test_hero_is_accepted_even_when_no_cell_is_fully_selected() -> None:
    evaluator = _spike_evaluator(HERO_POINT)
    hero = evaluator(HERO_POINT)
    result = build_adaptive_candidate_regions(
        Point2(0.0, 0.0),
        0.0,
        1.0,
        UNIT_BOUNDS,
        hero,
        etas=(0.01, 0.05, 0.10),
        config=CandidateRegionConfig(
            base_resolution=3,
            max_refinement_depth=0,
            target_boundary_resolution_m=0.25,
            max_refined_cells_per_level=2,
        ),
        evaluator=evaluator,
    )

    for eta, diagnostics in result.diagnostics.items():
        assert diagnostics.accepted_sample_count >= 1
        assert diagnostics.hero_is_in_accepted_samples is True
        assert diagnostics.sampled_inside_cell_count == 0
        assert HERO_POINT in {point for point, _ in result.accepted_samples[eta]}
        assert HERO_POINT in {point for point, _ in result.regions[eta]}
        # A selected-cell count of zero must never be reported as an empty
        # candidate set: the accepted sample set is the authority here.
        if diagnostics.area_estimate_m2 == 0.0:
            assert diagnostics.region_status in ZERO_AREA_STATUSES
            assert diagnostics.stop_reason
            assert diagnostics.area_estimation_method


def test_zero_area_without_any_candidate_is_reported_with_a_reason() -> None:
    hero = _infeasible_with_finite_q(HERO_POINT, 5.0)
    result = build_adaptive_candidate_regions(
        Point2(0.0, 0.0),
        0.0,
        1.0,
        UNIT_BOUNDS,
        hero,
        etas=(0.05,),
        config=CandidateRegionConfig(
            base_resolution=3,
            max_refinement_depth=0,
            target_boundary_resolution_m=0.25,
            max_refined_cells_per_level=2,
        ),
        evaluator=_invalid_evaluator,
    )

    diagnostics = result.diagnostics[0.05]
    assert diagnostics.accepted_sample_count == 0
    assert diagnostics.hero_is_in_accepted_samples is False
    assert diagnostics.sampled_inside_cell_count == 0
    assert diagnostics.area_estimate_m2 == 0.0
    assert diagnostics.region_status == REGION_STATUS_NO_INSIDE_CELLS
    assert diagnostics.stop_reason
    assert result.regions[0.05] == ()
    assert result.boundary_polygons[0.05] == ()


def test_mixed_cells_are_counted_and_never_silently_dropped() -> None:
    evaluator = _spike_evaluator(HERO_POINT)
    hero = evaluator(HERO_POINT)
    result = build_adaptive_candidate_regions(
        Point2(0.0, 0.0),
        0.0,
        1.0,
        UNIT_BOUNDS,
        hero,
        etas=(0.05,),
        config=CandidateRegionConfig(
            base_resolution=3,
            max_refinement_depth=0,
            target_boundary_resolution_m=0.25,
            max_refined_cells_per_level=2,
        ),
        evaluator=evaluator,
    )

    diagnostics = result.diagnostics[0.05]
    # The Hero is a corner of all four base cells; every one of them contains a
    # known in-threshold sample, so none may be reported as confirmed outside.
    assert diagnostics.mixed_cell_count == 4
    assert diagnostics.sampled_inside_cell_count == 0
    assert diagnostics.outside_by_samples_cell_count == 0
    assert len(result.mixed_cells[0.05]) == diagnostics.mixed_cell_count


def test_refinement_budget_never_starves_the_known_good_neighbourhood() -> None:
    evaluator = _spike_evaluator(HERO_POINT)
    hero = evaluator(HERO_POINT)
    result = build_adaptive_candidate_regions(
        Point2(0.0, 0.0),
        0.0,
        1.0,
        UNIT_BOUNDS,
        hero,
        etas=(0.05,),
        config=CandidateRegionConfig(
            base_resolution=9,
            max_refinement_depth=3,
            target_boundary_resolution_m=0.02,
            max_refined_cells_per_level=2,
        ),
        evaluator=evaluator,
    )

    diagnostics = result.diagnostics[0.05]
    assert diagnostics.requested_refinement_count > diagnostics.executed_refinement_count
    assert diagnostics.deferred_by_cap_count > 0
    assert diagnostics.refinement_cap_hit_count >= 1
    # Deferred cells stay visible as unresolved instead of disappearing, and a
    # cell holding the Hero is refined at every level it is still eligible.
    assert diagnostics.unresolved_cell_count > 0
    triggers = dict(diagnostics.trigger_category_counts)
    assert triggers.get("known_good_seed", 0) >= 1
    assert result.unresolved_cells[0.05]


def test_boundary_clip_masks_invalid_samples_and_does_not_bridge_branches() -> None:
    """A masked vertical band must split the cell, not be interpolated over."""
    corners = (Point2(-1.0, -1.0), Point2(1.0, -1.0), Point2(1.0, 1.0), Point2(-1.0, 1.0))
    center = Point2(0.0, 0.0)
    band = 0.25
    cache: dict[Point2, Q2PointResult] = {}

    def field(point: Point2) -> Q2PointResult:
        if abs(point.x) < band:
            return _sample(point, None, valid=False)
        return _sample(point, 0.0)

    def probe(point: Point2) -> Q2PointResult:
        result = field(point)
        cache[point] = result
        return result

    outcome = extract_mixed_cell_boundary(
        corners,
        center,
        cache,
        1.0,
        probe,
        config=BoundaryExtractionConfig(),
    )

    assert outcome.fragments
    assert outcome.area_m2 > 0.0
    # Nothing may bridge the masked band.
    for fragment in outcome.fragments:
        xs = [point.x for point in fragment.ring]
        assert not (min(xs) < -0.1 and max(xs) > 0.1)
        assert is_inside_threshold(probe(_centroid(fragment.ring)), 1.0)
    # Crossing brackets are recorded, and the clip may not claim the whole cell.
    assert outcome.brackets
    assert all(bracket.width_m >= 0.0 for bracket in outcome.brackets)
    assert outcome.area_m2 < 4.0


def test_boundary_clip_reports_multiple_crossings_instead_of_bridging() -> None:
    """A non-monotone edge (outside -> inside -> outside) is not clipped blindly."""
    corners = (Point2(-1.0, -1.0), Point2(1.0, -1.0), Point2(1.0, 1.0), Point2(-1.0, 1.0))
    center = Point2(0.0, 0.0)
    cache: dict[Point2, Q2PointResult] = {}

    def field(point: Point2) -> Q2PointResult:
        return _sample(point, 0.0 if abs(point.x) <= 0.3 else 1.0)

    def probe(point: Point2) -> Q2PointResult:
        result = field(point)
        cache[point] = result
        return result

    outcome = extract_mixed_cell_boundary(
        corners,
        center,
        cache,
        0.5,
        probe,
        config=BoundaryExtractionConfig(max_subdivision_depth=0),
    )

    assert REASON_MULTI_CROSSING in outcome.unresolved_reasons
    assert not outcome.resolved
    # The non-monotone triangle is not clipped blindly, and the fragments that
    # are emitted stay far below the true band area instead of over-claiming.
    assert outcome.area_m2 < 0.5 * 1.2


def test_boundary_clip_is_a_pure_function_of_its_inputs() -> None:
    def run() -> tuple[tuple[float, ...], float, tuple[tuple[float, float], ...]]:
        corners = (Point2(-1.0, -1.0), Point2(1.0, -1.0), Point2(1.0, 1.0), Point2(-1.0, 1.0))
        cache: dict[Point2, Q2PointResult] = {}

        def probe(point: Point2) -> Q2PointResult:
            inside = point.x * point.x + point.y * point.y <= 0.64
            result = _sample(point, 0.0 if inside else 1.0)
            cache[point] = result
            return result

        outcome = extract_mixed_cell_boundary(
            corners, Point2(0.0, 0.0), cache, 0.5, probe
        )
        areas = tuple(round(fragment.area_m2, 12) for fragment in outcome.fragments)
        rings = tuple(
            (round(point.x, 12), round(point.y, 12))
            for fragment in outcome.fragments
            for point in fragment.ring
        )
        return areas, round(outcome.area_m2, 12), rings

    first = run()
    second = run()
    assert first == second
    assert first[1] > 0.0


def test_builder_is_deterministic_for_the_same_inputs() -> None:
    """Same inputs must give the same regions, cells, areas and history."""
    evaluator = _spike_evaluator(HERO_POINT)
    hero = evaluator(HERO_POINT)
    config = CandidateRegionConfig(
        base_resolution=5,
        max_refinement_depth=1,
        target_boundary_resolution_m=0.25,
        max_refined_cells_per_level=4,
    )

    def run():
        return build_adaptive_candidate_regions(
            Point2(0.0, 0.0),
            0.0,
            1.0,
            UNIT_BOUNDS,
            hero,
            etas=(0.05,),
            config=config,
            evaluator=evaluator,
        )

    first = run()
    second = run()
    assert first.regions == second.regions
    assert first.cells == second.cells
    assert first.thresholds == second.thresholds
    assert first.approximate_areas_m2 == second.approximate_areas_m2
    assert first.boundary_polygons == second.boundary_polygons
    assert first.mixed_cells == second.mixed_cells
    assert first.unresolved_cells == second.unresolved_cells
    assert first.refinement_history == second.refinement_history
    assert first.surface == second.surface
    assert first.diagnostics == second.diagnostics


def test_frozen_hero_is_an_accepted_sample_for_every_eta_in_production_style_shape() -> None:
    """End-to-end check with the real evaluator on the frozen centered Hero."""
    S1 = Point2(0.0, 0.0)
    hero_point = Point2(800.1012338639696, -606.388471543349)
    hero = evaluate_q2_point(S1, 0.0, hero_point, 1.0)
    assert hero.Q is not None

    result = build_adaptive_candidate_regions(
        S1,
        0.0,
        1.0,
        SearchBounds(0.0, 1004.9992384757819, -982.5475935627165, 982.5475935627165, "test"),
        hero,
        etas=(0.01, 0.02, 0.05, 0.10),
        config=CandidateRegionConfig(
            base_resolution=3,
            max_refinement_depth=0,
            target_boundary_resolution_m=25.0,
            max_refined_cells_per_level=2,
        ),
    )

    assert result.kind == CANDIDATE_REGION_KIND
    assert result.classification_samples == CLASSIFICATION_SAMPLES
    for eta, diagnostics in result.diagnostics.items():
        assert diagnostics.threshold == pytest.approx((1.0 + eta) * float(hero.Q))
        assert diagnostics.hero_is_in_accepted_samples is True
        assert diagnostics.accepted_sample_count >= 1
        polygons = result.boundary_polygons[eta]
        if diagnostics.area_estimate_m2 == 0.0:
            assert diagnostics.region_status in ZERO_AREA_STATUSES
            assert diagnostics.stop_reason
        else:
            assert diagnostics.region_status == REGION_STATUS_POSITIVE_AREA
            assert polygons
            assert diagnostics.area_estimate_m2 == pytest.approx(
                math.fsum(ring_area_m2(ring) for ring in polygons)
            )


def _centroid(ring: tuple[Point2, ...]) -> Point2:
    count = float(len(ring))
    return Point2(
        math.fsum(point.x for point in ring) / count,
        math.fsum(point.y for point in ring) / count,
    )
