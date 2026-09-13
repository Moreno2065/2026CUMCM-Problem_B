"""T4: leaf-partition completeness of the recorded proof tree (spec s.46).

Every branch terminates in a classified leaf and the leaves tile the root:
verified through the replay's topology stage plus an explicit reachability
sweep (no dangling node, no unclassified leaf).
"""

import numpy as np

from src.q2.formal.proof_tree import (
    STATUS_LIVE_FINAL,
    STATUS_PRUNE_A,
    STATUS_PRUNE_B,
    STATUS_SPLIT,
)


def test_t4_leaf_partition_complete(tiny_arr):
    arr = tiny_arr
    n = int(arr["status"].size)
    status = arr["status"]
    # 1. every non-root node is reachable: parent chain terminates at root
    for i in range(1, n):
        p = int(arr["parent"][i])
        assert 0 <= p < i
    # 2. no dangling child links
    for i in range(n):
        if status[i] == STATUS_SPLIT:
            assert 0 <= arr["left"][i] < n and 0 <= arr["right"][i] < n
    # 3. classification complete: leaves are exactly
    #    LIVE_FINAL | PRUNE_A | PRUNE_B (no LIVE leftovers at save time)
    leaf = (arr["left"] == -1) & (arr["right"] == -1)
    leftover = leaf & ~np.isin(status, [STATUS_LIVE_FINAL, STATUS_PRUNE_A,
                                        STATUS_PRUNE_B])
    assert not np.any(leftover)
    # 4. measure conservation: total leaf area == root area (dyadic boxes,
    #    exact in binary64 since all endpoints are dyadic)
    area = ((arr["xhi"] - arr["xlo"]) * (arr["yhi"] - arr["ylo"]))[leaf]
    root_area = ((arr["xhi"][0] - arr["xlo"][0])
                 * (arr["yhi"][0] - arr["ylo"][0]))
    assert abs(float(area.sum()) - float(root_area)) <= 1e-9 * root_area
