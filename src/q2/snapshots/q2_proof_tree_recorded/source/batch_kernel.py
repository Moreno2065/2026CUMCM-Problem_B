"""Batched float64 interval kernel for the master lower bound (spec s.23 LB-1/2).

This is the *fast* interval engine: plain float64 arrays with outward
``nextafter`` rounding on every operation.  It implements exactly the same
mathematics as the scalar Arb path (``ivl_geometry`` / ``q1_diameter_interval``
/ ``scenario_loss``) but evaluates many S2 boxes at once.

Rigor notes
-----------
* Every arithmetic op pads its result outward by 2 ulp; trig/atan2 pads by
  8 ulp (libm/np trig max error is far below that; the padding is still
  ~1e-13 relative, i.e. ~1e-10 m at our scales, versus the 5e-3 m target).
* All geometric *decisions* (feasibility, boundedness, branch cut) are made
  with the same tri-state discipline as the Arb path: anything not definite
  degrades to the safe lower bound 0 (the master then subdivides).
* V0/V1/V2 tests fuzz this engine against the Arb engine; the final replay
  re-verifies sampled boxes with Arb at 2x precision (spec s.41/42).

Only the *lower* enclosure of D_Q1 is needed by the master, so no upper
enclosure is computed here.
"""

from __future__ import annotations

import math

import numpy as np

NA = np.nextafter
INF = np.inf
_SIGN_BIT = np.uint64(0x8000000000000000)
_POS_INF_BITS = np.uint64(0x7FF0000000000000)
_NEG_INF_BITS = np.uint64(0xFFF0000000000000)

# rigorous outward float bounds of the frozen constants
_EPS_TRUE = math.pi / 180.0  # pi/180, correctly rounded
EPS_LO = float(NA(_EPS_TRUE, -INF))
EPS_HI = float(NA(_EPS_TRUE, INF))
TWO_EPS_LO = float(NA(2.0 * EPS_LO, -INF))
TWO_EPS_HI = float(NA(2.0 * EPS_HI, INF))
PI = math.pi
TWO_PI = 2.0 * math.pi


def _pad_many_lo(x: np.ndarray, n: int) -> np.ndarray:
    """Move a float64 array exactly ``n`` representable values downward."""
    original = np.asarray(x, dtype=np.float64).view(np.uint64)
    bits = original.copy()
    positive = (bits & _SIGN_BIT) == 0
    magnitude = bits & ~_SIGN_BIT
    nan = magnitude > _POS_INF_BITS
    steps = np.uint64(n)
    crosses_zero = positive & (magnitude < steps)
    bits[positive & ~crosses_zero & ~nan] -= steps
    bits[crosses_zero] = _SIGN_BIT | (steps - magnitude[crosses_zero])
    grows_negative = ~positive & ~nan
    bits[grows_negative] = np.minimum(
        bits[grows_negative] + steps, _NEG_INF_BITS
    )
    bits[nan] = original[nan]
    return bits.view(np.float64)


def _pad_many_hi(x: np.ndarray, n: int) -> np.ndarray:
    """Move a float64 array exactly ``n`` representable values upward."""
    original = np.asarray(x, dtype=np.float64).view(np.uint64)
    bits = original.copy()
    positive = (bits & _SIGN_BIT) == 0
    magnitude = bits & ~_SIGN_BIT
    nan = magnitude > _POS_INF_BITS
    steps = np.uint64(n)
    grows_positive = positive & ~nan
    bits[grows_positive] = np.minimum(
        bits[grows_positive] + steps, _POS_INF_BITS
    )
    crosses_zero = ~positive & (magnitude < steps)
    bits[~positive & ~crosses_zero & ~nan] -= steps
    bits[crosses_zero] = steps - magnitude[crosses_zero]
    bits[nan] = original[nan]
    return bits.view(np.float64)


def pad_lo(x, n=2):
    if n == 8 and isinstance(x, np.ndarray) and x.dtype == np.float64:
        return _pad_many_lo(x, n)
    for _ in range(n):
        x = NA(x, -INF)
    return x


def pad_hi(x, n=2):
    if n == 8 and isinstance(x, np.ndarray) and x.dtype == np.float64:
        return _pad_many_hi(x, n)
    for _ in range(n):
        x = NA(x, INF)
    return x


# ----------------------------------------------------------------------
# scalar interval helpers on (lo, hi) array pairs
# ----------------------------------------------------------------------
def iv_add(al, ah, bl, bh):
    return pad_lo(al + bl), pad_hi(ah + bh)


def iv_sub(al, ah, bl, bh):
    return pad_lo(al - bh), pad_hi(ah - bl)


def iv_neg(al, ah):
    return -ah, -al


def iv_mul(al, ah, bl, bh):
    p1 = al * bl
    p2 = al * bh
    p3 = ah * bl
    p4 = ah * bh
    lo = np.minimum(np.minimum(p1, p2), np.minimum(p3, p4))
    hi = np.maximum(np.maximum(p1, p2), np.maximum(p3, p4))
    return pad_lo(lo), pad_hi(hi)


def iv_div(al, ah, bl, bh):
    """Valid only where 0 not in [bl, bh] (caller guarantees via mask)."""
    q1 = al / bl
    q2 = al / bh
    q3 = ah / bl
    q4 = ah / bh
    lo = np.minimum(np.minimum(q1, q2), np.minimum(q3, q4))
    hi = np.maximum(np.maximum(q1, q2), np.maximum(q3, q4))
    return pad_lo(lo), pad_hi(hi)


def iv_square(al, ah):
    lo2 = al * al
    hi2 = ah * ah
    # case: straddles zero -> lo = 0
    strad = (al <= 0.0) & (ah >= 0.0)
    lo = np.where(al >= 0.0, lo2, np.where(ah <= 0.0, hi2, 0.0))
    hi = np.maximum(lo2, hi2)
    lo = np.where(strad, 0.0, lo)
    return pad_lo(lo), pad_hi(hi)


def iv_sqrt(al, ah):
    if np.any(al < 0.0):
        raise ValueError("sqrt of interval reaching below 0")
    return pad_lo(np.sqrt(al)), pad_hi(np.sqrt(ah))


def _iv_sin(al, ah):
    wide = (ah - al) >= TWO_PI
    sa = np.sin(al)
    sb = np.sin(ah)
    lo = np.minimum(sa, sb)
    hi = np.maximum(sa, sb)
    # max = 1 if some pi/2 + 2 k pi in [al, ah]
    k1 = np.ceil((al - math.pi / 2.0) / TWO_PI)
    k2 = np.floor((ah - math.pi / 2.0) / TWO_PI)
    has_max = k1 <= k2
    # min = -1 if some -pi/2 + 2 k pi in [al, ah]
    k3 = np.ceil((al + math.pi / 2.0) / TWO_PI)
    k4 = np.floor((ah + math.pi / 2.0) / TWO_PI)
    has_min = k3 <= k4
    hi = np.where(has_max, 1.0, hi)
    lo = np.where(has_min, -1.0, lo)
    hi = np.where(wide, 1.0, hi)
    lo = np.where(wide, -1.0, lo)
    return pad_lo(lo, 8), pad_hi(hi, 8)


def _iv_cos(al, ah):
    wide = (ah - al) >= TWO_PI
    ca = np.cos(al)
    cb = np.cos(ah)
    lo = np.minimum(ca, cb)
    hi = np.maximum(ca, cb)
    k1 = np.ceil(al / TWO_PI)
    k2 = np.floor(ah / TWO_PI)
    has_max = k1 <= k2  # 2 k pi in interval -> cos = 1
    k3 = np.ceil((al - math.pi) / TWO_PI)
    k4 = np.floor((ah - math.pi) / TWO_PI)
    has_min = k3 <= k4  # (2k+1) pi in interval -> cos = -1
    hi = np.where(has_max, 1.0, hi)
    lo = np.where(has_min, -1.0, lo)
    hi = np.where(wide, 1.0, hi)
    lo = np.where(wide, -1.0, lo)
    return pad_lo(lo, 8), pad_hi(hi, 8)


def dir_vec(al, ah):
    """(cos, sin) interval of angle interval [al, ah] -> xl, xh, yl, yh."""
    xl, xh = _iv_cos(al, ah)
    yl, yh = _iv_sin(al, ah)
    return xl, xh, yl, yh


def cross(axl, axh, ayl, ayh, bxl, bxh, byl, byh):
    p1l, p1h = iv_mul(axl, axh, byl, byh)
    p2l, p2h = iv_mul(ayl, ayh, bxl, bxh)
    return iv_sub(p1l, p1h, p2l, p2h)


def arg_enclosure_batch(rxl, rxh, ryl, ryh):
    """Enclosure of atan2(y, x) over boxes; cut=True where undecidable.

    Mirrors ``ivl_geometry.arg_enclosure``: origin inside or negative-x
    branch-cut crossing -> cut (caller degrades to safe lower bound 0).
    Otherwise the extrema over the rectangle are attained at corners
    (atan2 has no interior critical points and is edge-monotone).
    """
    x_has0 = (rxl <= 0.0) & (rxh >= 0.0)
    y_has0 = (ryl <= 0.0) & (ryh >= 0.0)
    cut = (x_has0 & y_has0) | ((rxh < 0.0) & y_has0)
    a1 = np.arctan2(ryl, rxl)
    a2 = np.arctan2(ryl, rxh)
    a3 = np.arctan2(ryh, rxl)
    a4 = np.arctan2(ryh, rxh)
    lo = np.minimum(np.minimum(a1, a2), np.minimum(a3, a4))
    hi = np.maximum(np.maximum(a1, a2), np.maximum(a3, a4))
    lo = pad_lo(lo, 8)
    hi = pad_hi(hi, 8)
    return lo, hi, cut


def box_point_dist_lower(axl, axh, ayl, ayh, bxl, bxh, byl, byh):
    """Exact lower bound of min distance between two boxes (padded)."""
    gx = np.maximum(np.maximum(axl - bxh, bxl - axh), 0.0)
    gy = np.maximum(np.maximum(ayl - byh, byl - ayh), 0.0)
    return pad_lo(np.sqrt(gx * gx + gy * gy))


def box_point_dist_upper(axl, axh, ayl, ayh, bxl, bxh, byl, byh):
    sx = np.maximum(axh - bxl, bxh - axl)
    sy = np.maximum(ayh - byl, byh - ayl)
    return pad_hi(np.sqrt(sx * sx + sy * sy))


# ----------------------------------------------------------------------
# batched Q1 diameter lower enclosure (port of q1_diameter_interval.py)
# ----------------------------------------------------------------------
def q1_diameter_lower_batch(sxl, sxh, syl, syh, bl, bh):
    """Lower bound of D_Q1(S2, beta) over (S2 box) x (beta box).

    Returns lb array; +INF where the join is definitely unbounded on the
    whole box (|beta| <= 2 eps everywhere), 0 where undecidable.
    """
    n = sxl.shape[0]
    lb = np.zeros(n)

    abs_b_min = np.where(bl > 0.0, bl, np.where(bh < 0.0, -bh, 0.0))
    abs_b_max = np.maximum(np.abs(bl), np.abs(bh))
    unbounded = abs_b_max <= TWO_EPS_LO
    bounded = abs_b_min > TWO_EPS_HI
    lb[unbounded] = INF
    work = np.nonzero(bounded)[0]
    if work.size == 0:
        return lb

    sx0, sx1 = sxl[work], sxh[work]
    sy0, sy1 = syl[work], syh[work]
    b0, b1 = bl[work], bh[work]

    # u+ = dir(+eps), u- = dir(-eps) : tight constant intervals
    ce_lo, ce_hi = _iv_cos(np.array([EPS_LO]), np.array([EPS_HI]))
    se_lo, se_hi = _iv_sin(np.array([EPS_LO]), np.array([EPS_HI]))
    uxl, uxh = ce_lo[0], ce_hi[0]
    usyl, usyh = se_lo[0], se_hi[0]

    # v+ = dir(beta + eps), v- = dir(beta - eps)
    vpxl, vpxh, vpyl, vpyh = dir_vec(b0 + EPS_LO, b1 + EPS_HI)
    vmxl, vmxh, vmyl, vmyh = dir_vec(b0 - EPS_HI, b1 - EPS_LO)

    # apex1 = (0,0) in wedge2: cross(v+, -S2) <= 0 and cross(v-, -S2) >= 0
    nxl, nxh = -sx1, -sx0
    nyl, nyh = -sy1, -sy0
    cl, ch = cross(vpxl, vpxh, vpyl, vpyh, nxl, nxh, nyl, nyh)
    ok1 = ch <= 0.0
    cl, ch = cross(vmxl, vmxh, vmyl, vmyh, nxl, nxh, nyl, nyh)
    ok1 &= cl >= 0.0

    # apex2 = S2 box in wedge1: cross(u+, S2) <= 0 and cross(u-, S2) >= 0
    cl, ch = cross(
        np.full(work.size, uxl), np.full(work.size, uxh),
        np.full(work.size, usyl), np.full(work.size, usyh),
        sx0, sx1, sy0, sy1)
    ok2 = ch <= 0.0
    cl, ch = cross(
        np.full(work.size, uxl), np.full(work.size, uxh),
        np.full(work.size, -usyh), np.full(work.size, -usyl),
        sx0, sx1, sy0, sy1)
    ok2 &= cl >= 0.0

    # collect vertex boxes: (xl, xh, yl, yh, feasible_mask)
    z = np.zeros(work.size)
    vlist: list[tuple] = []
    vlist.append((z.copy(), z.copy(), z.copy(), z.copy(), ok1))  # apex1
    vlist.append((sx0, sx1, sy0, sy1, ok2))                        # apex2

    for (jxl, jxh, jyl, jyh), (kxl, kxh, kyl, kyh), j_is_plus in (
        ((vpxl, vpxh, vpyl, vpyh), (vmxl, vmxh, vmyl, vmyh), True),
        ((vmxl, vmxh, vmyl, vmyh), (vpxl, vpxh, vpyl, vpyh), False),
    ):
        for uyl_s, uyh_s in ((usyl, usyh), (-usyh, -usyl)):
            uxb_l = np.full(work.size, uxl)
            uxb_h = np.full(work.size, uxh)
            uyb_l = np.full(work.size, uyl_s)
            uyb_h = np.full(work.size, uyh_s)
            # denom = cross(u, v)
            dl, dh = cross(uxb_l, uxb_h, uyb_l, uyb_h, jxl, jxh, jyl, jyh)
            nz = (dl > 0.0) | (dh < 0.0)
            if not np.any(nz):
                continue
            # t = cross(S2, v) / denom
            tl_num, th_num = cross(sx0, sx1, sy0, sy1, jxl, jxh, jyl, jyh)
            dl_s = np.where(nz, dl, 1.0)
            dh_s = np.where(nz, dh, 1.0)
            tl, th = iv_div(tl_num, th_num, dl_s, dh_s)
            feas = nz & (tl >= 0.0)
            # point = t * u
            pxl, pxh = iv_mul(tl, th, uxb_l, uxb_h)
            pyl, pyh = iv_mul(tl, th, uyb_l, uyb_h)
            # other half-plane: plus -> cross(v-, p - S2) >= 0; minus -> <= 0
            rxl, rxh = iv_sub(pxl, pxh, sx0, sx1)
            ryl, ryh = iv_sub(pyl, pyh, sy0, sy1)
            cl, ch = cross(kxl, kxh, kyl, kyh, rxl, rxh, ryl, ryh)
            if j_is_plus:
                feas &= cl >= 0.0
            else:
                feas &= ch <= 0.0
            vlist.append((pxl, pxh, pyl, pyh, feas))

    # pairwise lower distances among definitely feasible vertices
    m = len(vlist)
    lbw = lb[work]
    for a in range(m):
        axl, axh, ayl, ayh, fa = vlist[a]
        for b in range(a + 1, m):
            bxl, bxh, byl, byh, fb = vlist[b]
            both = fa & fb
            if not np.any(both):
                continue
            d = box_point_dist_lower(axl, axh, ayl, ayh, bxl, bxh, byl, byh)
            d = np.where(both, d, 0.0)
            lbw = np.maximum(lbw, d)
    lb[work] = lbw
    return lb


# ----------------------------------------------------------------------
# batched scenario loss lower bound (port of scenario_loss.box_loss_lower)
# ----------------------------------------------------------------------
def scenario_loss_lower_batch(sxl, sxh, syl, syh, gx, gy, e_lo, e_hi):
    """Lower bound of loss(S2; (G, e)) over boxes; +INF = unbounded everywhere."""
    # distance from box to point G
    dxl = np.maximum(np.maximum(sxl - gx, gx - sxh), 0.0)
    dyl = np.maximum(np.maximum(syl - gy, gy - syh), 0.0)
    d_lo = pad_lo(np.sqrt(dxl * dxl + dyl * dyl))
    sx = np.maximum(sxh - gx, gx - sxl)
    sy = np.maximum(syh - gy, gy - syl)
    d_hi = pad_hi(np.sqrt(sx * sx + sy * sy))

    n = sxl.shape[0]
    lb = np.zeros(n)
    near = d_hi <= 5.0
    bearing = d_lo > 5.0
    work = np.nonzero(bearing & ~near)[0]
    if work.size == 0:
        return lb

    # beta = arg(G - S2) + e over the box
    rxl, rxh = gx - sxh[work], gx - sxl[work]
    ryl, ryh = gy - syh[work], gy - syl[work]
    blo, bhi, cut = arg_enclosure_batch(rxl, rxh, ryl, ryh)
    blo = pad_lo(blo + e_lo)
    bhi = pad_hi(bhi + e_hi)

    sub_lb = q1_diameter_lower_batch(
        sxl[work], sxh[work], syl[work], syh[work], blo, bhi)

    # Branch-cut boxes (in the bearing branch the relative box cannot
    # contain the origin, so a cut means rxh < 0 with y spanning 0): the
    # true bearing range is [-pi, amax] U [amin, pi]; a valid lower bound
    # over the box is min(lb_arc1, lb_arc2) (spec s.26).
    if np.any(cut):
        cpos = np.nonzero(cut)[0]
        cw = work[cpos]
        cut_lb = np.full(cpos.size, INF)
        neg = ryl[cpos] < 0.0
        if np.any(neg):
            amax = np.arctan2(ryl[cpos][neg], rxh[cpos][neg])
            a1l = pad_lo(np.full(int(neg.sum()), -PI) + e_lo, 8)
            a1h = pad_hi(amax + e_hi, 8)
            l1 = q1_diameter_lower_batch(
                sxl[cw[neg]], sxh[cw[neg]], syl[cw[neg]], syh[cw[neg]],
                a1l, a1h)
            cut_lb[neg] = np.minimum(cut_lb[neg], l1)
        amin = np.where(ryh[cpos] > 0.0,
                        np.arctan2(np.maximum(ryh[cpos], 0.0), rxh[cpos]),
                        PI)
        a2l = pad_lo(amin + e_lo, 8)
        a2h = pad_hi(np.full(cpos.size, PI) + e_hi, 8)
        l2 = q1_diameter_lower_batch(
            sxl[cw], sxh[cw], syl[cw], syh[cw], a2l, a2h)
        cut_lb = np.minimum(cut_lb, l2)
        sub_lb[cpos] = cut_lb
    lb[work] = sub_lb
    return lb


def witness_violation_batch(sxl, sxh, syl, syh, wx, wy, radius):
    """True where the whole box is strictly outside the witness ball."""
    dxl = np.maximum(np.maximum(sxl - wx, wx - sxh), 0.0)
    dyl = np.maximum(np.maximum(syl - wy, wy - syh), 0.0)
    d_lo = pad_lo(np.sqrt(dxl * dxl + dyl * dyl))
    return d_lo > radius
