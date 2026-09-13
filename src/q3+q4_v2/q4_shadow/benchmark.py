"""Paired Q4 benchmark for the selective fast-main/shadow controller."""
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
from q4_shadow.scheduler import Q4ShadowScheduler
from check_plan_execution import AuditingRunner
import production
import runtime


class TruthAuditingRunner(AuditingRunner):
    """Check that every live source stays inside its hard feasible polygon."""

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


def _mean(rows, policy, count):
    values = [row["seconds_per_source"] for row in rows
              if row["policy"] == policy and row["n"] == count]
    return statistics.mean(values)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", nargs="+", type=int,
                        default=[112233, 445566, 778899])
    parser.add_argument("--counts", nargs="+", type=int,
                        default=[10, 13, 16])
    parser.add_argument("--scenario", default="mixed")
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()

    output = ROOT / "tuning_runs" / "q4_shadow" / args.tag
    result_path = output / "results.json"
    if result_path.exists():
        raise SystemExit("choose a new --tag; results are immutable")
    output.mkdir(parents=True, exist_ok=True)
    runtime.V2GameRunner = TruthAuditingRunner
    policies = (
        ("production", LearnedSearchScheduler),
        ("q4-bisect", Q4BisectScheduler),
        ("q4-shadow", Q4ShadowScheduler),
    )
    rows = []
    for count in args.counts:
        for seed in args.seeds:
            for name, scheduler in policies:
                cfg = production.scheduler_kwargs("Q4")
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
                    "bisect": dict(getattr(
                        runner.scheduler, "q4_bisect_stats", {})),
                    "shadow": dict(getattr(
                        runner.scheduler, "shadow_stats", {})),
                }
                rows.append(row)
                result_path.write_text(json.dumps(
                    {"args": vars(args), "rows": rows}, indent=2),
                    encoding="utf-8")
                print(f"Q4/{count} seed={seed} {name}: "
                      f"{row['seconds_per_source']:.3f} s/src", flush=True)
                if (not row["complete"] or not row["verifier"] or
                        row["truth_failures"] or row["audit"]["mismatch"]):
                    return 1

    for count in args.counts:
        prod = _mean(rows, "production", count)
        bisect = _mean(rows, "q4-bisect", count)
        shadow = _mean(rows, "q4-shadow", count)
        paired = {}
        for policy in ("q4-bisect", "q4-shadow"):
            deltas = []
            for seed in args.seeds:
                p = next(row["seconds_per_source"] for row in rows
                         if row["n"] == count and row["seed"] == seed and
                         row["policy"] == "production")
                value = next(row["seconds_per_source"] for row in rows
                             if row["n"] == count and row["seed"] == seed and
                             row["policy"] == policy)
                deltas.append(value - p)
            paired[policy] = {
                "mean_delta": statistics.mean(deltas),
                "wins": sum(delta < 0 for delta in deltas),
                "regressions": sum(delta > 0 for delta in deltas),
            }
        print(f"Q4/{count}: {prod:.3f} -> {bisect:.3f} -> "
              f"{shadow:.3f}; shadow delta={shadow-prod:+.3f}")
        print(json.dumps(paired, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
