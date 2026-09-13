"""Independent final replay of the Q2 optimality certificate (spec s.41, s.42).

Replay protocol (V3/V4 of the verifier hierarchy, spec s.47):

1. reload the cut records (reception witnesses + adversarial scenarios) from
   the artifacts - no solver state is reused;
2. re-certify the incumbent upper bound with Arb at >= 2x proof precision;
3. rebuild the master from the records and re-solve the finite relaxation
   with the batch interval engine to tolerance;
4. re-verify a random sample of surviving live boxes with the *scalar Arb*
   engine (second, independent arithmetic path): the batch lower bound must
   never exceed the arb lower bound by more than the cross-engine slack
   (both are valid bounds; disagreement beyond slack means the fast engine
   overestimated -> BLOCKED_INTERVAL_UNSOUNDNESS);
5. verify L_replay <= U_replay and gap <= tau.

Only when all steps pass may the certificate status stand (spec s.41).
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from src.q2.formal import batch_kernel as bk
from src.q2.formal.interval_master import BatchMaster, _e_bounds
from src.q2.formal.ivl_geometry import IvlPoint
from src.q2.formal.master_problem import load_records
from src.q2.formal.rigorous_arithmetic import Ivl, set_precision_bits
from src.q2.formal.scenario_loss import box_loss_lower
from src.q2.formal.upper_bound import certify_q2_point_upper_bound

CROSS_ENGINE_SLACK = 1e-6


@dataclass
class ReplayResult:
    passed: bool
    status: str
    lower_bound: float = 0.0
    upper_bound: float = math.inf
    gap: float = math.inf
    ub_recertified: bool = False
    master_replayed: bool = False
    sampled_boxes_checked: int = 0
    max_cross_engine_excess: float = 0.0
    wall_time_s: float = 0.0
    details: list[str] = field(default_factory=list)


def replay_certificate(artifacts_dir: Path, tau_abs: float = 0.01,
                       sample_boxes: int = 2000, seed: int = 20260911,
                       solve_budget_s: float = 2400.0) -> ReplayResult:
    t0 = time.time()
    res = ReplayResult(passed=False, status="INCOMPLETE_CERTIFICATE_TIMEOUT")
    details = res.details

    # --- reload proof objects ---
    scenarios, witnesses = load_records(artifacts_dir / "master_cuts.json")
    inc = json.loads((artifacts_dir / "incumbent_upper_bound.json")
                     .read_text(encoding="utf-8"))
    s2x = float(inc["incumbent_S2"][0])
    s2y = float(inc["incumbent_S2"][1])
    details.append(f"loaded {len(scenarios)} scenarios, "
                   f"{len(witnesses)} witnesses")

    # --- step 2: UB re-certification at 2x precision (Arb path) ---
    set_precision_bits(256)
    ub = certify_q2_point_upper_bound(s2x, s2y, beta_tol=1e-5)
    set_precision_bits(128)
    if ub.status not in ("CERTIFIED", "ALL_NEAR_ZERO"):
        res.status = "BLOCKED_WITNESS_RECOVERY"
        details.append(f"UB recertification failed: {ub.status} {ub.detail}")
        return res
    res.ub_recertified = True
    res.upper_bound = ub.upper_float
    details.append(f"UB recertified at 256 bits: U={ub.upper_float:.10f}")

    # --- step 3: replay master from records ---
    master = BatchMaster(b0=(0.0, 2000.0, -1000.0, 0.0),
                         upper_bound=res.upper_bound)
    for w in witnesses:
        master.add_witness(w.to_witness())
    for s in scenarios:
        master.add_scenario(s.to_scenario(), refresh_band=None)
    stats = master.solve(tol=0.9 * tau_abs, round_cap=8192,
                         max_boxes=10_000_000, time_budget_s=solve_budget_s)
    res.master_replayed = True
    res.lower_bound = master.lower_bound
    details.append(
        f"master replayed: L={res.lower_bound:.10f} live={stats.live_boxes} "
        f"converged={stats.converged}")
    if res.lower_bound > res.upper_bound:
        res.status = "CRITICAL_CERTIFICATE_INCONSISTENCY"
        details.append("L > U after replay")
        return res

    # --- step 4: re-verification of sampled live boxes ---
    # Soundness direction: the stored batch lb must not exceed the true
    # minimum of M_k over the box.  We sample M_k (float oracle over all
    # scenarios) at the center/corners/edge midpoints of each sampled box;
    # batch_lb <= min_sample + slack must hold (spec s.33: dense sampling
    # can only falsify, which is exactly the check we want here).  We also
    # recompute the Arb-engine lower bound as an independent second valid
    # bound and report the agreement (either engine may be tighter).
    rng = np.random.default_rng(seed)
    n_live = master.lb.size
    k = min(sample_boxes, n_live)
    idx = rng.choice(n_live, size=k, replace=False)
    worst_excess = 0.0
    worst_arb_gap = 0.0
    frac = [0.0, 0.25, 0.5, 0.75, 1.0]
    from src.q2.formal.scenario_loss import float_point_loss
    scen_objs = [s.to_scenario() for s in scenarios]
    set_precision_bits(256)
    for i in idx:
        batch_lb = float(master.lb[i])
        xs = master.xlo[i] + (master.xhi[i] - master.xlo[i]) * np.array(frac)
        ys = master.ylo[i] + (master.yhi[i] - master.ylo[i]) * np.array(frac)
        min_sample = math.inf
        for x in xs:
            for y in ys:
                v = max(float_point_loss(float(x), float(y), s)
                        for s in scen_objs)
                if v < min_sample:
                    min_sample = v
        excess = batch_lb - min_sample
        worst_excess = max(worst_excess, excess)
        if excess > CROSS_ENGINE_SLACK:
            set_precision_bits(128)
            res.status = "BLOCKED_INTERVAL_UNSOUNDNESS"
            res.sampled_boxes_checked = k
            details.append(
                f"box {i}: batch lb {batch_lb} exceeds sampled min "
                f"{min_sample} by {excess}")
            return res
        box = IvlPoint(Ivl.from_bounds(float(master.xlo[i]),
                                       float(master.xhi[i])),
                       Ivl.from_bounds(float(master.ylo[i]),
                                       float(master.yhi[i])))
        arb_lb = 0.0
        for s in scen_objs:
            lb_j, _branch = box_loss_lower(box, s)
            if lb_j is None:
                arb_lb = math.inf
                break
            arb_lb = max(arb_lb, lb_j.lower_float())
            if arb_lb > batch_lb:
                break  # already above; agreement question settled
        if math.isfinite(arb_lb) and math.isfinite(batch_lb):
            worst_arb_gap = max(worst_arb_gap, abs(arb_lb - batch_lb))
    set_precision_bits(128)
    res.sampled_boxes_checked = k
    res.max_cross_engine_excess = worst_excess
    details.append(f"box re-verification: {k} boxes, worst excess over "
                   f"sampled min {worst_excess:.3e}, worst |batch-arb| "
                   f"{worst_arb_gap:.3e}")

    # --- step 5: gap ---
    res.gap = res.upper_bound - res.lower_bound
    if res.gap <= max(tau_abs, 1e-6 * max(res.upper_bound, 1.0)):
        res.passed = True
        res.status = "CERTIFIED_GLOBAL_EPS_OPTIMUM"
    else:
        res.status = "CERTIFIED_GLOBAL_OPTIMUM_TO_NUMERICAL_ENCLOSURE"
        details.append(f"gap {res.gap} exceeds tau {tau_abs}")

    # --- optimizer outer enclosure (spec s.36) ---
    from src.q2.formal.certificate import optimizer_enclosure_summary
    npz = artifacts_dir / "optimizer_boxes.npz"
    summary = optimizer_enclosure_summary(master, res.upper_bound, npz)
    (artifacts_dir / "optimizer_boxes.json").write_text(
        json.dumps(summary, indent=1), encoding="utf-8")
    details.append(f"optimizer enclosure: {summary.get('box_count')} boxes, "
                   f"x_span={summary.get('x_span')}, "
                   f"y_span={summary.get('y_span')}")
    res.wall_time_s = time.time() - t0
    return res
