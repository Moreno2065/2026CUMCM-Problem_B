"""Certified point upper bound for the frozen Q2 objective (spec s.11, s.29).

``certify_q2_point_upper_bound`` proves, with outward-rounded Arb arithmetic:

1. S2 in Crec (via the rigorous separator; Crec is closed, so a certified
   PASS with margin >= 0 suffices - extended-value formulation, spec s.1);
2. the all-near shortcut (spec s.10): max_G ||S2 - G|| <= 5  =>  Q = 0;
3. otherwise Q(S2) = sup over the rigorous measured-bearing superset
   [beta_lo, beta_hi] of D_Q1(S2, beta), computed by adaptive branch and
   bound over beta subintervals with the branch-complete interval Q1 kernel.

Coverage invariant of the beta B&B: at every moment, each point of the
superset interval lies in some live subinterval, hence
Q(S2) <= max over live subinterval uppers.  The returned enclosure
[q_lo, q_hi] satisfies Q(S2) in [q_lo, q_hi]; ``upper_float`` =
q_hi rounded up is the only value a certificate may use as U
(spec s.11: never the midpoint).
"""

from __future__ import annotations

import heapq
import itertools
import math
from dataclasses import dataclass

from src.q2.formal.angular_image_rigorous import measured_bearing_superset
from src.q2.formal.ivl_geometry import IvlPoint
from src.q2.formal.q1_diameter_interval import q1_diameter_enclosure
from src.q2.formal.reception_separator import (
    max_distance_to_a1,
    separate_crec,
)
from src.q2.formal.rigorous_arithmetic import Ivl, Tri, get_precision_bits

_counter = itertools.count()


@dataclass
class UpperBoundResult:
    status: str                 # CERTIFIED | ALL_NEAR_ZERO | UNBOUNDED |
                                # NOT_FEASIBLE | UNKNOWN
    q_lo: Ivl | None
    q_hi: Ivl | None
    upper_float: float
    all_near: bool
    crec_margin_lower: float | None
    worst_beta_interval: tuple[float, float] | None
    candidate_type: str
    beta_pieces: int
    precision_bits: int
    detail: str = ""


def _beta_bnb(s2: IvlPoint, sup_lo: Ivl, sup_hi: Ivl,
              beta_tol: float, max_beta_pieces: int,
              margin_lower: float | None, prec: int) -> UpperBoundResult:
    """Maximize D_Q1(S2, beta) over beta in [sup_lo, sup_hi] (rigorous)."""
    root = Ivl.hull(sup_lo, sup_hi)
    enc0 = q1_diameter_enclosure(s2, root)
    if enc0.bounded is Tri.FALSE:
        return UpperBoundResult(
            "UNBOUNDED", None, None, math.inf, False, margin_lower, None,
            "", 1, prec, "measured superset inside |beta| <= 2 eps")
    if enc0.bounded is not Tri.TRUE:
        return UpperBoundResult(
            "UNKNOWN", None, None, math.inf, False, margin_lower, None,
            "", 1, prec, "boundedness undecided on whole superset")

    best_lower = enc0.lower if enc0.lower is not None else Ivl.from_int(0)
    best_sub = root
    best_pair = enc0.lower_pair
    # heap of (-upper, counter, sub_ivl); undecided subs get key -1e30
    heap: list[tuple] = [(-enc0.upper.upper_float(), next(_counter), root)]
    pieces = 1

    while heap:
        neg_hi, _, sub = heapq.heappop(heap)
        live_hi = -neg_hi
        if neg_hi == -_UNDECIDED_KEY:
            # boundedness undecided: must split further (spec s.13)
            if sub.width().mid_float() < 1e-13:
                return UpperBoundResult(
                    "UNKNOWN", best_lower, None, math.inf, False,
                    margin_lower, (sub.lower_float(), sub.upper_float()),
                    "", pieces, prec, "boundedness undecided at floor width")
        elif live_hi - best_lower.lower_float() <= beta_tol:
            # every other live sub has upper <= live_hi (heap order):
            # Q <= live_hi; done.
            return UpperBoundResult(
                "CERTIFIED", best_lower, Ivl.from_float(live_hi), live_hi,
                False, margin_lower,
                (best_sub.lower_float(), best_sub.upper_float()),
                best_pair, pieces, prec)
        if pieces >= max_beta_pieces:
            return UpperBoundResult(
                "UNKNOWN", best_lower, Ivl.from_float(live_hi), live_hi,
                False, margin_lower,
                (sub.lower_float(), sub.upper_float()), "", pieces, prec,
                "beta piece cap reached")
        for child in sub.bisect():
            enc_c = q1_diameter_enclosure(s2, child)
            pieces += 1
            if enc_c.bounded is Tri.FALSE:
                return UpperBoundResult(
                    "UNBOUNDED", None, None, math.inf, False, margin_lower,
                    (child.lower_float(), child.upper_float()), "", pieces,
                    prec, "subinterval definitely inside |beta| <= 2 eps")
            elif enc_c.bounded is not Tri.TRUE:
                heapq.heappush(heap, (-_UNDECIDED_KEY, next(_counter), child))
            else:
                if enc_c.lower is not None and bool(
                        enc_c.lower.lower_arb() > best_lower.lower_arb()):
                    best_lower = enc_c.lower
                    best_sub = child
                    best_pair = enc_c.lower_pair
                # midpoint point value: a rigorous lower bound of the sup
                # (spec s.11/s.19 witness for the lower edge)
                mid = Ivl.from_float(child.mid_float())
                enc_m = q1_diameter_enclosure(s2, mid)
                if enc_m.bounded is Tri.TRUE and enc_m.lower is not None and bool(
                        enc_m.lower.lower_arb() > best_lower.lower_arb()):
                    best_lower = enc_m.lower
                    best_sub = child
                    best_pair = enc_m.lower_pair + "@mid"
                pieces += 1
                heapq.heappush(heap, (-enc_c.upper.upper_float(),
                                      next(_counter), child))
    # heap exhausted without meeting tolerance (cannot happen unless all
    # subs resolved below best_lower, in which case upper = best_lower)
    return UpperBoundResult(
        "CERTIFIED", best_lower, best_lower, best_lower.upper_float(),
        False, margin_lower,
        (best_sub.lower_float(), best_sub.upper_float()),
        best_pair, pieces, prec, "heap exhausted")


_UNDECIDED_KEY = 1e30


def certify_q2_point_upper_bound(
    s2x: float,
    s2y: float,
    beta_tol: float = 1e-4,
    max_beta_pieces: int = 20000,
    check_crec: bool = True,
) -> UpperBoundResult:
    """Rigorous enclosure of Q(S2) at the exact double point (s2x, s2y)."""
    prec = get_precision_bits()
    s2 = IvlPoint(Ivl.from_float(s2x), Ivl.from_float(s2y))

    margin_lower = None
    if check_crec:
        sep = separate_crec(s2)
        if sep.status == "FAIL":
            return UpperBoundResult(
                "NOT_FEASIBLE", None, None, math.inf, False, None, None,
                "", 0, prec, f"crec witness {sep.witness}")
        if sep.status == "UNKNOWN":
            return UpperBoundResult(
                "UNKNOWN", None, None, math.inf, False, None, None,
                "", 0, prec, f"crec UNKNOWN: {sep.detail}")
        margin_lower = sep.margin_lower

    # all-near shortcut (spec s.10)
    dmax = max_distance_to_a1(s2)
    if Ivl.le(dmax, Ivl.from_int(5)) is Tri.TRUE:
        z = Ivl.from_int(0)
        return UpperBoundResult(
            "ALL_NEAR_ZERO", z, z, 0.0, True, margin_lower, None,
            "all_near", 0, prec)

    # rigorous measured-bearing superset
    sup = measured_bearing_superset(s2)
    return _beta_bnb(s2, sup.beta_lo, sup.beta_hi, beta_tol,
                     max_beta_pieces, margin_lower, prec)
