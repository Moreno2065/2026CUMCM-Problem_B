"""Section-6 resolution stability: one target set, three extraction budgets.

The acceptance gates used here are imported from the implementation
(``DECLARED_RESOLUTION_CRITERIA``, ``DECLARED_PHASE_FRACTIONS``) and from the
generator's declared level budgets; this file never invents its own thresholds.
"""

from __future__ import annotations

from dataclasses import asdict
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.q2.code.geometry.primitives import Point2
from src.q2.code.solver.candidate_regions import (
    CANDIDATE_REGION_KIND,
    CLASSIFICATION_SAMPLES,
    CandidateCell,
    CandidateRegionConfig,
)
from src.q2.code.solver.outer_search import OuterSearchConfig, SearchBounds, search_outer
from src.q2.code.verifier.verify_candidate_resolution import (
    BOUNDARY_DISTANCE_METHOD,
    COMPONENT_METHOD,
    DECLARED_PHASE_FRACTIONS,
    DECLARED_RESOLUTION_CRITERIA,
    EVALUATOR_FINGERPRINT_ROOTS,
    ExtractionLevelSpec,
    _crop_to_roi,
    _component_count,
    _component_gate_is_comparable,
    _display_component_count,
    _normalise_level,
    boundary_bidirectional_distance_m,
    candidate_region_resolution_stability,
    evaluator_source_fingerprint,
)

S1 = Point2(0.0, 0.0)
THETA1_DEG = 0.0
EPSILON_DEG = 1.0
ETA = 0.05

# A bounded boundary budget keeps the regression test cheap; the *relative*
# extraction pattern is what the assertions are about.
BOUNDED_BOUNDARY = dict(
    boundary_max_cells=8,
    boundary_max_probes=60,
    boundary_probe_budget_per_cell=16,
)

TEST_OUTER = OuterSearchConfig(
    coarse_resolution=3, subdivision_depth=0, local_iterations=1, parallel_workers=4
)
TEST_LEVELS = (
    ExtractionLevelSpec(
        "coarse",
        CandidateRegionConfig(
            base_resolution=5,
            max_refinement_depth=0,
            target_boundary_resolution_m=120.0,
            max_refined_cells_per_level=2,
            **BOUNDED_BOUNDARY,
        ),
    ),
    ExtractionLevelSpec(
        "medium",
        CandidateRegionConfig(
            base_resolution=7,
            max_refinement_depth=1,
            target_boundary_resolution_m=60.0,
            max_refined_cells_per_level=4,
            **BOUNDED_BOUNDARY,
        ),
    ),
    ExtractionLevelSpec(
        "fine",
        CandidateRegionConfig(
            base_resolution=9,
            max_refinement_depth=1,
            target_boundary_resolution_m=30.0,
            max_refined_cells_per_level=4,
            **BOUNDED_BOUNDARY,
        ),
    ),
)
PHASE_PROBE_LEVEL = "coarse"
ARTIFACT = (
    Path(__file__).resolve().parents[2]
    / "q2_verification"
    / "candidate_region_resolution_stability.json"
)


@pytest.fixture(scope="module")
def shared_report():
    search = search_outer(S1, THETA1_DEG, EPSILON_DEG, config=TEST_OUTER)
    report = candidate_region_resolution_stability(
        S1,
        THETA1_DEG,
        EPSILON_DEG,
        TEST_LEVELS,
        eta=ETA,
        hero_result=search.recommended,
        bounds=search.bounds,
        mirror_symmetric=True,
        workers=2,
        phase_probe_level=PHASE_PROBE_LEVEL,
    )
    return search, report


def test_region_kind_is_declared_numerical_and_not_a_proof() -> None:
    assert CANDIDATE_REGION_KIND == "numerical_candidate_good_region_not_proof"
    assert CLASSIFICATION_SAMPLES == "corners_plus_center"


def test_component_count_detects_split_regions() -> None:
    left = CandidateCell(0.0, 1.0, 0.0, 1.0, 1)
    right = CandidateCell(1.0, 2.0, 0.0, 1.0, 1)
    far = CandidateCell(5.0, 6.0, 0.0, 1.0, 1)

    assert _component_count(()) == 0
    assert _component_count((left,)) == 1
    assert _component_count((left, right)) == 1
    assert _component_count((left, right, far)) == 2
    # Cells sharing only a corner are not edge-connected.
    diagonal = CandidateCell(1.0, 2.0, 1.0, 2.0, 1)
    assert _component_count((left, diagonal)) == 2


def test_display_component_count_uses_saved_polygons_and_not_corner_touches() -> None:
    left = CandidateCell(0.0, 1.0, 0.0, 1.0, 1)
    edge_neighbour = CandidateCell(1.0, 2.0, 0.0, 1.0, 1)
    diagonal = CandidateCell(1.0, 2.0, 1.0, 2.0, 1)
    far = CandidateCell(5.0, 6.0, 0.0, 1.0, 1)

    assert _display_component_count(()) == 0
    assert _display_component_count((left.ring(),)) == 1
    assert _display_component_count((left.ring(), edge_neighbour.ring())) == 1
    assert _display_component_count((left.ring(), diagonal.ring())) == 2
    assert _display_component_count((left.ring(), far.ring())) == 2


def test_component_gate_rejects_inside_cells_only_when_boundary_fragments_exist() -> None:
    """A clipped display region cannot inherit topology from full cells alone."""
    assert _component_gate_is_comparable(
        area_bearing_ring_count=0,
        unresolved_cell_count=0,
    ) is True
    assert _component_gate_is_comparable(
        area_bearing_ring_count=1,
        unresolved_cell_count=0,
    ) is False
    assert _component_gate_is_comparable(
        area_bearing_ring_count=0,
        unresolved_cell_count=1,
    ) is False


def test_production_phase_probe_uses_the_finest_declared_extraction() -> None:
    """Phase sensitivity belongs to the final numerical display resolution."""
    from src.q2.code.tools.generate_q2_verification import (
        PHASE_PROBE_LEVEL,
        RESOLUTION_LEVELS,
    )

    assert PHASE_PROBE_LEVEL == RESOLUTION_LEVELS[-1].name


def test_production_medium_budget_matches_the_resolved_fine_sampling_capacity() -> None:
    """Medium may use a looser target, but not a starved sampling lattice."""
    from src.q2.code.tools.generate_q2_verification import RESOLUTION_LEVELS

    medium = RESOLUTION_LEVELS[1].candidate_region_config
    fine = RESOLUTION_LEVELS[2].candidate_region_config
    assert medium.base_resolution == fine.base_resolution
    assert medium.max_refinement_depth == fine.max_refinement_depth
    assert medium.max_refined_cells_per_level == fine.max_refined_cells_per_level
    assert medium.boundary_max_cells == fine.boundary_max_cells
    assert medium.boundary_max_probes == fine.boundary_max_probes
    assert medium.boundary_probe_budget_per_cell == fine.boundary_probe_budget_per_cell
    assert medium.boundary_max_cell_diameter_factor == fine.boundary_max_cell_diameter_factor


def test_phase_crop_sums_each_saved_display_polygon_once() -> None:
    """Inside cells already occur in ``boundary_polygons`` as full rectangles."""
    cell = CandidateCell(0.0, 1.0, 0.0, 1.0, 0)
    adaptive = SimpleNamespace(
        cells={ETA: (cell,)},
        boundary_polygons={ETA: (cell.ring(),)},
    )
    roi = SearchBounds(0.0, 1.0, 0.0, 1.0, "unit")

    area, cropped, rings = _crop_to_roi(adaptive, ETA, roi)

    assert len(cropped) == 1
    assert rings == (cell.ring(),)
    assert area == pytest.approx(1.0)


def test_empty_boundary_sample_sets_report_a_sentinel_not_zero_distance() -> None:
    """An empty boundary must never be reported as a zero distance."""
    point = Point2(1.0, 2.0)
    assert boundary_bidirectional_distance_m((), ()) is None
    assert boundary_bidirectional_distance_m((), (point,)) is None
    assert boundary_bidirectional_distance_m((point,), ()) is None
    # A non-empty pair still reports a genuine number.
    value = boundary_bidirectional_distance_m((point,), (Point2(1.0, 3.0),))
    assert value is not None and math.isclose(value, 1.0, rel_tol=0.0, abs_tol=1e-12)


def test_per_level_outer_configuration_is_rejected_as_a_bare_triple() -> None:
    with pytest.raises(ValueError):
        _normalise_level(
            (
                "coarse",
                OuterSearchConfig(3, 0, 1),
                CandidateRegionConfig(base_resolution=5),
            )
        )
    assert _normalise_level(TEST_LEVELS[0]) is TEST_LEVELS[0]


def test_three_levels_compare_one_frozen_target_set(shared_report) -> None:
    search, report = shared_report
    frozen = report.frozen

    assert frozen.shared_hero is True
    assert frozen.shared_bounds is True
    assert frozen.q_reference_source != "per_level_search_outer"
    assert frozen.hero_S2 == pytest.approx(
        (search.recommended.S2.x, search.recommended.S2.y)
    )
    assert frozen.bounds == pytest.approx(
        (search.bounds.x_min, search.bounds.x_max, search.bounds.y_min, search.bounds.y_max)
    )

    # One evaluator fingerprint for the whole comparison.
    assert len(frozen.evaluator_fingerprint) == 64
    assert frozen.evaluator_fingerprint_file_count > 0
    assert [root for root, _ in frozen.evaluator_fingerprint_roots] == list(
        EVALUATOR_FINGERPRINT_ROOTS
    )

    # Every level reports the same q_reference, hero and thresholds.
    for level in report.levels:
        assert level.q_reference_m == pytest.approx(frozen.q_reference_m, rel=0.0, abs=0.0)
        assert level.hero_S2 == pytest.approx(frozen.hero_S2, rel=0.0, abs=0.0)
        assert level.thresholds_by_eta == frozen.thresholds_by_eta
        assert level.threshold == pytest.approx((1.0 + level.eta) * level.q_reference_m)
    thresholds = {level.threshold for level in report.levels}
    assert len(thresholds) == 1
    assert report.q_reference_relative_spread == pytest.approx(0.0, abs=1e-12)

    # The three levels differ only in their declared extraction budget.
    assert [level.name for level in report.levels] == [
        spec.name for spec in TEST_LEVELS
    ]
    for level, spec in zip(report.levels, TEST_LEVELS, strict=True):
        assert level.candidate_region_config == spec.candidate_region_config
        assert level.outer_config_used is False


def test_every_level_reports_the_section6_field_list(shared_report) -> None:
    _, report = shared_report
    assert report.levels, "the study must report at least one level row"
    for level in report.levels:
        diagnostics = level.region_diagnostics
        # Declared threshold and reference.
        assert math.isfinite(level.q_reference_m)
        assert level.thresholds_by_eta
        assert level.threshold == pytest.approx((1.0 + level.eta) * level.q_reference_m)
        # Sample counts.
        assert level.valid_sample_count >= level.threshold_inside_sample_count
        assert level.threshold_inside_sample_count == diagnostics.accepted_sample_count
        assert level.hero_is_in_accepted_samples is True
        # Cell classification counts.
        assert level.sampled_inside_cell_count >= 0
        assert level.mixed_cell_count >= 0
        assert level.unresolved_cell_count >= 0
        # Area, its method and the achieved boundary size.
        assert level.area_estimation_method
        assert level.area_role
        if level.area_estimate_m2 > 0.0:
            assert level.region_status == "positive_area_numerical"
        else:
            assert level.region_status in {
                "unresolved_thin_feature",
                "no_fully_selected_cells",
            }
            assert level.stop_reason
        assert level.target_boundary_resolution_m > 0.0
        assert level.achieved_max_boundary_cell_size_m > 0.0
        # Branch count and how it was decided.
        assert level.component_method == COMPONENT_METHOD
        assert level.component_count >= 0
        # Boundary geometry and its distance bookkeeping.
        assert level.boundary_distance_method == BOUNDARY_DISTANCE_METHOD
        assert level.boundary_sample_count >= 0
        if level.boundary_sample_count == 0:
            assert level.boundary_bidirectional_distance_m is None
        # Budget accounting and the stop reason.
        assert level.new_evaluation_count >= 0
        assert level.cache_hit_count >= 0
        assert level.runtime_s > 0.0
        assert level.refinement_stop_reason
        assert level.stop_reason


def test_cross_level_area_and_boundary_deltas_are_reported(shared_report) -> None:
    _, report = shared_report
    first_by_index = min(report.levels, key=lambda item: item.level_index)
    assert first_by_index.area_abs_delta_vs_previous_m2 is None
    assert first_by_index.area_relative_delta_vs_previous is None
    later = [level for level in report.levels if level.level_index > 0]
    assert later
    for level in later:
        assert level.area_abs_delta_vs_previous_m2 is not None
        assert level.area_relative_delta_reference_level is not None
        earlier = next(
            item
            for item in report.levels
            if item.level_index == level.level_index - 1 and item.eta == level.eta
        )
        assert level.area_abs_delta_vs_previous_m2 == pytest.approx(
            abs(level.area_estimate_m2 - earlier.area_estimate_m2)
        )
        if earlier.boundary_sample_count and level.boundary_sample_count:
            assert level.boundary_bidirectional_distance_m is not None
            assert level.boundary_distance_reference_level == earlier.name


def test_grid_phase_perturbation_moves_only_the_lattice_origin(shared_report) -> None:
    _, report = shared_report
    phase = report.grid_phase_perturbation
    assert phase.applied is True
    assert phase.level_name == PHASE_PROBE_LEVEL
    assert phase.roi == pytest.approx(report.frozen.bounds)
    assert phase.base_cell_size_m is not None
    assert phase.base_cell_size_m[0] > 0.0 and phase.base_cell_size_m[1] > 0.0

    fractions = [sample.phase_fraction for sample in phase.samples]
    assert fractions == [0.0] + list(DECLARED_PHASE_FRACTIONS)

    probe_row = next(level for level in report.levels if level.name == PHASE_PROBE_LEVEL)
    for sample in phase.samples:
        # The target set itself is untouched: same reference, same threshold.
        assert sample.q_reference_m == pytest.approx(report.frozen.q_reference_m, rel=0.0, abs=0.0)
        assert sample.threshold == pytest.approx(probe_row.threshold, rel=0.0, abs=0.0)
    assert phase.samples[0].lattice_shift_m == (0.0, 0.0)
    assert any(
        sample.lattice_shift_m != (0.0, 0.0) for sample in phase.samples[1:]
    )
    assert math.isclose(
        phase.samples[0].area_estimate_m2,
        probe_row.area_estimate_m2,
        rel_tol=0.0,
        abs_tol=1e-9,
    )

    # The declared phase gate and the reported verdict agree with each other.
    deviation = phase.max_area_relative_deviation
    if deviation is None or (
        deviation > DECLARED_RESOLUTION_CRITERIA.max_phase_area_relative_deviation
    ):
        assert report.converged is False
        assert any("phase" in reason for reason in report.unconverged_reasons)


def test_declared_criteria_drive_the_convergence_verdict(shared_report) -> None:
    _, report = shared_report
    assert report.criteria == DECLARED_RESOLUTION_CRITERIA
    assert report.certified is False
    zero_area = [level.name for level in report.levels if level.area_estimate_m2 <= 0.0]
    component_counts = {level.component_count for level in report.levels}
    if len(component_counts) > 1:
        assert report.converged is False
        assert any("component" in reason for reason in report.unconverged_reasons)
    if zero_area:
        assert report.converged is False
    if report.converged:
        assert report.unconverged_reasons == ()
    else:
        assert report.unconverged_reasons
    # Structural consistency is true by construction in shared mode.
    assert report.frozen.shared_hero and report.frozen.shared_bounds


def test_legacy_mode_warns_that_section6_is_not_satisfied() -> None:
    levels = (
        ExtractionLevelSpec(
            "coarse",
            CandidateRegionConfig(
                base_resolution=5,
                max_refinement_depth=0,
                target_boundary_resolution_m=120.0,
                max_refined_cells_per_level=2,
                **BOUNDED_BOUNDARY,
            ),
            OuterSearchConfig(3, 0, 1, parallel_workers=4),
        ),
        ExtractionLevelSpec(
            "medium",
            CandidateRegionConfig(
                base_resolution=7,
                max_refinement_depth=1,
                target_boundary_resolution_m=60.0,
                max_refined_cells_per_level=4,
                **BOUNDED_BOUNDARY,
            ),
            OuterSearchConfig(3, 0, 1, parallel_workers=4),
        ),
    )
    report = candidate_region_resolution_stability(
        S1, THETA1_DEG, EPSILON_DEG, levels, eta=ETA
    )

    assert report.frozen.shared_hero is False
    assert report.frozen.shared_bounds is False
    assert report.converged is False
    assert any("LEGACY MODE" in note for note in report.frozen.notes)
    assert any("LEGACY MODE" in reason for reason in report.unconverged_reasons)
    # Legacy levels do not even claim one shared reference.
    assert report.frozen.q_reference_source == "per_level_search_outer"
    assert report.grid_phase_perturbation.applied is False


def test_production_artifact_reports_the_section6_contract_honestly() -> None:
    if not ARTIFACT.is_file():
        pytest.skip(
            "candidate_region_resolution_stability.json has not been generated yet; "
            "run PYTHONPATH=. python src/q2/code/tools/generate_q2_verification.py"
        )
    from src.q2.code.tools.generate_q2_verification import RESOLUTION_LEVELS

    payload = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    if payload.get("schema") != "q2_candidate_region_resolution_stability_v2_section6":
        pytest.fail(
            "candidate_region_resolution_stability.json is stale (schema "
            f"{payload.get('schema')!r}); regenerate it with "
            "PYTHONPATH=. python src/q2/code/tools/generate_q2_verification.py"
        )
    assert payload["criteria"] == asdict(DECLARED_RESOLUTION_CRITERIA)
    assert payload["certified"] is False

    frozen = payload["frozen"]
    assert frozen["shared_hero"] is True
    assert frozen["shared_bounds"] is True
    assert frozen["evaluator_fingerprint"]
    assert frozen["evaluator_fingerprint"] == evaluator_source_fingerprint()[0]
    assert math.isfinite(frozen["q_reference_m"])

    declared = {spec.name: asdict(spec.candidate_region_config) for spec in RESOLUTION_LEVELS}
    rows = payload["levels"]
    assert [row["name"] for row in rows] == list(declared)
    for row in rows:
        assert row["candidate_region_config"] == declared[row["name"]]
        assert row["q_reference_m"] == pytest.approx(frozen["q_reference_m"], rel=0.0, abs=0.0)
        assert row["thresholds_by_eta"] == frozen["thresholds_by_eta"]
        assert row["achieved_max_boundary_cell_size_m"] > 0.0
        assert row["stop_reason"]

    # Honest reporting: an unconverged production result must say so.
    areas = [row["area_estimate_m2"] for row in rows]
    if any(area <= 0.0 for area in areas) or len({row["component_count"] for row in rows}) > 1:
        assert payload["converged"] is False
        assert payload["unconverged_reasons"]
    if payload["converged"]:
        assert payload["unconverged_reasons"] == []
    else:
        assert payload["unconverged_reasons"]
