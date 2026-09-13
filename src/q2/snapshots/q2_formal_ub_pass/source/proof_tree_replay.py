"""Rigorous proof-tree replay for the finite master B&B (closure spec
s.15-19, s.21-22, s.28-33, s.36-38, s.41, s.52-53).

Search once, verify the tree afterwards: the float64 batch engine generated
the recorded proof tree (``proof_tree.py``); THIS module is the certificate
engine.  Every decision that could possibly affect the global lower bound is
re-derived with Arb ball arithmetic:

  stage 0  frozen-input re-verification (anchor, witnesses, scenarios, root);
  stage 1  exact topology: children tile their parent, midpoints exact,
           no dangling nodes (BLOCKED_PROOF_TREE_COVERAGE otherwise);
  stage 2  every historical prune decision replayed:
             PRUNE_A (objective)  - Arb box lower bound of M_k > U (strict);
             PRUNE_B (reception)  - Arb distance proves the box strictly
                                    outside a witness ball;
           tri-state comparisons; UNKNOWN escalates 128 -> 256 -> 512 bit;
           an unconfirmed prune is superseded by a rigorous re-expansion
           (bisect + recurse) - never guessed;
  stage 3  every final live leaf receives a valid Arb lower bound of M_k
           (a partial scenario max is already a valid bound; the argmin
           band is evaluated over all scenarios);
           L_rigorous = min over live leaves <= inf_D M <= Q*  (THEOREM B);
  stage 4  if the gap exceeds tau: rigorous refinement - pop the argmin
           leaf, bisect it, reclassify its children (Arb only).  No model,
           cut, incumbent or tolerance change (spec s.41).

All live leaves live in a min-heap keyed by their valid Arb lower bound, so
the refinement stage is exact bookkeeping: L_rigorous is always the heap
minimum and every popped entry is genuinely the current argmin leaf.

Sampling/fuzz/mpmath results are falsification evidence only (spec s.36);
the global lower-bound completeness proof is THIS whole-tree replay.
"""

from __future__ import annotations

import heapq
import json
import math
import time
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import numpy as np

from src.q2.formal import batch_kernel as bk
from src.q2.formal.ivl_geometry import IvlPoint, box_point_distance
from src.q2.formal.master_problem import load_records
from src.q2.formal.proof_tree import (
    STATUS_LIVE_FINAL,
    STATUS_PRUNE_A,
    STATUS_PRUNE_B,
    STATUS_SPLIT,
)
from src.q2.formal.rigorous_arithmetic import Ivl, Tri, set_precision_bits
from src.q2.formal.scenario_loss import Scenario, box_loss_lower

B0 = (0.0, 2000.0, -1000.0, 0.0)
G0 = (1000.0, 0.0)
TAU = 0.01
MIN_LEAF_WIDTH = 1e-12
BASE_PRECISION = 128


@dataclass
class ReplayResult:
    passed: bool
    status: str
    L_rigorous: float = 0.0
    U_rigorous: float = math.inf
    gap: float = math.inf
    verified_pruned_objective: int = 0
    verified_pruned_reception: int = 0
    superseded_prunes: int = 0
    mixed_splits: int = 0
    unverified_pruned_nodes: int = 0
    live_leaves: int = 0
    refined_splits: int = 0
    precision_escalations: int = 0
    topology_ok: bool = False
    root_identity_ok: bool = False
    legalized_scenarios: list = field(default_factory=list)
    optimizer_summary: dict = field(default_factory=dict)
    details: list[str] = field(default_factory=list)
    wall_time_s: float = 0.0


# ----------------------------------------------------------------------
# exact helpers
# ----------------------------------------------------------------------
def _exact_midpoint(lo: float, hi: float) -> Fraction:
    return (Fraction(*lo.as_integer_ratio())
            + Fraction(*hi.as_integer_ratio())) / 2


def _leaf_box(arr, i: int) -> tuple[float, float, float, float]:
    return (float(arr["xlo"][i]), float(arr["xhi"][i]),
            float(arr["ylo"][i]), float(arr["yhi"][i]))


def _bisect(box):
    w = box[1] - box[0]
    h = box[3] - box[2]
    if w >= h:
        m = (box[0] + box[1]) / 2
        return (box[0], m, box[2], box[3]), (m, box[1], box[2], box[3])
    m = (box[2] + box[3]) / 2
    return (box[0], box[1], box[2], m), (box[0], box[1], m, box[3])


# ----------------------------------------------------------------------
# stage 0: frozen input re-verification (spec s.20, s.27)
# ----------------------------------------------------------------------
def _check_root_and_inputs(scen_objs, wit_objs, details):
    """Stage 0.  Returns (ok, verified_scen_objs, legalization_records).

    Error legality: |e_deg| <= 1 is checked in EXACT rational arithmetic
    (both e and eps scale by the same exact pi/180, and e_deg is an exact
    binary rational) - a ball comparison of |e| against eps cannot decide
    the equality case.  Wedge legality: a scenario whose stored float
    construction sits on/outside the closed boundary (measured: scenario 7
    at arg = -1.0000000000000000141 deg) is legalized by rotating G toward
    the interior by 1e-12 rad; the rotation is recorded and the legalized
    scenario is used for every Arb loss evaluation, keeping
    S_verified ⊆ S_phys (THEOREM B) with certainty margin ~1e-12 rad.
    """
    set_precision_bits(BASE_PRECISION)
    five = Ivl.from_int(5)
    r_max = Ivl.from_int(1500)
    eps = Ivl.pi() / Ivl.from_int(180)
    ok = True
    legalized = []

    def rho_arg(gx, gy):
        g = IvlPoint(Ivl.from_float(gx), Ivl.from_float(gy))
        rho = (g.x.square() + g.y.square()).sqrt()
        arg = g.y.atan2(g.x)
        return rho, arg, g

    def wedge_ok(arg):
        return (Ivl.le(arg, eps) is Tri.TRUE
                and Ivl.le(Ivl.from_int(0) - eps, arg) is Tri.TRUE)

    # anchor G0 in A1 -> C_rec subset B(G0, max(1000, ||G0||)) = B(G0,1000)
    rho, arg, _ = rho_arg(G0[0], G0[1])
    if not (Ivl.gt(rho, five) is Tri.TRUE and Ivl.le(rho, r_max) is Tri.TRUE
            and wedge_ok(arg)):
        details.append("anchor G0 not certainly in A1")
        ok = False
    # witnesses legal + radius semantics
    for i, w in enumerate(wit_objs):
        rho, arg, _ = rho_arg(w.gx, w.gy)
        if not (Ivl.gt(rho, five) is Tri.TRUE
                and Ivl.le(rho, r_max) is Tri.TRUE and wedge_ok(arg)):
            details.append(f"witness {i}: not certainly in A1"); ok = False
        if w.radius != max(1000.0, math.hypot(w.gx, w.gy)):
            details.append(f"witness {i}: radius != max(1000, |G|)")
            ok = False
    # scenarios: rho range, exact-rational error legality, wedge legality
    for i, s in enumerate(scen_objs):
        rho, arg, _ = rho_arg(s.gx, s.gy)
        if not (Ivl.gt(rho, five) is Tri.TRUE
                and Ivl.le(rho, r_max) is Tri.TRUE):
            details.append(f"scenario {i}: rho not certainly in (5, 1500]")
            ok = False
        if abs(s.e_deg) > 1.0:
            details.append(f"scenario {i}: |e_deg| > 1 (exact rational)")
            ok = False
        if not wedge_ok(arg):
            d = 1e-12 if arg.mid_float() < 0.0 else -1e-12
            gx2 = s.gx * math.cos(d) - s.gy * math.sin(d)
            gy2 = s.gx * math.sin(d) + s.gy * math.cos(d)
            rho2, arg2, _ = rho_arg(gx2, gy2)
            if (Ivl.gt(rho2, five) is Tri.TRUE
                    and Ivl.le(rho2, r_max) is Tri.TRUE
                    and wedge_ok(arg2)):
                legalized.append({
                    "scenario_index": i, "label": s.label,
                    "reason": "stored float construction on/outside the "
                              "closed wedge boundary (float noise ~1e-16 "
                              "deg); rotated 1e-12 rad toward the interior",
                    "rotation_rad": d,
                })
                scen_objs[i] = Scenario(gx2, gy2, s.e_deg, s.label)
                details.append(f"scenario {i}: G legalized by {d} rad "
                               f"rotation; certainly inside the wedge now")
            else:
                details.append(f"scenario {i}: legalization failed")
                ok = False
    details.append("root derivation: C_rec^- subset [0,2000]x[-1000,0] = B0^- "
                   "(anchor ball bounding box intersect closed half-plane)")
    return ok, scen_objs, legalized


# ----------------------------------------------------------------------
# stage 1: exact topology (spec s.21-22)
# ----------------------------------------------------------------------
def _check_topology(arr, details, expect_root_b0: bool = True) -> bool:
    n = int(arr["status"].size)
    status, parent, depth = arr["status"], arr["parent"], arr["depth"]
    left, right = arr["left"], arr["right"]
    ok = True
    idx = np.arange(n)
    if np.any((idx > 0) & (parent >= idx)):
        details.append("parent id not < node id"); ok = False
    if parent[0] != -1 or depth[0] != 0:
        details.append("root parent/depth invalid"); ok = False
    p_safe = np.maximum(parent, 0)
    if n > 1 and not np.all(depth[1:] == depth[p_safe][1:] + 1):
        details.append("depth != parent.depth + 1"); ok = False
    root_box = (arr["xlo"][0], arr["xhi"][0], arr["ylo"][0], arr["yhi"][0])
    if expect_root_b0 and root_box != B0:
        details.append("root box != B0^-"); ok = False
    if not (B0[0] <= root_box[0] and root_box[1] <= B0[1]
            and B0[2] <= root_box[2] and root_box[3] <= B0[3]):
        details.append("root box not inside B0^-"); ok = False
    is_split = status == STATUS_SPLIT
    if np.any(~is_split & ((left != -1) | (right != -1))):
        details.append("non-split node with children"); ok = False
    if np.any(is_split & ((left < 0) | (right < 0) | (arr["split_axis"] < 0))):
        details.append("split node missing child/axis"); ok = False
    if not ok:
        return False

    xlo, xhi, ylo, yhi = arr["xlo"], arr["xhi"], arr["ylo"], arr["yhi"]
    sv, ax = arr["split_value"], arr["split_axis"]
    for i in np.nonzero(is_split)[0]:
        i = int(i)
        l, r = int(left[i]), int(right[i])
        if ax[i] == 0:
            if not (xlo[l] == xlo[i] and xhi[l] == sv[i] == xlo[r]
                    and xhi[r] == xhi[i] and ylo[l] == ylo[i] == ylo[r]
                    and yhi[l] == yhi[i] == yhi[r]):
                details.append(f"node {i}: x-tiling broken")
                return False
            mid = _exact_midpoint(xlo[i], xhi[i])
        elif ax[i] == 1:
            if not (ylo[l] == ylo[i] and yhi[l] == sv[i] == ylo[r]
                    and yhi[r] == yhi[i] and xlo[l] == xlo[i] == xlo[r]
                    and xhi[l] == xhi[i] == xhi[r]):
                details.append(f"node {i}: y-tiling broken")
                return False
            mid = _exact_midpoint(ylo[i], yhi[i])
        else:
            details.append(f"node {i}: bad axis")
            return False
        if mid != Fraction(*sv[i].as_integer_ratio()):
            details.append(f"node {i}: split midpoint inexact")
            return False
        if parent[l] != i or parent[r] != i:
            details.append(f"node {i}: child parent link broken")
            return False
    details.append(f"topology OK: {len(np.nonzero(is_split)[0])} splits tile "
                   f"B0^- exactly; leaves partition the root")
    return True


# ----------------------------------------------------------------------
# the verifier
# ----------------------------------------------------------------------
class _Verifier:
    def __init__(self, scen_objs, wit_objs, U, precision_ladder,
                 static_order=None):
        self.scen = scen_objs
        self.wit = wit_objs
        self.U = float(U)
        self.U_ivl = Ivl.from_float(U)
        self.ladder = precision_ladder
        self.e_bounds = [(s.e_interval().lower_float(),
                          s.e_interval().upper_float()) for s in scen_objs]
        # hoisted witness arrays for the float prefilter (search metadata)
        self._gx = np.array([w.gx for w in wit_objs], dtype=np.float64)
        self._gy = np.array([w.gy for w in wit_objs], dtype=np.float64)
        self._rr = np.array([w.radius for w in wit_objs], dtype=np.float64)
        # static scenario evaluation order: descending fast loss at the
        # incumbent (the argmin region's binding scenarios first), so the
        # fused single-pass lower bound can early-exit after 1-2 evals
        self.static_order = static_order or list(range(len(scen_objs)))
        self.verified_a = 0
        self.verified_b = 0
        self.escalations = 0
        self.superseded = 0
        self.mixed_splits = 0
        self.heap: list = []          # (valid_lb, seq, box)
        self.seq = 0

    # -- Arb primitives --------------------------------------------------
    def _arb_lb(self, box, j: float):
        s = self.scen[j]
        s2box = IvlPoint(Ivl.from_bounds(box[0], box[1]),
                         Ivl.from_bounds(box[2], box[3]))
        return box_loss_lower(s2box, s)

    def _reception_candidates(self, box):
        """Witness indices whose float64 criterion flags the box strictly
        outside the ball (the search engine's own sound prefilter).  Arb
        confirmation is only run against these candidates."""
        dxl = np.maximum(np.maximum(self._gx - box[1], box[0] - self._gx), 0.0)
        dyl = np.maximum(np.maximum(self._gy - box[3], box[2] - self._gy), 0.0)
        d_lo = bk.pad_lo(np.sqrt(dxl * dxl + dyl * dyl))
        return list(np.nonzero(d_lo > self._rr)[0])

    def _reception_confirmable(self, box, candidates=None) -> bool:
        """Rigorous (Arb) proof that the box is strictly outside some
        witness ball, i.e. B ∩ D_k = ∅ (spec s.23 PRUNE-B)."""
        for i in (candidates if candidates is not None
                  else self._reception_candidates(box)):
            w = self.wit[i]
            for p in self.ladder:
                set_precision_bits(p)
                g = IvlPoint(Ivl.from_float(w.gx), Ivl.from_float(w.gy))
                d_lo, _ = box_point_distance(
                    IvlPoint(Ivl.from_bounds(box[0], box[1]),
                             Ivl.from_bounds(box[2], box[3])), g)
                if Ivl.gt(d_lo, Ivl.from_float(w.radius)) is Tri.TRUE:
                    set_precision_bits(BASE_PRECISION)
                    return True
        set_precision_bits(BASE_PRECISION)
        return False

    def _reception_confirmable(self, box, candidates=None) -> bool:
        """Rigorous (Arb) proof that the box is strictly outside some
        witness ball, i.e. B ∩ D_k = ∅ (spec s.23 PRUNE-B)."""
        for i in (candidates if candidates is not None
                  else self._reception_candidates(box)):
            w = self.wit[i]
            for p in self.ladder:
                set_precision_bits(p)
                g = IvlPoint(Ivl.from_float(w.gx), Ivl.from_float(w.gy))
                d_lo, _ = box_point_distance(
                    IvlPoint(Ivl.from_bounds(box[0], box[1]),
                             Ivl.from_bounds(box[2], box[3])), g)
                if Ivl.gt(d_lo, Ivl.from_float(w.radius)) is Tri.TRUE:
                    set_precision_bits(BASE_PRECISION)
                    return True
        set_precision_bits(BASE_PRECISION)
        return False

    def _box_lb(self, box, first=None):
        """Fused single pass: a valid (possibly partial) Arb lower bound of
        M_k over the box.

        Scenarios are evaluated hint-first, then in the static order (no
        per-box fast reordering - that numpy overhead dominated the cost).
        Early exits, both sound:
          * best > U        -> the box cannot contain a master solution
                               better than U (prune-confirmed);
          * best > min_live -> the box cannot be the argmin leaf; the
                               partial max is still a valid lower bound.
        Returns (lb, hit_threshold, mixed) where ``mixed`` flags that at
        least one evaluated scenario straddled the near circle or the
        atan2 branch cut on this box (spec s.25: such a box may only be
        SUBDIVIDED, never accepted with the loose 0 bound, if a tighter
        bound is needed).
        """
        order = []
        if first is not None and 0 <= first < len(self.scen):
            order.append(first)
        order.extend(j for j in self.static_order if j not in order)
        best = 0.0
        mixed = False
        inconclusive = False
        for p in self.ladder:
            set_precision_bits(p)
            try:
                for j in order:
                    lower, branch = self._arb_lb(box, j)
                    if branch == "unbounded":
                        set_precision_bits(BASE_PRECISION)
                        return math.inf, True, False
                    if branch == "mixed":
                        mixed = True
                    if lower is None:
                        # no certainly-feasible vertex pair on this box:
                        # the feasibility tests are undecidable at this
                        # precision/size (spec s.28: UNKNOWN -> subdivide)
                        inconclusive = True
                    if lower is not None:
                        v = lower.lower_float()
                        if v > best:
                            best = v
                    if best > self.U:
                        set_precision_bits(BASE_PRECISION)
                        return best, True, False
                    if best > self.min_live:
                        set_precision_bits(BASE_PRECISION)
                        return best, False, mixed
            except Exception:
                mixed = True  # enclosure failure: treat as needing a split
            if p != self.ladder[-1]:
                self.escalations += 1
        set_precision_bits(BASE_PRECISION)
        return best, False, (mixed or inconclusive)

    # -- heap bookkeeping --------------------------------------------------
    def push_live(self, lb: float, box) -> None:
        heapq.heappush(self.heap, (lb, self.seq, box))
        self.seq += 1

    @property
    def min_live(self) -> float:
        return self.heap[0][0] if self.heap else math.inf

    # -- classification of one box ------------------------------------------
    def classify(self, box, first_hint=None, historical: bool = False,
                 depth: int = 0):
        """Rigorously classify one box (spec s.23, s.25, s.31, s.41).

        Outcome 1: PRUNE_B - Arb proves the box strictly outside a witness
        ball.  Outcome 2: PRUNE_A - Arb proves inf_B M > U (strict, the
        unified prune convention).  Outcome 3: the box becomes a live leaf
        with a valid Arb lower bound.  A mixed box (straddling the near
        circle or the branch cut) is never accepted with its loose 0 bound
        when a tighter bound is needed - it is SUBDIVIDED (spec s.25).  A
        historical prune that ends up demoted to a live leaf is counted as
        superseded; the lower bound stays rigorous and honest (s.41).
        """
        cand = self._reception_candidates(box)
        if cand and self._reception_confirmable(box, cand):
            self.verified_b += 1
            return "pruned_b"
        lb, hit, mixed = self._box_lb(box, first=first_hint)
        if lb > self.U:
            self.verified_a += 1
            return "pruned_a"
        if mixed and depth < 40:
            if historical:
                self.superseded += 1
            lo, hi = _bisect(box)
            self.mixed_splits += 1
            self.classify(lo, depth=depth + 1)
            self.classify(hi, depth=depth + 1)
            return "split_mixed"
        if historical:
            self.superseded += 1
        self.push_live(lb, box)
        return "live"

    def refine_pop_and_split(self) -> bool:
        """Pop the argmin leaf and reclassify its children (spec s.41)."""
        if not self.heap:
            return False
        _lb, _seq, box = heapq.heappop(self.heap)
        lo, hi = _bisect(box)
        self.classify(lo)
        self.classify(hi)
        return True


# ----------------------------------------------------------------------
# main replay
# ----------------------------------------------------------------------
def replay_proof_tree(artifacts_dir: Path, tau: float = TAU,
                      cuts_dir: Path | None = None,
                      precision_ladder=(128, 256, 512),
                      refine_time_budget_s: float = 1800.0,
                      progress_every: int = 50000,
                      expect_root_b0: bool = True,
                      ) -> ReplayResult:
    t0 = time.time()
    artifacts_dir = Path(artifacts_dir)
    cuts_dir = Path(cuts_dir or artifacts_dir)
    res = ReplayResult(passed=False, status="BLOCKED_RIGOROUS_TREE_REPLAY")
    det = res.details

    npz = np.load(artifacts_dir / "proof_tree.npz")
    # materialize ONCE: NpzFile re-decompresses on every [] access, which
    # would dominate the replay cost (measured 341 ms/node vs 0.3 ms Arb)
    arr = {k: npz[k] for k in npz.files}
    npz.close()
    index = json.loads((artifacts_dir / "proof_tree_index.json").read_text())
    U = float(index["u_cert_decimal"])
    res.U_rigorous = U
    scen_recs, wit_recs = load_records(cuts_dir / "master_cuts.json")
    scen_objs = [s.to_scenario() for s in scen_recs]
    wit_objs = [w.to_witness() for w in wit_recs]
    det.append(f"tree loaded: {int(arr['status'].size)} nodes; U={U!r}; "
               f"{len(scen_objs)} scenarios / {len(wit_objs)} witnesses")

    res.root_identity_ok, scen_objs, legalizations = _check_root_and_inputs(
        scen_objs, wit_objs, det)
    res.legalized_scenarios = legalizations
    if not res.root_identity_ok:
        res.status = "BLOCKED_MODEL_COUNTEREXAMPLE"
        res.wall_time_s = time.time() - t0
        return res
    det.append("stage 0 PASS: anchor/witnesses/scenarios rigorously legal; "
               "C_rec^- subset B0^- re-derived")

    res.topology_ok = _check_topology(arr, det, expect_root_b0)
    if not res.topology_ok:
        res.status = "BLOCKED_PROOF_TREE_COVERAGE"
        res.wall_time_s = time.time() - t0
        return res

    # static scenario order: descending float loss at the incumbent (the
    # argmin region's binding scenarios are evaluated first)
    from src.q2.formal.scenario_loss import float_point_loss
    inc = (805.1110506884, -599.7632926544)
    losses = [float_point_loss(inc[0], inc[1], s) for s in scen_objs]
    static_order = sorted(range(len(scen_objs)),
                          key=lambda j: -(losses[j]
                                          if math.isfinite(losses[j])
                                          else 1e18))
    ver = _Verifier(scen_objs, wit_objs, U, precision_ladder,
                    static_order=static_order)

    # -- stage 2: historical prunes
    status = arr["status"]
    pb = np.nonzero(status == STATUS_PRUNE_B)[0]
    pa = np.nonzero(status == STATUS_PRUNE_A)[0]
    hint = arr["prune_scen"]
    t2 = time.time()
    for k, i in enumerate(pb):
        ver.classify(_leaf_box(arr, int(i)), historical=True)
        if (k + 1) % progress_every == 0:
            det.append(f"  PRUNE_B replay {k+1}/{len(pb)} "
                       f"(B={ver.verified_b} superseded={ver.superseded})")
    for k, i in enumerate(pa):
        h = int(hint[i])
        first = h if 0 <= h < len(scen_objs) else None
        ver.classify(_leaf_box(arr, int(i)), first_hint=first,
                     historical=True)
        if (k + 1) % progress_every == 0:
            det.append(f"  PRUNE_A replay {k+1}/{len(pa)} "
                       f"(A={ver.verified_a} B={ver.verified_b} "
                       f"superseded={ver.superseded} esc={ver.escalations}) "
                       f"t={time.time()-t2:.0f}s")
    res.verified_pruned_objective = ver.verified_a
    res.verified_pruned_reception = ver.verified_b
    res.superseded_prunes = ver.superseded
    res.mixed_splits = ver.mixed_splits
    det.append(f"stage 2: historical prunes {len(pa)+len(pb)} = "
               f"objective-verified {ver.verified_a} + reception-verified "
               f"{ver.verified_b} + superseded (demoted to live leaves with "
               f"valid Arb bounds) {ver.superseded}; unverified = 0; "
               f"precision escalations {ver.escalations}")

    # -- stage 3: live leaves -> valid Arb lower bounds into the heap
    live_idx = np.nonzero(status == STATUS_LIVE_FINAL)[0]
    order = np.argsort(arr["lb_fast"][live_idx])  # argmin candidates first
    t3 = time.time()
    for k, pos in enumerate(order):
        box = _leaf_box(arr, int(live_idx[pos]))
        ver.classify(box)
        if (k + 1) % 200000 == 0:
            det.append(f"  live leaves {k+1}/{len(order)} "
                       f"L={ver.min_live!r} t={time.time()-t3:.0f}s")
    res.live_leaves = len(order)
    res.L_rigorous = ver.min_live
    det.append(f"stage 3: L_rigorous = min over {res.live_leaves} live leaves "
               f"= {res.L_rigorous!r}")

    # -- stage 4: rigorous refinement until gap <= tau or budget
    refined = 0
    t_ref = time.time()
    while (res.U_rigorous - ver.min_live > tau
           and time.time() - t_ref < refine_time_budget_s
           and ver.refine_pop_and_split()):
        refined += 1
        if refined % 200 == 0:
            det.append(f"  refinement {refined}: L={ver.min_live!r} "
                       f"gap={res.U_rigorous - ver.min_live:.6f}")
    res.refined_splits = refined
    res.L_rigorous = ver.min_live
    if not ver.heap:
        # every leaf rigorously pruned: the master optimum is pinned by U
        res.L_rigorous = res.U_rigorous
    res.gap = res.U_rigorous - res.L_rigorous
    res.unverified_pruned_nodes = 0

    # -- replay-surviving live leaves: optimizer outer enclosure (s.43) --
    boxes = np.array([b for _, _, b in ver.heap], dtype=np.float64) \
        if ver.heap else np.zeros((0, 4), dtype=np.float64)
    np.savez_compressed(artifacts_dir / "optimizer_live_boxes.npz",
                        xlo=boxes[:, 0], xhi=boxes[:, 1],
                        ylo=boxes[:, 2], yhi=boxes[:, 3])
    if len(boxes):
        res.optimizer_summary = {
            "box_count": int(len(boxes)),
            "x_span": [float(boxes[:, 0].min()), float(boxes[:, 1].max())],
            "y_span": [float(boxes[:, 2].min()), float(boxes[:, 3].max())],
            "max_box_diameter_m": float(np.max(np.hypot(
                boxes[:, 1] - boxes[:, 0], boxes[:, 3] - boxes[:, 2]))),
            "note": "union of the replay-surviving live leaves (each with a "
                    "valid Arb lower bound) is a rigorous outer "
                    "approximation of the finite-master optimizer set",
            "boxes_file": "optimizer_live_boxes.npz",
        }
    else:
        res.optimizer_summary = {"box_count": 0}

    if res.gap <= max(tau, 1e-6 * max(res.U_rigorous, 1.0)):
        res.passed = True
        res.status = "CERTIFIED_GLOBAL_EPS_OPTIMUM"
    else:
        res.status = "CERTIFIED_GLOBAL_BOUND"
    res.wall_time_s = time.time() - t0
    return res


def main() -> int:
    artifacts_dir = Path("src/q2/artifacts/formal")
    res = replay_proof_tree(artifacts_dir)
    out = {
        "passed": res.passed, "status": res.status,
        "rigorous_lower_bound_m": repr(res.L_rigorous),
        "rigorous_upper_bound_m": repr(res.U_rigorous),
        "absolute_gap_m": repr(res.gap),
        "verified_pruned_objective": res.verified_pruned_objective,
        "verified_pruned_reception": res.verified_pruned_reception,
        "superseded_prunes": res.superseded_prunes,
        "mixed_splits": res.mixed_splits,
        "unverified_pruned_nodes": res.unverified_pruned_nodes,
        "live_leaves": res.live_leaves,
        "refined_splits": res.refined_splits,
        "precision_escalations": res.precision_escalations,
        "topology_ok": res.topology_ok,
        "root_identity_ok": res.root_identity_ok,
        "legalized_scenarios": res.legalized_scenarios,
        "optimizer_outer_enclosure": res.optimizer_summary,
        "wall_time_s": res.wall_time_s,
        "details": res.details,
    }
    (artifacts_dir / "proof_tree_replay_result.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")
    (artifacts_dir / "rigorous_master_lower_bound.json").write_text(
        json.dumps({
            "theorem": "THEOREM B - Master Relaxation Lower Bound",
            "chain": "L_rigorous = min_live LB_Arb(B) "
                     "<= inf_{D_k ∩ {y<=0}} M "
                     "<= inf_{C_rec ∩ {y<=0}} Q~ = Q* "
                     "(C_rec subset D_k, S subset S_phys, Corollary A)",
            "L_rigorous_m": repr(res.L_rigorous),
            "U_rigorous_m": repr(res.U_rigorous),
            "absolute_gap_m": repr(res.gap),
            "live_leaves": res.live_leaves,
            "status": res.status,
        }, indent=1), encoding="utf-8")
    print("passed:", res.passed, "| status:", res.status)
    print(f"L={res.L_rigorous!r} U={res.U_rigorous!r} gap={res.gap!r}")
    for d in res.details:
        print(" *", d)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
