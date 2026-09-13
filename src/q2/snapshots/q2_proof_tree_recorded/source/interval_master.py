"""Rigorous master lower bound for the proof loop (spec sections 8, 14-16).

Solves the finite relaxation

    L_k = inf_{S2 in D_k}  M_k(S2),   M_k(S2) = max_{s in S_k} loss(S2; s)

with D_k = B0 intersected with the witness reception balls, using a batched
float64-interval branch-and-bound (``batch_kernel``) with outward nextafter
rounding.  Validity:

* for every box B and scenario s, ``scenario_loss_lower_batch`` returns
  lb_j(B) with loss(S2; s) >= lb_j(B) for all S2 in B (spec s.15);
* hence M_k >= max_j lb_j(B) on B (spec s.16) - the stored per-box lb is
  exactly this running max;
* boxes are pruned only when lb(B) > U (M_k cannot attain its infimum there
  since M_k <= Q* <= U on Crec ⊆ D_k) or when the box provably violates a
  witness ball (outside D_k);
* children tile their parent (midpoint split), so the live set always covers
  D_k minus pruned regions and min over live lb is a rigorous lower bound
  for inf_{D_k} M_k <= Q*.

The tree is *persistent* across proof-loop iterations: adding a scenario
re-evaluates only the new scenario on live boxes and raises their lb
(monotone, spec s.21); adding a witness or lowering U only prunes.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np

from src.q2.formal import batch_kernel as bk
from src.q2.formal.proof_tree import STATUS_PRUNE_A, STATUS_PRUNE_B
from src.q2.formal.scenario_loss import Scenario


class MasterInconsistencyError(RuntimeError):
    """Live box set became empty: L > U or an enclosure is unsound (spec s.4)."""


@dataclass(frozen=True)
class ReceptionWitness:
    """A ball constraint ||S2 - G|| <= R that Crec points must satisfy."""

    gx: float
    gy: float
    radius: float


@dataclass
class MasterSolveStats:
    lower_bound: float
    converged: bool
    stuck: bool
    live_boxes: int
    eval_count: int
    rounds: int
    wall_time_s: float


@dataclass
class BatchMaster:
    """Persistent batched interval B&B for the finite master relaxation."""

    b0: tuple[float, float, float, float]
    upper_bound: float = math.inf
    min_width: float = 1e-9
    # live box arrays (created in __post_init__)
    xlo: np.ndarray = field(init=False, default=None)
    xhi: np.ndarray = field(init=False, default=None)
    ylo: np.ndarray = field(init=False, default=None)
    yhi: np.ndarray = field(init=False, default=None)
    lb: np.ndarray = field(init=False, default=None)
    stuck: np.ndarray = field(init=False, default=None)
    witnesses: list[ReceptionWitness] = field(default_factory=list)
    scenarios: list[Scenario] = field(default_factory=list)
    eval_count: int = 0
    recorder: object = None   # TreeRecorder; None = unrecorded (default)

    def __post_init__(self):
        x0, x1, y0, y1 = self.b0
        self.xlo = np.array([x0])
        self.xhi = np.array([x1])
        self.ylo = np.array([y0])
        self.yhi = np.array([y1])
        self.lb = np.array([0.0])  # loss >= 0 always
        self.stuck = np.array([False])
        if self.recorder is not None:
            # parallel provenance arrays for the live boxes
            self.rec_node = np.array([0], dtype=np.int64)
            self.rec_parent = np.array([-1], dtype=np.int64)
            self.rec_depth = np.array([0], dtype=np.int32)
            self.recorder.register_root()

    # ------------------------------------------------------------------
    # cut management
    # ------------------------------------------------------------------
    def add_witness(self, w: ReceptionWitness) -> int:
        """Add a reception ball; prune live boxes definitely outside it."""
        self.witnesses.append(w)
        keep = ~bk.witness_violation_batch(
            self.xlo, self.xhi, self.ylo, self.yhi, w.gx, w.gy, w.radius)
        self._restrict(keep, prune_reason=STATUS_PRUNE_B, prune_scen=-2)
        return int(np.count_nonzero(~keep))

    def add_scenario(self, scen: Scenario, refresh_band: float | None = 5.0
                     ) -> None:
        """Add an adversarial scenario and raise live box lower bounds (s.21).

        Stored lb values remain valid without any update (the max over the
        old scenario subset is still a lower bound of the new M_k).  For
        tightness we re-evaluate the new scenario on the low band of boxes
        (lb <= min + refresh_band) that drive convergence; ``refresh_band``
        None refreshes every live box.
        """
        self.scenarios.append(scen)
        e_lo, e_hi = _e_bounds(scen)
        if refresh_band is None:
            idx = np.arange(self.lb.size)
        else:
            idx = np.nonzero(self.lb <= self.lower_bound + refresh_band)[0]
        if idx.size == 0:
            return
        lb_new = bk.scenario_loss_lower_batch(
            self.xlo[idx], self.xhi[idx], self.ylo[idx], self.yhi[idx],
            scen.gx, scen.gy, e_lo, e_hi)
        self.eval_count += idx.size
        self.lb[idx] = np.maximum(self.lb[idx], lb_new)
        # boxes pushed over U are attributable to the newly added scenario:
        # the invariant lb <= U held for all live boxes before the refresh
        self._restrict(self.lb <= self.upper_bound,
                       prune_reason=STATUS_PRUNE_A,
                       prune_scen=len(self.scenarios) - 1)

    def set_upper_bound(self, u: float) -> None:
        if u > self.upper_bound:
            raise ValueError("upper bound must be monotone nonincreasing")
        self.upper_bound = u
        self._restrict(self.lb <= self.upper_bound,
                       prune_reason=STATUS_PRUNE_A, prune_scen=-1)

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------
    @property
    def lower_bound(self) -> float:
        if self.lb.size == 0:
            raise MasterInconsistencyError(
                "no live boxes remain: master LB would exceed U (spec s.4)")
        return float(self.lb.min())

    def best_candidates(self, k: int = 8) -> list[tuple[float, float]]:
        k = min(k, self.lb.size)
        idx = np.argpartition(self.lb, k - 1)[:k]
        idx = idx[np.argsort(self.lb[idx])]
        cx = 0.5 * (self.xlo[idx] + self.xhi[idx])
        cy = 0.5 * (self.ylo[idx] + self.yhi[idx])
        return [(float(a), float(b)) for a, b in zip(cx, cy)]

    # ------------------------------------------------------------------
    # branch and bound
    # ------------------------------------------------------------------
    def solve(self, tol: float, round_cap: int = 4096,
              max_boxes: int = 2_000_000, time_budget_s: float = 600.0,
              quality_tol: float | None = None,
              mk_float=None,
              ) -> MasterSolveStats:
        """Split lowest-lb boxes until min lb >= U - tol or budgets run out.

        If ``quality_tol`` and ``mk_float`` (callable (x, y) -> float M_k)
        are given, also stop when the best probed candidate satisfies
        float M_k(candidate) - min_lb <= quality_tol (exchange-loop mode:
        the candidate is then certified near-optimal for M_k).
        """
        t0 = time.time()
        rounds = 0
        converged = False
        stuck_hit = False
        best_mk = math.inf
        probe_cache: dict[tuple[float, float], float] = {}
        while True:
            L = self.lower_bound
            if self.upper_bound - L <= tol:
                converged = True
                break
            if quality_tol is not None and mk_float is not None:
                for cx, cy in self.best_candidates(16):
                    key = (cx, cy)
                    if key not in probe_cache:
                        probe_cache[key] = mk_float(cx, cy)
                    best_mk = min(best_mk, probe_cache[key])
                if best_mk - L <= quality_tol:
                    converged = True
                    break
            if self.lb.size > max_boxes or time.time() - t0 > time_budget_s:
                break
            active = np.nonzero((self.lb < self.upper_bound - tol) & ~self.stuck)[0]
            if active.size == 0:
                stuck_hit = True
                break
            m = min(round_cap, active.size)
            if m < active.size:
                sel = active[np.argpartition(self.lb[active], m - 1)[:m]]
            else:
                sel = active
            self._split_boxes(sel)
            rounds += 1
        return MasterSolveStats(
            lower_bound=self.lower_bound,
            converged=converged,
            stuck=stuck_hit,
            live_boxes=self.lb.size,
            eval_count=self.eval_count,
            rounds=rounds,
            wall_time_s=time.time() - t0,
        )

    def split_lowest_near(self, x: float, y: float, radius: float,
                          m: int = 512) -> int:
        """Force-split the m lowest-lb live boxes whose center lies within
        ``radius`` of (x, y).  Used when a reception witness is already
        present but the boxes there have not yet resolved the Crec boundary
        (duplicate-witness refinement, spec s.34)."""
        cx = 0.5 * (self.xlo + self.xhi)
        cy = 0.5 * (self.ylo + self.yhi)
        near = (cx - x) ** 2 + (cy - y) ** 2 <= radius * radius
        idx = np.nonzero(near & ~self.stuck)[0]
        if idx.size == 0:
            return 0
        m = min(m, idx.size)
        sel = idx[np.argpartition(self.lb[idx], m - 1)[:m]]
        self._split_boxes(sel)
        return int(m)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _restrict(self, keep: np.ndarray, prune_reason: int | None = None,
                  prune_scen: int = -2) -> None:
        if np.all(keep):
            return
        if self.recorder is not None and prune_reason is not None:
            removed = np.nonzero(~keep)[0]
            for i in removed:
                self.recorder.on_prune_existing(int(self.rec_node[i]),
                                                prune_reason, prune_scen)
            self.rec_node = self.rec_node[keep]
            self.rec_parent = self.rec_parent[keep]
            self.rec_depth = self.rec_depth[keep]
        if not np.any(keep):
            raise MasterInconsistencyError(
                "all boxes pruned: L > U or unsound enclosure (spec s.4)")
        self.xlo = self.xlo[keep]
        self.xhi = self.xhi[keep]
        self.ylo = self.ylo[keep]
        self.yhi = self.yhi[keep]
        self.lb = self.lb[keep]
        self.stuck = self.stuck[keep]

    def _split_boxes(self, sel: np.ndarray) -> None:
        xl = self.xlo[sel]
        xh = self.xhi[sel]
        yl = self.ylo[sel]
        yh = self.yhi[sel]
        xmid = xl + 0.5 * (xh - xl)
        ymid = yl + 0.5 * (yh - yl)
        split_x = (xh - xl) >= (yh - yl)
        sx2 = np.concatenate([split_x, split_x])
        # children: two per parent, tiling the parent (shared midpoint)
        c_xlo = np.where(sx2, np.concatenate([xl, xmid]), np.concatenate([xl, xl]))
        c_xhi = np.where(sx2, np.concatenate([xmid, xh]), np.concatenate([xh, xh]))
        c_ylo = np.where(sx2, np.concatenate([yl, yl]), np.concatenate([yl, ymid]))
        c_yhi = np.where(sx2, np.concatenate([yh, yh]), np.concatenate([ymid, yh]))
        c_stuck = ((c_xhi - c_xlo) < self.min_width) & ((c_yhi - c_ylo) < self.min_width)

        # witness pruning
        keep = np.ones(c_xlo.size, dtype=bool)
        for w in self.witnesses:
            viol = bk.witness_violation_batch(
                c_xlo, c_xhi, c_ylo, c_yhi, w.gx, w.gy, w.radius)
            keep &= ~viol
        w_killed = ~keep.copy()
        # scenario evaluation with early exit (order: most recent first -
        # fresh cuts dominate the regions the master currently prefers)
        c_lb = np.zeros(c_xlo.size)
        n_child = c_xlo.size
        prune_scen_arr = np.full(n_child, -2, dtype=np.int16)
        obj_scen_hint = len(self.scenarios) - 1
        for pos, scen in enumerate(reversed(self.scenarios)):
            idx = np.nonzero(keep)[0]
            if idx.size == 0:
                break
            e_lo, e_hi = _e_bounds(scen)
            lb_new = bk.scenario_loss_lower_batch(
                c_xlo[idx], c_xhi[idx], c_ylo[idx], c_yhi[idx],
                scen.gx, scen.gy, e_lo, e_hi)
            self.eval_count += idx.size
            c_lb[idx] = np.maximum(c_lb[idx], lb_new)
            new_over = idx[c_lb[idx] > self.upper_bound]
            prune_scen_arr[new_over] = obj_scen_hint - pos
            keep[idx] &= c_lb[idx] <= self.upper_bound
        keep &= c_lb <= self.upper_bound

        # new live set = (old boxes not split) + (surviving children)
        parent_keep = np.ones(self.lb.size, dtype=bool)
        parent_keep[sel] = False
        xlo = np.concatenate([self.xlo[parent_keep], c_xlo[keep]])
        xhi = np.concatenate([self.xhi[parent_keep], c_xhi[keep]])
        ylo = np.concatenate([self.ylo[parent_keep], c_ylo[keep]])
        yhi = np.concatenate([self.yhi[parent_keep], c_yhi[keep]])
        lb = np.concatenate([self.lb[parent_keep], c_lb[keep]])
        stuck = np.concatenate([self.stuck[parent_keep], c_stuck[keep]])
        if self.recorder is not None:
            m = sel.size
            child_ids = np.empty(2 * m, dtype=np.int64)
            for pi in range(m):
                live_idx = int(sel[pi])
                p_node = int(self.rec_node[live_idx])
                p_depth = int(self.rec_depth[live_idx])
                p_box = (float(xl[pi]), float(xh[pi]),
                         float(yl[pi]), float(yh[pi]))
                if split_x[pi]:
                    axis, val = 0, float(xmid[pi])
                    lbox = (float(xl[pi]), float(xmid[pi]),
                            float(yl[pi]), float(yh[pi]))
                    rbox = (float(xmid[pi]), float(xh[pi]),
                            float(yl[pi]), float(yh[pi]))
                else:
                    axis, val = 1, float(ymid[pi])
                    lbox = (float(xl[pi]), float(xh[pi]),
                            float(yl[pi]), float(ymid[pi]))
                    rbox = (float(xl[pi]), float(xh[pi]),
                            float(ymid[pi]), float(yh[pi]))
                l_stat = None if keep[pi] else (
                    STATUS_PRUNE_B if w_killed[pi] else STATUS_PRUNE_A)
                r_stat = None if keep[m + pi] else (
                    STATUS_PRUNE_B if w_killed[m + pi] else STATUS_PRUNE_A)
                lid, rid, _, _ = self.recorder.on_split(
                    p_node, p_depth, p_box, float(self.lb[live_idx]),
                    axis, val,
                    lbox, float(c_lb[pi]), l_stat, int(prune_scen_arr[pi]),
                    rbox, float(c_lb[m + pi]), r_stat,
                    int(prune_scen_arr[m + pi]))
                child_ids[pi] = lid
                child_ids[m + pi] = rid
            old_node = self.rec_node
            old_parent = self.rec_parent
            old_depth = self.rec_depth
            self.rec_node = np.concatenate([
                old_node[parent_keep], child_ids[keep]])
            self.rec_parent = np.concatenate([
                old_parent[parent_keep],
                np.concatenate([old_node[sel], old_node[sel]])[keep]])
            self.rec_depth = np.concatenate([
                old_depth[parent_keep],
                (np.concatenate([old_depth[sel], old_depth[sel]]) + 1)[keep]])
        if lb.size == 0:
            raise MasterInconsistencyError(
                "all boxes pruned: L > U or unsound enclosure (spec s.4)")
        self.xlo, self.xhi = xlo, xhi
        self.ylo, self.yhi = ylo, yhi
        self.lb, self.stuck = lb, stuck


def _e_bounds(scen: Scenario) -> tuple[float, float]:
    """Outward float64 enclosure of the scenario bearing error [rad]."""
    r = math.radians(scen.e_deg)
    return float(bk.pad_lo(r, 8)), float(bk.pad_hi(r, 8))
