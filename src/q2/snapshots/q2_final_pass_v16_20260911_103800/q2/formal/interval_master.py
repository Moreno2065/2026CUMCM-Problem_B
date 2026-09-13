"""Rigorous master lower bound for the proof loop (spec sections 8, 14-16).

Solves the finite relaxation

    L_k = inf_{S2 in D_k}  M_k(S2),   M_k(S2) = max_{s in S_k} loss(S2; s)

with D_k = B0 intersected with the witness reception balls.  Every returned
lower bound is certified: for each box B and each scenario s,
``box_loss_lower`` gives loss >= lb_j(B) on B, hence M_k >= max_j lb_j(B)
on B (spec s.16); boxes are pruned only when this lower bound exceeds the
global upper bound U or when the box provably violates a witness ball
(outside D_k).  Therefore the minimum lower bound over all live boxes is a
rigorous lower bound for inf_{D_k} M_k <= Q*.

The master candidate X_k is the box center minimizing the *float* scenario
maximum (heuristic choice only; the certified number is L_k).
"""

from __future__ import annotations

import heapq
import itertools
import math
import time
from dataclasses import dataclass, field

from src.q2.formal.rigorous_arithmetic import Ivl, Tri
from src.q2.formal.ivl_geometry import IvlPoint, box_point_distance
from src.q2.formal.scenario_loss import Scenario, box_loss_lower, float_point_loss

_counter = itertools.count()


@dataclass(frozen=True)
class ReceptionWitness:
    """A ball constraint ||S2 - G|| <= R that Crec points must satisfy."""

    gx: float
    gy: float
    radius: float

    def ball_point(self) -> IvlPoint:
        return IvlPoint.from_floats(self.gx, self.gy)


@dataclass
class MasterResult:
    lower_bound: float            # certified L_k (float, outward-rounded down)
    lower_bound_ivl: Ivl          # rigorous interval of the master infimum
    candidate: tuple[float, float] | None
    candidate_mk: float           # float M_k at the candidate
    boxes_evaluated: int
    live_boxes: int
    converged: bool
    wall_time_s: float
    per_scenario_lb_calls: int


@dataclass(order=True)
class _Box:
    sort: float
    order: int
    x: Ivl = field(compare=False)
    y: Ivl = field(compare=False)
    lb: float = field(compare=False)


def _box_violates_witness(x: Ivl, y: Ivl, w: ReceptionWitness) -> Tri:
    """TRUE if the whole box is strictly outside the witness ball."""
    box = IvlPoint(x, y)
    d_lo, _ = box_point_distance(box, w.ball_point())
    return Ivl.gt(d_lo, Ivl.from_float(w.radius))


def box_master_lower(
    x: Ivl, y: Ivl, scenarios: list[Scenario], cut_above: float
) -> tuple[float | None, str]:
    """LB(B) = max_j lb_j(B) (spec s.16).  Returns (lb, branch_summary);
    lb is None (+inf, box prunable) if some scenario is unbounded here.
    Early-exits once the running max exceeds ``cut_above``.
    """
    best = 0.0
    branches: set[str] = set()
    s2box = IvlPoint(x, y)
    for scen in scenarios:
        lb, branch = box_loss_lower(s2box, scen)
        branches.add(branch)
        if lb is None:
            return None, "unbounded"
        v = lb.lower_float()
        if v > best:
            best = v
            if best > cut_above:
                return best, "+".join(sorted(branches))
    return best, "+".join(sorted(branches))


def solve_master(
    scenarios: list[Scenario],
    witnesses: list[ReceptionWitness],
    b0: tuple[float, float, float, float],
    upper_bound: float,
    target_tol: float,
    max_boxes: int = 300000,
    time_budget_s: float = 600.0,
    init_box: tuple[float, float, float, float] | None = None,
) -> MasterResult:
    """Best-first interval branch-and-bound for the finite master."""
    t0 = time.time()
    x0 = Ivl.from_bounds(b0[0], b0[1])
    y0 = Ivl.from_bounds(b0[2], b0[3])

    heap: list[_Box] = []

    def push(x: Ivl, y: Ivl) -> int:
        # domain check: witness balls
        for w in witnesses:
            if _box_violates_witness(x, y, w) is Tri.TRUE:
                return 0
        lb, _branch = box_master_lower(x, y, scenarios, upper_bound)
        if lb is None or lb > upper_bound:
            return 0
        heapq.heappush(heap, _Box(lb, next(_counter), x, y, lb))
        return 1

    boxes_evaluated = push(x0, y0)
    lb_calls = len(scenarios)

    best_cand: tuple[float, float] | None = None
    best_cand_mk = math.inf

    converged = False
    lower_global = 0.0 if not heap else heap[0].lb
    # L = 0 is always valid (losses are nonnegative)
    while heap:
        box = heapq.heappop(heap)
        lower_global = box.lb
        if upper_bound - lower_global <= target_tol:
            converged = True
            break
        if boxes_evaluated >= max_boxes or time.time() - t0 > time_budget_s:
            # put the box back: L must reflect it
            heapq.heappush(heap, box)
            break
        # candidate probe (float) at the center
        cx, cy = box.x.mid_float(), box.y.mid_float()
        mk = 0.0
        for scen in scenarios:
            v = float_point_loss(cx, cy, scen)
            if v > mk:
                mk = v
        if mk < best_cand_mk:
            # keep only if inside all witness balls (float check)
            ok = True
            for w in witnesses:
                if math.hypot(cx - w.gx, cy - w.gy) > w.radius:
                    ok = False
                    break
            if ok:
                best_cand_mk = mk
                best_cand = (cx, cy)
        # split wider side
        wx = box.x.width().mid_float()
        wy = box.y.width().mid_float()
        if wx >= wy:
            c1, c2 = box.x.bisect()
            kids = [(c1, box.y), (c2, box.y)]
        else:
            c1, c2 = box.y.bisect()
            kids = [(box.x, c1), (box.x, c2)]
        for kx, ky in kids:
            boxes_evaluated += push(kx, ky)
        lb_calls += 2 * len(scenarios)

    live = len(heap)
    if heap:
        lower_global = heap[0].lb
    lower_ivl = Ivl.from_bounds(lower_global, max(lower_global, min(
        best_cand_mk, upper_bound)))
    return MasterResult(
        lower_bound=lower_global,
        lower_bound_ivl=lower_ivl,
        candidate=best_cand,
        candidate_mk=best_cand_mk,
        boxes_evaluated=boxes_evaluated,
        live_boxes=live,
        converged=converged,
        wall_time_s=time.time() - t0,
        per_scenario_lb_calls=lb_calls,
    )
