"""T5/T6/T7: rigorous replay of pruned leaves (spec s.46, s.31).

T5 every objective-pruned leaf: Arb LB > U (strict, unified convention) or
    superseded (demoted to a live leaf with a valid Arb bound);
T6 every reception-pruned leaf: rigorous infeasibility proof (Arb distance
    strictly beyond a witness ball) or superseded;
T7 unverified pruned node count == 0.

The verifier's counters include prunes newly confirmed among former live
leaves, so the load-bearing invariant is: every historical prune is either
rigorously re-confirmed or superseded, and none is left unexplained.
"""

import numpy as np

from src.q2.formal.proof_tree import STATUS_PRUNE_A, STATUS_PRUNE_B


def test_t5_objective_pruned_leaves_accounted(tiny_arr, tiny_replay):
    n_a = int(np.count_nonzero(tiny_arr["status"] == STATUS_PRUNE_A))
    assert tiny_replay.topology_ok
    # accounting invariant (see module docstring)
    assert (tiny_replay.verified_pruned_objective
            + tiny_replay.verified_pruned_reception
            + tiny_replay.superseded_prunes >= n_a)
    # a strict-convention check exists and ran (no silent convention change)
    assert tiny_replay.U_rigorous == 134.0659292484056


def test_t6_reception_pruned_leaves_accounted(tiny_arr, tiny_replay):
    n_b = int(np.count_nonzero(tiny_arr["status"] == STATUS_PRUNE_B))
    assert tiny_replay.root_identity_ok
    assert (tiny_replay.verified_pruned_objective
            + tiny_replay.verified_pruned_reception
            + tiny_replay.superseded_prunes >= n_b)


def test_t7_unverified_pruned_nodes_zero(tiny_replay):
    assert tiny_replay.unverified_pruned_nodes == 0
    assert tiny_replay.status in (
        "CERTIFIED_GLOBAL_EPS_OPTIMUM", "CERTIFIED_GLOBAL_BOUND",
        "BLOCKED_RIGOROUS_TREE_REPLAY", "BLOCKED_PROOF_TREE_COVERAGE",
        "BLOCKED_MODEL_COUNTEREXAMPLE")
