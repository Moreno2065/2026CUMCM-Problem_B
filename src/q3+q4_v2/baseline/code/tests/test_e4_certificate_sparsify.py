# -*- coding: utf-8 -*-
"""E4: residual closure ranking and exact certificate sparsification."""

import copy
import json
import math

import pytest

from executor.action_executor import ActionExecutor
from experiment.config import MainlineConfig
from experiment.runner import GameRunner
from experiment.simulator import SimulatorBackend, SyntheticSimulator
from geometry.certificate import (
    q4_channel_certified,
    q4_grid_points,
    q4_lattice_points,
)
from geometry.q4_sparse_mesh import q4_sparse25_points
from policy.certificate_policy import CertificatePolicy
from policy.certificate_sparsify import (
    prune_certified_centers,
    q4_residual_closure_score,
)
from policy.scheduler import Scheduler
from state.channel_state import ChannelState, ChannelStatus
from state.knowledge_state import KnowledgeState


def _only_unknown():
    ks = KnowledgeState("Q4")
    for channel_id in range(2, 21):
        ks[channel_id].status = ChannelStatus.CERTIFIED_ABSENT
    return ks


def _candidate_snapshot(policy, ks, position=(0.0, 0.0)):
    candidates = []
    choice = policy.choose(ks, position, 1, candidates.extend)
    return choice, candidates


def _membership(candidates):
    return {
        (tuple(candidate["point"]), tuple(candidate["channels"]),
         candidate["kind"])
        for candidate in candidates
    }


def _ring(cell):
    return [
        (cell[0] + 620.0 * math.cos(2.0 * math.pi * k / 6.0),
         cell[1] + 620.0 * math.sin(2.0 * math.pi * k / 6.0))
        for k in range(6)
    ]


def test_q4_grid_points_prune_while_exact_cover_remains():
    centers = q4_grid_points()

    result = prune_certified_centers(centers)

    assert result["accepted"]
    assert result["initial_certified"]
    assert result["final_certified"]
    assert result["raw_count"] == len(centers)
    assert result["retained_count"] < len(centers)
    assert q4_channel_certified(result["centers"])["certified"]


def test_prune_result_is_irreducible_and_is_unchanged_on_second_pass():
    first = prune_certified_centers(q4_grid_points())
    retained = first["centers"]

    second = prune_certified_centers(retained)

    assert second["centers"] == retained
    assert second["retained_count"] == len(retained)
    for index in range(len(retained)):
        trial = retained[:index] + retained[index + 1:]
        assert not q4_channel_certified(trial)["certified"]


@pytest.mark.parametrize("bad_centers", [
    None,
    [(float("nan"), 0.0)],
    [(float("inf"), 0.0)],
    [(0.0,)],
    [{"x": 0.0, "y": 0.0}],
    [(0.0, 0.0), (0.0, 0.0)],
])
def test_pruner_fails_closed_for_malformed_nonfinite_or_duplicate_input(
        bad_centers):
    before = copy.deepcopy(bad_centers)

    result = prune_certified_centers(bad_centers)

    assert not result["accepted"]
    assert not result["final_certified"]
    assert result["centers"] == before


def test_pruner_returns_uncertified_input_unchanged():
    centers = q4_grid_points()[:3]
    result = prune_certified_centers(centers)

    assert result["accepted"]
    assert not result["initial_certified"]
    assert not result["final_certified"]
    assert result["centers"] == centers


def test_residual_closure_scorer_is_exact_and_does_not_mutate_state():
    channel = ChannelState(1, mode="Q4")
    cell = q4_grid_points()[20]
    for index, point in enumerate(_ring(cell)[:5]):
        channel.update_no_signal(point, float(index))
    before = copy.deepcopy(channel.to_dict())

    score = q4_residual_closure_score(channel, _ring(cell)[5])

    assert score["residual_closure_gain"] >= 1
    assert score["residual_target_cell_count"] > 0
    assert channel.to_dict() == before


def test_residual_closure_scorer_is_zero_outside_unknown_q4():
    q3 = ChannelState(1, mode="Q3")
    q4_active = ChannelState(1, mode="Q4")
    q4_active.status = ChannelStatus.ACTIVE

    for channel in (q3, q4_active):
        score = q4_residual_closure_score(channel, (0.0, 0.0))
        assert score["residual_closure_gain"] == 0
        assert score["residual_target_cell_count"] == 0


def test_disabled_mode_preserves_exact_policy_and_scheduler_behavior():
    ks = _only_unknown()
    implicit, implicit_candidates = _candidate_snapshot(
        CertificatePolicy("Q4"), ks)
    disabled, disabled_candidates = _candidate_snapshot(
        CertificatePolicy("Q4", q4_residual_sparsify=False), ks)

    assert disabled == implicit
    assert disabled_candidates == implicit_candidates

    implicit_scheduler = Scheduler("Q4")
    disabled_scheduler = Scheduler("Q4", q4_residual_sparsify=False)
    implicit_trace = []
    disabled_trace = []
    implicit_scheduler.decision_listener = implicit_trace.append
    disabled_scheduler.decision_listener = disabled_trace.append
    assert disabled_scheduler.decide(ks, (0.0, 0.0), 1).__dict__ == \
        implicit_scheduler.decide(ks, (0.0, 0.0), 1).__dict__
    assert disabled_trace == implicit_trace


def test_e4_never_reduces_baseline_candidate_pool_and_exposes_ring_early():
    ks = _only_unknown()
    cell = q4_grid_points()[20]
    for index, point in enumerate(_ring(cell)[:2]):
        ks[1].update_no_signal(point, float(index))

    _, baseline = _candidate_snapshot(CertificatePolicy("Q4"), ks)
    _, enabled = _candidate_snapshot(
        CertificatePolicy("Q4", q4_residual_sparsify=True), ks)

    assert _membership(baseline) <= _membership(enabled)
    assert any(candidate["kind"] == "q4_supplementary"
               for candidate in enabled)
    assert all("residual_closure_gain" in candidate and
               "residual_target_cell_count" in candidate
               for candidate in enabled)


def test_e4_with_no_positive_closure_preserves_existing_safe_choice():
    ks = _only_unknown()
    cell = q4_grid_points()[20]
    for index, point in enumerate(_ring(cell)[:2]):
        ks[1].update_no_signal(point, float(index))

    baseline, _ = _candidate_snapshot(CertificatePolicy("Q4"), ks)
    enabled, candidates = _candidate_snapshot(
        CertificatePolicy("Q4", q4_residual_sparsify=True), ks)

    assert not any(candidate["residual_closure_gain"] > 0
                   for candidate in candidates)
    assert enabled["point"] == baseline["point"]
    assert enabled["channels"] == baseline["channels"]
    assert enabled["kind"] == baseline["kind"]


def test_e4_positive_closure_ratio_is_primary_then_existing_ordering():
    ks = _only_unknown()
    cell = q4_grid_points()[20]
    ring = _ring(cell)
    for index, point in enumerate(ring[:5]):
        ks[1].update_no_signal(point, float(index))

    choice, candidates = _candidate_snapshot(
        CertificatePolicy("Q4", q4_joint_rank=True,
                          cert_route_mode="lookahead2",
                          q4_residual_sparsify=True),
        ks, position=ring[5])

    assert choice["residual_closure_gain"] > 0
    positive = [candidate for candidate in candidates
                if candidate["residual_closure_gain"] > 0]
    best_ratio = max(candidate["residual_closure_gain"] /
                     max(candidate["cost"], 1e-9)
                     for candidate in positive)
    assert math.isclose(choice["residual_closure_gain"] /
                        max(choice["cost"], 1e-9), best_ratio)
    assert "joint_state_score" in choice
    assert choice["lookahead_depth"] in (1, 2)


def test_e2_e3_e4_scheduler_trace_contains_all_finite_fields():
    scheduler = Scheduler(
        "Q4", q4_joint_rank=True, cert_route_mode="lookahead2",
        q4_residual_sparsify=True)
    traces = []
    scheduler.decision_listener = traces.append

    mission = scheduler.decide(_only_unknown(), (0.0, 0.0), 1)

    assert mission.kind == "scan"
    selected = traces[-1]["selected"]
    for field in (
        "joint_state_score", "joint_hypothesis_count", "lookahead_depth",
        "lookahead_pair_cost", "lookahead_pair_gain",
        "residual_closure_gain", "residual_target_cell_count",
    ):
        assert field in selected
        assert math.isfinite(float(selected[field]))
    assert all(math.isfinite(float(candidate[field]))
               for candidate in traces[-1]["candidates"]
               for field in ("residual_closure_gain",
                             "residual_target_cell_count"))


def test_channel_state_tracks_raw_and_retained_center_counts():
    channel = ChannelState(1, mode="Q4")
    for center in q4_grid_points():
        channel.add_q4_certified_center(center)
    raw = channel.q4_certified_centers_raw_count
    result = prune_certified_centers(channel.certified_centers)
    channel.retain_q4_certified_centers(result["centers"])

    serialized = channel.to_dict()
    assert raw == len(q4_grid_points())
    assert serialized["q4_certified_centers_raw_count"] == raw
    assert serialized["q4_certified_centers_retained_count"] == \
        len(result["centers"])
    assert raw >= serialized["q4_certified_centers_retained_count"]
    assert q4_channel_certified(channel.certified_centers)["certified"]


@pytest.mark.parametrize(("layout", "witnesses", "expected_basis"), [
    ("lattice31", q4_lattice_points(), "lattice31"),
    ("sparse25", q4_sparse25_points(), "sparse25"),
])
def test_default_layout_certificate_keeps_historical_basis_when_exact_also_holds(
        layout, witnesses, expected_basis):
    channel = ChannelState(1, mode="Q4", q4_certificate_layout=layout)
    channel.certificate_region.extend(witnesses)
    for center in q4_grid_points():
        channel.add_q4_certified_center(center)

    channel.refresh_certificate()

    assert channel.status == ChannelStatus.CERTIFIED_ABSENT
    assert channel.absent_basis == expected_basis


def test_sparse25_incomplete_layout_still_accepts_complete_exact_cover():
    channel = ChannelState(1, mode="Q4", q4_certificate_layout="sparse25")
    channel.certificate_region.extend(q4_sparse25_points()[:-1])
    for center in q4_grid_points():
        channel.add_q4_certified_center(center)

    channel.refresh_certificate()

    assert channel.status == ChannelStatus.CERTIFIED_ABSENT
    assert channel.absent_basis == "certificate"


def test_sparse25_basis_also_serializes_and_independently_verifies_e4_cover(
        tmp_path):
    simulator = SyntheticSimulator("Q4", seed=17, n_sources=1,
                                   scenario="random")
    runner = GameRunner(
        "Q4", ActionExecutor(SimulatorBackend(simulator)), str(tmp_path),
        simulator=simulator,
        config=MainlineConfig(q4_certificate_layout="sparse25",
                              q4_residual_sparsify=True))
    channel = runner.ks[1]
    witnesses = q4_sparse25_points()
    for cell in q4_grid_points():
        witnesses.extend(_ring(cell))
    channel.certificate_region.extend(dict.fromkeys(witnesses))
    for center in q4_grid_points():
        channel.add_q4_certified_center(center)
    pruned = prune_certified_centers(channel.certified_centers)
    channel.retain_q4_certified_centers(pruned["centers"])
    channel.status = ChannelStatus.CERTIFIED_ABSENT
    channel.absent_basis = "sparse25"

    serialized = runner._serialized_certificate_result(channel)
    verifier = runner._verify()

    assert serialized["basis"] == "sparse25"
    assert serialized["ok"]
    assert serialized["retained_exact_cover"]["ok"]
    assert verifier["q4_sparse_channel"][0]["ok"]
    exact_entry = next(entry for entry in verifier["q4_channel_cover"]
                       if entry["channel"] == channel.channel_id)
    assert exact_entry["ok"]
    assert verifier["all_ok"]


def test_runner_propagates_e4_and_q4_end_to_end_verifies_retained_cover(
        tmp_path):
    simulator = SyntheticSimulator(
        "Q4", seed=17, n_sources=0, scenario="random")
    # SyntheticSimulator clamps n_sources to at least one.  Remove sources
    # explicitly so every accepted measurement is deterministically no_signal.
    simulator.sources = []
    config = MainlineConfig(q4_residual_sparsify=True)
    runner = GameRunner(
        "Q4", ActionExecutor(SimulatorBackend(simulator)), str(tmp_path),
        simulator=simulator, config=config)

    report = runner.run()
    verifier = json.loads((tmp_path / "verifier_report.json").read_text(
        encoding="utf-8"))

    assert runner.scheduler.q4_residual_sparsify is True
    assert runner.scheduler.certificate.q4_residual_sparsify is True
    assert report["complete"]
    assert report["failure"] is None
    assert report["verifier_all_ok"]
    assert verifier["all_ok"]
    exact_channels = [ch for ch in runner.ks.channels.values()
                      if ch.absent_basis == "certificate"]
    assert exact_channels
    assert any(ch.q4_certified_centers_raw_count >
               len(ch.certified_centers) for ch in exact_channels)
    assert all(q4_channel_certified(ch.certified_centers)["certified"]
               for ch in exact_channels)
    checked_channels = {entry["channel"]
                        for entry in verifier["q4_channel_cover"]
                        if entry["ok"]}
    assert {ch.channel_id for ch in exact_channels} <= checked_channels
