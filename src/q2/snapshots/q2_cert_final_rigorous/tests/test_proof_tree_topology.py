"""T2/T3: proof-tree topology tests on a tiny recorded tree (spec s.46).

T2 root/children exact coverage; T3 every internal node has exactly two
legal children.  The same checks run on the certificate tree inside
``replay_proof_tree`` stage 1; here they are exercised standalone with
exact (Fraction) arithmetic.
"""

import numpy as np
import pytest
from fractions import Fraction

from src.q2.formal.proof_tree import (
    STATUS_LIVE_FINAL,
    STATUS_PRUNE_A,
    STATUS_PRUNE_B,
    STATUS_SPLIT,
)
from src.q2.formal.proof_tree_replay import _exact_midpoint


def test_t2_root_matches_b0_and_children_tile(tiny_arr):
    arr = tiny_arr
    n = int(arr["status"].size)
    assert arr["xlo"][0] == 700.0 and arr["xhi"][0] == 950.0
    assert arr["ylo"][0] == -700.0 and arr["yhi"][0] == -480.0
    assert arr["parent"][0] == -1 and arr["depth"][0] == 0
    for i in np.nonzero(arr["status"] == STATUS_SPLIT)[0]:
        i = int(i)
        l, r = int(arr["left"][i]), int(arr["right"][i])
        if arr["split_axis"][i] == 0:
            m = arr["split_value"][i]
            assert arr["xhi"][l] == m == arr["xlo"][r]
            assert arr["xlo"][l] == arr["xlo"][i]
            assert arr["xhi"][r] == arr["xhi"][i]
            assert _exact_midpoint(arr["xlo"][i], arr["xhi"][i]) == \
                Fraction(*m.as_integer_ratio())
        else:
            m = arr["split_value"][i]
            assert arr["yhi"][l] == m == arr["ylo"][r]
            assert arr["ylo"][l] == arr["ylo"][i]
            assert arr["yhi"][r] == arr["yhi"][i]
            assert _exact_midpoint(arr["ylo"][i], arr["yhi"][i]) == \
                Fraction(*m.as_integer_ratio())


def test_t3_internal_nodes_have_exactly_two_children(tiny_arr):
    arr = tiny_arr
    splits = int(np.count_nonzero(arr["status"] == STATUS_SPLIT))
    assert splits >= 1, "tiny tree must contain at least one split"
    # every split has two distinct children, linked back to it
    for i in np.nonzero(arr["status"] == STATUS_SPLIT)[0]:
        i = int(i)
        l, r = int(arr["left"][i]), int(arr["right"][i])
        assert l != r and l >= 0 and r >= 0
        assert arr["parent"][l] == i and arr["parent"][r] == i
        assert arr["depth"][l] == arr["depth"][i] + 1
        assert arr["depth"][r] == arr["depth"][i] + 1
    # conservation: 1 + 2*S = total nodes
    total = int(arr["status"].size)
    assert total == 1 + 2 * splits


def test_leaves_are_classified(tiny_arr):
    arr = tiny_arr
    leaf_mask = (arr["left"] == -1) & (arr["right"] == -1)
    status = arr["status"]
    # every node is either an internal split or a classified leaf
    assert np.all(leaf_mask | (status == STATUS_SPLIT))
    assert np.all(status[leaf_mask] != STATUS_SPLIT)
    assert set(np.unique(status[leaf_mask])).issubset(
        {STATUS_LIVE_FINAL, STATUS_PRUNE_A, STATUS_PRUNE_B})
    # leaf count conservation (T4 companion)
    assert int(np.count_nonzero(leaf_mask)) == \
        int(np.count_nonzero(arr["status"] == STATUS_SPLIT)) + 1
