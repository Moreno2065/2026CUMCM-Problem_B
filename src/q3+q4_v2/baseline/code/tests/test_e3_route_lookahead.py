# -*- coding: utf-8 -*-
"""E3: deterministic two-stop lookahead for Q4 certificate routing."""

import copy

import pytest

from executor.action_executor import ActionExecutor
from experiment.config import MainlineConfig
from experiment.runner import GameRunner
from experiment.simulator import SimulatorBackend, SyntheticSimulator
from policy.certificate_policy import CertificatePolicy
from policy.route_lookahead import choose_lookahead2
from policy.scheduler import Scheduler
from state.channel_state import ChannelStatus
from state.knowledge_state import KnowledgeState


def _candidate(point, channels, gain, score=None, joint=None):
    candidate = {
        "point": point,
        "channels": channels,
        "gain": float(gain),
        "cost": 999.0,
        "score": float(gain if score is None else score),
        "kind": "fixture",
    }
    if joint is not None:
        candidate["joint_state_score"] = float(joint)
    return candidate


def _only_unknown(channel_id=1):
    ks = KnowledgeState("Q4")
    for cid, channel in ks.channels.items():
        if cid != channel_id:
            channel.status = ChannelStatus.CERTIFIED_ABSENT
            channel.absent_basis = "test_fixture"
    return ks


def _membership(candidates):
    return [
        (tuple(candidate["point"]), tuple(candidate["channels"]),
         candidate["kind"])
        for candidate in candidates
    ]


def test_pair_cost_uses_exact_measure_and_channel_switch_sequence():
    candidates = [
        _candidate((15.0, 20.0), [3, 1, 3], 2.0),
        _candidate((15.0, 30.0), [4, 2], 2.0),
    ]

    chosen = choose_lookahead2(candidates, (0.0, 0.0), 3)

    assert chosen["point"] == (15.0, 20.0)
    # First stop: 25/5 + 2*5 + one transition (3 -> 1) = 16.
    # Second: 10/5 + 2*5 + two transitions (1 -> 2 -> 4) = 14.
    assert chosen["lookahead_pair_cost"] == pytest.approx(30.0)
    assert chosen["lookahead_pair_gain"] == 4.0
    assert chosen["lookahead_second_point"] == [15.0, 30.0]
    assert chosen["lookahead_depth"] == 2


def test_lookahead_rejects_best_immediate_greedy_first_stop():
    greedy = _candidate((1.0, 0.0), [1], 5.0, score=100.0)
    productive_a = _candidate((100.0, 0.0), [1], 20.0, score=2.0)
    productive_b = _candidate((101.0, 0.0), [1], 20.0, score=1.0)

    chosen = choose_lookahead2(
        [greedy, productive_a, productive_b], (0.0, 0.0), 1)

    assert chosen["point"] == (100.0, 0.0)
    assert chosen["lookahead_second_point"] == [101.0, 0.0]


def test_one_distinct_point_falls_back_to_existing_greedy_and_depth_one():
    candidates = [
        _candidate((10.0, 0.0), [1], 1.0, score=1.0),
        _candidate((10.0, 0.0), [1, 2], 2.0, score=2.0),
    ]

    chosen = choose_lookahead2(candidates, (0.0, 0.0), 1)

    assert chosen["channels"] == [1, 2]
    assert chosen["lookahead_depth"] == 1
    assert chosen["lookahead_second_point"] is None
    assert chosen["lookahead_pair_gain"] == 2.0
    assert chosen["lookahead_pair_cost"] == pytest.approx(13.0)


def test_route_tie_is_deterministic_and_lexicographic():
    left = _candidate((-10.0, 0.0), [1], 1.0, score=1.0)
    right = _candidate((10.0, 0.0), [1], 1.0, score=100.0)

    forward = choose_lookahead2([right, left], (0.0, 0.0), 1)
    reverse = choose_lookahead2([left, right], (0.0, 0.0), 1)

    assert forward == reverse
    assert forward["point"] == (-10.0, 0.0)
    assert forward["lookahead_second_point"] == [10.0, 0.0]


def test_joint_score_breaks_exact_route_tie_before_existing_score():
    left = _candidate((-10.0, 0.0), [1], 1.0,
                      score=100.0, joint=0.1)
    right = _candidate((10.0, 0.0), [1], 1.0,
                       score=1.0, joint=0.9)

    chosen = choose_lookahead2([left, right], (0.0, 0.0), 1)

    assert chosen["point"] == (10.0, 0.0)
    assert chosen["joint_state_score"] == 0.9


@pytest.mark.parametrize(
    "invalid",
    [
        {"point": (0.0,), "channels": [1], "gain": 1.0},
        {"point": (0.0, 0.0, 0.0), "channels": [1], "gain": 1.0},
        {"point": (float("nan"), 0.0), "channels": [1], "gain": 1.0},
        {"point": (float("inf"), 0.0), "channels": [1], "gain": 1.0},
        {"point": (0.0, 0.0), "channels": [], "gain": 1.0},
        {"point": (0.0, 0.0), "channels": None, "gain": 1.0},
        {"point": (0.0, 0.0), "channels": [1.0], "gain": 1.0},
        {"point": (0.0, 0.0), "channels": [0], "gain": 1.0},
        {"point": (0.0, 0.0), "channels": [21], "gain": 1.0},
        {"point": (0.0, 0.0), "channels": [1], "gain": -1.0},
        {"point": (0.0, 0.0), "channels": [1],
         "gain": float("nan")},
        {"point": (0.0, 0.0), "channels": [1],
         "gain": float("inf")},
        {"point": (0.0, 0.0), "channels": [1], "gain": 1.0,
         "score": float("nan")},
        {"point": (0.0, 0.0), "channels": [1], "gain": 1.0,
         "score": float("inf")},
        {"point": (0.0, 0.0), "channels": [1], "gain": 1.0,
         "joint_state_score": float("nan")},
        {"point": (0.0, 0.0), "channels": [1], "gain": 1.0,
         "joint_state_score": float("-inf")},
    ],
)
def test_invalid_candidate_is_excluded_fail_closed(invalid):
    valid = _candidate((10.0, 0.0), [1], 1.0)

    chosen = choose_lookahead2([invalid, valid], (0.0, 0.0), 1)

    assert chosen["point"] == valid["point"]
    assert chosen["lookahead_depth"] == 1


def test_all_invalid_candidates_return_none_without_raising():
    invalid = [
        {"point": (float("nan"), 0.0), "channels": [1], "gain": 1.0},
        {"point": (0.0, 0.0), "channels": [], "gain": 1.0},
        {"point": (1.0, 0.0), "channels": [1], "gain": -1.0},
    ]

    assert choose_lookahead2(invalid, (0.0, 0.0), 1) is None


@pytest.mark.parametrize("cost", [float("nan"), float("inf"), -1.0])
def test_invalid_cost_key_excludes_candidate_fail_closed(cost):
    invalid = _candidate((0.0, 0.0), [1], 10.0)
    invalid["cost"] = cost
    valid = _candidate((10.0, 0.0), [1], 1.0)

    chosen = choose_lookahead2([invalid, valid], (0.0, 0.0), 1)

    assert chosen["point"] == valid["point"]
    assert chosen["lookahead_depth"] == 1


@pytest.mark.parametrize("cost", [0.0, 999.0])
def test_finite_nonnegative_cost_key_is_accepted(cost):
    candidate = _candidate((0.0, 0.0), [1], 1.0)
    candidate["cost"] = cost

    chosen = choose_lookahead2([candidate], (0.0, 0.0), 1)

    assert chosen["point"] == candidate["point"]


@pytest.mark.parametrize(
    "metadata",
    [object(), {"nested": [float("nan")]}, {"nested": float("inf")}],
)
def test_unstable_or_nonfinite_extra_metadata_excludes_candidate(metadata):
    invalid = _candidate((0.0, 0.0), [1], 10.0)
    invalid["metadata"] = metadata
    valid = _candidate((10.0, 0.0), [1], 1.0)

    chosen = choose_lookahead2([invalid, valid], (0.0, 0.0), 1)

    assert chosen["point"] == valid["point"]
    assert chosen["lookahead_depth"] == 1


def test_duplicate_coordinate_identity_is_independent_of_input_order():
    alpha = _candidate((-10.0, 0.0), [2, 1, 2], 2.0)
    alpha.update({"kind": "alpha", "marker": "chosen"})
    beta = _candidate((-10.0, 0.0), [1, 2], 2.0)
    beta.update({"kind": "beta", "marker": "not-chosen"})
    other = _candidate((10.0, 0.0), [1, 2], 2.0)

    forward = choose_lookahead2([beta, other, alpha], (0.0, 0.0), 1)
    reverse = choose_lookahead2([alpha, other, beta], (0.0, 0.0), 1)

    assert forward == reverse
    assert forward["marker"] == "chosen"


def test_duplicate_coordinate_final_json_identity_is_input_order_independent():
    alpha = _candidate((-10.0, 0.0), [1, 2], 2.0)
    alpha.update({"kind": "same", "metadata": {"tag": "a"}})
    zulu = _candidate((-10.0, 0.0), [1, 2], 2.0)
    zulu.update({"kind": "same", "metadata": {"tag": "z"}})
    other = _candidate((10.0, 0.0), [1, 2], 2.0)

    forward = choose_lookahead2([zulu, other, alpha], (0.0, 0.0), 1)
    reverse = choose_lookahead2([alpha, other, zulu], (0.0, 0.0), 1)

    assert forward == reverse
    assert forward["metadata"] == {"tag": "a"}


def test_selector_normalization_does_not_mutate_candidate_trace_pool():
    candidates = [
        _candidate((-10.0, 0.0), [2, 1, 2], 2.0),
        _candidate((10.0, 0.0), [1], 1.0),
        {"point": (float("nan"), 0.0), "channels": [1], "gain": 1.0},
    ]
    before = copy.deepcopy(candidates)

    choose_lookahead2(candidates, (0.0, 0.0), 1)

    assert candidates == before


def test_disabled_mode_preserves_exact_policy_and_scheduler_behavior():
    ks = _only_unknown()
    implicit_candidates = []
    disabled_candidates = []
    implicit = CertificatePolicy("Q4").choose(
        ks, (0.0, 0.0), 1, implicit_candidates.extend)
    disabled = CertificatePolicy("Q4", cert_route_mode="greedy").choose(
        ks, (0.0, 0.0), 1, disabled_candidates.extend)

    assert disabled == implicit
    assert disabled_candidates == implicit_candidates

    implicit_scheduler = Scheduler("Q4")
    disabled_scheduler = Scheduler("Q4", cert_route_mode="greedy")
    implicit_trace = []
    disabled_trace = []
    implicit_scheduler.decision_listener = implicit_trace.append
    disabled_scheduler.decision_listener = disabled_trace.append
    assert disabled_scheduler.decide(ks, (0.0, 0.0), 1).__dict__ == \
        implicit_scheduler.decide(ks, (0.0, 0.0), 1).__dict__
    assert disabled_trace == implicit_trace


def test_greedy_route_keeps_existing_e2_mission_metadata_shape():
    mission = Scheduler("Q4", q4_joint_rank=True,
                        cert_route_mode="greedy").decide(
                            _only_unknown(), (0.0, 0.0), 1)

    assert set(mission.meta) == {"kind", "gain", "cost"}


def test_enabled_mode_keeps_candidate_pool_membership_unchanged():
    ks = _only_unknown()
    greedy_candidates = []
    route_candidates = []
    CertificatePolicy("Q4").choose(
        ks, (100.0, 0.0), 1, greedy_candidates.extend)
    CertificatePolicy("Q4", cert_route_mode="lookahead2").choose(
        ks, (100.0, 0.0), 1, route_candidates.extend)

    assert _membership(route_candidates) == _membership(greedy_candidates)


def test_e2_e3_scheduler_trace_and_mission_expose_route_metadata():
    ks = _only_unknown()
    scheduler = Scheduler(
        "Q4", q4_joint_rank=True, cert_route_mode="lookahead2")
    traces = []
    scheduler.decision_listener = traces.append

    mission = scheduler.decide(ks, (0.0, 0.0), 1)

    assert mission.kind == "scan"
    for field in (
        "lookahead_depth", "lookahead_second_point",
        "lookahead_pair_cost", "lookahead_pair_gain",
    ):
        assert field in mission.meta
        assert traces[-1]["selected"][field] == mission.meta[field]
    assert "joint_state_score" in traces[-1]["selected"]
    assert "joint_hypothesis_count" in traces[-1]["selected"]
    assert "E2 joint score" in traces[-1]["tie_break"]


def test_e3_trace_without_e2_describes_only_active_tie_breaks():
    scheduler = Scheduler("Q4", cert_route_mode="lookahead2")
    traces = []
    scheduler.decision_listener = traces.append

    scheduler.decide(_only_unknown(), (0.0, 0.0), 1)

    tie_break = traces[-1]["tie_break"]
    assert "E2" not in tie_break
    assert "route ratio" in tie_break
    assert "pair cost" in tie_break
    assert "deterministic identity" in tie_break


def test_tau_fallthrough_uses_lookahead_and_records_route_metadata():
    ks = KnowledgeState("Q4")
    ks[1].update_direction((-1000.0, 0.0), 0.0, 0.0)
    scheduler = Scheduler("Q4", tau=1e9, cert_route_mode="lookahead2")
    traces = []
    scheduler.decision_listener = traces.append

    mission = scheduler.decide(ks, (0.0, 0.0), 1)

    assert mission.kind == "scan"
    assert mission.meta["tau_fallthrough"] is True
    assert mission.meta["lookahead_depth"] == 2
    audit = traces[-1]
    assert audit["policy_mode"] == "certificate_tau_fallthrough"
    assert audit["selected"]["lookahead_second_point"] == \
        mission.meta["lookahead_second_point"]


def test_runner_propagates_route_mode_without_mutating_config():
    config = MainlineConfig(cert_route_mode="lookahead2")
    before = copy.deepcopy(config.to_dict())
    simulator = SyntheticSimulator("Q4", seed=17, n_sources=0,
                                   scenario="random")
    runner = GameRunner(
        "Q4", ActionExecutor(SimulatorBackend(simulator)),
        "unused-test-output", simulator=simulator, config=config)

    assert runner.scheduler.cert_route_mode == "lookahead2"
    assert runner.scheduler.certificate.cert_route_mode == "lookahead2"
    assert config.to_dict() == before


def test_q4_e3_end_to_end_completes_with_verifier_ok(tmp_path):
    simulator = SyntheticSimulator(
        "Q4", seed=17, n_sources=1, scenario="random")
    executor = ActionExecutor(SimulatorBackend(simulator))
    config = MainlineConfig(cert_route_mode="lookahead2")
    runner = GameRunner(
        "Q4", executor, str(tmp_path), simulator=simulator, config=config)

    report = runner.run()

    assert report["complete"]
    assert report["failure"] is None
    assert report["verifier_all_ok"]
    assert any(
        trace.get("selected", {}).get("lookahead_depth") == 2
        for trace in runner.decision_trace
        if trace.get("selected")
    )
    assert all(source.cleared for source in simulator.sources)
