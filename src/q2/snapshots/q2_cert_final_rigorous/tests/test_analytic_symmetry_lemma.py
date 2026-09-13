"""T1: numeric regression for the analytic symmetry lemma (spec s.46).

The analytic proof lives in src/q2/Q2_CANONICAL_SYMMETRY_LEMMA.md; these
tests can only FALSIFY it (spec s.36) by checking the lemma's mapping
identities numerically with independent evaluators:

* ||RG|| = ||G||, arg(RG) = -arg(G) mod 2pi on A1 samples;
* Crec membership is mirror-invariant (float separator as oracle);
* near/bearing branch preservation and beta' = -beta (float loss oracle);
* D_Q1(S2, beta) = D_Q1(RS2, -beta) through the float Q1 evaluator;
* Q(RS2) = Q(S2) through the independent float Q2 point evaluator.
"""

import math

import numpy as np

rng = np.random.default_rng(20260912)


def _rand_a1(n):
    """Strictly legal A1 samples (rho in (5,1500], |phi| <= 1 deg)."""
    rho = np.exp(rng.uniform(math.log(5.5), math.log(1500.0), n))
    phi = np.radians(rng.uniform(-0.999, 0.999, n))
    return rho * np.cos(phi), rho * np.sin(phi)


def test_norm_and_arg_reflection_identities():
    for _ in range(300):
        gx, gy = _rand_a1(1)
        # ||RG|| = ||G||
        assert math.isclose(math.hypot(gx, -gy), math.hypot(gx, gy),
                            rel_tol=1e-15)
        # arg(RG) = -arg(G) mod 2pi
        a = math.atan2(gy, gx)
        b = math.atan2(-gy, gx)
        wrap = (a + b + math.pi) % (2 * math.pi) - math.pi
        assert abs(wrap) <= 1e-15
        # d_S(-a, 0) = d_S(a, 0)
        assert min(abs(-a), 2 * math.pi - abs(-a)) == min(abs(a),
                                                         2 * math.pi - abs(a))


def test_crec_membership_mirror_invariant():
    from src.q2.code.geometry.a1 import FirstObservation, build_a1
    from src.q2.code.geometry.crec import build_crec, is_in_crec
    from src.q2.code.geometry.primitives import Point2

    crec = build_crec(build_a1(FirstObservation(Point2(0.0, 0.0), 0.0, 1.0)))
    checked = 0
    for _ in range(80):
        x = float(rng.uniform(-200, 1900))
        y = float(rng.uniform(-1050, 1050))
        if abs(y) < 1e-9:
            continue  # mirror-fixed points carry no information
        a = is_in_crec(crec, Point2(x, y)).in_crec
        b = is_in_crec(crec, Point2(x, -y)).in_crec
        assert a == b, (x, y, a, b)
        checked += 1
    assert checked >= 60


def test_near_branch_and_measured_bearing_mirror():
    from src.q2.formal.scenario_loss import Scenario, float_point_loss

    for _ in range(120):
        gx, gy = _rand_a1(1)
        gx, gy = float(gx), float(gy)
        e = float(rng.uniform(-1.0, 1.0))
        s = Scenario(gx, gy, e)
        sm = Scenario(gx, -gy, -e)  # mirrored scenario (G, e) -> (RG, -e)
        s2x = float(rng.uniform(0, 1800))
        s2y = float(rng.uniform(-1000, 0))
        va = float_point_loss(s2x, s2y, s)
        vb = float_point_loss(s2x, -s2y, sm)
        # measured bearing reflection: beta' = -beta
        if dx_ok(gx, gy, s2x, s2y):
            ba = math.atan2(gy - s2y, gx - s2x) + math.radians(e)
            bb = math.atan2(-gy - (-s2y), gx - s2x) + math.radians(-e)
            wrap = (ba + bb + math.pi) % (2 * math.pi) - math.pi
            assert abs(wrap) <= 1e-14
        if math.isinf(va) or math.isinf(vb):
            assert math.isinf(va) and math.isinf(vb)
        else:
            assert abs(va - vb) <= 1e-6 * max(va, vb, 1.0), (va, vb)


def dx_ok(gx, gy, s2x, s2y):
    dx, dy = gx - s2x, gy - s2y
    return dx * dx + dy * dy > 25.0


def test_q1_diameter_mirror_via_float_evaluator():
    """D_Q1(S2, beta) = D_Q1(RS2, -beta) through the frozen Q1 adapter."""
    from src.q2.code.model.q1_adapter import evaluate_q1

    class P:
        def __init__(self, x, y):
            self.x, self.y = x, y

    for _ in range(60):
        s2x = float(rng.uniform(100, 1700))
        s2y = float(rng.uniform(-900, -50))
        beta = float(rng.uniform(-math.pi, math.pi))
        a = evaluate_q1(P(0.0, 0.0), 0.0, P(s2x, s2y), math.degrees(beta), 1.0)
        b = evaluate_q1(P(0.0, 0.0), 0.0, P(s2x, -s2y), -math.degrees(beta), 1.0)
        assert a.unbounded == b.unbounded
        if a.diameter is None or b.diameter is None:
            assert a.diameter is None and b.diameter is None
            continue
        if not a.unbounded:
            assert abs(a.diameter - b.diameter) <= 1e-6 * max(a.diameter, 1.0)


def test_q_objective_mirror_via_q2_point_evaluator():
    """Q(RS2) = Q(S2) through the independent float Q2 evaluator."""
    from src.q2.code.geometry.primitives import Point2
    from src.q2.code.solver.q2_point import evaluate_q2_point

    cases = [
        (805.1110506884, -599.7632926544),
        (300.0, -250.0),
        (1000.0, -400.0),
        (650.0, -750.0),
    ]
    for x, y in cases:
        qa = evaluate_q2_point(Point2(0.0, 0.0), 0.0, Point2(x, y))
        qb = evaluate_q2_point(Point2(0.0, 0.0), 0.0, Point2(x, -y))
        assert qa.in_crec == qb.in_crec, (x, y)
        assert qa.all_near == qb.all_near
        assert qa.admissible == qb.admissible
        if qa.Q is None or qb.Q is None:
            assert qa.Q is None and qb.Q is None
            continue
        assert abs(qa.Q - qb.Q) <= 1e-7 * max(abs(qa.Q), 1.0), (x, y)


def test_symmetry_lemma_artifact_matches_document():
    """The machine-readable lemma must claim exactly the proven statements."""
    import json
    from pathlib import Path

    art = json.loads(Path(
        "src/q2/artifacts/formal/canonical_symmetry_lemma.json"
    ).read_text(encoding="utf-8"))
    assert art["status"] == "PROVEN_ANALYTIC"
    assert art["scope"]["certificate_scope"] == "canonical_center_case"
    assert art["scope"]["theta1_deg"] == "0"
    claims = art["claims"]
    for key in ("A1_reflection_invariant", "Crec_reflection_invariant",
                "near_branch_invariant", "scenario_bijection",
                "Q1_polygon_isometric", "Q_objective_invariant",
                "half_domain_equivalent"):
        assert claims[key] is True, key
    assert art["proof_obligations"]["numeric_tests_are_proof"] is False
    assert art["half_domain_reduction_certified"] is True
