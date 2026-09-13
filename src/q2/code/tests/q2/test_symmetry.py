"""Centered-case mirror symmetry used only as a special-case verifier."""

from __future__ import annotations

import math

import pytest

from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver.candidate_regions import (
    CandidateRegionConfig,
    build_adaptive_candidate_regions,
)
from src.q2.code.solver.outer_search import OuterSearchConfig, search_outer
from src.q2.code.solver.q2_point import evaluate_q2_point
from src.q2.code.verifier.verify_symmetry import build_symmetry_report


FAST = OuterSearchConfig(coarse_resolution=4, subdivision_depth=1, local_iterations=3)
FAST_REGION = CandidateRegionConfig(
    base_resolution=9,
    max_refinement_depth=2,
    target_boundary_resolution_m=40.0,
    max_refined_cells_per_level=8,
)


def test_centered_hero_and_its_mirror_are_equivalent_through_the_same_evaluator() -> None:
    search = search_outer(Point2(0.0, 0.0), 0.0, 1.0, config=FAST)
    hero = search.recommended

    report = build_symmetry_report(Point2(0.0, 0.0), 0.0, hero)

    assert report.applicable is True
    assert report.both_crec_feasible is True
    assert report.both_admissible is True
    assert report.abs_Q_difference_m <= report.tolerance_m
    assert report.passed is True

    mirror = evaluate_q2_point(
        Point2(0.0, 0.0), 0.0, Point2(hero.S2.x, -hero.S2.y), 1.0
    )
    assert mirror.Q == report.mirror_Q_m
    assert math.isclose(report.mirror_S2[0], hero.S2.x, abs_tol=1e-12)
    assert math.isclose(report.mirror_S2[1], -hero.S2.y, abs_tol=1e-12)


def test_off_center_case_is_not_claimed_symmetric() -> None:
    hero = evaluate_q2_point(Point2(1200.0, 0.0), 30.0, Point2(0.0, 0.0), 1.0)

    report = build_symmetry_report(Point2(1200.0, 0.0), 30.0, hero)

    assert report.applicable is False
    assert report.passed is False
    assert "centered" in report.notes[0]


def test_candidate_region_samples_are_mirror_paired_in_the_centered_case() -> None:
    search = search_outer(Point2(0.0, 0.0), 0.0, 1.0, config=FAST)
    hero = search.recommended
    mirror_hero = Point2(hero.S2.x, -hero.S2.y)
    adaptive = build_adaptive_candidate_regions(
        Point2(0.0, 0.0),
        0.0,
        1.0,
        search.bounds,
        hero,
        etas=(0.05,),
        config=FAST_REGION,
        extra_seeds=(mirror_hero,),
        mirror_hero=mirror_hero,
    )

    report = build_symmetry_report(
        Point2(0.0, 0.0), 0.0, hero, adaptive=adaptive, eta=0.05
    )

    assert report.applicable is True
    assert report.mirror_paired_points >= 1
    assert report.unpaired_points == 0
    assert report.passed is True
