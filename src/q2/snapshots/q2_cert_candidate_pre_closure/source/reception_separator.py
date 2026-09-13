"""Rigorous separator for the robust reception region Crec (spec s.17, s.31).

For the frozen representative case Crec is

    Crec = { S2 : for all (rho, phi) in [5,1500] x [-eps, eps],
                  ||S2 - G(rho, phi)|| <= max(1000, rho) }

with G(rho, phi) = (rho cos phi, rho sin phi) (Omega inactive, see
polar_bb).  Equivalently the violation function

    v(rho, phi) = ||S2 - G(rho, phi)|| - max(1000, rho)

has global max <= 0 over the polar rectangle.

``separate_crec(S2)`` returns a tri-state verdict:

* PASS    - certified max <= 0, with margin enclosure (margin = -max v);
* FAIL    - with a strictly legal witness G in A1 (rho > 5 verified) whose
            certified violation is > 0 (spec: witness is a proof object);
* UNKNOWN - the max straddles zero within the working tolerances.

``max_distance_to_a1`` bounds max_G ||S2 - G|| for the all-near shortcut
(spec section 10).
"""

from __future__ import annotations

import heapq
import itertools
import math
from dataclasses import dataclass

from src.q2.formal.ivl_geometry import (
    EPS,
    IvlPoint,
    polar_point,
    box_point_distance,
)
from src.q2.formal.polar_bb import PHI_RANGE, RHO_RANGE, _split
from src.q2.formal.rigorous_arithmetic import Ivl, Tri

_counter = itertools.count()


@dataclass
class SeparationResult:
    status: str               # "PASS" | "FAIL" | "UNKNOWN"
    margin: Ivl | None        # enclosure of min reception slack when finite
    margin_lower: float | None = None   # certified lower bound of the margin
    witness: tuple[float, float] | None = None  # Cartesian G in A1 (FAIL)
    witness_violation: Ivl | None = None
    pieces_evaluated: int = 0
    detail: str = ""


def _violation_enclosure(rho: Ivl, phi: Ivl, s2: IvlPoint) -> Ivl:
    g = polar_point(rho, phi)
    d_lo, d_hi = box_point_distance(s2, g)
    rmax = Ivl.max(Ivl.from_int(1000), rho)
    # enclosure of d - rmax over the box
    return Ivl.from_bounds((d_lo.lower_arb() - rmax.upper_arb()).lower(),
                           (d_hi.upper_arb() - rmax.lower_arb()).upper())


def _violation_float(rho: float, phi: float, s2x: float, s2y: float) -> float:
    gx = rho * math.cos(phi)
    gy = rho * math.sin(phi)
    return math.hypot(s2x - gx, s2y - gy) - max(1000.0, rho)


def _violation_point(rho: float, phi: float, s2: IvlPoint) -> Ivl:
    """Rigorous violation at one exact polar point."""
    return _violation_enclosure(Ivl.from_float(rho), Ivl.from_float(phi), s2)


def separate_crec(
    s2: IvlPoint,
    max_pieces: int = 200000,
    zero_tol: float = 1e-9,
) -> SeparationResult:
    """Tri-state Crec membership with witness / certified margin."""
    s2x, s2y = s2.x.mid_float(), s2.y.mid_float()
    heap: list[tuple] = []
    enc0 = _violation_enclosure(Ivl.from_bounds(*RHO_RANGE),
                                Ivl.from_bounds(*PHI_RANGE), s2)
    heapq.heappush(heap, (-enc0.upper_float(), next(_counter),
                          Ivl.from_bounds(*RHO_RANGE),
                          Ivl.from_bounds(*PHI_RANGE)))
    pieces = 1
    wit_pt = None            # (rho, phi) of the best verified point value
    wit_lo = -math.inf       # verified lower bound of v at wit_pt
    resolved_hi = -math.inf  # max upper over all resolved (dropped) boxes

    while heap:
        neg_hi, _, rho, phi = heapq.heappop(heap)
        live_hi = -neg_hi
        if live_hi <= 0.0:
            # every live box <= 0; dropped boxes <= resolved_hi <= 0
            resolved_hi = max(resolved_hi, live_hi)
            vmax = (Ivl.from_bounds(wit_lo, resolved_hi)
                    if wit_pt is not None else None)
            return SeparationResult("PASS", vmax, -resolved_hi,
                                    None, None, pieces)
        if wit_pt is not None and live_hi - wit_lo <= zero_tol and live_hi > 0:
            # max resolved to a tight interval straddling zero
            vmax = Ivl.from_bounds(wit_lo, max(live_hi, resolved_hi))
            return SeparationResult("UNKNOWN", -vmax, -max(live_hi, resolved_hi),
                                    None, None, pieces,
                                    "max within zero tolerance")
        # float probe at midpoint (clamped: witness must lie in the domain)
        rm = min(max(rho.mid_float(), 5.0), 1500.0)
        pm = min(max(phi.mid_float(), PHI_RANGE[0]), PHI_RANGE[1])
        fv = _violation_float(rm, pm, s2x, s2y)
        if fv > 0.0:
            # legalize the witness: rho must be strictly > 5
            for dr in (0.0, 1e-9, 1e-6, 1e-3):
                rw = min(max(rm, 5.0 + dr), 1500.0)
                pw = min(max(pm, PHI_RANGE[0]), PHI_RANGE[1])
                pv = _violation_point(rw, pw, s2)
                if Ivl.gt(pv, 0) is Tri.TRUE:
                    gx = rw * math.cos(pw)
                    gy = rw * math.sin(pw)
                    return SeparationResult("FAIL", None, None,
                                            (gx, gy), pv, pieces)
        if wit_pt is None or fv > wit_lo:
            pv = _violation_point(rm, pm, s2)
            wit_pt, wit_lo = (rm, pm), pv.lower_float()
        for cr, cp in _split(rho, phi):
            enc = _violation_enclosure(cr, cp, s2)
            hi = enc.upper_float()
            if hi <= 0.0:
                resolved_hi = max(resolved_hi, hi)
                continue  # box entirely feasible -> drop
            heapq.heappush(heap, (-hi, next(_counter), cr, cp))
            pieces += 1
            if pieces >= max_pieces:
                cap_hi = max([-p[0] for p in heap] + [resolved_hi])
                lo = wit_lo if wit_pt is not None else -1e30
                vmax = Ivl.from_bounds(lo, cap_hi)
                return SeparationResult("UNKNOWN", -vmax, -cap_hi,
                                        None, None, pieces,
                                        "piece cap reached")
    # heap exhausted: every box was resolved with upper <= 0
    vmax = (Ivl.from_bounds(wit_lo, resolved_hi)
            if wit_pt is not None else None)
    return SeparationResult("PASS", vmax, -resolved_hi, None, None,
                            pieces, "exhausted")


def max_distance_to_a1(s2: IvlPoint, target_tol: float = 1e-7) -> Ivl:
    """Rigorous enclosure of max over closure(A1) of ||S2 - G||.

    Used by the all-near shortcut (spec s.10): all-near iff this is <= 5.
    """
    from src.q2.formal.polar_bb import polar_max

    def f(rho: Ivl, phi: Ivl) -> Ivl:
        g = polar_point(rho, phi)
        d_lo, d_hi = box_point_distance(s2, g)
        return Ivl.from_bounds(d_lo.lower_float(), d_hi.upper_float())

    def ff(rho: float, phi: float) -> float:
        return math.hypot(s2.x.mid_float() - rho * math.cos(phi),
                          s2.y.mid_float() - rho * math.sin(phi))

    return polar_max(f, ff, target_tol=target_tol).value
