# -*- coding: utf-8 -*-
"""Q3 ML experimental branch: offline ranker and frozen-mainline isolation."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from experiment.config import MainlineConfig, load_config
from experiment.casefile import (
    audit_case_hash_isolation,
    canonical_case_hash,
    generate_q3_ml_case_sets,
    generate_case,
    save_case_set,
)
from experiment.runner import GameRunner
from experiment.simulator import SimulatorBackend, SyntheticSimulator
from executor.action_executor import ActionExecutor
from experiment.suite import VARIANTS, _case_entry, _run_one_case
from policy.q3_ml_ranker import (
    Q3LinearRanker,
    rank_q3_candidates,
    select_q3_candidate,
)
from policy.q3_ml_replay import (
    collect_replay_labeled_traces,
    collect_replay_labeled_trace_file,
    replay_candidate_branch,
    replay_candidate_labels,
)
from policy.q3_ml_train import (
    _trace_pairs,
    calibrate_takeover_gate,
    train_q3_ranker,
)
from policy.scheduler import Scheduler


def _candidate(x, y, score, gain, cost, kind="nbv"):
    return {"channel": 1, "point": [x, y], "score": score,
            "gain": gain, "cost": cost, "kind": kind}


def test_pairwise_ranker_learns_preferred_candidate_deterministically():
    model = Q3LinearRanker.fit_pairwise([
        ({"score": 0.3, "gain": 3.0, "cost": 10.0,
          "point": [100.0, 0.0], "kind": "nbv"},
         {"score": 0.2, "gain": 2.0, "cost": 10.0,
          "point": [0.0, 100.0], "kind": "nbv"}),
    ], epochs=8)
    candidates = [
        _candidate(0, 100, 0.2, 2.0, 10.0),
        _candidate(100, 0, 0.3, 3.0, 10.0),
    ]
    ranked = rank_q3_candidates(model, candidates, (0.0, 0.0))
    assert ranked[0]["point"] == [100.0, 0.0]
    assert ranked[0]["ml_score"] > ranked[1]["ml_score"]


def test_pairwise_training_uses_decision_position_for_distance_feature():
    preferred = _candidate(1000.0, 0.0, 0.0, 1.0, 10.0)
    rejected = _candidate(0.0, 0.0, 0.0, 1.0, 10.0)

    model = Q3LinearRanker.fit_pairwise([
        (preferred, rejected, (1000.0, 0.0)),
    ], epochs=1, learning_rate=0.001)

    ranked = rank_q3_candidates(
        model, [rejected, preferred], position=(1000.0, 0.0))
    assert ranked[0]["point"] == [1000.0, 0.0]
    assert model.normalization["feature_names"]
    assert model.normalization["scales"][3] > 0.0


def test_q3_ml_gate_falls_back_on_low_margin():
    model = Q3LinearRanker({"distance": -0.00001}, metadata={
        "takeover_gate": {"min_ml_margin": 0.05},
    })
    candidates = [
        _candidate(100.0, 0.0, 0.9, 9.0, 10.0),
        _candidate(0.0, 0.0, 0.8, 8.0, 10.0),
    ]

    choice = select_q3_candidate(model, candidates, position=(0.0, 0.0))

    assert choice["point"] == [100.0, 0.0]
    assert choice["takeover"] is False
    assert choice["takeover_reason"] == "low_confidence_or_margin"


def test_q3_ml_gate_allows_high_margin_takeover():
    model = Q3LinearRanker({"distance": -1.0}, metadata={
        "takeover_gate": {"min_ml_margin": 0.05},
    })
    candidates = [
        _candidate(100.0, 0.0, 0.9, 9.0, 10.0),
        _candidate(0.0, 0.0, 0.8, 8.0, 10.0),
    ]

    choice = select_q3_candidate(model, candidates, position=(0.0, 0.0))

    assert choice["point"] == [0.0, 0.0]
    assert choice["takeover"] is True
    assert choice["takeover_reason"] == "margin_cleared"


def test_q3_ml_gate_rejects_abnormal_takeover_candidate():
    model = Q3LinearRanker({"distance": -1.0}, metadata={
        "takeover_gate": {"min_ml_margin": 0.0},
    })
    candidates = [
        _candidate(100.0, 0.0, 0.9, 9.0, 10.0),
        _candidate(0.0, 0.0, 0.8, -1.0, 10.0),
    ]

    choice = select_q3_candidate(model, candidates, position=(0.0, 0.0))

    assert choice["point"] == [100.0, 0.0]
    assert choice["takeover"] is False
    assert choice["takeover_reason"] == "abnormal_candidate"


def test_takeover_gate_calibration_uses_replay_labels(tmp_path):
    model = Q3LinearRanker({"distance": -1.0})
    trace = tmp_path / "calibration.jsonl"
    candidates = [
        {**_candidate(100.0, 0.0, 0.9, 9.0, 10.0),
         "long_horizon_cost_s": 120.0},
        {**_candidate(0.0, 0.0, 0.8, 8.0, 10.0),
         "long_horizon_cost_s": 80.0},
    ]
    trace.write_text(json.dumps({
        "policy_mode": "active_localization",
        "position": [0.0, 0.0],
        "candidates": candidates,
    }) + "\n", encoding="utf-8")

    gate = calibrate_takeover_gate(model, [str(trace)])

    assert gate["enabled"] is True
    assert gate["min_ml_margin"] > 0.0
    assert gate["calibration"]["worst_saving_s"] == 40.0


def test_disabled_takeover_gate_falls_back_even_with_large_margin():
    model = Q3LinearRanker({"distance": -1.0}, metadata={
        "takeover_gate": {"enabled": False, "min_ml_margin": 0.0},
    })
    candidates = [
        _candidate(100.0, 0.0, 0.9, 9.0, 10.0),
        _candidate(0.0, 0.0, 0.8, 8.0, 10.0),
    ]

    choice = select_q3_candidate(model, candidates)

    assert choice["takeover"] is False
    assert choice["takeover_reason"] == "gate_disabled"


def test_ranker_rejects_nonfinite_candidate_without_mutating_input():
    model = Q3LinearRanker.default()
    bad = _candidate(0, 0, float("nan"), 1.0, 2.0)
    original = json.loads(json.dumps({"candidate": "bad"}))
    with pytest.raises(ValueError):
        rank_q3_candidates(model, [bad], (0.0, 0.0))
    assert original == {"candidate": "bad"}


def test_q3_ml_config_and_registry_are_explicit_and_disabled_by_default():
    cfg = MainlineConfig()
    assert cfg.to_dict()["q3_ml_ranker"] is False
    assert cfg.to_dict()["q3_ml_model_path"] is None
    assert VARIANTS["q3_ml_experimental"][0] == {"q3_ml_ranker": True}
    assert VARIANTS["q3_ml_experimental"][1] == ("q3",)
    assert MainlineConfig().derive(q3_ml_ranker=True).to_dict()[
        "q3_ml_ranker"] is True

    path = os.path.join(os.path.dirname(__file__), "_q3_ml_config.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"q3_ml_ranker": True}, f)
        assert load_config(path).q3_ml_ranker is True
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_scheduler_q3_ml_branch_keeps_q4_disabled():
    q3 = Scheduler("Q3", q3_ml_ranker=True)
    q4 = Scheduler("Q4", q3_ml_ranker=True)
    assert q3.q3_ml_ranker is not None
    assert q4.q3_ml_ranker is None


def test_offline_trace_training_writes_a_versioned_model(tmp_path):
    trace = tmp_path / "decision_trace.jsonl"
    trace.write_text(json.dumps({
        "policy_mode": "active_localization",
        "position": [1000.0, 0.0],
        "candidates": [
            {**_candidate(100, 0, 0.4, 4.0, 10.0),
             "long_horizon_cost_s": 20.0},
            {**_candidate(0, 100, 0.1, 1.0, 10.0),
             "long_horizon_cost_s": 30.0},
        ],
    }) + "\n", encoding="utf-8")
    model_path = tmp_path / "q3_ranker.json"
    report = train_q3_ranker([str(trace)], str(model_path), epochs=4)
    loaded = Q3LinearRanker.load(str(model_path))
    assert report["pair_count"] == 1
    assert loaded.metadata["source"] == "offline_pairwise_perceptron"
    assert loaded.metadata["label_field"] == "long_horizon_cost_s"
    assert loaded.to_dict()["model_version"] == "q3-linear-ranker-v2"


def test_trace_pairs_carry_the_recorded_decision_position(tmp_path):
    trace = tmp_path / "decision_trace.jsonl"
    trace.write_text(json.dumps({
        "policy_mode": "active_localization",
        "position": [1000.0, 0.0],
        "candidates": [
            {**_candidate(100.0, 0.0, 0.4, 4.0, 10.0),
             "long_horizon_cost_s": 20.0},
            {**_candidate(0.0, 100.0, 0.1, 1.0, 10.0),
             "long_horizon_cost_s": 30.0},
        ],
    }) + "\n", encoding="utf-8")

    pairs = _trace_pairs(str(trace), min_gap=0.0)
    assert len(pairs) == 1
    assert pairs[0][2] == (1000.0, 0.0)


def test_trainer_rejects_teacher_only_trace_by_default(tmp_path):
    trace = tmp_path / "legacy_trace.jsonl"
    trace.write_text(json.dumps({
        "policy_mode": "active_localization",
        "position": [0.0, 0.0],
        "candidates": [
            _candidate(100.0, 0.0, 0.4, 4.0, 10.0),
            _candidate(0.0, 100.0, 0.1, 1.0, 10.0),
        ],
    }) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="long_horizon_cost_s"):
        train_q3_ranker([str(trace)], str(tmp_path / "model.json"))


def test_canonical_case_hash_ignores_case_id_but_tracks_case_content():
    first = generate_case("q3", 222222, case_id="first", n_sources=1)
    second = dict(first, case_id="renamed")
    changed = dict(first, positions=[[first["positions"][0][0] + 1.0,
                                      first["positions"][0][1]]])

    assert canonical_case_hash(first) == canonical_case_hash(second)
    assert canonical_case_hash(first) != canonical_case_hash(changed)


def test_case_hash_audit_rejects_cross_split_duplicate(tmp_path):
    case = generate_case("q3", 333333, case_id="shared", n_sources=1)
    train_path = tmp_path / "train.json"
    holdout_path = tmp_path / "holdout.json"
    save_case_set("train", "training", "q3", [case], str(train_path))
    save_case_set("holdout", "holdout", "q3",
                  [dict(case, case_id="holdout_copy")],
                  str(holdout_path))

    report = audit_case_hash_isolation({
        "train": [str(train_path)],
        "holdout": [str(holdout_path)],
    })
    assert not report["ok"]
    assert report["duplicate_hashes"]
    assert {loc["split"] for loc in
            report["duplicates"][0]["locations"]} == {"train", "holdout"}


def test_q3_ml_case_generator_records_isolated_canonical_hashes(tmp_path):
    generated = generate_q3_ml_case_sets(
        str(tmp_path / "q3_ml_cases"), train_count=2, explore_count=2,
        holdout_count=2, seed_start=2_000_000)

    report = audit_case_hash_isolation(generated)
    assert report["ok"]
    assert report["total_cases"] == 6
    manifest = json.loads((tmp_path / "q3_ml_cases" / "manifest.json")
                          .read_text(encoding="utf-8"))
    assert manifest["isolation"]["cross_split_ok"]
    assert manifest["splits"]["train"]["case_hashes"]


def test_candidate_branch_replay_returns_long_horizon_cost_without_mutating_source(
        tmp_path):
    case = generate_case("q3", 987654, n_sources=1, scenario="random")
    simulator = SyntheticSimulator.from_case(case)
    executor = ActionExecutor(SimulatorBackend(simulator))
    runner = GameRunner("Q3", executor, str(tmp_path / "replay_source"),
                        simulator=simulator, case=case)
    executor.enter()

    candidate = None
    for _ in range(20):
        mission = runner.scheduler.decide(
            runner.ks, runner.executor.position, runner.executor.current_channel)
        trace = runner.decision_trace[-1]
        if trace["policy_mode"] == "active_localization" \
                and trace["candidates"]:
            candidate = trace["candidates"][0]
            break
        assert mission is not None
        runner._current_mission = mission
        runner._execute(mission)
        runner._current_mission = None
        runner._step += 1
    assert candidate is not None
    before = runner.executor.virtual_time

    label = replay_candidate_branch(runner, candidate, max_steps=2000)

    assert label["complete"]
    assert label["candidate"]["channel"] == candidate["channel"]
    assert label["delta_virtual_time_s"] > 0.0
    assert runner.executor.virtual_time == before

    labels = replay_candidate_labels(runner, [candidate], max_steps=2000)
    assert labels[0]["label_source"] == "synthetic_branch_replay"
    assert labels[0]["long_horizon_cost_s"] == label[
        "delta_virtual_time_s"]
    assert labels[0]["decision_position"] == list(runner.executor.position)


def test_replay_collector_emits_long_horizon_labeled_trace(tmp_path):
    case = generate_case("q3", 987654, n_sources=1, scenario="random")
    collected = collect_replay_labeled_traces(
        case, max_steps=2000, branch_max_steps=2000)

    assert collected["case_id"] == case["case_id"]
    assert collected["labeled_decision_count"] > 0
    labeled = next(trace for trace in collected["traces"]
                   if trace.get("label_source") ==
                   "synthetic_branch_replay")
    assert labeled["label_source"] == "synthetic_branch_replay"
    assert all("long_horizon_cost_s" in candidate
               for candidate in labeled["candidates"])


def test_replay_collector_can_write_training_trace_file(tmp_path):
    case = generate_case("q3", 987654, n_sources=1, scenario="random")
    output = tmp_path / "labeled.jsonl"

    report = collect_replay_labeled_trace_file(
        case, output, max_steps=2000, branch_max_steps=2000)

    assert report["trace_path"] == str(output.resolve())
    assert output.exists()
    assert "synthetic_branch_replay" in output.read_text(encoding="utf-8")


def test_decision_trace_records_position_before_scheduler_decision(tmp_path):
    case = generate_case("q3", 987654, n_sources=1, scenario="random")
    cfg = MainlineConfig()
    report, runner = _run_one_case(
        case, cfg, None, str(tmp_path / "trace_position"),
        policy_variant="mainline")
    assert report["complete"]
    assert runner.decision_trace
    assert all(
        isinstance(trace.get("position"), list)
        and len(trace["position"]) == 2
        for trace in runner.decision_trace
    )


def test_q3_ml_variant_completes_small_case_without_false_success(tmp_path):
    case = generate_case("q3", 987654, n_sources=1, scenario="random")
    cfg = MainlineConfig().derive(q3_ml_ranker=True)
    report, runner = _run_one_case(
        case, cfg, None, str(tmp_path / "q3_ml"),
        policy_variant="q3_ml_experimental")
    entry = _case_entry(case, report, runner)
    assert report["complete"]
    assert entry["false_certified_absent"] == 0
    trace_path = tmp_path / "q3_ml" / "decision_trace.jsonl"
    traces = [json.loads(line) for line in trace_path.read_text(
        encoding="utf-8").splitlines() if line.strip()]
    assert any(t.get("q3_ml_ranker") for t in traces)
