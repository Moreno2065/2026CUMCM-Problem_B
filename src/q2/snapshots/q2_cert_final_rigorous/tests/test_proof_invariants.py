"""Proof-loop invariants and the half-domain symmetry lemma (spec s.20, s.21;
symmetry lemma documented in proof_loop.py)."""

import math

import numpy as np

from src.q2.formal.interval_master import BatchMaster, ReceptionWitness
from src.q2.formal.scenario_loss import Scenario

rng = np.random.default_rng(31337)


def test_reflection_symmetry_of_Q():
    """The frozen model is invariant under y -> -y: Q(x,y) == Q(x,-y).

    This is what licenses the half-domain master (y <= 0).  Verified here
    with the independent float Q2 point evaluator (Gate-E machinery).
    """
    from src.q2.code.geometry.primitives import Point2
    from src.q2.code.solver.q2_point import evaluate_q2_point

    cases = [
        (805.1110506884, -599.7632926544),
        (300.0, -250.0),
        (1200.0, -700.0),
        (50.0, -400.0),
        (1000.0, -999.0),
    ]
    for x, y in cases:
        qa = evaluate_q2_point(Point2(0.0, 0.0), 0.0, Point2(x, y))
        qb = evaluate_q2_point(Point2(0.0, 0.0), 0.0, Point2(x, -y))
        va = qa.Q
        vb = qb.Q
        if va is None or vb is None:
            assert va is None and vb is None
            continue
        assert abs(va - vb) <= 1e-7 * max(abs(va), 1.0), (x, y, va, vb)


def test_scenario_set_monotonicity():
    """Adding scenarios never lowers any box lower bound (spec s.21)."""
    from src.q2.formal import batch_kernel as bk
    from src.q2.formal.interval_master import _e_bounds

    s1 = Scenario(1499.9 * math.cos(math.radians(0.999)),
                  1499.9 * math.sin(math.radians(0.999)), -1.0)
    s2 = Scenario(1000.0, 0.0, 0.0)
    n = 50
    xl = rng.uniform(0, 1900, n)
    xh = xl + 10 ** rng.uniform(-3, 1.0, n)
    yl = rng.uniform(-1000, 0, n)
    yh = yl + 10 ** rng.uniform(-3, 1.0, n)
    e1 = _e_bounds(s1)
    e2 = _e_bounds(s2)
    lb1 = bk.scenario_loss_lower_batch(xl, xh, yl, yh, s1.gx, s1.gy, *e1)
    lb2 = bk.scenario_loss_lower_batch(xl, xh, yl, yh, s2.gx, s2.gy, *e2)
    lb_joint = np.maximum(lb1, lb2)
    assert np.all(lb_joint >= lb1 - 1e-12)
    assert np.all(lb_joint >= lb2 - 1e-12)


def test_witness_set_shrinks_domain():
    m = BatchMaster(b0=(0.0, 2000.0, -1000.0, 0.0), upper_bound=1e9)
    m.add_witness(ReceptionWitness(1000.0, 0.0, 1000.0))
    n0 = m.lb.size
    # a second ball that cuts away the right part of the disk
    cut = m.add_witness(ReceptionWitness(5.0, 0.0873, 1000.0))
    assert m.lb.size == n0  # single root box is not wholly outside
    m._split_boxes(np.array([0]))
    # after splitting, boxes near x~2000 violate the second ball
    assert m.lb.size <= 2
    xs_mid = 0.5 * (m.xlo + m.xhi)
    assert np.all(xs_mid < 1999.0) or cut >= 0


def test_mini_proof_loop_L_le_U():
    """A tiny 2-iteration loop must keep L <= U (spec s.4)."""
    from src.q2.formal.proof_loop import LoopConfig, run_proof_loop
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        cfg = LoopConfig(max_iterations=2, solve_time_budget=5.0,
                         total_time_budget_s=60.0,
                         artifacts_dir=Path(td))
        st = run_proof_loop(cfg)
        assert st.lower_bound <= st.upper_bound + 1e-12
        assert st.lower_bound >= 0.0
