"""Gate G contracts for reproducible paper-facing Q2 evidence."""

from __future__ import annotations

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
    build_gate_g_case,
    evaluate_evidence_row,
    render_saved_gate_g_figures,
)
from src.q2.code.solver.candidate_regions import CandidateRegionConfig
from src.q2.code.solver.outer_search import OuterSearchConfig, derive_search_bounds
from src.q2.code.solver.q2_point import evaluate_q2_point
from src.q2.code.verifier.verify_gate_g import verify_gate_g


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


def test_b1_uses_frozen_center_ray_max_min_angle_formula() -> None:
    station = Point2(0.0, 0.0)
    a1 = build_a1(FirstObservation(station, 0.0))
    bounds = derive_search_bounds(a1, build_crec(a1))
    point = _center_ray_max_min_angle(a1, bounds)
    length = 1500.0 - 5.0
    expected_x = 5.0 + 1000.0**2 / length
    expected_abs_y = 1000.0 * math.sqrt(1.0 - (1000.0 / length) ** 2)

    assert point.x == pytest.approx(expected_x)
    assert abs(point.y) == pytest.approx(expected_abs_y)


def test_b1_formula_and_numerical_provenance_are_persisted(evidence) -> None:
    provenance = evidence.method_provenance["B1"]
    assert provenance["heuristic"] == "center_ray_max_min_angle"
    assert provenance["rho_a_m"] == 5.0
    assert provenance["rho_b_m"] == 1500.0
    assert provenance["L_m"] == 1495.0
    assert provenance["reception_radius_m"] == 1000.0
    assert provenance["x_star_m"] == pytest.approx(673.8963210702341)
    assert provenance["abs_y_star_m"] == pytest.approx(743.3557100464799)
    assert provenance["S2"] == [evidence.rows[1].S2.x, evidence.rows[1].S2.y]
    persisted = json.loads(evidence.method_provenance_path.read_text(encoding="utf-8"))
    assert persisted == evidence.method_provenance
    table = json.loads(evidence.evidence_table_path.read_text(encoding="utf-8"))
    assert table["method_provenance"]["B1"] == provenance


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
