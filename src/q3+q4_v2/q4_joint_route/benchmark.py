"""Paired Q4 production/joint-route benchmark with ledger verification."""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "baseline" / "code"),
                str(ROOT / "tools")]

import production
import runtime
from check_plan_execution import AuditingRunner
from learned_search.scheduler import LearnedSearchScheduler
from q4_joint_route.scheduler import Q4JointRouteScheduler


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", nargs="+", type=int, default=[101, 303, 505])
    p.add_argument("--counts", nargs="+", type=int, default=[10, 13, 16])
    p.add_argument("--scenario", default="mixed")
    p.add_argument("--tag", required=True)
    p.add_argument("--policies", nargs="+", choices=["production", "joint"],
                   default=["production", "joint"])
    p.add_argument("--active-attempts", type=int, default=3)
    p.add_argument("--optical-cover-points", type=int, default=0)
    p.add_argument("--share-coverage", action="store_true")
    p.add_argument("--coverage-active-limit", type=int, default=3)
    p.add_argument("--coverage-min-mec", type=float, default=80.0)
    p.add_argument("--tail", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--route-ready", action="store_true")
    p.add_argument("--include-nbv", action="store_true")
    args = p.parse_args()

    out = ROOT / "tuning_runs" / "q4_joint_route" / args.tag
    out.mkdir(parents=True, exist_ok=True)
    result_path = out / "results.json"
    if result_path.exists():
        raise SystemExit("Choose a new --tag; results are immutable")
    sources = [ROOT / "runtime.py", ROOT / "production.py",
               ROOT / "learned_search" / "scheduler.py",
               ROOT / "q4_joint_route" / "scheduler.py"]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sources}
    runtime.V2GameRunner = AuditingRunner
    rows = []
    for n in args.counts:
        for seed in args.seeds:
            for name in args.policies:
                cls = (LearnedSearchScheduler if name == "production"
                       else Q4JointRouteScheduler)
                cfg = production.scheduler_kwargs("Q4")
                if name == "joint":
                    cfg.update(
                        q4jr_active_attempts=args.active_attempts,
                        q4jr_optical_cover_points=args.optical_cover_points,
                        q4jr_share_coverage=args.share_coverage,
                        q4jr_coverage_active_limit=args.coverage_active_limit,
                        q4jr_coverage_min_mec=args.coverage_min_mec,
                        q4jr_tail_enabled=args.tail,
                        q4jr_route_ready=args.route_ready,
                        q4jr_include_nbv=args.include_nbv)
                target = out / f"Q4_{n}_{seed}" / name
                report = runtime.run_case("Q4", seed, n, args.scenario,
                                          cls, target, cfg)
                runner = AuditingRunner.LAST
                m = report["metrics"]
                row = dict(policy=name, n=n, seed=seed,
                           complete=bool(report["complete"]),
                           verifier=bool(report["verifier_all_ok"]),
                           cleared=m["cleared_count"],
                           seconds_per_source=m["t_per_source_s"],
                           total_s=m["T_total_virtual"],
                           move_s=m["T_move"], measure_s=m["T_measure"],
                           switch_s=m["T_switch"], clear_s=m["T_clear"],
                           wall_s=m["wall_clock_s"], audit=dict(runner.audit),
                           anomalies=list(runner.scheduler.anomalies),
                           q4jr=getattr(runner.scheduler, "q4jr_stats", {}))
                rows.append(row)
                result_path.write_text(json.dumps(
                    dict(args=vars(args), code_sha256=hashes, rows=rows),
                    indent=2), encoding="utf-8")
                print(f"Q4/{n} seed={seed} {name}: "
                      f"{row['seconds_per_source']:.3f} s/src "
                      f"complete={row['complete']} verifier={row['verifier']} "
                      f"audit={row['audit']} stats={row['q4jr']}", flush=True)
                if (not row["complete"] or not row["verifier"]
                        or row["cleared"] != n or row["audit"]["mismatch"]):
                    return 1
    for n in args.counts:
        for name in args.policies:
            vals = [r["seconds_per_source"] for r in rows
                    if r["n"] == n and r["policy"] == name]
            print(f"Q4/{n} {name}: mean={statistics.mean(vals):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
