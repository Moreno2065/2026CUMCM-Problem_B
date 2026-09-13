from pathlib import Path
import sys


PIPELINE_PARENT = Path(__file__).resolve().parents[2]
if str(PIPELINE_PARENT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_PARENT))

from paper_pipeline.aggregate import accepted, paired_effect, summarize_variant_rows


def test_accepted_requires_complete_full_clear_and_verifier():
    good = {"complete": True, "cleared_count": 10, "sources_total": 10,
            "verifier_all_ok": True}
    assert accepted(good)
    assert not accepted(dict(good, complete=False))
    assert not accepted(dict(good, cleared_count=9))
    assert not accepted(dict(good, verifier_all_ok=False))


def test_paired_effect_uses_case_identity_and_reports_reduction():
    rows = [
        {"policy": "v1_frozen", "case_hash": "a", "t_per_source_s": 100.0},
        {"policy": "v2_final", "case_hash": "a", "t_per_source_s": 70.0},
        {"policy": "v1_frozen", "case_hash": "b", "t_per_source_s": 120.0},
        {"policy": "v2_final", "case_hash": "b", "t_per_source_s": 90.0},
        {"policy": "v2_final", "case_hash": "unpaired", "t_per_source_s": 1.0},
    ]
    result = paired_effect(rows, bootstrap_samples=500, rng_seed=7)
    assert result["n_pairs"] == 2
    assert result["mean_v1_s"] == 110.0
    assert result["mean_v2_s"] == 80.0
    assert result["mean_delta_s"] == -30.0
    assert round(result["relative_reduction_pct"], 6) == round(100 * 30 / 110, 6)
    assert result["wins_v2"] == 2


def test_variant_summary_separates_safety_failures_from_efficiency():
    rows = [
        {"variant_id": "safe", "accepted": True, "t_per_source_s": 10.0},
        {"variant_id": "safe", "accepted": True, "t_per_source_s": 14.0},
        {"variant_id": "unsafe", "accepted": False, "t_per_source_s": 1.0},
        {"variant_id": "unsafe", "accepted": True, "t_per_source_s": 20.0},
    ]
    summaries = {row["variant_id"]: row for row in summarize_variant_rows(rows)}
    assert summaries["safe"]["acceptance_rate"] == 1.0
    assert summaries["safe"]["mean_t_per_source_s"] == 12.0
    assert summaries["unsafe"]["acceptance_rate"] == 0.5
    assert summaries["unsafe"]["mean_t_per_source_s"] == 20.0
