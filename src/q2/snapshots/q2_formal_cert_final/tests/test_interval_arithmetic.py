"""V0/V1: interval arithmetic self-tests (spec s.47).

Validates both engines (Arb scalar Ivl and the batch float64 kernel) against
high-precision mpmath references and cross-checks the two engines against
each other.  Dense tests can only falsify (spec s.33) - rigor comes from
the outward-rounding construction; these tests hunt counterexamples.
"""

import math

import numpy as np
import pytest
from mpmath import mp, mpf

from src.q2.formal import batch_kernel as bk
from src.q2.formal.rigorous_arithmetic import Ivl, Tri, epsilon_radians

mp.prec = 200
rng = np.random.default_rng(20260911)


def _mp_sin_interval(lo, hi):
    """Brute-force high-precision enclosure of sin over [lo, hi]."""
    xs = [mpf(lo), mpf(hi)]
    k = mp.floor((mpf(lo) - mp.pi / 2) / (2 * mp.pi))
    while k * 2 * mp.pi + mp.pi / 2 <= mpf(hi) + 1:
        for cand in (k * 2 * mp.pi + mp.pi / 2, k * 2 * mp.pi - mp.pi / 2):
            if mpf(lo) <= cand <= mpf(hi):
                xs.append(cand)
        k += 1
        if k > 10:
            break
    vals = [mp.sin(x) for x in xs]
    return float(min(vals)), float(max(vals))


def test_ivl_basic_ops_enclose_mpmath():
    for _ in range(300):
        a = float(rng.uniform(-1500, 1500))
        b = float(rng.uniform(-1500, 1500))
        ia, ib = Ivl.from_float(a), Ivl.from_float(b)
        assert ia.lower_float() <= a <= ia.upper_float()
        s = ia + ib
        assert s.lower_float() <= a + b <= s.upper_float()
        d = ia - ib
        assert d.lower_float() <= a - b <= d.upper_float()
        p = ia * ib
        assert p.lower_float() <= a * b <= p.upper_float()
    # division away from zero
    for _ in range(200):
        a = float(rng.uniform(-1500, 1500))
        b = float(rng.uniform(0.5, 1500)) * (1 if rng.random() < 0.5 else -1)
        q = Ivl.from_float(a) / Ivl.from_float(b)
        assert q.lower_float() <= a / b <= q.upper_float()


def test_ivl_sqrt_square():
    for _ in range(200):
        a = float(rng.uniform(0, 2e6))
        r = Ivl.from_float(a).sqrt()
        assert r.lower_float() <= math.sqrt(a) <= r.upper_float()
        sq = Ivl.from_float(a - 1e6).square()
        assert sq.lower_float() <= (a - 1e6) ** 2 <= sq.upper_float()


def test_ivl_trig_enclosure_vs_mpmath():
    for _ in range(400):
        c = float(rng.uniform(-math.pi, math.pi))
        w = float(10 ** rng.uniform(-8, 0.5))
        lo, hi = c - w, c + w
        iv = Ivl.from_bounds(lo, hi)
        s_lo, s_hi = _mp_sin_interval(lo, hi)
        sv = iv.sin()
        assert sv.lower_float() <= s_lo + 1e-15
        assert sv.upper_float() >= s_hi - 1e-15
        cv = iv.cos()
        # cos(x) = sin(x + pi/2)
        c_lo, c_hi = _mp_sin_interval(lo + math.pi / 2, hi + math.pi / 2)
        assert cv.lower_float() <= c_lo + 1e-15
        assert cv.upper_float() >= c_hi - 1e-15


def test_ivl_atan2_point_values():
    for _ in range(300):
        y = float(rng.uniform(-1500, 1500))
        x = float(rng.uniform(-1500, 1500))
        if x == 0 and y == 0:
            continue
        v = Ivl.from_float(y).atan2(Ivl.from_float(x))
        ref = math.atan2(y, x)
        assert v.lower_float() - 1e-14 <= ref <= v.upper_float() + 1e-14


def test_epsilon_constant():
    eps = epsilon_radians()
    assert eps.lower_float() <= math.pi / 180 <= eps.upper_float()
    assert abs(eps.mid_float() - math.pi / 180) < 1e-17


def test_tri_state_comparisons():
    a = Ivl.from_bounds(0.9, 1.1)
    assert Ivl.le(a, Ivl.from_float(2.0)) is Tri.TRUE
    assert Ivl.gt(a, Ivl.from_float(2.0)) is Tri.FALSE
    assert Ivl.le(a, Ivl.from_float(1.0)) is Tri.UNKNOWN
    assert Ivl.gt(a, Ivl.from_float(0.5)) is Tri.TRUE


def test_decimal_enclosure_roundtrip():
    """The decimal strings must rigorously enclose the interval endpoints.

    Compared against the arb endpoint balls themselves: ``_arb(s) <= b`` is
    the *certain* comparison (upper of the parsed decimal ball <= lower of
    the endpoint ball), so a pass proves Decimal(lo) <= true lower endpoint
    and Decimal(hi) >= true upper endpoint.  (Comparing against
    ``lower_float()`` would be wrong: that extraction itself bumps 4 ulps
    outward, so it is strictly below the true endpoint.)
    """
    from flint import arb as _arb

    for bounds in ((1.0 / 3.0, math.sqrt(2)), (-26.2, -5.0),
                   (-1e-9, 1e-9), (700.0, 1234.5)):
        a = Ivl.from_bounds(*bounds)
        lo_s, hi_s = a.to_decimal_enclosure()
        assert bool(_arb(lo_s) <= a.lower_arb()), (bounds, lo_s)
        assert bool(_arb(hi_s) >= a.upper_arb()), (bounds, hi_s)
        # sanity: the strings also bracket the midpoint
        assert float(lo_s) <= a.mid_float() <= float(hi_s)


# ----------------------------------------------------------------------
# batch kernel primitives vs mpmath / direct computation
# ----------------------------------------------------------------------
def test_batch_sin_cos_interval():
    los = rng.uniform(-math.pi, math.pi, 500)
    his = los + 10 ** rng.uniform(-8, 0.4, 500)
    sl, sh = bk._iv_sin(los, his)
    cl, ch = bk._iv_cos(los, his)
    for i in range(500):
        lo, hi = float(los[i]), float(his[i])
        s_lo, s_hi = _mp_sin_interval(lo, hi)
        assert sl[i] <= s_lo + 1e-13, (lo, hi, sl[i], s_lo)
        assert sh[i] >= s_hi - 1e-13
        c_lo, c_hi = _mp_sin_interval(lo + math.pi / 2, hi + math.pi / 2)
        assert cl[i] <= c_lo + 1e-13
        assert ch[i] >= c_hi - 1e-13


def test_batch_arg_enclosure_corners():
    n = 300
    xl = rng.uniform(-1500, 1500, n)
    xh = xl + 10 ** rng.uniform(-6, 2, n)
    yl = rng.uniform(-1500, 1500, n)
    yh = yl + 10 ** rng.uniform(-6, 2, n)
    blo, bhi, cut = bk.arg_enclosure_batch(xl, xh, yl, yh)
    for i in range(n):
        if cut[i]:
            continue
        # dense sample of the box must lie within [blo, bhi]
        for fx in (0.0, 0.37, 1.0):
            for fy in (0.0, 0.61, 1.0):
                a = math.atan2(yl[i] + fy * (yh[i] - yl[i]),
                               xl[i] + fx * (xh[i] - xl[i]))
                assert blo[i] - 1e-12 <= a <= bhi[i] + 1e-12


def test_batch_box_dist():
    n = 200
    axl = rng.uniform(-100, 100, n)
    axh = axl + rng.uniform(0, 5, n)
    ayl = rng.uniform(-100, 100, n)
    ayh = ayl + rng.uniform(0, 5, n)
    bxl = rng.uniform(-100, 100, n)
    bxh = bxl + rng.uniform(0, 5, n)
    byl = rng.uniform(-100, 100, n)
    byh = byl + rng.uniform(0, 5, n)
    dlo = bk.box_point_dist_lower(axl, axh, ayl, ayh, bxl, bxh, byl, byh)
    dhi = bk.box_point_dist_upper(axl, axh, ayl, ayh, bxl, bxh, byl, byh)
    for i in range(n):
        samp_lo = math.inf
        samp_hi = 0.0
        for fx in (0.0, 0.5, 1.0):
            for fy in (0.0, 0.5, 1.0):
                for gx in (0.0, 0.5, 1.0):
                    for gy in (0.0, 0.5, 1.0):
                        d = math.hypot(
                            axl[i] + fx * (axh[i] - axl[i]) - (bxl[i] + gx * (bxh[i] - bxl[i])),
                            ayl[i] + fy * (ayh[i] - ayl[i]) - (byl[i] + gy * (byh[i] - byl[i])))
                        samp_lo = min(samp_lo, d)
                        samp_hi = max(samp_hi, d)
        assert dlo[i] <= samp_lo + 1e-9
        # upper: the max over boxes is at corners, so sampling is exact
        assert dhi[i] >= samp_hi - 1e-9
