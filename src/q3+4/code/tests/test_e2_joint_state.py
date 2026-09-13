# -*- coding: utf-8 -*-
"""E2: Q4 joint source-state ensemble is a ranking-only ablation."""

import copy
import math

import pytest

import policy.q4_joint_state as joint_state
from executor.action_executor import ActionExecutor
from experiment.config import MainlineConfig
from experiment.runner import GameRunner
from experiment.simulator import SimulatorBackend, Source, SyntheticSimulator
from geometry import constants as C
from geometry.certificate import q4_grid_points
from policy.certificate_policy import CertificatePolicy
from policy.q4_joint_state import rank_q4_candidate
from policy.scheduler import Scheduler
from state.channel_state import ChannelState, ChannelStatus
from state.knowledge_state import KnowledgeState


def _only_unknown(channel_id=1):
    ks = KnowledgeState("Q4")
    for cid, channel in ks.channels.items():
        if cid != channel_id:
            channel.status = ChannelStatus.CERTIFIED_ABSENT
            channel.absent_basis = "test_fixture"
    return ks


def _candidate_snapshot(policy, ks, position=(0.0, 0.0), current_channel=1):
    candidates = []
    choice = policy.choose(
        ks, position, current_channel, candidate_sink=candidates.extend)
    return choice, candidates


def _candidate_membership(candidates):
    return [
        (tuple(candidate["point"]), tuple(candidate["channels"]),
         candidate["kind"])
        for candidate in candidates
    ]


def test_rank_is_deterministic_balanced_and_does_not_mutate_channel_state():
    channel = ChannelState(1, mode="Q4")
    channel.update_no_signal((0.0, 0.0), 1.0)
    before = copy.deepcopy(channel.__dict__)

    first = rank_q4_candidate(channel, (950.0, 0.0))
    second = rank_q4_candidate(channel, (950.0, 0.0))

    assert first == second
    assert channel.__dict__ == before
    assert set(first) == {
        "score", "signal_count", "no_signal_count", "hypothesis_count"
    }
    assert first["hypothesis_count"] > 0
    assert first["signal_count"] + first["no_signal_count"] == \
        first["hypothesis_count"]
    p_signal = first["signal_count"] / first["hypothesis_count"]
    assert first["score"] == 4.0 * p_signal * (1.0 - p_signal)
    assert 0.0 <= first["score"] <= 1.0


def test_rank_fails_closed_for_malformed_candidate_and_empty_ensemble():
    channel = ChannelState(1, mode="Q4")
    for index, point in enumerate(q4_grid_points()):
        if math.hypot(*point) <= C.OMEGA_RADIUS + C.EPS:
            channel.update_no_signal(point, float(index))

    empty = rank_q4_candidate(channel, (0.0, 0.0))
    malformed = rank_q4_candidate(channel, (float("nan"), 0.0))

    assert empty == {
        "score": 0.0,
        "signal_count": 0,
        "no_signal_count": 0,
        "hypothesis_count": 0,
    }
    assert malformed == empty


@pytest.mark.parametrize(
    "candidate",
    [None, "12", {}, {0: 1.0, 1: 2.0}, (0.0,), (0.0, object())],
)
def test_rank_fails_closed_for_arbitrary_malformed_candidate(candidate):
    assert rank_q4_candidate(ChannelState(1, mode="Q4"), candidate) == {
        "score": 0.0,
        "signal_count": 0,
        "no_signal_count": 0,
        "hypothesis_count": 0,
    }


def test_near_or_cleared_channel_has_no_joint_ranking():
    near = ChannelState(1, mode="Q4")
    near.update_near((1.0, 2.0), 0.0)
    cleared = ChannelState(2, mode="Q4")
    cleared.update_near((1.0, 2.0), 0.0)
    cleared.mark_cleared(1.0)

    for channel in (near, cleared):
        assert rank_q4_candidate(channel, (0.0, 0.0))["score"] == 0.0
        assert rank_q4_candidate(channel, (0.0, 0.0))[
            "hypothesis_count"] == 0


@pytest.mark.parametrize(
    "result",
    ["near", "cleared", "direction", "no_signal"],
)
def test_rejected_observations_are_ignored_before_terminal_scan(result):
    baseline_channel = ChannelState(1, mode="Q4")
    rejected_channel = ChannelState(1, mode="Q4")
    rejected_channel.observations.append({
        "accepted": False,
        "position": (float("nan"), float("nan")),
        "result": result,
        "bearing": float("nan"),
    })

    assert rank_q4_candidate(rejected_channel, (620.0, 0.0)) == \
        rank_q4_candidate(baseline_channel, (620.0, 0.0))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda channel: setattr(channel, "feasible_region", [(0.0, 0.0),
                                                               (1.0, 1.0)]),
        lambda channel: setattr(
            channel, "feasible_region",
            [(0.0, 0.0), (1.0, 0.0), (float("nan"), 1.0)]),
        lambda channel: setattr(channel, "observations", None),
        lambda channel: setattr(channel, "observations", ()),
        lambda channel: channel.observations.append({
            "position": (0.0, 0.0),
        }),
        lambda channel: channel.observations.append({
            "result": "no_signal",
        }),
        lambda channel: channel.observations.append({
            "result": "no_signal", "position": (float("nan"), 0.0),
        }),
        lambda channel: channel.observations.append({
            "result": "direction", "position": (0.0, 0.0),
            "bearing": float("nan"),
        }),
    ],
)
def test_malformed_channel_state_fails_closed_without_raising(mutate):
    channel = ChannelState(1, mode="Q4")
    mutate(channel)

    assert rank_q4_candidate(channel, (620.0, 0.0)) == {
        "score": 0.0,
        "signal_count": 0,
        "no_signal_count": 0,
        "hypothesis_count": 0,
    }


def test_survivor_filter_is_cached_independently_of_candidate():
    survivor_builder = getattr(joint_state, "_survivors_cached", None)
    assert survivor_builder is not None
    survivor_builder.cache_clear()
    channel = ChannelState(1, mode="Q4")
    channel.update_no_signal((0.0, 0.0), 0.0)

    rank_q4_candidate(channel, (620.0, 0.0))
    rank_q4_candidate(channel, (-620.0, 0.0))

    info = survivor_builder.cache_info()
    assert info.misses == 1
    assert info.hits == 1


def test_directional_prediction_matches_simulator_closed_half_plane():
    source_point = (100.0, -200.0)
    radius = 1250.0
    for orientation in range(0, 360, 30):
        source = Source(1, *source_point, radius, True, orientation)
        hypothesis = (*source_point, radius, "directional",
                      float(orientation))
        for relative_angle in (-91.0, -90.0, 0.0, 90.0, 91.0):
            angle = math.radians(orientation + relative_angle)
            stop = (source_point[0] + 500.0 * math.cos(angle),
                    source_point[1] + 500.0 * math.sin(angle))
            assert joint_state._predicts_signal(hypothesis, stop) == \
                source.covers(stop)


def test_direction_filters_location_by_current_feasible_region():
    channel = ChannelState(1, mode="Q4")
    before = rank_q4_candidate(channel, (620.0, 0.0))
    channel.update_direction((-1000.0, 0.0), 0.0, 1.0)
    after = rank_q4_candidate(channel, (620.0, 0.0))

    assert 0 < after["hypothesis_count"] < before["hypothesis_count"]
    assert after["signal_count"] + after["no_signal_count"] == \
        after["hypothesis_count"]


def test_disabled_mode_preserves_exact_candidate_and_decision_behavior():
    ks = _only_unknown()
    implicit, implicit_candidates = _candidate_snapshot(
        CertificatePolicy("Q4"), ks)
    disabled, disabled_candidates = _candidate_snapshot(
        CertificatePolicy("Q4", q4_joint_rank=False), ks)

    assert disabled == implicit
    assert disabled_candidates == implicit_candidates

    implicit_scheduler = Scheduler("Q4")
    disabled_scheduler = Scheduler("Q4", q4_joint_rank=False)
    implicit_trace = []
    disabled_trace = []
    implicit_scheduler.decision_listener = implicit_trace.append
    disabled_scheduler.decision_listener = disabled_trace.append
    implicit_mission = implicit_scheduler.decide(ks, (0.0, 0.0), 1)
    disabled_mission = disabled_scheduler.decide(ks, (0.0, 0.0), 1)

    assert disabled_mission.__dict__ == implicit_mission.__dict__
    assert disabled_trace == implicit_trace


def test_enabled_mode_changes_controlled_choice_without_changing_candidates():
    ks = _only_unknown()
    channel = ks[1]
    position = (100.0, 0.0)
    # A tight no-signal ring makes the unmeasured zero-move point an
    # uninformative prediction without touching any lattice membership.
    offsets = (
        (2.0, 0.0), (-2.0, 0.0), (0.0, 2.0), (0.0, -2.0),
        (2.0, 2.0), (2.0, -2.0), (-2.0, 2.0), (-2.0, -2.0),
    )
    for index, (dx, dy) in enumerate(offsets):
        channel.update_no_signal(
            (position[0] + dx, position[1] + dy), float(index))

    plain, plain_candidates = _candidate_snapshot(
        CertificatePolicy("Q4"), ks, position)
    joint, joint_candidates = _candidate_snapshot(
        CertificatePolicy("Q4", q4_joint_rank=True), ks, position)

    assert _candidate_membership(joint_candidates) == \
        _candidate_membership(plain_candidates)
    assert joint["point"] != plain["point"]
    assert all("joint_state_score" in candidate
               and "joint_hypothesis_count" in candidate
               for candidate in joint_candidates)
    assert all("joint_state_score" not in candidate
               and "joint_hypothesis_count" not in candidate
               for candidate in plain_candidates)


def test_scheduler_trace_exposes_joint_candidate_fields():
    ks = _only_unknown()
    scheduler = Scheduler("Q4", q4_joint_rank=True)
    traces = []
    scheduler.decision_listener = traces.append

    mission = scheduler.decide(ks, (0.0, 0.0), 1)

    assert mission.kind == "scan"
    assert traces[-1]["policy_mode"] == "certificate"
    assert traces[-1]["candidates"]
    assert all("joint_state_score" in candidate
               and "joint_hypothesis_count" in candidate
               for candidate in traces[-1]["candidates"])


def test_tau_fallthrough_emits_audit_trace_for_executed_joint_scan():
    ks = KnowledgeState("Q4")
    ks[1].update_direction((-1000.0, 0.0), 0.0, 0.0)
    scheduler = Scheduler("Q4", tau=1e9, q4_joint_rank=True)
    traces = []
    scheduler.decision_listener = traces.append

    mission = scheduler.decide(ks, (0.0, 0.0), 1)

    assert mission.kind == "scan"
    assert mission.meta["tau_fallthrough"] is True
    audit = traces[-1]
    assert audit["policy_mode"] == "certificate_tau_fallthrough"
    assert audit["candidates"]
    assert audit["selected"]["point"] == list(mission.target)
    assert audit["selected"]["channels"] == mission.channels
    assert "joint_state_score" in audit["selected"]
    assert "joint_hypothesis_count" in audit["selected"]
    assert all("joint_state_score" in candidate
               and "joint_hypothesis_count" in candidate
               for candidate in audit["candidates"])


def test_q4_e2_end_to_end_completes_with_verifier_ok(tmp_path):
    simulator = SyntheticSimulator(
        "Q4", seed=17, n_sources=1, scenario="random")
    executor = ActionExecutor(SimulatorBackend(simulator))
    config = MainlineConfig(q4_joint_rank=True)
    runner = GameRunner(
        "Q4", executor, str(tmp_path), simulator=simulator, config=config)

    report = runner.run()

    assert runner.scheduler.q4_joint_rank is True
    assert runner.scheduler.certificate.q4_joint_rank is True
    assert report["complete"]
    assert report["failure"] is None
    assert report["verifier_all_ok"]
    assert all(source.cleared for source in simulator.sources)
