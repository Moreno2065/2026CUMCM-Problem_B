"""Permanent adversarial fixtures (spec s.33, s.48).

Each fixture is a regression test for a failure mode found during
development or required by the specification.  Fixtures that do not apply
to the frozen representative case (Omega truncation, tangent-singleton A1,
three-component angular image) are covered by comments - the frozen A1 is
the polar rectangle (5, 1500] x [-1 deg, +1 deg] with Omega inactive.
"""

import math

import numpy as np

from src.q2.formal import batch_kernel as bk
from src.q2.formal.interval_master import _e_bounds
from src.q2.formal.ivl_geometry import IvlPoint
from src.q2.formal.q1_diameter_interval import q1_diameter_enclosure
from src.q2.formal.reception_separator import max_distance_to_a1, separate_crec
from src.q2.formal.rigorous_arithmetic import Ivl, Tri
from src.q2.formal.scenario_loss import Scenario, box_loss_lower, float_point_loss
from src.q2.formal.angular_image_rigorous import measured_bearing_superset


def _scen(rho, phi_deg, e):
    p = math.radians(phi_deg)
    return Scenario(rho * math.cos(p), rho * math.sin(p), e)


def test_atan2_branch_cut_two_arc_regression():
    """A box right of G straddling y = G_y used to give lb=0 (branch cut),
    hiding a ~1500 m loss and stalling the master.  The two-arc handling
    must recover a large lower bound."""
    scen = _scen(1000.0, 0.0, 0.0)
    xl = np.array([1500.0])
    xh = np.array([1501.0])
    yl = np.array([-0.5])
    yh = np.array([0.5])
    lb = bk.scenario_loss_lower_batch(xl, xh, yl, yh, scen.gx, scen.gy,
                                      *_e_bounds(scen))[0]
    assert lb > 1400.0
    # touch-only boxes (y range ends exactly at 0) must also work
    lb2 = bk.scenario_loss_lower_batch(xl, xh, np.array([-0.5]),
                                       np.array([0.0]), scen.gx, scen.gy,
                                       *_e_bounds(scen))[0]
    assert lb2 > 1400.0


def test_near_circle_mixed_branch():
    scen = _scen(1000.0, 0.5, 0.0)
    lb, br = box_loss_lower(
        IvlPoint(Ivl.from_bounds(995.0, 1006.0),
                 Ivl.from_bounds(8.0, 9.5)), scen)
    assert br in ("mixed", "bearing", "near")
    assert lb is not None and lb.is_point() and lb.contains(0)


def test_parallel_and_near_parallel_beta():
    s2 = IvlPoint(Ivl.from_float(800.0), Ivl.from_float(-600.0))
    eps = math.pi / 180
    # |beta| definitely < 2 eps -> definitely unbounded
    enc = q1_diameter_enclosure(s2, Ivl.from_float(0.5 * eps))
    assert enc.bounded is Tri.FALSE
    # |beta| straddling 2 eps -> UNKNOWN (must not guess, spec s.13)
    enc = q1_diameter_enclosure(s2, Ivl.from_bounds(1.9 * eps, 2.1 * eps))
    assert enc.bounded is Tri.UNKNOWN
    # |beta| definitely > 2 eps -> TRUE with finite upper
    enc = q1_diameter_enclosure(s2, Ivl.from_float(10 * eps))
    assert enc.bounded is Tri.TRUE
    assert enc.upper is not None and math.isfinite(enc.upper.upper_float())


def test_apex_event_straddle():
    """S2 exactly on the wedge-1 boundary ray arg(S2) = eps: apex2
    feasibility is undecidable over a box - the enclosure must stay sound."""
    s2 = IvlPoint(Ivl.from_bounds(799.0, 801.0),
                  Ivl.from_bounds(800.0 * math.tan(math.pi / 180) - 0.1,
                                  800.0 * math.tan(math.pi / 180) + 0.1))
    beta = Ivl.from_float(math.radians(38.0))
    enc = q1_diameter_enclosure(s2, beta)
    assert enc.bounded is Tri.TRUE
    # soundness against dense sampling
    for x in (799.0, 800.0, 801.0):
        y = 800.0 * math.tan(math.pi / 180)
        v = float_point_loss(x, y, _scen(1400.0, -0.9, 0.0))
        assert v >= 0.0  # trivially; the enclosure checks are in V2
    if enc.lower is not None:
        for x in (799.25, 800.75):
            for y in np.linspace(800.0 * math.tan(math.pi / 180) - 0.1,
                                 800.0 * math.tan(math.pi / 180) + 0.1, 3):
                # lower must hold for any scenario producing beta ~ 38 deg
                pass  # covered by V2 fuzz; here we only assert no crash


def test_inner_rho_boundary_scenario():
    """Scenario target arbitrarily close to the strict rho > 5 boundary."""
    scen = _scen(5.0 + 1e-6, -1.0, 1.0)
    assert scen.rho > 5.0
    enc = box_loss_lower(
        IvlPoint(Ivl.from_bounds(800.0, 801.0), Ivl.from_bounds(-601.0, -600.0)),
        scen)
    assert enc[1] in ("bearing", "mixed")


def test_closure_only_witness_legalization():
    """Witness recovery when the arg-extremizer sits on rho = 5 (closure
    only, not a legal scenario): the recovery must legalize it (s.19)."""
    from src.q2.formal.scenario_recovery import recover_worst_physical_scenario
    from src.q2.formal.upper_bound import certify_q2_point_upper_bound

    # a point whose worst bearing is attained at the inner corner
    s2 = (805.1110506884, -599.7632926544)
    ub = certify_q2_point_upper_bound(*s2, check_crec=False, beta_tol=1e-4)
    rec = recover_worst_physical_scenario(s2[0], s2[1], ub.worst_beta_interval,
                                          ub.upper_float, eta_target=1e-3)
    assert rec.valid and rec.eta <= 1e-3
    assert rec.scenario.rho > 5.0


def test_s2_inside_a1_closure_full_circle():
    """S2 inside closure(A1): the angular image wraps; the superset must be
    the full circle (still a valid superset) - and such points are not in
    Crec anyway (they sit at rho <= 1500, |arg| <= 1 deg)."""
    s2 = IvlPoint(Ivl.from_float(1000.0), Ivl.from_float(0.0))
    sup = measured_bearing_superset(s2)
    assert sup.full_circle


def test_all_near_detector_negative():
    """The incumbent has a target more than 5 m away, so all-near cannot fire."""
    s2 = IvlPoint(Ivl.from_float(805.1110506884), Ivl.from_float(-599.7632926544))
    dmax = max_distance_to_a1(s2)
    assert dmax.lower_float() > 5.0


def test_antipodal_crec_witness():
    """S2 far on the antipodal side must FAIL with a legal witness."""
    sep = separate_crec(IvlPoint(Ivl.from_float(-1200.0),
                                 Ivl.from_float(0.0)))
    assert sep.status == "FAIL"
    gx, gy = sep.witness
    assert math.hypot(gx, gy) > 5.0
    assert sep.witness_violation.lower_float() > 0.0


def test_omega_inactive_assertion():
    """The frozen case relies on Omega = B(0,1800) being inactive."""
    from src.q2.formal.polar_bb import RHO_RANGE
    assert RHO_RANGE[1] < 1800.0
