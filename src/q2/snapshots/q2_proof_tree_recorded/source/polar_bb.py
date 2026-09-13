"""Generic rigorous branch-and-bound over the frozen polar A1 rectangle.

The representative-case first-observation target set closure is the polar
rectangle

    closure(A1) = { (rho cos phi, rho sin phi) : rho in [5, 1500],
                    phi in [-eps, +eps] }

(Omega = B(0, 1800) is inactive because rho <= 1500 < 1800; this is asserted
rigorously at module import.)

``polar_max`` / ``polar_min`` compute rigorous global extrema of a scalar
function f(rho, phi) -> Ivl over the rectangle by best-first box splitting.
Pruning uses a rigorously verified point value as the incumbent extreme, so
work concentrates near the attaining set.  The result is an Ivl enclosure of
the global extremum plus a float witness location.

This is a proof object: every enclosure is outward-rounded arb arithmetic.
"""

from __future__ import annotations

import heapq
import itertools
import math
from dataclasses import dataclass, field
from typing import Callable

from src.q2.formal.ivl_geometry import EPS, OMEGA_R, RHO_HI
from src.q2.formal.rigorous_arithmetic import Ivl, Tri

# Omega inactivity check (representative case): max rho = 1500 < 1800.
assert Ivl.lt(RHO_HI, OMEGA_R) is Tri.TRUE, "Omega must be inactive"

RHO_RANGE = (5.0, 1500.0)
PHI_RANGE = (-float(EPS.upper_float()), float(EPS.upper_float()))

_counter = itertools.count()


@dataclass(order=True)
class _Piece:
    sort: float
    order: int
    rho: Ivl = field(compare=False)
    phi: Ivl = field(compare=False)
    hi: float = field(compare=False)  # upper endpoint of f enclosure (float)


@dataclass
class PolarExtremum:
    value: Ivl            # enclosure of the global extremum
    arg_rho: float        # float witness location (polar)
    arg_phi: float
    pieces_evaluated: int
    converged: bool       # False if the iteration cap was hit


def _split(rho: Ivl, phi: Ivl) -> list[tuple[Ivl, Ivl]]:
    """Split the physically wider side, then clamp children to the exact
    domain [5, 1500] x [-eps, +eps] (exact arb endpoints, no float drift).
    """
    from flint import arb as _arb
    from src.q2.formal.ivl_geometry import EPS as _EPS
    dom_rho_lo, dom_rho_hi = _arb(5.0), _arb(1500.0)
    dom_phi_lo, dom_phi_hi = -_EPS._b, _EPS._b
    w_rho = rho.width().mid_float()
    mid_rho = max((rho.lower_float() + rho.upper_float()) / 2, 1e-300)
    w_phi = mid_rho * phi.width().mid_float()
    if w_rho >= w_phi:
        c1, c2 = rho.bisect()
        pairs = [(c1, phi), (c2, phi)]
    else:
        c1, c2 = phi.bisect()
        pairs = [(rho, c1), (rho, c2)]
    out = []
    for kr, kp in pairs:
        cr = kr.clamp(dom_rho_lo, dom_rho_hi)
        cp = kp.clamp(dom_phi_lo, dom_phi_hi)
        if cr is not None and cp is not None:
            out.append((cr, cp))
    return out


def polar_max(
    f: Callable[[Ivl, Ivl], Ivl],
    f_float: Callable[[float, float], float],
    target_tol: float = 1e-9,
    max_pieces: int = 400000,
    rho_range: tuple[float, float] = RHO_RANGE,
    phi_range: tuple[float, float] = PHI_RANGE,
) -> PolarExtremum:
    """Rigorous global max of f over the polar rectangle.

    The returned enclosure [lo, hi] satisfies: the true global max lies in
    [lo, hi]; lo is achieved at a rigorously evaluated point; hi is the max
    over all live boxes.  f must be a rigorous enclosure of the function
    that f_float samples (the float oracle picks the incumbent only).
    """
    rho0 = Ivl.from_bounds(*rho_range)
    phi0 = Ivl.from_bounds(*phi_range)

    def push(heap, rho, phi):
        enc = f(rho, phi)
        heapq.heappush(heap, _Piece(-enc.upper_float(), next(_counter),
                                    rho, phi, enc.upper_float()))
        return enc

    heap: list[_Piece] = []
    push(heap, rho0, phi0)
    pieces = 1

    best_lo = None        # rigorous point value (Ivl) at the best witness
    best_pt = (0.5 * sum(rho_range), 0.0)
    best_float = -math.inf
    stopping_hi: float | None = None

    # Seed the incumbent with points strictly inside each domain corner plus
    # the midpoint.  ``PHI_RANGE`` is an outward-float enclosure of the exact
    # Arb endpoints, so moving one float inward keeps every probe admissible.
    # These are only witnesses: all pruning still uses their rigorous ``f``
    # intervals and every live-box upper bound remains Arb-certified.
    rlo, rhi = rho_range
    plo, phi = phi_range
    rlo_in = math.nextafter(rlo, rhi) if rlo < rhi else rlo
    rhi_in = math.nextafter(rhi, rlo) if rlo < rhi else rhi
    plo_in = math.nextafter(plo, phi) if plo < phi else plo
    phi_in = math.nextafter(phi, plo) if plo < phi else phi
    float_probe_cache: dict[tuple[float, float], float] = {}
    seed_points = (
        best_pt,
        (rlo_in, plo_in),
        (rlo_in, phi_in),
        (rhi_in, plo_in),
        (rhi_in, phi_in),
    )
    for rm, pm in seed_points:
        fv = f_float(rm, pm)
        float_probe_cache[(rm, pm)] = fv
        if fv > best_float:
            best_float = fv
            best_lo = f(Ivl.from_float(rm), Ivl.from_float(pm))
            best_pt = (rm, pm)

    while heap:
        piece = heapq.heappop(heap)
        upper_global = -piece.sort
        if best_lo is not None and \
                upper_global - best_lo.lower_float() <= target_tol:
            # ``piece`` is no longer in ``heap``, but it still covers part of
            # the domain.  Preserve its upper endpoint in the final enclosure.
            stopping_hi = upper_global
            break
        # float probe at the box midpoint -> candidate witness
        rm, pm = piece.rho.mid_float(), piece.phi.mid_float()
        key = (rm, pm)
        if key in float_probe_cache:
            fv = float_probe_cache[key]
        else:
            fv = f_float(rm, pm)
            float_probe_cache[key] = fv
        if fv > best_float:
            best_float = fv
            pt_val = f(Ivl.from_float(rm), Ivl.from_float(pm))
            best_lo, best_pt = pt_val, (rm, pm)
        for child_rho, child_phi in _split(piece.rho, piece.phi):
            enc_lohi = f(child_rho, child_phi)
            hi = enc_lohi.upper_float()
            if best_lo is not None and hi < best_lo.lower_float():
                continue  # pruned: whole box strictly below the witness
            heapq.heappush(heap, _Piece(-hi, next(_counter),
                                        child_rho, child_phi, hi))
            pieces += 1
            if pieces >= max_pieces:
                hi_all = max([-p.sort for p in heap] + [upper_global])
                lo_all = best_lo.lower_float() if best_lo is not None else -math.inf
                return PolarExtremum(Ivl.from_bounds(lo_all, hi_all),
                                     best_pt[0], best_pt[1], pieces, False)
    if best_lo is None:
        enc = f(rho0, phi0)
        return PolarExtremum(enc, best_pt[0], best_pt[1], pieces, True)
    hi_all = max(
        [-p.sort for p in heap]
        + [best_lo.upper_float()]
        + ([] if stopping_hi is None else [stopping_hi])
    )
    return PolarExtremum(Ivl.from_bounds(best_lo.lower_float(), hi_all),
                         best_pt[0], best_pt[1], pieces, True)


def polar_min(
    f: Callable[[Ivl, Ivl], Ivl],
    f_float: Callable[[float, float], float],
    target_tol: float = 1e-9,
    max_pieces: int = 400000,
    rho_range: tuple[float, float] = RHO_RANGE,
    phi_range: tuple[float, float] = PHI_RANGE,
) -> PolarExtremum:
    """Rigorous global min of f over the polar rectangle."""
    neg = polar_max(lambda r, p: -f(r, p), lambda r, p: -f_float(r, p),
                    target_tol, max_pieces, rho_range, phi_range)
    lo, hi = (-neg.value).lower_float(), (-neg.value).upper_float()
    return PolarExtremum(Ivl.from_bounds(lo, hi), neg.arg_rho, neg.arg_phi,
                         neg.pieces_evaluated, neg.converged)
