"""Regression tests for the Q2 evaluated-solution closure boundary."""

from __future__ import annotations

import json

from src.q2.code.geometry.a1 import FirstObservation, build_a1
from src.q2.code.geometry.crec import build_crec
from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver.candidate_regions import CandidateRegionConfig, build_adaptive_candidate_regions
from src.q2.code.solver.gate_g import GateGConfig, build_gate_g_case
from src.q2.code.solver.incumbent import EvaluationRegistry, update_incumbent
from src.q2.code.solver.outer_search import (
    OuterSearchConfig,
    derive_search_bounds,
    search_outer,
)
from src.q2.code.solver.q2_point import evaluate_q2_point
from src.q2.code.verifier.verify_gate_g import verify_gate_g


def _context() -> tuple[Point2, object]:
    s1 = Point2(0.0, 0.0)
    a1 = build_a1(FirstObservation(s1, 0.0, 1.0))
    return s1, derive_search_bounds(a1, build_crec(a1))


def test_incumbent_promotes_known_better_evidence_point() -> None:
    s1, _ = _context()
    old = evaluate_q2_point(s1, 0.0, Point2(792.3025077759607, -616.4786501226868))
    evidence = evaluate_q2_point(s1, 0.0, Point2(800.0736125053295, -606.4160929019891))

    incumbent = update_incumbent(
        None, old, 1e-9, source="outer_search", stage="outer", evaluation_id=1
    )
    promoted = update_incumbent(
        incumbent,
        evidence,
        1e-9,
        source="adaptive_evidence",
        stage="candidate_region",
        evaluation_id=2,
    )

    assert promoted.S2 == evidence.S2
    assert promoted.Q == evidence.Q
    assert promoted.source == "adaptive_evidence"


def test_incumbent_tie_break_is_independent_of_arrival_order() -> None:
    s1, _ = _context()
    plus = evaluate_q2_point(s1, 0.0, Point2(792.3025077759607, 616.4786501226868))
    minus = evaluate_q2_point(s1, 0.0, Point2(792.3025077759607, -616.4786501226868))

    from_plus = update_incumbent(None, plus, 1e-7)
    from_minus = update_incumbent(None, minus, 1e-7)

    assert update_incumbent(from_plus, minus, 1e-7).S2 == update_incumbent(
        from_minus, plus, 1e-7
    ).S2


def test_stale_hero_regression_promotes_the_known_better_evidence_seed(tmp_path) -> None:
    known_better = Point2(800.0736125053295, -606.4160929019891)
    evidence = build_gate_g_case(
        Point2(0.0, 0.0),
        0.0,
        tmp_path,
        config=GateGConfig(
            outer_config=OuterSearchConfig(3, 0, 1),
            candidate_region_config=CandidateRegionConfig(
                base_resolution=3,
                max_refinement_depth=0,
                target_boundary_resolution_m=25.0,
                max_refined_cells_per_level=2,
            ),
            closure_seed_points=(known_better,),
            figure_dpi=72,
        ),
        render_figures=False,
    )

    known_result = evaluate_q2_point(Point2(0.0, 0.0), 0.0, known_better)
    assert evidence.hero_result.Q <= known_result.Q + 1e-9
    assert any(round_payload["promoted"] for round_payload in evidence.hero_closure["rounds"])


def test_registry_deduplicates_exact_coordinates_without_overwriting_provenance() -> None:
    s1, _ = _context()
    result = evaluate_q2_point(s1, 0.0, Point2(792.3025077759607, -616.4786501226868))
    registry = EvaluationRegistry()

    first = registry.register(result, source="outer_search", stage="coarse_grid")
    second = registry.register(result, source="adaptive_evidence", stage="base")

    assert second.evaluation_id == first.evaluation_id
    assert second.source == "outer_search"
    assert second.stage == "coarse_grid"
    assert len(registry.records) == 1


def test_adaptive_result_exposes_all_evaluated_results() -> None:
    s1, bounds = _context()
    hero = evaluate_q2_point(s1, 0.0, Point2(792.3025077759607, -616.4786501226868))

    adaptive = build_adaptive_candidate_regions(
        s1,
        0.0,
        1.0,
        bounds,
        hero,
        etas=(0.05,),
        config=CandidateRegionConfig(
            base_resolution=3,
            max_refinement_depth=0,
            target_boundary_resolution_m=25.0,
            max_refined_cells_per_level=2,
        ),
    )

    assert adaptive.all_evaluated_results
    assert set(adaptive.all_evaluated_results) == set(adaptive.surface)


def test_outer_result_exposes_first_seen_evaluation_records() -> None:
    outcome = search_outer(
        Point2(0.0, 0.0),
        0.0,
        config=OuterSearchConfig(
            coarse_resolution=3,
            subdivision_depth=0,
            local_iterations=1,
            parallel_workers=1,
        ),
    )

    assert outcome.evaluated_records
    assert len(outcome.evaluated_records) == outcome.evaluated_count
    assert all(record.source == "outer_search" for record in outcome.evaluated_records)
    assert len({record.result.S2 for record in outcome.evaluated_records}) == outcome.evaluated_count


def test_gate_g_persists_closure_provenance_and_evaluated_set_dominance(tmp_path) -> None:
    evidence = build_gate_g_case(
        Point2(0.0, 0.0),
        0.0,
        tmp_path,
        config=GateGConfig(
            outer_config=OuterSearchConfig(3, 0, 1),
            candidate_region_config=CandidateRegionConfig(
                base_resolution=3,
                max_refinement_depth=0,
                target_boundary_resolution_m=25.0,
                max_refined_cells_per_level=2,
            ),
            figure_dpi=72,
        ),
        render_figures=False,
    )

    assert evidence.hero_closure_path.exists()
    closure = json.loads(evidence.hero_closure_path.read_text(encoding="utf-8"))
    assert closure["closure_pass"] is True
    assert closure["best_evaluated_q"]
    assert evidence.all_evaluated_results
    valid_q = [
        float(result.Q)
        for result in evidence.all_evaluated_results
        if result.in_crec and (result.admissible or result.all_near) and result.Q is not None
    ]
    assert float(evidence.hero_result.Q) <= min(valid_q) + 1e-9
    for eta in (0.01, 0.02, 0.05, 0.10):
        assert evidence.candidate_region_thresholds[eta] == (
            1.0 + eta
        ) * evidence.qhat_star
        payload = json.loads(
            evidence.candidate_region_paths[eta].read_text(encoding="utf-8")
        )
        assert payload["qhat_star"] == evidence.qhat_star
        assert payload["threshold"] == evidence.candidate_region_thresholds[eta]
        assert payload["hero_closure"] == closure


def test_gate_g_verifier_reports_closure_and_independent_hero_checks(tmp_path) -> None:
    evidence = build_gate_g_case(
        Point2(0.0, 0.0),
        0.0,
        tmp_path,
        config=GateGConfig(
            outer_config=OuterSearchConfig(3, 0, 1),
            candidate_region_config=CandidateRegionConfig(
                base_resolution=3,
                max_refinement_depth=0,
                target_boundary_resolution_m=25.0,
                max_refined_cells_per_level=2,
            ),
            figure_dpi=72,
        ),
        render_figures=True,
    )

    report = verify_gate_g(evidence)

    assert report.passed, report.failures
    assert report.hero_closure_passed is True
    assert report.independent_hero_passed is True
