"""V4: end-to-end certificate replay against the real artifacts (spec s.41,
s.47).

Skipped by default (the full replay takes ~2 minutes and ~1.5 GB of master
boxes).  Run with

    RUN_FULL_REPLAY=1 python -m pytest -q src/q2/tests_formal/test_certificate_replay.py

to re-verify the shipped certificate: reload the frozen proof objects,
re-certify the incumbent UB at 256-bit Arb precision, rebuild and re-solve
the master relaxation, cross-check sampled boxes against the scalar Arb
engine, and assert the certified gap.  Also (always) checks the static
self-consistency of the certificate JSON artifact.
"""

import json
import math
import os
from pathlib import Path

import pytest

ARTIFACTS = Path("src/q2/artifacts/formal")


def _load_certificate():
    path = ARTIFACTS / "q2_global_optimality_certificate.json"
    if not path.exists():
        pytest.skip("certificate JSON not generated yet")
    return json.loads(path.read_text(encoding="utf-8"))


def test_certificate_json_self_consistency():
    """Static checks (no compute): schema, enclosures, gap arithmetic."""
    cert = _load_certificate()
    assert cert["model"] == "frozen_q2_bounded_error_minimax"
    assert cert["status"] in (
        "CERTIFIED_EXACT_ZERO_ALL_NEAR",
        "CERTIFIED_GLOBAL_EPS_OPTIMUM",
        "CERTIFIED_GLOBAL_OPTIMUM_TO_NUMERICAL_ENCLOSURE",
        "CERTIFIED_GLOBAL_BOUND",
        "GLOBAL_EPS_CERTIFICATE_CANDIDATE",
        "NUMERICALLY_STABLE_NOT_CERTIFIED",
        "INCOMPLETE_CERTIFICATE_TIMEOUT",
        "BLOCKED_PROOF_GAP",
        "BLOCKED_INTERVAL_UNSOUNDNESS",
        "BLOCKED_INNER_MAX_INCOMPLETENESS",
        "BLOCKED_WITNESS_RECOVERY",
        "BLOCKED_MODEL_COUNTEREXAMPLE",
        "BLOCKED_PROOF_TREE_COVERAGE",
        "BLOCKED_RIGOROUS_TREE_REPLAY",
    )
    if cert.get("schema_version", 1) >= 2:
        # closure schema (closure spec s.42)
        L = float(cert["rigorous_lower_bound_m"])
        U = float(cert["rigorous_upper_bound_m"])
        gap = float(cert["absolute_gap_m"])
        tau = float(cert["epsilon_optimality_tolerance_m"])
        assert cert["certificate_scope"] == "canonical_center_case"
        assert cert["incumbent_symbol"] == "S2_hat"
        assert cert["float_batch_engine_used_only_for_search"] is True
        assert cert["sampling_used_as_proof"] is False
        assert cert["unique_optimizer"] == "NOT_PROVEN"
        if cert["status"] == "CERTIFIED_GLOBAL_EPS_OPTIMUM":
            assert cert["symmetry_lemma_analytic"] is True
            assert cert["half_domain_reduction_certified"] is True
            assert cert["proof_tree_complete"] is True
            assert cert["proof_tree_coverage_verified"] is True
            assert cert["historical_prunes_replayed"] is True
            assert cert["unverified_pruned_nodes"] == 0
    else:
        L = float(cert["lower_bound_m"])
        U = float(cert["upper_bound_m"])
        gap = float(cert["absolute_gap_m"])
        tau = float(cert["absolute_tolerance_m"])
    # bounds enclosure and gap arithmetic (decimal-string round trip)
    assert 0.0 <= L <= U
    assert abs((U - L) - gap) <= 1e-9 * max(U, 1.0)
    if cert["status"] == "CERTIFIED_GLOBAL_EPS_OPTIMUM":
        assert gap <= tau
        assert cert["certified_epsilon_global_optimum"] is True
        assert cert["certificate_replayed_independently"] is True
        assert cert["point_evaluator_verified"] is True
        assert cert["master_lower_bound_verified"] is True
    # a certified claim always requires the independent replay to have run
    if cert["status"].startswith(("CERTIFIED_GLOBAL", "CERTIFIED_EXACT")):
        assert cert["certificate_replayed_independently"] is True
        assert cert["source_snapshot_id"], "snapshot id required"
        assert cert["source_sha256_manifest"], "sha256 manifest required"
    # never claim exact global optimality unless L == U in enclosure terms
    if L != U:
        assert cert["certified_global_optimum"] is False
    # incumbent consistency: its certified Q enclosure must bracket U usage
    q_lo, q_hi = (float(v) for v in cert["incumbent_Q_enclosure_m"])
    assert q_lo <= U <= q_hi + 1e-9 * max(U, 1.0)


@pytest.mark.skipif(os.environ.get("RUN_FULL_REPLAY") != "1",
                    reason="full V4 replay is expensive; set RUN_FULL_REPLAY=1")
def test_full_certificate_replay_passes():
    from src.q2.formal.replay_certificate import replay_certificate

    res = replay_certificate(ARTIFACTS, tau_abs=0.01, sample_boxes=500,
                             solve_budget_s=1800.0)
    assert res.passed, res.details
    assert res.status == "CERTIFIED_GLOBAL_EPS_OPTIMUM"
    assert res.lower_bound <= res.upper_bound
    assert res.gap <= 0.01
    # the shipped certificate must agree with the fresh replay on U (the
    # same frozen 256-bit certification) and never sit above it
    cert = _load_certificate()
    U_ship = float(cert.get("rigorous_upper_bound_m",
                            cert.get("upper_bound_m")))
    assert abs(res.upper_bound - U_ship) <= 1e-9
    assert res.lower_bound <= U_ship
    # replayed bounds must not contradict the frozen bounds (s.41 step 8)
    assert res.lower_bound <= res.upper_bound
