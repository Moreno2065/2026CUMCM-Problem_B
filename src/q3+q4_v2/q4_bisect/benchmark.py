"""Paired Q4 production/bisect benchmark with truth-containment audit."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "baseline" / "code"),
                str(ROOT / "tools")]

from geometry.polygon import contains_point
from learned_search.scheduler import LearnedSearchScheduler
from q4_bisect.scheduler import Q4BisectScheduler
from check_plan_execution import AuditingRunner
import production
import runtime


class TruthAuditingRunner(AuditingRunner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.truth_checks = 0
        self.truth_failures = []

    def _execute(self, mission):
        super()._execute(mission)
        for source in self.simulator.sources:
            channel = self.ks[source.channel]
            if not channel.feasible_region:
                continue
            self.truth_checks += 1
            if not contains_point(channel.feasible_region, source.pos,
                                  eps=1e-6):
                self.truth_failures.append({"step": self._step,
                                            "channel": source.channel})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", nargs="+", type=int,
                        default=[101, 303, 505])
    parser.add_argument("--counts", nargs="+", type=int,
                        default=[10, 13, 16])
    parser.add_argument("--scenario", default="random")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--min-no-shrink", type=int, default=3)
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--detour", type=float, default=250.0)
    parser.add_argument("--tail-only", action="store_true")
    parser.add_argument("--min-known", type=int, default=16)
    parser.add_argument("--min-area", type=float, default=5000.0)
    parser.add_argument("--round-budget", type=int, default=6)
    args = parser.parse_args()

    output = ROOT / "tuning_runs" / "q4_bisect" / args.tag
    result_path = output / "results.json"
    if result_path.exists():
        raise SystemExit("choose a new --tag; results are immutable")
    output.mkdir(parents=True, exist_ok=True)
    runtime.V2GameRunner = TruthAuditingRunner
    rows = []
    for count in args.counts:
        for seed in args.seeds:
            for name, scheduler in (("production", LearnedSearchScheduler),
                                    ("q4-bisect", Q4BisectScheduler)):
                cfg = production.scheduler_kwargs("Q4")
                if name == "q4-bisect":
                    cfg.update(
                        q4_bisect_tail_only=args.tail_only,
                        q4_bisect_min_no_shrink=args.min_no_shrink,
                        q4_bisect_max_rounds=args.max_rounds,
                        q4_bisect_enroute_detour_m=args.detour,
                        q4_bisect_min_known=args.min_known,
                        q4_bisect_min_area_m2=args.min_area,
                        q4_bisect_global_round_budget=args.round_budget)
                report = runtime.run_case(
                    "Q4", seed, count, args.scenario, scheduler,
                    output / f"Q4_{count}_{seed}" / name, cfg)
                runner = AuditingRunner.LAST
                metrics = report["metrics"]
                row = {
                    "policy": name, "n": count, "seed": seed,
                    "complete": bool(report["complete"]),
                    "verifier": bool(report["verifier_all_ok"]),
                    "seconds_per_source": metrics["t_per_source_s"],
                    "total_s": metrics["T_total_virtual"],
                    "move_s": metrics["T_move"],
                    "measure_s": metrics["T_measure"],
                    "switch_s": metrics["T_switch"],
                    "clear_s": metrics["T_clear"],
                    "truth_checks": runner.truth_checks,
                    "truth_failures": list(runner.truth_failures),
                    "audit": dict(runner.audit),
                    "mismatch_samples": list(runner.mismatch_samples),
                    "bisect": dict(getattr(runner.scheduler,
                                           "q4_bisect_stats", {})),
                }
                rows.append(row)
                result_path.write_text(json.dumps(
                    {"args": vars(args), "rows": rows}, indent=2),
                    encoding="utf-8")
                print(f"Q4/{count} seed={seed} {name}: "
                      f"{row['seconds_per_source']:.3f} s/src",
                      flush=True)
                if (not row["complete"] or not row["verifier"] or
                        row["truth_failures"]):
                    return 1
    for count in args.counts:
        prod = [r["seconds_per_source"] for r in rows
                if r["n"] == count and r["policy"] == "production"]
        bisect = [r["seconds_per_source"] for r in rows
                  if r["n"] == count and r["policy"] == "q4-bisect"]
        changes = [b - p for p, b in zip(prod, bisect)]
        print(f"Q4/{count}: {statistics.mean(prod):.3f} -> "
              f"{statistics.mean(bisect):.3f}; "
              f"delta={statistics.mean(changes):+.3f}; "
              f"wins={sum(d < 0 for d in changes)}/{len(changes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
