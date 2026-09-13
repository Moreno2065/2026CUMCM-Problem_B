"""Gate F contracts for deterministic, explicitly non-certified outer search."""

from __future__ import annotations

from dataclasses import replace
import inspect
import math

import pytest

from src.q2.code.geometry.a1 import FirstObservation, build_a1
from src.q2.code.geometry.crec import build_crec
from src.q2.code.geometry.circular_intervals import CircularIntervalUnion
from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver.outer_search import (
    CERTIFIED_GLOBAL_OPTIMUM,
    OuterSearchConfig,
    derive_search_bounds,
    search_outer,
)
from src.q2.code.verifier.verify_outer import verify_outer


FAST = OuterSearchConfig(coarse_resolution=5, subdivision_depth=1, local_iterations=5)


def test_crec_derived_bounds_are_compact_and_not_an_arbitrary_huge_box() -> None:
    a1 = build_a1(FirstObservation(Point2(0.0, 0.0), 0.0))
    bounds = derive_search_bounds(a1, build_crec(a1))

    assert bounds.x_min < bounds.x_max
    assert bounds.y_min < bounds.y_max
    assert bounds.width <= 3000.0
    assert bounds.height <= 3000.0
    assert max(map(abs, (bounds.x_min, bounds.x_max, bounds.y_min, bounds.y_max))) < 5000.0
    assert bounds.derivation == "intersection_of_crec_witness_disk_boxes"


def test_outer_search_returns_full_valid_provenance_and_no_certificate() -> None:
    result = search_outer(Point2(0.0, 0.0), 0.0, 1.0, config=FAST)

    assert CERTIFIED_GLOBAL_OPTIMUM is False
    assert result.certified_global_optimum is False
    assert result.recommended.in_crec
    assert result.recommended.admissible
    assert result.recommended.Q is not None
    assert result.recommended.active_geometry_labels
    assert result.evaluated_count >= result.valid_count > 0
    assert result.seeds
    assert {seed.layout for seed in result.seeds} >= {
        "analytic_baseline",
        "boundary",
        "interior",
        "coarse_grid_best",
    }
    assert result.no_known_better_neighbor
    assert "certif" not in result.method.lower()


def test_outer_search_is_deterministic_and_stable_across_resolutions() -> None:
    low = search_outer(
        Point2(0.0, 0.0),
        0.0,
        1.0,
        config=OuterSearchConfig(4, 1, 4),
    )
    repeated = search_outer(
        Point2(0.0, 0.0),
        0.0,
        1.0,
        config=OuterSearchConfig(4, 1, 4),
    )
    high = search_outer(
        Point2(0.0, 0.0),
        0.0,
        1.0,
        config=OuterSearchConfig(6, 2, 6),
    )

    assert low.recommended == repeated.recommended
    assert low.history == repeated.history
    assert high.recommended.Q <= low.recommended.Q + 2.0
    assert high.recommended.S2.distance_to(low.recommended.S2) <= 100.0
    assert len(high.history) > len(low.history)


def test_independent_outer_verifier_recomputes_and_checks_local_perturbations() -> None:
    result = search_outer(Point2(0.0, 0.0), 0.0, 1.0, config=FAST)
    report = verify_outer(
        Point2(0.0, 0.0),
        0.0,
        1.0,
        result,
        mesh_radius_m=5.0,
        mesh_resolution=5,
    )

    assert report.passed, report.failures
    assert report.recomputed == result.recommended
    assert report.checked_points >= 25
    assert report.no_better_local_point
    source = inspect.getsource(__import__(verify_outer.__module__, fromlist=["*"]))
    assert "outer_search" not in source
    assert "search_outer" not in source


def test_outer_verifier_rejects_tampered_full_provenance_and_certificate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = search_outer(
        Point2(0.0, 0.0),
        0.0,
        1.0,
        config=OuterSearchConfig(3, 0, 1),
    )
    recommended = result.recommended
    assert recommended.Q is not None
    assert recommended.worst_beta is not None
    assert recommended.worst_Q1_polygon
    assert recommended.diameter_witness_pair is not None
    monkeypatch.setattr(
        "src.q2.code.verifier.verify_outer._local_points",
        lambda center, radius, resolution: (center,),
    )
    opposite_raw = (
        CircularIntervalUnion.empty()
        if not recommended.raw_theta_intervals.is_empty
        else CircularIntervalUnion.full()
    )
    opposite_expanded = (
        CircularIntervalUnion.empty()
        if not recommended.expanded_theta_intervals.is_empty
        else CircularIntervalUnion.full()
    )
    tampered_recommendations = (
        replace(recommended, S2=Point2(recommended.S2.x + 1.0, recommended.S2.y)),
        replace(recommended, in_crec=not recommended.in_crec),
        replace(recommended, crec_margin=recommended.crec_margin + 1.0),
        replace(recommended, all_near=not recommended.all_near),
        replace(recommended, raw_theta_intervals=opposite_raw),
        replace(recommended, expanded_theta_intervals=opposite_expanded),
        replace(recommended, admissible=not recommended.admissible),
        replace(recommended, Q=recommended.Q + 1.0),
        replace(recommended, worst_beta=recommended.worst_beta + 1.0),
        replace(recommended, worst_candidate_type="FORGED"),
        replace(recommended, worst_Q1_status="FORGED"),
        replace(recommended, worst_Q1_polygon=recommended.worst_Q1_polygon[:-1]),
        replace(recommended, diameter_witness_pair=None),
        replace(recommended, active_geometry_labels=("forged",)),
    )

    for tampered in tampered_recommendations:
        report = verify_outer(
            Point2(0.0, 0.0),
            0.0,
            1.0,
            replace(result, recommended=tampered),
            mesh_radius_m=1.0,
            mesh_resolution=3,
        )
        assert not report.passed
        assert not report.q_agrees

    certificate_report = verify_outer(
        Point2(0.0, 0.0),
        0.0,
        1.0,
        replace(result, certified_global_optimum=True),
        mesh_radius_m=1.0,
        mesh_resolution=3,
    )
    assert not certificate_report.passed
    assert any("certificate" in failure for failure in certificate_report.failures)


def test_coarse_grid_best_seed_is_selected_only_from_coarse_grid_records() -> None:
    result = search_outer(
        Point2(0.0, 0.0),
        0.0,
        1.0,
        config=OuterSearchConfig(3, 0, 1),
    )
    valid_coarse = [
        record
        for record in result.history
        if record.stage == "coarse_grid" and record.Q is not None
    ]
    coarse_seeds = [seed for seed in result.seeds if seed.layout == "coarse_grid_best"]
    if not valid_coarse:
        assert not coarse_seeds
    else:
        expected = min(
            valid_coarse,
            key=lambda record: (float(record.Q), record.point.x, record.point.y),
        )
        assert len(coarse_seeds) == 1
        assert coarse_seeds[0].point == expected.point
        assert coarse_seeds[0].Q == expected.Q


@pytest.mark.parametrize(
    ("station", "bearing"),
    [
        (Point2(-400.0, 300.0), 123.0),
        (Point2(900.0, -500.0), 548.0),
    ],
)
def test_general_legal_first_observations_use_geometry_relative_bounds_and_search(
    station: Point2, bearing: float
) -> None:
    result = search_outer(station, bearing, 1.0, config=OuterSearchConfig(4, 1, 3))

    assert result.recommended.in_crec
    assert result.recommended.admissible
    assert math.isfinite(result.recommended.Q)
    assert result.bounds.contains(result.recommended.S2)
    assert result.bounds.width <= 3000.0
    assert result.bounds.height <= 3000.0


def test_gate_f_has_no_gate_g_or_stochastic_scope_creep() -> None:
    import src.q2.code.solver.outer_search as outer_module

    source = inspect.getsource(outer_module).lower()
    assert "certified_global_optimum = false" in source
    for forbidden in ("genetic", "pso", "particle swarm", "reinforcement", "neural"):
        assert forbidden not in source
    assert "candidate region" not in source
    assert "gate g" not in source
