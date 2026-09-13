"""Reception separator and objective-cut recovery tests (spec s.17, s.18,
s.31, s.32)."""

import math

import numpy as np

from src.q2.formal.ivl_geometry import IvlPoint
from src.q2.formal.rigorous_arithmetic import Ivl
from src.q2.formal.reception_separator import separate_crec
from src.q2.formal.scenario_loss import float_point_loss
from src.q2.formal.scenario_recovery import (
    recover_unbounded_scenario,
    recover_worst_physical_scenario,
)
from src.q2.formal.upper_bound import certify_q2_point_upper_bound

rng = np.random.default_rng(9902)


def _float_in_crec(x, y):
    from src.q2.code.geometry.a1 import FirstObservation, build_a1
    from src.q2.code.geometry.crec import build_crec, is_in_crec
    from src.q2.code.geometry.primitives import Point2
    crec = build_crec(build_a1(FirstObservation(Point2(0.0, 0.0), 0.0, 1.0)))
    return is_in_crec(crec, Point2(x, y)).in_crec


def test_separator_fuzz_matches_float():
    checked = 0
    for _ in range(120):
        # concentrate near the Crec boundary ring but sample widely
        if rng.random() < 0.5:
            ang = float(rng.uniform(-math.pi, 0))
            r = float(rng.uniform(500, 1600))
            x, y = 1000 + r * math.cos(ang), r * math.sin(ang)
        else:
            x = float(rng.uniform(-100, 2100))
            y = float(rng.uniform(-1100, 1100))
        sep = separate_crec(IvlPoint(Ivl.from_float(x), Ivl.from_float(y)))
        fo = _float_in_crec(x, y)
        if sep.status == "PASS":
            assert fo, (x, y, sep.detail)
            checked += 1
        elif sep.status == "FAIL":
            assert not fo or abs(_float_margin(x, y)) < 1e-6, (x, y)
            # witness must be strictly legal and strictly violated
            gx, gy = sep.witness
            rho = math.hypot(gx, gy)
            phi = math.degrees(math.atan2(gy, gx))
            assert 5.0 < rho <= 1500.0 + 1e-9
            assert abs(phi) <= 1.0 + 1e-9
            assert sep.witness_violation.lower_float() > 0.0
            checked += 1
    assert checked > 80


def _float_margin(x, y):
    from src.q2.code.geometry.a1 import FirstObservation, build_a1
    from src.q2.code.geometry.crec import build_crec, is_in_crec
    from src.q2.code.geometry.primitives import Point2
    crec = build_crec(build_a1(FirstObservation(Point2(0.0, 0.0), 0.0, 1.0)))
    return is_in_crec(crec, Point2(x, y)).margin_m


def test_recovery_at_incumbent():
    s2 = (805.1110506884, -599.7632926544)
    ub = certify_q2_point_upper_bound(*s2, beta_tol=1e-4, check_crec=False)
    assert ub.status == "CERTIFIED"
    rec = recover_worst_physical_scenario(
        s2[0], s2[1], ub.worst_beta_interval, ub.upper_float,
        eta_target=1e-4)
    assert rec.valid
    assert rec.eta <= 1e-3
    # scenario is strictly legal and its loss matches the certified Q
    s = rec.scenario
    assert 5.0 < s.rho <= 1500.0
    assert abs(s.phi_deg) <= 1.0 + 1e-9
    assert abs(s.e_deg) <= 1.0 + 1e-9
    assert rec.loss_lo <= ub.upper_float + 1e-9
    assert rec.loss_lo >= ub.q_lo.lower_float() - 1e-3
    assert float_point_loss(s2[0], s2[1], s) >= rec.loss_lo - 1e-6


def test_recovery_unbounded():
    # S2 near the origin: measured bearings near 0 -> unbounded join
    rec = recover_unbounded_scenario(10.0, 0.0)
    assert rec is not None and rec.valid
    s = rec.scenario
    assert 5.0 < s.rho <= 1500.0
    v = float_point_loss(10.0, 0.0, s)
    assert math.isinf(v)
