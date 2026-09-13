"""Regression checks for the final standardized Q2 handoff artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from src.q2.code.model.frozen_contract import (
    EPSILON_DEG,
    OMEGA_RADIUS_M,
    RADIAL_HI_M,
    RADIAL_LO_M,
    RECEPTION_RADIUS_M,
)
from src.q2.code.solver.baselines import BaselineFormula


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"


def test_frozen_contract_constants_are_explicit() -> None:
    assert (OMEGA_RADIUS_M, RADIAL_LO_M, RADIAL_HI_M) == (1800.0, 5.0, 1500.0)
    assert RECEPTION_RADIUS_M == 1000.0
    assert EPSILON_DEG == 1.0


def test_b1_formula_matches_frozen_numbers() -> None:
    formula = BaselineFormula()
    assert formula.length_m == 1495.0
    assert formula.x_star_m == 673.8963210702341
    assert formula.abs_y_star_m == 743.3557100464799


def test_required_standardized_artifacts_exist_and_are_json_valid() -> None:
    names = (
        "q2_model_spec.json",
        "q2_solver_config.json",
        "q2_final_verification_report.json",
        "q2_regression_cases.json",
        "q2_candidate_regions.json",
        "q2_solution_examples.json",
        "q2_run_manifest.json",
    )
    for name in names:
        payload = json.loads((ARTIFACTS / name).read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
    assert (ARTIFACTS / "q2_baseline_comparison.csv").exists()


def test_baseline_comparison_has_all_headline_methods() -> None:
    with (ARTIFACTS / "q2_baseline_comparison.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert [row["method"] for row in rows] == ["B0", "B1", "B2", "Hero"]
    assert rows[-1]["Q_m"] == "134.07676525132717"
