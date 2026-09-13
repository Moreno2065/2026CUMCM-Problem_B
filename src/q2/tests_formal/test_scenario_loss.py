"""V1/V2: scenario loss enclosure tests (spec s.6, s.15, s.27, s.47).

* float oracle agrees with the existing Q1 adapter (point values);
* interval point enclosures contain the float value;
* batch box lower bounds never exceed dense sampled minima (falsification
  direction of soundness);
* branch logic: near / bearing / mixed / unbounded handled as specified.
"""

import math

import numpy as np
import pytest

from src.q2.formal import batch_kernel as bk
from src.q2.formal.interval_master import _e_bounds
from src.q2.formal.ivl_geometry import IvlPoint
from src.q2.formal.rigorous_arithmetic import Ivl, Tri
from src.q2.formal.scenario_loss import (
    Scenario,
    box_loss_lower,
    float_point_loss,
    point_loss_enclosure,
)

rng = np.random.default_rng(77001)


def _rand_scenario():
    rho = float(np.exp(rng.uniform(math.log(5.01), math.log(1499.9))))
    phi = float(rng.uniform(-0.999, 0.999))
    e = float(rng.uniform(-1.0, 1.0))
    return Scenario(rho * math.cos(math.radians(phi)),
                    rho * math.sin(math.radians(phi)), e)


def test_float_oracle_matches_q1_adapter():
    """spec s.6 equivalence at point level: loss uses the same D_Q1."""
    from src.q2.code.model.q1_adapter import evaluate_q1

    class P:
        def __init__(self, x, y):
            self.x, self.y = x, y

    for _ in range(60):
        scen = _rand_scenario()
        s2x, s2y = float(rng.uniform(0, 1800)), float(rng.uniform(-900, 0))
        v = float_point_loss(s2x, s2y, scen)
        dx, dy = scen.gx - s2x, scen.gy - s2y
        if dx * dx + dy * dy <= 25.0:
            assert v == 0.0
            continue
        beta = math.degrees(math.atan2(dy, dx)) + scen.e_deg
        ref = evaluate_q1(P(0.0, 0.0), 0.0, P(s2x, s2y), beta, 1.0)
        if math.isinf(v):
            assert ref.unbounded
        else:
            assert not ref.unbounded
            assert abs(ref.diameter - v) <= 1e-6 * max(v, 1.0)


@pytest.mark.parametrize("error_deg", [-1.0, 1.0])
def test_scenario_error_interval_encloses_exact_degree_to_radian_conversion(error_deg):
    """The certificate path converts degrees inside Arb, not through math.radians."""
    scenario = Scenario(1000.0, 0.0, error_deg)
    exact_radians = Ivl.from_float(error_deg) * Ivl.pi() / Ivl.from_int(180)

    assert scenario.e_interval().contains(exact_radians)


def test_point_enclosure_contains_float():
    for _ in range(80):
        scen = _rand_scenario()
        s2x, s2y = float(rng.uniform(0, 1800)), float(rng.uniform(-900, 0))
        fv = float_point_loss(s2x, s2y, scen)
        enc = point_loss_enclosure(
            IvlPoint(Ivl.from_float(s2x), Ivl.from_float(s2y)), scen)
        if math.isinf(fv):
            assert enc.bounded is not Tri.TRUE or enc.upper is None
            continue
        if enc.lower is not None:
            assert enc.lower.lower_float() <= fv + 1e-9
        if enc.upper is not None:
            assert enc.upper.upper_float() >= fv - 1e-9


def test_box_lower_never_exceeds_samples():
    """V2 soundness fuzz: batch and arb box LBs <= dense sampled min."""
    fails = 0
    for _ in range(150):
        scen = _rand_scenario()
        cx = float(rng.uniform(0, 1990))
        cy = float(rng.uniform(-1000, 0))
        w = float(10 ** rng.uniform(-3, 1.5))
        xl, xh, yl, yh = cx, cx + w, cy, cy + w
        e_lo, e_hi = _e_bounds(scen)
        lb_b = bk.scenario_loss_lower_batch(
            np.array([xl]), np.array([xh]), np.array([yl]), np.array([yh]),
            scen.gx, scen.gy, e_lo, e_hi)[0]
        lb_a, _br = box_loss_lower(
            IvlPoint(Ivl.from_bounds(xl, xh), Ivl.from_bounds(yl, yh)), scen)
        samp = min(
            float_point_loss(x, y, scen)
            for x in np.linspace(xl, xh, 7) for y in np.linspace(yl, yh, 7))
        if math.isinf(lb_b):
            assert math.isinf(samp), (xl, xh, yl, yh, samp)
        else:
            if lb_b > samp + 1e-9:
                fails += 1
        if lb_a is not None:
            assert lb_a.lower_float() <= samp + 1e-9
    assert fails == 0


def test_branch_logic():
    # near: S2 within 5 of G
    scen = Scenario(1000.0, 10.0, 0.0)
    lb, br = box_loss_lower(
        IvlPoint(Ivl.from_float(1000.0), Ivl.from_float(10.0)), scen)
    assert br == "near" and lb.is_point() and lb.contains(0)
    # unbounded: S2 such that bearing is ~0 (within 2 eps)
    lb, br = box_loss_lower(
        IvlPoint(Ivl.from_float(500.0), Ivl.from_float(0.0)), scen)
    assert lb is None and br == "unbounded"
    # mixed: box straddling the near circle
    lb, br = box_loss_lower(
        IvlPoint(Ivl.from_bounds(995.0, 1005.0), Ivl.from_float(10.0)), scen)
    assert br == "mixed" and lb.is_point() and lb.contains(0)


def test_superset_supremum_relation():
    """spec s.6: max over a few sampled scenarios <= certified Q upper."""
    from src.q2.formal.upper_bound import certify_q2_point_upper_bound

    s2 = (805.1110506884, -599.7632926544)
    ub = certify_q2_point_upper_bound(*s2, beta_tol=1e-4, check_crec=False)
    assert ub.status == "CERTIFIED"
    for _ in range(30):
        scen = _rand_scenario()
        fv = float_point_loss(s2[0], s2[1], scen)
        assert fv <= ub.upper_float + 1e-9

def test_eight_ulp_padding_matches_repeated_nextafter_bitwise():
    values = np.array([
        -np.inf,
        -np.finfo(float).max,
        -1.0,
        np.nextafter(0.0, -1.0),
        -0.0,
        0.0,
        np.nextafter(0.0, 1.0),
        1.0,
        np.finfo(float).max,
        np.inf,
        np.nan,
    ])
    expected_lo = values.copy()
    expected_hi = values.copy()
    with np.errstate(over="ignore"):
        for _ in range(8):
            expected_lo = np.nextafter(expected_lo, -np.inf)
            expected_hi = np.nextafter(expected_hi, np.inf)

    actual_lo = bk.pad_lo(values, 8)
    actual_hi = bk.pad_hi(values, 8)

    assert np.array_equal(
        actual_lo.view(np.uint64), expected_lo.view(np.uint64)
    )
    assert np.array_equal(
        actual_hi.view(np.uint64), expected_hi.view(np.uint64)
    )
