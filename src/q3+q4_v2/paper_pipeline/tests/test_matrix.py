from pathlib import Path
import hashlib
import json
import sys


PIPELINE_PARENT = Path(__file__).resolve().parents[2]
if str(PIPELINE_PARENT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_PARENT))

from paper_pipeline.matrix import build_case_sets, canonical_payload_hash


REPO_ROOT = Path(__file__).resolve().parents[4]


def test_case_matrix_is_deterministic_and_complete():
    first = build_case_sets(REPO_ROOT)
    second = build_case_sets(REPO_ROOT)
    assert first == second
    assert len(first["q3"]["cases"]) == 60
    assert len(first["q4"]["cases"]) == 60


def test_matrix_has_planned_sources_scenarios_and_seed_counts():
    sets = build_case_sets(REPO_ROOT)
    for question, seed_start, scenario in (
        ("q3", 950000, "random"),
        ("q4", 960000, "mixed"),
    ):
        cases = sets[question]["cases"]
        assert {case["source_count"] for case in cases} == {10, 13, 16}
        assert {case["scenario"] for case in cases} == {scenario}
        for source_count in (10, 13, 16):
            block = [c for c in cases if c["source_count"] == source_count]
            assert len(block) == 20
        assert min(c["case_seed"] for c in cases) == seed_start
        assert max(c["case_seed"] for c in cases) == seed_start + 59


def test_q3_is_omnidirectional_and_payload_hash_ignores_case_label():
    case = build_case_sets(REPO_ROOT)["q3"]["cases"][0]
    assert all(direction is None for direction in case["directions"])
    renamed = dict(case, case_id="renamed_for_reporting")
    assert canonical_payload_hash(case) == canonical_payload_hash(renamed)
    assert len(canonical_payload_hash(case)) == 64
