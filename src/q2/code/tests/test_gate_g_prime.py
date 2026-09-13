"""Gate G-prime semantic, symmetry, and visual-artifact regressions."""

from __future__ import annotations

import json
from pathlib import Path


ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts"
FIGURES = Path(__file__).resolve().parents[1] / "figures"
PRODUCTION = ARTIFACTS / "gate_g_representative"


def test_production_candidate_regions_are_adaptive_nontrivial_regions() -> None:
    config = json.loads((PRODUCTION / "q2_final_evidence_config.json").read_text(encoding="utf-8"))
    candidate = json.loads((PRODUCTION / "q2_candidate_good_regions.json").read_text(encoding="utf-8"))
    assert config["candidate_region_config"]["base_resolution"] == 21
    assert config["candidate_region_config"]["target_boundary_resolution_m"] == 5.0
    assert config["candidate_region_config"]["max_refinement_depth"] == 6
    assert config["candidate_region_config"]["max_refined_cells_per_level"] == 32
    assert config["parallel_workers"] == 8
    assert config["outer_search_config"]["parallel_workers"] == 8
    assert candidate["evidence_config_id"] == config["config_id"]
    assert candidate["kind"] == "numerical_candidate_good_regions_not_proof"
    assert candidate["classification_samples"] == "corners_plus_center"
    assert all(len(candidate["regions"][eta]) > 1 for eta in ("0.01", "0.02", "0.05", "0.10"))
    assert all(candidate["approximate_areas_m2"][eta] > 0.0 for eta in ("0.01", "0.02", "0.05", "0.10"))
    assert max(item["point_count"] for item in candidate["refinement_history"]) > 1000
    for eta in ("01", "02", "05", "10"):
        path = PRODUCTION / f"q2_candidate_region_eta_{eta}.geojson"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["type"] == "FeatureCollection"
        assert payload["properties"]["classification_samples"] == "corners_plus_center"
        assert any(feature["geometry"]["type"] == "Polygon" for feature in payload["features"])
    per_eta = json.loads(
        (PRODUCTION / "q2_candidate_good_eta_05.json").read_text(encoding="utf-8")
    )
    assert per_eta["classification_samples"] == "corners_plus_center"


def test_adaptive_surface_does_not_beat_reported_hero() -> None:
    table = json.loads((PRODUCTION / "q2_evidence_table.json").read_text(encoding="utf-8"))
    hero_q = next(row["Q"] for row in table["rows"] if row["method"] == "Hero")
    surface = json.loads((PRODUCTION / "q2_q_surface.json").read_text(encoding="utf-8"))["data"]["surface"]
    valid = [item["Q"] for item in surface if item["in_crec"] and item["admissible"] and item["Q"] is not None]
    assert min(valid) >= hero_q - 1e-9


def test_symmetric_candidate_regions_have_mirror_balanced_samples_and_cells() -> None:
    for eta in ("01", "02", "05", "10"):
        payload = json.loads((PRODUCTION / f"q2_candidate_region_eta_{eta}.geojson").read_text(encoding="utf-8"))
        points = [
            feature["geometry"]["coordinates"]
            for feature in payload["features"]
            if feature["geometry"]["type"] == "Point"
        ]
        positive = sum(1 for _, y in points if y > 1e-9)
        negative = sum(1 for _, y in points if y < -1e-9)
        assert abs(positive - negative) <= 1
        cell_areas = {"positive": 0.0, "negative": 0.0}
        for feature in payload["features"]:
            if feature["properties"].get("kind") != "inside_cell":
                continue
            ring = feature["geometry"]["coordinates"][0]
            area = abs(sum(
                ring[index][0] * ring[(index + 1) % len(ring)][1]
                - ring[(index + 1) % len(ring)][0] * ring[index][1]
                for index in range(len(ring))
            )) / 2.0
            center_y = sum(point[1] for point in ring) / len(ring)
            cell_areas["positive" if center_y > 1e-9 else "negative"] += area
        assert abs(cell_areas["positive"] - cell_areas["negative"]) <= 0.01 * max(cell_areas.values())


def test_production_symmetry_and_baseline_semantics_are_persisted() -> None:
    sidecar = json.loads((PRODUCTION / "q2_geometry_overview.json").read_text(encoding="utf-8"))
    symmetry = sidecar["data"]["geometry"]["symmetry"]
    assert symmetry["passed"] is True
    assert symmetry["abs_Q_difference_m"] <= symmetry["tolerance_m"]
    table = json.loads((PRODUCTION / "q2_evidence_table.json").read_text(encoding="utf-8"))
    rows = {row["method"]: row for row in table["rows"]}
    assert rows["B1"]["Q"] is None and rows["B2"]["Q"] is None
    svg = (PRODUCTION / "q2_baseline_comparison.svg").read_text(encoding="utf-8")
    assert "Infeasible" in svg
    assert '"Q": 0' not in (PRODUCTION / "q2_baseline_comparison.json").read_text(encoding="utf-8")


def test_baseline_figure_persists_numeric_row_positions() -> None:
    payload = json.loads((PRODUCTION / "q2_baseline_comparison.json").read_text(encoding="utf-8"))
    assert payload["data"]["baseline_bar_indices"] == [0, 3]
    assert payload["data"]["baseline_infeasible_indices"] == [1, 2]


def test_production_figures_have_paper_metadata_and_adaptive_surface() -> None:
    for name in (
        "q2_geometry_overview",
        "q2_crec",
        "q2_angular_image",
        "q2_q_surface",
        "q2_optimum_and_candidate_region",
        "q2_baseline_comparison",
        "q2_worst_case_intersection",
    ):
        payload = json.loads((PRODUCTION / f"{name}.json").read_text(encoding="utf-8"))
        metadata = payload["metadata"]
        assert metadata["dpi"] >= 300
        assert metadata["text_editable"] is True
        assert metadata["candidate_region_semantics"].endswith("not proof")
        assert Path(FIGURES / f"{name}.svg").exists()
        assert Path(FIGURES / f"{name}.pdf").exists()
        assert Path(FIGURES / f"{name}.png").exists()
    surface = json.loads((PRODUCTION / "q2_q_surface.json").read_text(encoding="utf-8"))["data"]["surface"]
    assert len(surface) > 1000


def test_parallel_benchmark_is_exact_and_meets_adoption_threshold() -> None:
    benchmark = json.loads((ARTIFACTS / "q2_batch_benchmark.json").read_text(encoding="utf-8"))
    for rows in benchmark["workloads"].values():
        assert all(row["equivalent_to_workers_1"] for row in rows)
        row8 = next(row for row in rows if row["workers"] == 8)
        assert row8["speedup"] >= 1.33
