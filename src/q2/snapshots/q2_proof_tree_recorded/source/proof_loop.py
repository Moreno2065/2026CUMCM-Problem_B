"""Dual-exchange global optimality proof loop for the frozen Q2 model.

Implements spec s.20: reception-cut exchange + adversarial-scenario exchange
over a persistent batched interval branch-and-bound master.  Invariants
(spec s.4, s.21):

* 0 <= L_k <= Q* <= U_k at all times.  L_k is the certified master lower
  bound over D_k (a superset of Crec); U_k only comes from
  ``certify_q2_point_upper_bound`` (the upper edge of the enclosure).
* L is reported as the running max over all historical master bounds (each
  is an independent valid global lower bound), so the reported L is
  monotone by construction.

Symmetry lemma (half domain): the frozen model is invariant under
y -> -y (A1 symmetric about the x-axis, theta1 = 0, eps symmetric), so
Q~(x, -y) = Q~(x, y) and Crec is symmetric; therefore
    inf_{D_k ∩ {y<=0}} M_k <= inf_{Crec ∩ {y<=0}} Q~ = Q*.
The master domain is clipped to y <= 0.  (Verified numerically in
tests_formal/test_proof_invariants.py.)

Loop statuses (spec s.49) and certificate statuses (spec s.2) are used
verbatim.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.q2.formal.interval_master import (
    BatchMaster,
    MasterInconsistencyError,
    ReceptionWitness,
)
from src.q2.formal.master_problem import (
    ScenarioRecord,
    WitnessRecord,
    dump_records,
)
from src.q2.formal.reception_separator import separate_crec
from src.q2.formal.scenario_loss import Scenario, float_point_loss
from src.q2.formal.scenario_recovery import (
    recover_unbounded_scenario,
    recover_worst_physical_scenario,
)
from src.q2.formal.upper_bound import certify_q2_point_upper_bound
from src.q2.formal.ivl_geometry import IvlPoint
from src.q2.formal.rigorous_arithmetic import Ivl, get_precision_bits

ARTIFACTS = Path("src/q2/artifacts/formal")
SNAPSHOTS = Path("snapshots")

TAU_ABS = 0.01


class CertificateHalt(Exception):
    def __init__(self, status: str, detail: str):
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


@dataclass
class LoopConfig:
    incumbent: tuple[float, float] = (805.1110506884, -599.7632926544)
    b0: tuple[float, float, float, float] = (0.0, 2000.0, -1000.0, 0.0)
    g0: tuple[float, float] = (1000.0, 0.0)     # spec s.9 anchor (in A1)
    tau_abs: float = TAU_ABS
    max_iterations: int = 150
    solve_time_budget: float = 25.0
    round_cap: int = 8192
    max_boxes: int = 8_000_000
    quality_tol_max: float = 0.02
    total_time_budget_s: float = 7200.0
    artifacts_dir: Path = ARTIFACTS


@dataclass
class LoopState:
    lower_bound: float = 0.0            # running max of certified master LBs
    upper_bound: float = math.inf
    incumbent: tuple[float, float] | None = None
    incumbent_q: tuple[float, float] | None = None
    iteration: int = 0
    scenario_records: list[ScenarioRecord] = field(default_factory=list)
    witness_records: list[WitnessRecord] = field(default_factory=list)
    status: str = "CONTINUE_SUBDIVIDE"


# ----------------------------------------------------------------------
# snapshot helper (spec s.38, s.53 - manual snapshots, no git)
# ----------------------------------------------------------------------
def make_snapshot(name: str, state: dict, artifacts_dir: Path) -> Path:
    dest = SNAPSHOTS / name
    src_dest = dest / "source"
    art_dest = dest / "artifacts"
    if src_dest.exists():
        shutil.rmtree(src_dest)
    shutil.copytree("src/q2/formal", src_dest,
                    ignore=shutil.ignore_patterns("__pycache__"))
    art_dest.mkdir(parents=True, exist_ok=True)
    for p in artifacts_dir.glob("*.json*"):
        shutil.copy2(p, art_dest / p.name)
    manifest = {}
    for p in sorted(src_dest.rglob("*.py")):
        manifest[str(p.relative_to(src_dest))] = hashlib.sha256(
            p.read_bytes()).hexdigest()
    (dest / "source_manifest_sha256.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8")
    (dest / "certificate_state.json").write_text(
        json.dumps(state, indent=1, default=str), encoding="utf-8")
    (dest / "SNAPSHOT_MANIFEST.md").write_text(
        f"# {name}\n\nfiles: {len(manifest)}\n\nstate: see certificate_state.json\n",
        encoding="utf-8")
    return dest


# ----------------------------------------------------------------------
# seed scenarios (spec s.22)
# ----------------------------------------------------------------------
def _polar(rho, phi_deg):
    p = math.radians(phi_deg)
    return rho * math.cos(p), rho * math.sin(p)


def seed_scenarios(incumbent) -> list[Scenario]:
    out = []
    for phi in (+0.999, -0.999):
        gx, gy = _polar(1499.9, phi)
        for e in (-1.0, 0.0, 1.0):
            out.append(Scenario(gx, gy, e, label=f"seed_corner{phi:+}"))
    gx, gy = _polar(1000.0, 0.0)
    out.append(Scenario(gx, gy, 0.0, label="seed_mid"))
    gx, gy = _polar(1499.999, -1.0)
    out.append(Scenario(gx, gy, -1.0, label="seed_incumbent_worst"))
    gx, gy = _polar(6.0, 0.0)
    out.append(Scenario(gx, gy, 0.0, label="seed_inner"))
    return out


# ----------------------------------------------------------------------
# the loop
# ----------------------------------------------------------------------
def run_proof_loop(cfg: LoopConfig) -> LoopState:
    t0 = time.time()
    cfg.artifacts_dir.mkdir(parents=True, exist_ok=True)
    log_path = cfg.artifacts_dir / "proof_loop.jsonl"
    logf = open(log_path, "w", encoding="utf-8")

    def log(rec: dict):
        logf.write(json.dumps(rec, default=str) + "\n")
        logf.flush()

    state = LoopState()

    # --- certified incumbent upper bound (spec s.11) ---
    ub0 = certify_q2_point_upper_bound(*cfg.incumbent)
    if ub0.status == "ALL_NEAR_ZERO":
        state.status = "CERTIFIED_EXACT_ZERO_ALL_NEAR"
        state.upper_bound = 0.0
        state.lower_bound = 0.0
        state.incumbent = cfg.incumbent
        return state
    if ub0.status != "CERTIFIED":
        raise CertificateHalt("BLOCKED_WITNESS_RECOVERY",
                              f"initial incumbent not certified: {ub0.status} "
                              f"{ub0.detail}")
    U = ub0.upper_float
    state.upper_bound = U
    state.incumbent = cfg.incumbent
    state.incumbent_q = (ub0.q_lo.lower_float(), U)
    (cfg.artifacts_dir / "incumbent_upper_bound.json").write_text(
        json.dumps({
            "incumbent_S2": [repr(cfg.incumbent[0]), repr(cfg.incumbent[1])],
            "q_interval_decimal": [ub0.q_lo.to_decimal_enclosure()[0],
                                   ub0.q_hi.to_decimal_enclosure()[1]],
            "q_lo": ub0.q_lo.lower_float(),
            "q_hi": ub0.q_hi.upper_float(),
            "worst_beta_interval_rad": ub0.worst_beta_interval,
            "candidate_type": ub0.candidate_type,
            "all_near": ub0.all_near,
            "crec_margin_lower": ub0.crec_margin_lower,
            "beta_pieces": ub0.beta_pieces,
            "precision_bits": ub0.precision_bits,
        }, indent=1), encoding="utf-8")
    make_snapshot("q2_formal_ub_pass",
                  {"U": U, "incumbent": cfg.incumbent}, cfg.artifacts_dir)

    # --- master construction (spec s.9) ---
    master = BatchMaster(b0=cfg.b0, upper_bound=U)
    g0 = cfg.g0
    master.add_witness(ReceptionWitness(g0[0], g0[1],
                                        max(1000.0, math.hypot(*g0))))
    state.witness_records.append(
        WitnessRecord(g0[0], g0[1], max(1000.0, math.hypot(*g0)), -1,
                      0.0))
    witness_keys = {_wkey(g0[0], g0[1])}
    scenario_keys: set[tuple] = set()
    for s in seed_scenarios(cfg.incumbent):
        master.add_scenario(s, refresh_band=None)
        state.scenario_records.append(
            ScenarioRecord(s.gx, s.gy, s.e_deg, s.label, -1))
        scenario_keys.add(_skey(s))

    def mk_float(x, y):
        return max(float_point_loss(x, y, s) for s in master.scenarios)

    lb_history: list[float] = []
    stall_count = 0

    for it in range(cfg.max_iterations):
        state.iteration = it
        quality_tol = min(cfg.quality_tol_max,
                          max(0.2 * (U - state.lower_bound), cfg.tau_abs / 4))
        try:
            stats = master.solve(
                tol=0.9 * cfg.tau_abs, round_cap=cfg.round_cap,
                max_boxes=cfg.max_boxes, time_budget_s=cfg.solve_time_budget,
                quality_tol=quality_tol, mk_float=mk_float)
        except MasterInconsistencyError as exc:
            raise CertificateHalt("CRITICAL_CERTIFICATE_INCONSISTENCY",
                                  str(exc))
        L_now = master.lower_bound
        if L_now > U:
            raise CertificateHalt(
                "CRITICAL_CERTIFICATE_INCONSISTENCY",
                f"master LB {L_now} > U {U}")
        mono_violation = L_now < state.lower_bound - 1e-9
        state.lower_bound = max(state.lower_bound, L_now)
        lb_history.append(state.lower_bound)

        gap = U - state.lower_bound
        cands = master.best_candidates(24)
        ranked = sorted(((mk_float(*c), c) for c in cands))
        best_mk, best_c = ranked[0]

        rec = {
            "iteration": it,
            "lower_bound": state.lower_bound,
            "upper_bound": U,
            "absolute_gap": gap,
            "relative_gap": gap / max(U, 1.0),
            "reception_witness_count": len(state.witness_records),
            "scenario_count": len(state.scenario_records),
            "master_box_count": stats.live_boxes,
            "incumbent": list(state.incumbent),
            "master_candidate": list(best_c),
            "candidate_mk_float": best_mk,
            "monotonicity_violation": mono_violation,
            "precision_bits": get_precision_bits(),
            "status": "CONTINUE",
        }

        if gap <= cfg.tau_abs:
            rec["status"] = "ENTER_FINAL_REPLAY"
            log(rec)
            state.status = "ENTER_FINAL_REPLAY"
            break

        acted = False
        cut_type = "none"
        for cand_mk, cand in ranked:
            sep = separate_crec(
                IvlPoint(Ivl.from_float(cand[0]), Ivl.from_float(cand[1])))
            if sep.status == "UNKNOWN":
                continue
            if sep.status == "FAIL":
                wkey = _wkey(sep.witness[0], sep.witness[1])
                if wkey in witness_keys:
                    master.split_lowest_near(cand[0], cand[1], radius=2.0,
                                             m=1024)
                    cut_type = "refine_duplicate_witness"
                else:
                    witness_keys.add(wkey)
                    r = max(1000.0, math.hypot(*sep.witness))
                    master.add_witness(
                        ReceptionWitness(sep.witness[0], sep.witness[1], r))
                    state.witness_records.append(
                        WitnessRecord(sep.witness[0], sep.witness[1], r, it,
                                      sep.witness_violation.lower_float()))
                    cut_type = "reception"
                acted = True
                break
            # PASS: candidate certifiably in Crec
            ub = certify_q2_point_upper_bound(*cand, check_crec=False)
            if ub.status == "ALL_NEAR_ZERO":
                state.status = "CERTIFIED_EXACT_ZERO_ALL_NEAR"
                state.incumbent = cand
                state.upper_bound = 0.0
                rec["status"] = "CERTIFIED_EXACT_ZERO_ALL_NEAR"
                rec["new_cut_type"] = "all_near"
                log(rec)
                return state
            if ub.status == "UNBOUNDED":
                ub_rec = recover_unbounded_scenario(*cand)
                if ub_rec is not None and ub_rec.valid:
                    s = ub_rec.scenario
                    if _skey(s) not in scenario_keys:
                        scenario_keys.add(_skey(s))
                        master.add_scenario(s)
                        state.scenario_records.append(
                            ScenarioRecord(s.gx, s.gy, s.e_deg, s.label, it,
                                           ub_rec.support_type, ub_rec.eta))
                        cut_type = "objective_unbounded"
                        acted = True
                        break
                continue
            if ub.status != "CERTIFIED":
                continue
            if ub.upper_float < U:
                U = ub.upper_float
                state.upper_bound = U
                state.incumbent = cand
                state.incumbent_q = (ub.q_lo.lower_float(), U)
                master.set_upper_bound(U)
            rec_eta = min(0.1 * (U - state.lower_bound), 1e-4)
            recov = recover_worst_physical_scenario(
                cand[0], cand[1], ub.worst_beta_interval, ub.upper_float,
                eta_target=max(rec_eta, 1e-6))
            if recov.valid:
                s = recov.scenario
                if _skey(s) in scenario_keys:
                    master.split_lowest_near(cand[0], cand[1], radius=2.0,
                                             m=1024)
                    cut_type = "refine_duplicate_scenario"
                else:
                    scenario_keys.add(_skey(s))
                    master.add_scenario(s)
                    state.scenario_records.append(
                        ScenarioRecord(s.gx, s.gy, s.e_deg, s.label, it,
                                       recov.support_type, recov.eta))
                    cut_type = "objective_scenario"
                acted = True
                break
        if not acted:
            master.split_lowest_near(best_c[0], best_c[1], radius=5.0,
                                     m=2048)
            cut_type = "refine_fallback"

        # stall diagnosis (spec s.34)
        if len(lb_history) >= 6:
            recent = lb_history[-1] - lb_history[-6]
            if recent < 1e-3 * max(gap, 1e-9):
                stall_count += 1
                rec["stall_diagnosis"] = {
                    "lb_gain_5iters": recent,
                    "lowest_boxes": master.best_candidates(5),
                    "scenarios": len(master.scenarios),
                    "witnesses": len(master.witnesses),
                }
            else:
                stall_count = 0

        rec["candidate_in_crec"] = cut_type in (
            "objective_scenario", "objective_unbounded",
            "refine_duplicate_scenario")
        rec["new_cut_type"] = cut_type
        log(rec)
        print(f"it={it} L={state.lower_bound:.6f} U={U:.6f} "
              f"gap={gap:.5f} cut={cut_type} live={stats.live_boxes} "
              f"t={time.time()-t0:.0f}s", flush=True)

        if time.time() - t0 > cfg.total_time_budget_s:
            state.status = "INCOMPLETE_CERTIFICATE_TIMEOUT"
            break
    else:
        state.status = "INCOMPLETE_CERTIFICATE_TIMEOUT"

    logf.close()
    dump_records(state.scenario_records, state.witness_records,
                 cfg.artifacts_dir / "master_cuts.json")
    (cfg.artifacts_dir / "master_lower_bound.json").write_text(json.dumps({
        "lower_bound": state.lower_bound,
        "upper_bound": state.upper_bound,
        "absolute_gap": state.upper_bound - state.lower_bound,
        "scenario_count": len(state.scenario_records),
        "reception_witness_count": len(state.witness_records),
        "live_boxes": master.lb.size,
        "status": state.status,
    }, indent=1), encoding="utf-8")
    return state


def _wkey(gx: float, gy: float) -> tuple:
    return (round(gx, 9), round(gy, 9))


def _skey(s: Scenario) -> tuple:
    return (round(s.gx, 9), round(s.gy, 9), round(s.e_deg, 9))
