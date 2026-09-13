"""Gate G contracts for reproducible paper-facing Q2 evidence."""

from __future__ import annotations

import copy
from dataclasses import replace
import inspect
import json
import math
from pathlib import Path
import shutil

import pytest

from src.q2.code.geometry.primitives import Point2
from src.q2.code.geometry.a1 import FirstObservation, build_a1
from src.q2.code.geometry.crec import build_crec
from src.q2.code.solver.gate_g import (
    CERTIFIED_GLOBAL_OPTIMUM,
    FIGURE_NAMES,
    GateGConfig,
    _center_ray_max_min_angle,
    _circular_span_segments_deg,
    build_gate_g_case,
    evaluate_evidence_row,
    render_saved_gate_g_figures,
)
from src.q2.code.solver.candidate_regions import CandidateRegionConfig
from src.q2.code.solver.outer_search import OuterSearchConfig, derive_search_bounds
from src.q2.code.solver.q2_point import evaluate_q2_point
from src.q2.code.verifier.verify_gate_g import (
    METHOD_ID_B0,
    METHOD_ID_B1,
    METHOD_ID_B2,
    METHOD_ID_HERO,
    REGION_KIND,
    REGION_STATUS_NO_INSIDE,
    REGION_STATUS_UNRESOLVED,
    _expected_region_scalars,
    verify_gate_g,
)


REGION_SCALAR_FIELDS = (
    "kind",
    "classification_samples",
    "accepted_sample_count",
    "hero_is_in_accepted_samples",
    "sampled_inside_cell_count",
    "mixed_cell_count",
    "unresolved_cell_count",
    "area_estimate_m2",
    "area_estimation_method",
    "region_status",
    "stop_reason",
    "achieved_max_boundary_cell_size_m",
    "requested_refinement_count",
    "executed_refinement_count",
    "deferred_by_cap_count",
    "refinement_cap_hit",
    "trigger_counts",
)


FAST = GateGConfig(
    outer_config=OuterSearchConfig(3, 0, 1),
    surface_resolution=5,
    figure_dpi=72,
    candidate_region_config=CandidateRegionConfig(
        base_resolution=5,
        max_refinement_depth=2,
        target_boundary_resolution_m=25.0,
        max_refined_cells_per_level=12,
    ),
)


def test_circular_span_wraps_across_zero_for_plotting() -> None:
    assert _circular_span_segments_deg(0.0, 3.0) == (
        (0.0, 3.0),
        (357.0, 360.0),
    )


@pytest.fixture(scope="module")
def evidence(tmp_path_factory: pytest.TempPathFactory):
    output = tmp_path_factory.mktemp("gate_g")
    return build_gate_g_case(Point2(0.0, 0.0), 0.0, output, config=FAST)


def test_four_headline_methods_share_the_frozen_q2_metric(evidence) -> None:
    assert [row.method for row in evidence.rows] == ["B0", "B1", "B2", "Hero"]
    assert evidence.rows[0].crec_feasible
    for row in evidence.rows:
        direct = evaluate_q2_point(evidence.S1, evidence.theta1_deg, row.S2, 1.0)
        assert row.Q == direct.Q
        assert row.crec_feasible == direct.in_crec
        assert row.admissible == direct.admissible
        assert row.all_near == direct.all_near
        assert row.worst_beta_deg == direct.worst_beta
    assert evidence.certified_global_optimum is False
    assert CERTIFIED_GLOBAL_OPTIMUM is False


def test_infeasible_baseline_row_remains_honest() -> None:
    row = evaluate_evidence_row(
        "B-test",
        Point2(0.0, 0.0),
        0.0,
        Point2(-5000.0, 5000.0),
        runtime_s=0.0,
    )

    assert not row.crec_feasible
    assert not row.admissible
    assert row.Q is None
    assert row.verification == "infeasible"


def test_b2_uses_frozen_center_ray_max_min_angle_formula() -> None:
    station = Point2(0.0, 0.0)
    a1 = build_a1(FirstObservation(station, 0.0))
    bounds = derive_search_bounds(a1, build_crec(a1))
    point = _center_ray_max_min_angle(a1, bounds)
    length = 1500.0 - 5.0
    expected_x = 5.0 + 1000.0**2 / length
    expected_abs_y = 1000.0 * math.sqrt(1.0 - (1000.0 / length) ** 2)

    assert point.x == pytest.approx(expected_x)
    assert abs(point.y) == pytest.approx(expected_abs_y)


def test_b2_formula_and_numerical_provenance_are_persisted(evidence) -> None:
    provenance = evidence.method_provenance[METHOD_ID_B2]
    assert provenance["method_id"] == METHOD_ID_B2
    assert provenance["paper_alias"] == "B2"
    assert provenance["heuristic"] == "center_ray_max_min_angle"
    assert provenance["rho_a_m"] == 5.0
    assert provenance["rho_b_m"] == 1500.0
    assert provenance["L_m"] == 1495.0
    assert provenance["reception_radius_m"] == 1000.0
    assert provenance["x_star_m"] == pytest.approx(673.8963210702341)
    assert provenance["abs_y_star_m"] == pytest.approx(743.3557100464799)
    assert provenance["S2"] == [evidence.rows[2].S2.x, evidence.rows[2].S2.y]
    assert provenance["analytic_optimality_claimed"] is True
    assert provenance["omega_truncated"] is False
    assert provenance["side_selection"] == "positive_perpendicular"
    assert provenance["source_fingerprint"].startswith("sha256:")
    assert provenance["validity"] == (evidence.rows[2].verification == "fresh_metric")
    persisted = json.loads(evidence.method_provenance_path.read_text(encoding="utf-8"))
    assert persisted == evidence.method_provenance
    table = json.loads(evidence.evidence_table_path.read_text(encoding="utf-8"))
    assert table["method_provenance"][METHOD_ID_B2] == provenance


def test_b1_two_sided_right_angle_provenance_is_persisted(evidence) -> None:
    provenance = evidence.method_provenance[METHOD_ID_B1]
    assert provenance["method_id"] == METHOD_ID_B1
    assert provenance["paper_alias"] == "B1"
    assert provenance["heuristic"] == "right_angle_radial_midpoint"
    assert provenance["selection_rule"] == "min_Q_over_symmetric_sides"
    assert provenance["side_selection"] == "min_Q_over_symmetric_sides"
    sides = provenance["evaluated_sides"]
    assert len(sides) == 2
    assert [item["side"] for item in sides] == [
        "positive_perpendicular",
        "negative_perpendicular",
    ]
    index = next(
        i for i, item in enumerate(sides) if item["side"] == provenance["chosen_side"]
    )
    assert provenance["chosen_side"] == sides[index]["side"]
    assert provenance["S2"] == sides[index]["clamped_S2"]
    assert provenance["S2"] == [evidence.rows[1].S2.x, evidence.rows[1].S2.y]
    assert provenance["clamp"] == "componentwise_to_crec_derived_bounds"
    assert provenance["source_fingerprint"].startswith("sha256:")
    persisted = json.loads(evidence.method_provenance_path.read_text(encoding="utf-8"))
    assert persisted == evidence.method_provenance
    table = json.loads(evidence.evidence_table_path.read_text(encoding="utf-8"))
    assert table["method_provenance"][METHOD_ID_B1] == provenance


def test_candidate_good_regions_are_separate_numerical_nonproof_sets(evidence) -> None:
    assert set(evidence.candidate_regions) == {0.01, 0.02, 0.05, 0.10}
    assert set(evidence.candidate_region_paths) == {0.01, 0.02, 0.05, 0.10}
    assert len(set(evidence.candidate_region_paths.values())) == 4
    assert all(path.exists() for path in evidence.candidate_region_paths.values())
    assert evidence.qhat_star == evidence.rows[-1].Q
    for eta, points in evidence.candidate_regions.items():
        assert points
        assert all(point.Q <= (1.0 + eta) * evidence.qhat_star + 1e-9 for point in points)
    payload = json.loads(evidence.candidate_regions_path.read_text(encoding="utf-8"))
    assert payload["kind"] == "numerical_candidate_good_regions_not_proof"
    assert payload["qhat_star_source"] == "Hero numerical search"
    assert all(len(points) > 1 for points in evidence.candidate_regions.values())
    assert all(path.exists() for path in evidence.candidate_region_geojson_paths.values())


def test_representative_symmetry_regression(evidence) -> None:
    check = evidence.symmetry_check
    assert check["passed"] is True
    assert check["both_crec_feasible"] is True
    assert check["both_admissible"] is True
    assert check["abs_Q_difference_m"] <= check["tolerance_m"]


def test_infeasible_baselines_are_not_serialized_as_zero_or_plotted_as_zero(evidence) -> None:
    table = json.loads(evidence.evidence_table_path.read_text(encoding="utf-8"))
    rows = {row["method"]: row for row in table["rows"]}
    assert rows["B1"]["Q"] is None
    assert rows["B2"]["Q"] is None
    svg = evidence.figure_artifacts["q2_baseline_comparison"].rendered_paths[0].read_text(
        encoding="utf-8"
    )
    assert "Infeasible" in svg
    assert '"Q": 0' not in evidence.figure_artifacts["q2_baseline_comparison"].data_path.read_text(
        encoding="utf-8"
    )


def test_figures_can_be_re_rendered_from_saved_sidecars_only(evidence) -> None:
    render_saved_gate_g_figures(evidence.evidence_table_path.parent, dpi=72)
    assert all(
        path.exists() and path.stat().st_size > 100
        for artifact in evidence.figure_artifacts.values()
        for path in artifact.rendered_paths
    )


def test_seven_figures_have_data_and_three_rendered_formats(evidence) -> None:
    assert set(evidence.figure_artifacts) == set(FIGURE_NAMES)
    for name, artifact in evidence.figure_artifacts.items():
        assert artifact.data_path.exists()
        metadata = json.loads(artifact.data_path.read_text(encoding="utf-8"))["metadata"]
        assert metadata["equal_axes"] is True
        assert metadata["units"] == "m"
        assert metadata["baseline_style"] == "muted"
        assert metadata["colormap"] != "rainbow"
        assert {path.suffix for path in artifact.rendered_paths} == {".svg", ".pdf", ".png"}
        assert all(path.exists() and path.stat().st_size > 100 for path in artifact.rendered_paths)
    crec_data = json.loads(
        evidence.figure_artifacts["q2_crec"].data_path.read_text(encoding="utf-8")
    )["data"]["surface"]
    assert all({"S2", "Q", "in_crec", "admissible"} <= set(item) for item in crec_data)


def test_compact_table_schema_and_independent_verifier(evidence) -> None:
    table = json.loads(evidence.evidence_table_path.read_text(encoding="utf-8"))
    assert set(table["rows"][0]) == {
        "method", "S2", "Q", "Crec_feasible", "admissible", "move_distance_m",
        "all_near", "worst_beta_deg", "runtime_s", "verification",
    }
    report = verify_gate_g(evidence)
    assert report.passed, report.failures
    assert report.recomputed_rows == 4
    assert report.checked_candidate_points > 0
    assert report.checked_figure_files == 3 * len(FIGURE_NAMES)
    source = inspect.getsource(__import__(verify_gate_g.__module__, fromlist=["*"]))
    assert "build_gate_g_case" not in source
    assert "search_outer" not in source


def test_verifier_rejects_tampered_table_regions_figure_and_qhat(
    evidence, tmp_path: Path
) -> None:
    def copied(path: Path, name: str) -> Path:
        target = tmp_path / name
        shutil.copy2(path, target)
        return target

    table_path = copied(evidence.evidence_table_path, "tampered_table.json")
    table = json.loads(table_path.read_text(encoding="utf-8"))
    table["rows"][0]["Q"] = 123456.0
    table_path.write_text(json.dumps(table), encoding="utf-8")
    assert not verify_gate_g(replace(evidence, evidence_table_path=table_path)).passed

    combined_path = copied(evidence.candidate_regions_path, "tampered_combined.json")
    combined = json.loads(combined_path.read_text(encoding="utf-8"))
    combined["regions"]["0.01"] = []
    combined_path.write_text(json.dumps(combined), encoding="utf-8")
    assert not verify_gate_g(replace(evidence, candidate_regions_path=combined_path)).passed

    eta_paths = dict(evidence.candidate_region_paths)
    eta_path = copied(eta_paths[0.02], "tampered_eta.json")
    eta = json.loads(eta_path.read_text(encoding="utf-8"))
    eta["points"] = []
    eta_path.write_text(json.dumps(eta), encoding="utf-8")
    eta_paths[0.02] = eta_path
    assert not verify_gate_g(replace(evidence, candidate_region_paths=eta_paths)).passed

    artifacts = dict(evidence.figure_artifacts)
    figure = artifacts["q2_crec"]
    figure_path = copied(figure.data_path, "tampered_figure.json")
    figure_data = json.loads(figure_path.read_text(encoding="utf-8"))
    figure_data["metadata"]["units"] = "furlong"
    figure_path.write_text(json.dumps(figure_data), encoding="utf-8")
    artifacts["q2_crec"] = replace(figure, data_path=figure_path)
    assert not verify_gate_g(replace(evidence, figure_artifacts=artifacts)).passed

    assert not verify_gate_g(replace(evidence, qhat_star=evidence.qhat_star + 1.0)).passed


@pytest.mark.parametrize(
    ("station", "bearing"),
    [
        (Point2(10.0, 5.0), 37.0),
        (Point2(-8.0, 12.0), 211.0),
    ],
)
def test_arbitrary_legal_inputs_are_explicitly_illustrative(
    tmp_path: Path, station: Point2, bearing: float
) -> None:
    result = build_gate_g_case(station, bearing, tmp_path, config=FAST, render_figures=False)

    assert result.case_label == "representative illustrative case"
    assert result.S1 == station
    assert math.isclose(result.theta1_deg, bearing)
    assert not result.certified_global_optimum
    assert "global optimum" not in result.claims.lower()
    assert "universal s2" not in result.claims.lower()


def test_gate_g_source_contains_no_universal_or_certified_claims() -> None:
    import src.q2.code.solver.gate_g as module

    source = inspect.getsource(module).lower()
    assert "certified_global_optimum = false" in source
    assert "unique universal" not in source
    assert "proved optimum" not in source


def _copied(path: Path, target_dir: Path, name: str) -> Path:
    target = target_dir / name
    shutil.copy2(path, target)
    return target


def test_region_payloads_carry_nonproof_scalars_and_full_accepted_samples(
    evidence,
) -> None:
    aggregate = json.loads(
        evidence.candidate_regions_path.read_text(encoding="utf-8")
    )
    assert aggregate["region_kind"] == REGION_KIND
    assert set(aggregate["diagnostics"]) == {"0.01", "0.02", "0.05", "0.10"}
    assert aggregate["representative_accepted_sample_limit"] == 16
    assert aggregate["accepted_samples_note"]
    for key, scalar in aggregate["diagnostics"].items():
        for field in REGION_SCALAR_FIELDS:
            assert field in scalar, (key, field)
        assert scalar["kind"] == REGION_KIND
        assert scalar["classification_samples"] == "corners_plus_center"
        if scalar["area_estimate_m2"] == 0.0:
            assert scalar["region_status"] in {
                REGION_STATUS_NO_INSIDE,
                REGION_STATUS_UNRESOLVED,
            }
            assert str(scalar["stop_reason"]).strip()
    for eta in (0.01, 0.02, 0.05, 0.10):
        payload = json.loads(
            evidence.candidate_region_paths[eta].read_text(encoding="utf-8")
        )
        for field in REGION_SCALAR_FIELDS:
            assert field in payload, (eta, field)
        assert payload["kind"] == REGION_KIND
        assert payload["diagnostics"]["accepted_sample_count"] == payload[
            "accepted_sample_count"
        ]
        accepted = payload["accepted_samples"]
        assert payload["accepted_samples_total"] == len(accepted)
        assert len(accepted) == payload["accepted_sample_count"]
        assert all(
            isinstance(item, list)
            and len(item) == 2
            and isinstance(item[0], list)
            and len(item[0]) == 2
            for item in accepted
        )
        if len(accepted) > 16:
            assert aggregate["representative_accepted_samples_truncated"][
                f"{eta:.2f}"
            ]


def test_geojson_boundary_fragments_keep_multiple_branches(evidence) -> None:
    for eta in (0.01, 0.02, 0.05, 0.10):
        payload = json.loads(
            evidence.candidate_region_geojson_paths[eta].read_text(encoding="utf-8")
        )
        assert payload["type"] == "FeatureCollection"
        properties = payload["properties"]
        for field in REGION_SCALAR_FIELDS:
            assert field in properties, (eta, field)
        assert properties["kind"] == REGION_KIND
        fragments = [
            feature
            for feature in payload["features"]
            if feature["properties"].get("kind") == "boundary_fragment"
        ]
        expected = (
            len(evidence.candidate_region_boundary_polygons[eta])
            - len(evidence.candidate_region_cells[eta])
        )
        assert len(fragments) == expected
        assert properties["boundary_fragment_count"] == expected
        for index, feature in enumerate(fragments):
            assert feature["geometry"]["type"] == "Polygon"
            ring = feature["geometry"]["coordinates"][0]
            assert ring[0] == ring[-1]
            assert feature["properties"]["fragment_index"] == index
            assert feature["properties"]["ring_vertex_count"] == len(ring) - 1
        # A multi-branch result must not be collapsed into one outer ring.
        if expected > 1:
            assert len({feature["properties"]["fragment_index"] for feature in fragments}) == expected
        assert all(
            feature["properties"].get("kind") != "certified_inside"
            for feature in payload["features"]
        )


def test_method_provenance_identities_are_distinct_and_persisted(evidence) -> None:
    provenance = evidence.method_provenance
    assert set(provenance) == {
        METHOD_ID_B0,
        METHOD_ID_B1,
        METHOD_ID_B2,
        METHOD_ID_HERO,
    }
    for method_id, entry in provenance.items():
        assert entry["method_id"] == method_id
        for field in (
            "paper_alias",
            "formula_or_constructor",
            "inputs",
            "side_selection",
            "clamp_or_projection_policy",
            "S2",
            "fresh_Q",
            "validity",
            "margin",
            "source_fingerprint",
        ):
            assert field in entry, (method_id, field)
        assert entry["source_fingerprint"].startswith("sha256:")
    assert {entry["paper_alias"] for entry in provenance.values()} == {
        "B0",
        "B1",
        "B2",
        "Hero",
    }
    assert (
        provenance[METHOD_ID_B1]["formula_or_constructor"]
        != provenance[METHOD_ID_B2]["formula_or_constructor"]
    )
    assert (
        provenance[METHOD_ID_B1]["source_fingerprint"]
        != provenance[METHOD_ID_B2]["source_fingerprint"]
    )
    persisted = json.loads(evidence.method_provenance_path.read_text(encoding="utf-8"))
    assert persisted == provenance
    table = json.loads(evidence.evidence_table_path.read_text(encoding="utf-8"))
    assert table["method_provenance"] == provenance


def test_swapped_method_ids_fail_semantic_verification(evidence) -> None:
    provenance = copy.deepcopy(evidence.method_provenance)
    provenance[METHOD_ID_B1]["method_id"], provenance[METHOD_ID_B2]["method_id"] = (
        provenance[METHOD_ID_B2]["method_id"],
        provenance[METHOD_ID_B1]["method_id"],
    )
    report = verify_gate_g(replace(evidence, method_provenance=provenance))
    assert not report.passed


def test_swapped_constructor_and_fingerprint_fail_semantic_verification(
    evidence,
) -> None:
    provenance = copy.deepcopy(evidence.method_provenance)
    b1 = provenance[METHOD_ID_B1]
    b2 = provenance[METHOD_ID_B2]
    b1["formula_or_constructor"], b2["formula_or_constructor"] = (
        b2["formula_or_constructor"],
        b1["formula_or_constructor"],
    )
    b1["source_fingerprint"], b2["source_fingerprint"] = (
        b2["source_fingerprint"],
        b1["source_fingerprint"],
    )
    report = verify_gate_g(replace(evidence, method_provenance=provenance))
    assert not report.passed


def test_tampered_region_status_counts_and_hero_flag_are_rejected(
    evidence, tmp_path: Path
) -> None:
    eta_path = _copied(evidence.candidate_region_paths[0.01], tmp_path, "eta_status.json")
    payload = json.loads(eta_path.read_text(encoding="utf-8"))
    payload["region_status"] = "proved_empty_set"
    eta_path.write_text(json.dumps(payload), encoding="utf-8")
    report = verify_gate_g(
        replace(
            evidence,
            candidate_region_paths={**evidence.candidate_region_paths, 0.01: eta_path},
        )
    )
    assert not report.passed

    aggregate_path = _copied(
        evidence.candidate_regions_path, tmp_path, "agg_count.json"
    )
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["accepted_sample_count"]["0.01"] += 1
    aggregate_path.write_text(json.dumps(aggregate), encoding="utf-8")
    report = verify_gate_g(
        replace(evidence, candidate_regions_path=aggregate_path)
    )
    assert not report.passed

    hero_path = _copied(evidence.candidate_region_paths[0.02], tmp_path, "eta_hero.json")
    payload = json.loads(hero_path.read_text(encoding="utf-8"))
    payload["hero_is_in_accepted_samples"] = not payload[
        "hero_is_in_accepted_samples"
    ]
    hero_path.write_text(json.dumps(payload), encoding="utf-8")
    report = verify_gate_g(
        replace(
            evidence,
            candidate_region_paths={**evidence.candidate_region_paths, 0.02: hero_path},
        )
    )
    assert not report.passed


def test_verifier_recomputes_region_scalars_independently(evidence) -> None:
    """The verifier must recompute counts instead of trusting stored diagnostics."""
    diagnostics = dict(evidence.candidate_region_diagnostics)
    true_count = diagnostics[0.01].accepted_sample_count
    diagnostics[0.01] = replace(
        diagnostics[0.01],
        accepted_sample_count=true_count + 7,
        hero_is_in_accepted_samples=not diagnostics[
            0.01
        ].hero_is_in_accepted_samples,
    )
    failures: list[str] = []
    scalars = _expected_region_scalars(
        replace(evidence, candidate_region_diagnostics=diagnostics), 0.01, failures
    )
    assert scalars is not None
    assert scalars["accepted_sample_count"] == true_count
    assert any("accepted_sample_count" in message for message in failures)
    assert any("hero_is_in_accepted_samples" in message for message in failures)


def test_geojson_fragment_deletion_and_branch_merge_are_rejected(
    evidence, tmp_path: Path
) -> None:
    source = evidence.candidate_region_geojson_paths[0.01]
    payload = json.loads(source.read_text(encoding="utf-8"))
    fragment_indices = [
        index
        for index, feature in enumerate(payload["features"])
        if feature["properties"].get("kind") == "boundary_fragment"
    ]
    assert len(fragment_indices) >= 2, "fixture must retain several clipped branches"

    deleted_payload = copy.deepcopy(payload)
    del deleted_payload["features"][fragment_indices[0]]
    deleted_path = _copied(source, tmp_path, "geo_deleted.json")
    deleted_path.write_text(json.dumps(deleted_payload), encoding="utf-8")
    report = verify_gate_g(
        replace(
            evidence,
            candidate_region_geojson_paths={
                **evidence.candidate_region_geojson_paths,
                0.01: deleted_path,
            },
        )
    )
    assert not report.passed

    merged_payload = copy.deepcopy(payload)
    first, second = fragment_indices[0], fragment_indices[1]
    first_ring = merged_payload["features"][first]["geometry"]["coordinates"][0][:-1]
    second_ring = merged_payload["features"][second]["geometry"]["coordinates"][0]
    merged_payload["features"][first]["geometry"]["coordinates"] = [
        first_ring + second_ring
    ]
    del merged_payload["features"][second]
    merged_path = _copied(source, tmp_path, "geo_merged.json")
    merged_path.write_text(json.dumps(merged_payload), encoding="utf-8")
    report = verify_gate_g(
        replace(
            evidence,
            candidate_region_geojson_paths={
                **evidence.candidate_region_geojson_paths,
                0.01: merged_path,
            },
        )
    )
    assert not report.passed
