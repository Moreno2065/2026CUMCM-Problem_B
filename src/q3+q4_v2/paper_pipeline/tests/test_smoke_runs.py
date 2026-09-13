from pathlib import Path
import subprocess
import sys


PIPELINE_PARENT = Path(__file__).resolve().parents[2]
if str(PIPELINE_PARENT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_PARENT))

from paper_pipeline.run_matrix import ground_truth_matches_case


def test_ground_truth_match_ignores_runtime_cleared_flag_and_order():
    case = {
        "channels": [2, 1],
        "positions": [[20.0, 21.0], [10.0, 11.0]],
        "receive_radii": [1200.0, 1100.0],
        "directions": [45.0, None],
    }
    truth = [
        {
            "channel": 1,
            "x": 10.0,
            "y": 11.0,
            "r_eff": 1100.0,
            "directional": False,
            "orientation": None,
            "cleared": True,
        },
        {
            "channel": 2,
            "x": 20.0,
            "y": 21.0,
            "r_eff": 1200.0,
            "directional": True,
            "orientation": 45.0,
            "cleared": False,
        },
    ]
    assert ground_truth_matches_case(case, truth)


def test_omnidirectional_runtime_zero_orientation_is_not_a_mismatch():
    case = {
        "channels": [1],
        "positions": [[10.0, 11.0]],
        "receive_radii": [1100.0],
        "directions": [None],
    }
    truth = [
        {
            "channel": 1,
            "x": 10.0,
            "y": 11.0,
            "r_eff": 1100.0,
            "directional": False,
            "orientation": 0.0,
        }
    ]
    assert ground_truth_matches_case(case, truth)


def test_ground_truth_mismatch_is_detected():
    case = {
        "channels": [1],
        "positions": [[10.0, 11.0]],
        "receive_radii": [1100.0],
        "directions": [None],
    }
    truth = [
        {
            "channel": 1,
            "x": 10.5,
            "y": 11.0,
            "r_eff": 1100.0,
            "directional": False,
            "orientation": None,
        }
    ]
    assert not ground_truth_matches_case(case, truth)


def test_run_matrix_script_can_be_invoked_directly():
    script = PIPELINE_PARENT / "paper_pipeline" / "run_matrix.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=Path(__file__).resolve().parents[4],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--phase" in completed.stdout
