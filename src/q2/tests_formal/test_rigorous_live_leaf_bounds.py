"""T8/T9: rigorous live-leaf lower bounds (spec s.46).

T8 L_rigorous never exceeds any independent feasible objective value:
    a feasible objective is float M_k at a point that is itself certified
    (float, padded) inside D_k - every witness ball satisfied with margin -
    and inside the tree root.  (float M is fuzz-validated against the Q1
    adapter to 1e-6 relative, hence the 1e-3 comparison slack.)
T9 L_rigorous <= U_rigorous.
"""

import math

import numpy as np

from src.q2.formal.master_problem import load_records
from src.q2.formal.scenario_loss import float_point_loss

from pathlib import Path

ARTIFACTS = Path("src/q2/artifacts/formal")


def _feasible_in_domain(x, y, wit_recs, root, margin=1e-4):
    if not (root[0] <= x <= root[1] and root[2] <= y <= root[3]):
        return False
    for w in wit_recs:
        d = math.hypot(x - w.gx, y - w.gy)
        if d > w.radius - margin:
            return False
    return True


def test_t9_lower_not_above_upper(tiny_replay):
    assert tiny_replay.L_rigorous <= tiny_replay.U_rigorous + 1e-12
    assert tiny_replay.L_rigorous >= 0.0


def test_t8_lb_below_all_feasible_objectives(tiny_arr, tiny_tree,
                                             tiny_replay):
    scen_recs, wit_recs = load_records(ARTIFACTS / "master_cuts.json")
    scen = [s.to_scenario() for s in scen_recs]
    npz = np.load(tiny_tree / "proof_tree.npz")
    root = (float(npz["xlo"][0]), float(npz["xhi"][0]),
            float(npz["ylo"][0]), float(npz["yhi"][0]))
    npz.close()

    candidates = [(805.1110506884, -599.7632926544),  # the incumbent
                  (804.5, -599.5), (805.5, -600.2), (804.8, -600.0),
                  (805.2, -599.9), (806.0, -600.5)]
    feas = [(x, y) for x, y in candidates
            if _feasible_in_domain(x, y, wit_recs, root)]
    assert len(feas) >= 3, "need feasible sample points inside D_k"
    best = min(max(float_point_loss(x, y, s) for s in scen)
               for x, y in feas)
    assert best < float("inf")
    # falsification direction: the rigorous LB must not exceed a feasible
    # objective (1e-3 slack covers the float oracle's 1e-6-relative error)
    assert tiny_replay.L_rigorous <= best + 1e-3, (
        "rigorous LB must not exceed a feasible objective (T8)",
        tiny_replay.L_rigorous, best)
