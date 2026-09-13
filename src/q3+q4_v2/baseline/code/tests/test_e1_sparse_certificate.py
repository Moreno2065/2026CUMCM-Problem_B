# -*- coding: utf-8 -*-
"""E1: Q4 25-point sparse mesh construction and independent verification."""

import json
import math
import random

import pytest

from executor.action_executor import ActionExecutor
from experiment.config import MainlineConfig
from experiment.runner import GameRunner
from experiment.simulator import SimulatorBackend, SyntheticSimulator
from geometry import q4_sparse_mesh as sparse_mesh
from geometry.certificate import q3_backbone_points, q4_lattice_points
from geometry.constants import OMEGA_RADIUS, R_EFF_MIN
from geometry.q4_sparse_mesh import (
    q4_sparse25_points,
    q4_sparse25_triangles,
)
from state.channel_state import ChannelState, ChannelStatus
from verifier.q4_sparse_verifier import (
    MAX_SAFE_MATCH_TOL,
    _maximum_bipartite_matching,
    verify_q4_sparse25_channel,
    verify_q4_sparse25_mesh,
)


def test_sparse25_geometry_has_fixed_order_and_36_triangles():
    points = q4_sparse25_points()
    triangles = q4_sparse25_triangles()

    assert len(points) == 25
    assert points[0] == (0.0, 0.0)
    for k, point in enumerate(points[1:13]):
        angle = math.radians(15.0 + 30.0 * k)
        assert math.dist(point, (950.0 * math.cos(angle),
                                 950.0 * math.sin(angle))) < 1e-9
    for k, point in enumerate(points[13:25]):
        angle = math.radians(30.0 * k)
        assert math.dist(point, (1870.0 * math.cos(angle),
                                 1870.0 * math.sin(angle))) < 1e-9

    expected = []
    for k in range(12):
        expected.append((0, 1 + k, 1 + (k + 1) % 12))
    for k in range(12):
        expected.append((13 + k, 13 + (k + 1) % 12, 1 + k))
    for k in range(12):
        expected.append((13 + k, 1 + k, 1 + (k - 1) % 12))
    assert triangles == expected


def test_sparse25_mesh_positive_proof_and_math_margins():
    result = verify_q4_sparse25_mesh(q4_sparse25_points())

    assert result["ok"], result
    assert result["n_points"] == 25
    assert result["n_triangles"] == 36
    assert result["failures"] == []
    assert result["triangles_unique"]
    assert result["triangles_nondegenerate"]
    assert result["triangles_consistently_oriented"]
    assert math.isclose(result["triangle_area"], result["outer_area"],
                        rel_tol=0.0, abs_tol=1e-6)
    assert result["outer_inradius"] >= OMEGA_RADIUS
    assert result["max_triangle_edge"] <= R_EFF_MIN

    expected_inradius = 1870.0 * math.cos(math.pi / 12.0)
    expected_long_edge = math.sqrt(
        1870.0 ** 2 + 950.0 ** 2
        - 2.0 * 1870.0 * 950.0 * math.cos(math.pi / 12.0)
    )
    assert math.isclose(result["outer_inradius"], expected_inradius,
                        rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(result["max_triangle_edge"], expected_long_edge,
                        rel_tol=0.0, abs_tol=1e-9)
    assert OMEGA_RADIUS < result["outer_inradius"] < OMEGA_RADIUS + 7.0
    assert R_EFF_MIN - 17.0 < result["max_triangle_edge"] < R_EFF_MIN - 16.0


def test_sparse25_mesh_rejects_missing_point():
    result = verify_q4_sparse25_mesh(q4_sparse25_points()[:-1])
    assert not result["ok"]
    assert result["n_points"] == 24
    assert result["failures"]


def test_sparse25_mesh_rejects_moved_point():
    points = q4_sparse25_points()
    points[7] = (points[7][0] + 0.01, points[7][1])

    result = verify_q4_sparse25_mesh(points)
    assert not result["ok"]
    assert any("match" in failure or "radius" in failure
               for failure in result["failures"])


def test_sparse25_mesh_accepts_permutation():
    points = q4_sparse25_points()
    random.Random(2026).shuffle(points)
    result = verify_q4_sparse25_mesh(points)
    assert result["ok"], result


def test_sparse25_channel_matches_complete_set_in_any_order():
    points = q4_sparse25_points()
    random.Random(4).shuffle(points)
    result = verify_q4_sparse25_channel(points)
    assert result["ok"], result
    assert result["matched_count"] == 25
    assert result["missing_indices"] == []
    assert result["failures"] == []


def test_sparse25_channel_rejects_missing_and_duplicated_substitution():
    points = q4_sparse25_points()
    missing = verify_q4_sparse25_channel(points[:-1])
    assert not missing["ok"]
    assert missing["matched_count"] == 24
    assert missing["missing_indices"] == [24]

    substituted = points[:-1] + [points[0]]
    assert len(substituted) == 25
    result = verify_q4_sparse25_channel(substituted)
    assert not result["ok"]
    assert result["matched_count"] == 24
    assert result["missing_indices"] == [24]


def test_sparse25_channel_rejects_perturbed_witness():
    points = q4_sparse25_points()
    points[3] = (points[3][0] + 2e-6, points[3][1])
    result = verify_q4_sparse25_channel(points, match_tol=1e-6)
    assert not result["ok"]
    assert result["missing_indices"] == [3]


def test_sparse25_channel_accepts_irrelevant_extra_observations():
    points = [(123.0, -456.0)] + q4_sparse25_points()
    assert verify_q4_sparse25_channel(points)["ok"]


def test_sparse25_channel_rejects_unsafe_tolerance_and_duplicate_forgery():
    duplicated = [(0.0, 0.0)] * 25
    result = verify_q4_sparse25_channel(duplicated, match_tol=5000.0)

    assert not result["ok"]
    assert result["matched_count"] == 0
    assert result["missing_indices"] == list(range(25))
    assert any("tolerance" in failure for failure in result["failures"])
    assert MAX_SAFE_MATCH_TOL < 250.0


def test_sparse25_channel_rejects_unsafe_tolerance_and_out_of_domain_forgery():
    arbitrary = [(6000.0 + k, 6000.0) for k in range(25)]
    result = verify_q4_sparse25_channel(arbitrary, match_tol=10000.0)

    assert not result["ok"]
    assert any("tolerance" in failure for failure in result["failures"])


def test_sparse25_channel_caller_cannot_relax_tolerance_for_translated_mesh():
    translated = [(x + 200.0, y) for x, y in q4_sparse25_points()]
    result = verify_q4_sparse25_channel(translated, match_tol=200.0)

    assert not result["ok"]
    assert result["matched_count"] == 0
    assert result["missing_indices"] == list(range(25))
    assert any("tolerance" in failure for failure in result["failures"])


def test_maximum_bipartite_matching_uses_augmenting_path():
    # Greedy expected-0 -> observation-0 would strand expected-1.  A maximum
    # matching must reassign expected-0 -> observation-1.
    mapping = _maximum_bipartite_matching([[0, 1], [0]], n_right=2)
    assert mapping == {0: 1, 1: 0}


@pytest.mark.parametrize("bad_points", [
    [(float("nan"), 0.0)],
    [(float("inf"), 0.0)],
    [(0.0,)],
    [(0.0, 0.0, 0.0)],
    [{"x": 0.0, "y": 0.0}],
    [object()],
    None,
])
def test_sparse25_verifiers_fail_closed_for_malformed_points(bad_points):
    mesh = verify_q4_sparse25_mesh(bad_points)
    channel = verify_q4_sparse25_channel(bad_points)

    assert not mesh["ok"]
    assert mesh["failures"]
    assert not channel["ok"]
    assert channel["failures"]


@pytest.mark.parametrize("bad_tol", [None, "1e-6", object(), float("nan"),
                                      float("inf"), -1.0])
def test_sparse25_channel_fails_closed_for_nonnumeric_or_invalid_tolerance(
        bad_tol):
    result = verify_q4_sparse25_channel(q4_sparse25_points(),
                                        match_tol=bad_tol)
    assert not result["ok"]
    assert result["matched_count"] == 0
    assert result["missing_indices"] == list(range(25))
    assert result["failures"]


# ---------------------------------------------------------------------------
# Task 3: runtime propagation, policy selection, state transition, verification
# ---------------------------------------------------------------------------

def _runner(tmp_path, mode="Q4", config=None, seed=2026, n_sources=1):
    sim = SyntheticSimulator(mode, seed, n_sources=n_sources,
                             scenario="random")
    executor = ActionExecutor(SimulatorBackend(sim))
    runner = GameRunner(mode, executor, str(tmp_path), simulator=sim,
                        config=config)
    return sim, runner


def _last_certificate_history_entries(output_dir):
    entries = []
    for path in sorted((output_dir / "certificate_history").glob("*.jsonl")):
        lines = path.read_text(encoding="utf-8").splitlines()
        entries.append(json.loads(lines[-1]))
    return entries


def test_sparse25_config_propagates_through_runner_state_and_scheduler(
        tmp_path):
    config = MainlineConfig(q4_certificate_layout="sparse25")
    _, runner = _runner(tmp_path, config=config)

    assert runner.ks.q4_certificate_layout == "sparse25"
    assert all(ch.q4_certificate_layout == "sparse25"
               for ch in runner.ks.channels.values())
    assert runner.scheduler.certificate.q4_certificate_layout == "sparse25"
    assert runner.scheduler.certificate.lattice == q4_sparse25_points()


def test_sparse25_channel_requires_every_expected_no_signal_witness():
    channel = ChannelState(1, mode="Q4",
                           q4_certificate_layout="sparse25")
    points = q4_sparse25_points()

    for index, point in enumerate(points[:-1]):
        channel.update_no_signal(point, float(index))
        channel.refresh_certificate()

    assert channel.status == ChannelStatus.UNKNOWN
    assert channel.absent_basis is None
    assert not sparse_mesh.q4_channel_certified_sparse25(
        channel.certificate_region)

    channel.update_no_signal(points[-1], float(len(points) - 1))
    channel.refresh_certificate()
    assert channel.status == ChannelStatus.CERTIFIED_ABSENT
    assert channel.absent_basis == "sparse25"
    assert sparse_mesh.q4_channel_certified_sparse25(
        channel.certificate_region)


def test_default_q4_and_q3_certificate_basis_remain_unchanged():
    q4 = ChannelState(1, mode="Q4")
    assert q4.q4_certificate_layout == "lattice31"
    for index, point in enumerate(q4_lattice_points()):
        q4.update_no_signal(point, float(index))
    q4.refresh_certificate()
    assert q4.status == ChannelStatus.CERTIFIED_ABSENT
    assert q4.absent_basis == "lattice31"

    q3 = ChannelState(1, mode="Q3",
                      q4_certificate_layout="sparse25")
    for index, point in enumerate(q3_backbone_points()):
        q3.update_no_signal(point, float(index))
    q3.refresh_certificate()
    assert q3.status == ChannelStatus.CERTIFIED_ABSENT
    assert q3.absent_basis == "certificate"


def test_sparse25_verifier_report_fails_closed_on_missing_witness(tmp_path):
    config = MainlineConfig(q4_certificate_layout="sparse25")
    _, runner = _runner(tmp_path, config=config)
    channel = runner.ks[1]
    for index, point in enumerate(q4_sparse25_points()[:-1]):
        channel.update_no_signal(point, float(index))
    # Simulate corrupted persisted/runtime state.  Independent verification
    # must reject it even if the status claims a completed sparse certificate.
    channel.status = ChannelStatus.CERTIFIED_ABSENT
    channel.absent_basis = "sparse25"

    report = runner._verify()

    assert not report["all_ok"]
    assert report["q4_sparse_static"]["ok"]
    assert len(report["q4_sparse_channel"]) == 1
    assert not report["q4_sparse_channel"][0]["ok"]
    assert report["q4_sparse_channel"][0]["missing_indices"] == [24]


def test_sparse25_empty_source_q4_completes_with_at_most_25_witnesses(
        tmp_path):
    config = MainlineConfig(q4_certificate_layout="sparse25")
    sim, runner = _runner(tmp_path, config=config)
    sim.sources = []

    report = runner.run()
    verifier = json.loads((tmp_path / "verifier_report.json").read_text(
        encoding="utf-8"))
    certificate = json.loads((tmp_path / "certificate.json").read_text(
        encoding="utf-8"))

    assert report["complete"]
    assert report["failure"] is None
    assert report["verifier_all_ok"]
    assert verifier["q4_sparse_static"]["ok"]
    assert len(verifier["q4_sparse_channel"]) == 20
    assert all(entry["ok"] for entry in verifier["q4_sparse_channel"])
    assert all(entry["certificate_result"]["ok"]
               for entry in certificate.values())
    history = _last_certificate_history_entries(tmp_path)
    assert len(history) == 20
    assert all(entry["coverage_definition"] ==
               "sparse25_witness_completion" for entry in history)
    assert all(entry["coverage_ratio"] == 1.0 for entry in history)
    assert all(ch.status == ChannelStatus.CERTIFIED_ABSENT
               and ch.absent_basis == "sparse25"
               and len(ch.certificate_region) <= 25
               for ch in runner.ks.channels.values())


def test_sparse25_deterministic_q4_source_case_completes(tmp_path):
    config = MainlineConfig(q4_certificate_layout="sparse25")
    sim, runner = _runner(tmp_path, config=config, seed=17, n_sources=1)

    report = runner.run()

    assert report["complete"]
    assert report["failure"] is None
    assert report["verifier_all_ok"]
    assert all(source.cleared for source in sim.sources)


def test_q4_naive_certificate_history_and_result_use_q3_disk_semantics(
        tmp_path):
    config = MainlineConfig(q4_naive=True)
    sim, runner = _runner(tmp_path, config=config)
    sim.sources = []

    report = runner.run()
    verifier = json.loads((tmp_path / "verifier_report.json").read_text(
        encoding="utf-8"))
    certificate = json.loads((tmp_path / "certificate.json").read_text(
        encoding="utf-8"))
    history = _last_certificate_history_entries(tmp_path)

    assert report["complete"]
    assert report["failure"] is None
    assert report["verifier_all_ok"]
    assert len(verifier["q3_cover"]) == 20
    assert all(entry["ok"] and entry["basis"] == "naive_q3_style"
               for entry in verifier["q3_cover"])
    assert all(entry["absent_basis"] == "naive_q3_style"
               and entry["certificate_result"]["ok"]
               for entry in certificate.values())
    assert len(history) == 20
    assert all(entry["coverage_definition"] == "q3_disk_coverage_naive"
               for entry in history)
    assert all(entry["coverage_ratio"] == 1.0 for entry in history)
