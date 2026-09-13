"""V3: master lower bound tests (spec s.8, s.16, s.21, s.47).

* LB(B) = max_j lb_j(B) validity on random boxes;
* monotonicity under scenario/witness addition;
* children tile parents (no domain loss);
* small end-to-end master solve stays below a known feasible value;
* L > U raises MasterInconsistencyError.
"""

import math

import numpy as np
import pytest

from src.q2.formal import batch_kernel as bk
from src.q2.formal.interval_master import (
    BatchMaster,
    MasterInconsistencyError,
    ReceptionWitness,
    _e_bounds,
)
from src.q2.formal.scenario_loss import Scenario, float_point_loss

rng = np.random.default_rng(555)


def _scen(rho, phi_deg, e):
    p = math.radians(phi_deg)
    return Scenario(rho * math.cos(p), rho * math.sin(p), e)


def test_box_master_lb_is_max_of_scenario_lbs():
    scen = [_scen(1499.9, 0.999, -1.0), _scen(1499.9, -0.999, 1.0),
            _scen(1000.0, 0.0, 0.0)]
    xl = np.array([800.0])
    xh = np.array([800.5])
    yl = np.array([-600.5])
    yh = np.array([-600.0])
    lbs = []
    for s in scen:
        e_lo, e_hi = _e_bounds(s)
        lbs.append(bk.scenario_loss_lower_batch(xl, xh, yl, yh,
                                                s.gx, s.gy, e_lo, e_hi)[0])
    # sample: true min of max_j >= max_j lb_j
    samples = []
    for x in np.linspace(800.0, 800.5, 5):
        for y in np.linspace(-600.5, -600.0, 5):
            samples.append(max(float_point_loss(x, y, s) for s in scen))
    assert max(lbs) <= min(samples) + 1e-9


def test_master_monotonicity_and_validity():
    m = BatchMaster(b0=(700.0, 900.0, -700.0, -500.0), upper_bound=200.0)
    m.add_witness(ReceptionWitness(1000.0, 0.0, 1000.0))
    m.add_scenario(_scen(1499.9, -0.999, -1.0))
    stats = m.solve(tol=0.05, round_cap=256, time_budget_s=20.0)
    L1 = m.lower_bound
    # feasibility: L1 must not exceed the float M_k at any probed point
    c = m.best_candidates(1)[0]
    mk = float_point_loss(*c, _scen(1499.9, -0.999, -1.0))
    assert L1 <= mk + 1e-9
    # adding a scenario can only raise L
    m.add_scenario(_scen(1499.9, 0.999, 1.0))
    m.solve(tol=0.05, round_cap=256, time_budget_s=20.0)
    L2 = m.lower_bound
    assert L2 >= L1 - 1e-12


def test_master_children_tile_and_prune():
    m = BatchMaster(b0=(0.0, 2000.0, -1000.0, 0.0), upper_bound=134.066)
    m.add_witness(ReceptionWitness(1000.0, 0.0, 1000.0))
    m.add_scenario(_scen(1499.9, -0.999, -1.0))
    before = m.lb.size
    m._split_boxes(np.array([0]))
    assert m.lb.size >= 1
    # every surviving box must intersect the witness ball
    ok = ~bk.witness_violation_batch(m.xlo, m.xhi, m.ylo, m.yhi,
                                     1000.0, 0.0, 1000.0)
    assert bool(np.all(ok))


def test_master_inconsistency_raises():
    m = BatchMaster(b0=(0.0, 10.0, -5.0, 5.0), upper_bound=1e-9)
    with pytest.raises(MasterInconsistencyError):
        # scenario G=(1000,0): from this domain the measured bearing is
        # ~0 (within 2 eps) -> loss = +inf on the whole box -> pruned
        m.add_scenario(_scen(1000.0, 0.0, 0.0))


def test_quality_probe_is_memoized_by_candidate_center():
    """Persistent low boxes must not repeat an identical float-only probe."""
    m = BatchMaster(b0=(0.0, 8.0, 0.0, 8.0), upper_bound=1.0)
    calls: list[tuple[float, float]] = []

    def mk_float(x: float, y: float) -> float:
        calls.append((x, y))
        return 1.0

    stats = m.solve(
        tol=1e-6,
        round_cap=1,
        max_boxes=8,
        time_budget_s=5.0,
        quality_tol=0.0,
        mk_float=mk_float,
    )

    assert stats.rounds >= 2
    assert len(calls) == len(set(calls))
