"""Does the first-step reference plan cost separate the "long tour" episodes?

t29 has to replace an offline quantity (a run's realised ``T_move``) with an
online one (the production-order reference plan cost computed at the first
planning step).  This read-only probe checks whether that substitution can work
at all, using traces that already exist: any run whose ``decision_trace.jsonl``
contains ``order_plan`` steps records ``planned_cost_s`` / ``reference_cost_s``
per planning step.

Target set: runs whose realised ``T_move`` exceeds 4000 s (the only threshold in
the gate screen that was non-positive on all 5 evidence sets x 3 cells).

Usage: python -X utf8 tools/order_gate_calib_probe.py
"""

from __future__ import annotations

import glob
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET_MOVE = 4000.0


def probe(path: Path):
    trace = path / "decision_trace.jsonl"
    report = path / "run_report.json"
    if not trace.exists() or not report.exists():
        return None
    first = None
    n_steps = 0
    for line in trace.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("policy_mode") != "order_plan":
            continue
        n_steps += 1
        ref = r.get("reference_cost_s")
        if ref is None:
            continue
        if first is None or r.get("step", 1 << 30) < first[0]:
            first = (r.get("step"), r.get("virtual_time"), float(ref),
                     r.get("tasks"), r.get("plan_cost_s"))
    if first is None:
        return None
    rep = json.loads(report.read_text(encoding="utf-8"))
    met = rep.get("metrics") or {}
    return {
        "first_step": first[0], "first_vtime": first[1],
        "first_ref_s": first[2], "tasks": first[3], "plan_cost_s": first[4],
        "T_move": met.get("T_move") or 0.0,
        "tps": met.get("t_per_source_s") or 0.0,
        "n_plan_steps": n_steps,
    }


def main() -> int:
    rows = []
    for d in sorted(glob.glob(str(ROOT / "tuning_runs/ab_probe/*/Q3_*_*"))):
        p = Path(d)
        arm = p.parent.name
        mode_n = p.name.split("_")
        info = probe(p)
        if info:
            info.update({"arm": arm, "cell": f"Q3/{mode_n[1]}",
                         "seed": mode_n[2], "run": p.name})
            rows.append(info)
    print(f"runs with an order_plan trace: {len(rows)}")
    if not rows:
        return 0
    by_cell = {}
    for r in rows:
        by_cell.setdefault(r["cell"], []).append(r)
    for cell, sub in sorted(by_cell.items()):
        print(f"\n== {cell} ({len(sub)} runs) ==")
        for r in sorted(sub, key=lambda x: x["T_move"] or 0):
            flag = "TARGET" if (r["T_move"] or 0) > TARGET_MOVE else "      "
            print(f"  {r['arm'][:22]:22} {r['seed']:>7} first_ref {r['first_ref_s']:8.1f} "
                  f"tasks {str(r['tasks']):>3} steps {r['n_plan_steps']:>3} "
                  f"T_move {r['T_move']:8.1f} {flag}")
    print("\n== separation: first_ref_s threshold vs target (T_move > "
          f"{TARGET_MOVE:g}) ==")
    for cell, sub in sorted(by_cell.items()):
        vals = sorted(r["first_ref_s"] for r in sub)
        if len(vals) < 4:
            continue
        best = None
        for thr in [vals[i] for i in range(len(vals))]:
            tp = sum(1 for r in sub if r["first_ref_s"] > thr and (r["T_move"] or 0) > TARGET_MOVE)
            fp = sum(1 for r in sub if r["first_ref_s"] > thr and (r["T_move"] or 0) <= TARGET_MOVE)
            fn = sum(1 for r in sub if r["first_ref_s"] <= thr and (r["T_move"] or 0) > TARGET_MOVE)
            tn = len(sub) - tp - fp - fn
            jac = tp / (tp + fp + fn) if (tp + fp + fn) else 0.0
            if best is None or jac > best[1]:
                best = (thr, jac, tp, fp, fn, tn)
        thr, jac, tp, fp, fn, tn = best
        print(f"  {cell}: best thr {thr:8.1f} Jaccard {jac:.3f} "
              f"(tp {tp} fp {fp} fn {fn} tn {tn}); targets "
              f"{sum(1 for r in sub if (r['T_move'] or 0) > TARGET_MOVE)}/{len(sub)}")
    corr_num = [(r["first_ref_s"], r["T_move"]) for r in rows if r["T_move"]]
    n = len(corr_num)
    mx = statistics.mean(x for x, _ in corr_num)
    my = statistics.mean(y for _, y in corr_num)
    sx = statistics.pstdev(x for x, _ in corr_num)
    sy = statistics.pstdev(y for _, y in corr_num)
    cov = sum((x - mx) * (y - my) for x, y in corr_num) / n
    print(f"\noverall corr(first_ref_s, T_move) = {cov / (sx * sy):+.3f} (n={n})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
