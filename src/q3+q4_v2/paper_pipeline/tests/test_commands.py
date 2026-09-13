from pathlib import Path
import sys


PIPELINE_PARENT = Path(__file__).resolve().parents[2]
if str(PIPELINE_PARENT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_PARENT))

from paper_pipeline.commands import build_command


REPO_ROOT = Path(__file__).resolve().parents[4]
CASE_SET = REPO_ROOT / "src/q3+q4_v2/paper_evidence/cases/paper_q3.json"
RUN_ROOT = REPO_ROOT / "src/q3+q4_v2/paper_evidence/runs"
CASE = {
    "question": "q3",
    "case_id": "paper_q3_n10_s950000",
    "case_seed": 950000,
    "source_count": 10,
    "scenario": "random",
}


def test_v1_command_is_frozen_and_case_bound():
    command = build_command(
        "v1_frozen", CASE, CASE_SET, RUN_ROOT / "v1", REPO_ROOT
    )
    joined = " ".join(command)
    assert "candidate_v1_FROZEN_CONFIG.yaml" in joined
    assert "candidate_a1_a3" in command
    assert command[command.index("--case-id") + 1] == CASE["case_id"]
    assert command[command.index("--max-steps") + 1] == "20000"


def test_v2_final_command_uses_absorbed_engine_and_same_world_tuple():
    command = build_command(
        "v2_final", CASE, CASE_SET, RUN_ROOT / "v2", REPO_ROOT
    )
    assert command[command.index("--engine") + 1] == "q3-v5"
    assert command[command.index("--seed") + 1] == "950000"
    assert command[command.index("--n-sources") + 1] == "10"
    assert command[command.index("--scenario") + 1] == "random"
    assert command[command.index("--sim") + 1] == "synthetic"


def test_output_must_stay_under_paper_evidence_runs():
    outside = REPO_ROOT / "paper" / "unsafe-output"
    try:
        build_command("v2_final", CASE, CASE_SET, outside, REPO_ROOT)
    except ValueError as exc:
        assert "paper_evidence/runs" in str(exc).replace("\\", "/")
    else:
        raise AssertionError("outside output path was accepted")
