from copy import deepcopy
from pathlib import Path
import sys


PIPELINE_PARENT = Path(__file__).resolve().parents[2]
if str(PIPELINE_PARENT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_PARENT))

from paper_pipeline.variants import build_registry, effective_parameters
from paper_pipeline.run_variant import _engine, select_cases


def test_ablation_changes_only_declared_keys():
    registry = build_registry()
    for variant in registry["variants"]:
        base = deepcopy(registry["base_parameters"][variant["question"]])
        effective = effective_parameters(base, variant["overrides"])
        changed = {key for key in base if base[key] != effective[key]}
        assert changed == set(variant["overrides"])
        assert base == registry["base_parameters"][variant["question"]]


def test_registry_has_identifiable_major_modules_for_both_questions():
    registry = build_registry()
    names = {row["variant_id"] for row in registry["variants"]}
    assert {
        "q3_no_joint_route",
        "q3_no_shared_probe",
        "q3_no_site_projection",
        "q3_no_trial_clear",
        "q4_no_exact_insertion",
        "q4_no_rotation",
        "q4_no_crossbar",
        "q4_no_negative_update",
        "q4_no_trial_clear",
    } <= names


def test_tuning_values_include_locked_value_and_neighboring_values():
    registry = build_registry()
    for sweep in registry["tuning"]:
        assert sweep["locked_value"] in sweep["values"]
        assert len(sweep["values"]) >= 3


def test_ablation_case_selection_uses_twenty_seeds_at_10_and_16_sources():
    cases = [
        {"case_id": f"n{n}_s{i}", "source_count": n}
        for n in (10, 13, 16)
        for i in range(20)
    ]
    selected = select_cases(cases, kind="ablation", phase="main")
    assert len(selected) == 40
    assert {row["source_count"] for row in selected} == {10, 16}


def test_tuning_case_selection_uses_separate_fixed_subset():
    cases = [
        {"case_id": f"n{n}_s{i}", "source_count": n}
        for n in (10, 13, 16)
        for i in range(20)
    ]
    selected = select_cases(cases, kind="tuning", phase="main")
    assert len(selected) == 10
    assert {row["source_count"] for row in selected} == {13}


def test_q4_variant_uses_locked_version_with_strategy_solve():
    engine, version, solve = _engine("q4")
    assert engine == "q4-v4"
    assert version == "q4_21station_exact_route_v4"
    assert callable(solve)
