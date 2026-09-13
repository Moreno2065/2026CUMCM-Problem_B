"""Offline choice audit: is there value left on the table at a decision?

For a sampled decision step, every candidate action is executed (the episode is
re-run with that action forced at that step, then the normal policy continues)
and the realised total cost is recorded.  The policy's own choice is compared
with the best candidate, so the answer is in real seconds of the real ledger,
not in the policy's own score units.

This is the check the review asked for before any training: if forcing the best
candidate at a decision is much cheaper than what the policy chose, the action
*set* contains better options and the bottleneck is the value model; if even
the best candidate is no better, the bottleneck is elsewhere.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "baseline" / "code"))

from runtime import run_case                      # noqa: E402
from production import scheduler_kwargs           # noqa: E402
from learned_search.scheduler import LearnedSearchScheduler   # noqa: E402


class ForcingScheduler(LearnedSearchScheduler):
    """Scheduler that can be pinned to one joint candidate at one step."""

    def __init__(self, *args, force_step=None, force_variant=None,
                 record_steps=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.force_step = force_step
        self.force_variant = force_variant
        self.record_steps = record_steps if record_steps is not None else []
        self.step_index = 0
        self.recorded = []
        self.total = None

    def decide(self, ks, position, current_channel):
        self.step_index += 1
        mission = super().decide(ks, position, current_channel)
        joint_rows = getattr(self, "_last_joint_rows", None) or []
        is_joint = bool(mission is not None
                        and mission.meta.get("interleaved"))
        if self.step_index in self.record_steps and joint_rows:
            self.recorded.append({
                "step": self.step_index,
                "chosen": mission.meta.get("scan_variant") if is_joint else None,
                "policy_kind": mission.kind if mission is not None else None,
                "candidates": [
                    {k: v for k, v in row.items() if k != "mission"}
                    for row in joint_rows
                ],
            })
        if (self.force_step is not None and self.step_index == self.force_step
                and self.force_variant is not None and joint_rows):
            if self.force_variant == "certificate":
                # Alternative stop: take the next finite certificate point.
                if self._coverage_index < len(self._coverage_points):
                    mission = self._coverage_scan(ks)
                    return mission
            forced = next((row for row in joint_rows
                           if row["variant"] == self.force_variant), None)
            if forced is not None:
                mission = copy.deepcopy(forced["mission"])
                mission.meta["interleaved"] = True
        return mission


def run_once(mode, seed, n, scenario, force_step=None, force_variant=None,
             record_steps=None):
    """Run one episode, optionally forcing a variant at one step."""
    cfg = scheduler_kwargs(mode)
    cfg.update({"q3_interleave": True, "joint_action": True,
                "active_scan_angle_gate_deg": 30.0})
    holder = {}

    class Wrapped(ForcingScheduler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, force_step=force_step,
                             force_variant=force_variant,
                             record_steps=record_steps, **kwargs)
            holder["scheduler"] = self

    out = ROOT / "tuning_runs" / "choice_audit" / (
        "%s_%d_%s" % (mode, seed, "forced" if force_step else "base"))
    report = run_case(mode, seed, n, scenario, Wrapped, out,
                      scheduler_kwargs=cfg)
    return report, holder.get("scheduler")


def sweep(cases, max_steps_per_case=4, variants=("primary", "discover", "full",
                                                 "certificate")):
    """Audit several cases and report the one-step oracle improvement.

    For each case the base run is compared with runs that force an alternative
    action at one decision.  The gap ``base - min(forced)`` is the cost that a
    perfect one-step chooser would have recovered at that decision, measured in
    the real ledger rather than in policy score units.
    """
    summary = []
    for mode, n, seed in cases:
        scenario = "random" if mode == "Q3" else "mixed"
        base_report, scheduler = run_once(mode, seed, n, scenario,
                                          record_steps=list(range(5, 90)))
        base = base_report["metrics"]["T_total_virtual"]
        picks = []
        for row in scheduler.recorded:
            if not row.get("chosen"):
                continue
            if max(c["measures"] for c in row["candidates"]) > 1:
                picks.append(row["step"])
        picks = picks[:max_steps_per_case]
        print("%s/%d seed %d: base %.0f s (%.2f s/source), auditable steps %s"
              % (mode, n, seed, base,
                 base_report["metrics"]["t_per_source_s"], picks or "none"))
        for step in picks:
            costs = {}
            for variant in variants:
                report, _ = run_once(mode, seed, n, scenario, force_step=step,
                                     force_variant=variant)
                costs[variant] = report["metrics"]["T_total_virtual"]
            best = min(costs, key=costs.get)
            gap = base - costs[best]
            summary.append({"mode": mode, "n": n, "seed": seed, "step": step,
                            "base": base, "best": best,
                            "best_cost": costs[best], "gap": gap,
                            "costs": costs})
            print("   step %-3d %s -> best %-11s %7.0f s (gap %+6.0f s)"
                  % (step, " ".join("%s=%.0f" % (k, v)
                                    for k, v in costs.items()),
                     best, costs[best], gap))
    if summary:
        mean_gap = sum(row["gap"] for row in summary) / len(summary)
        share = sum(row["gap"] / row["base"] for row in summary) / len(summary)
        print("audited %d decisions; mean one-step oracle gain %.0f s "
              "(%.1f%% of the run)" % (len(summary), mean_gap, 100.0 * share))
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="Q3")
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--n", type=int, default=16)
    parser.add_argument("--steps", default="10,30,50")
    parser.add_argument("--variants", default="primary,active,discover,full")
    parser.add_argument("--sweep", action="store_true",
                        help="audit several cases and print the aggregate gap")
    parser.add_argument("--cases", default="Q3:16:101,Q3:16:303,Q3:10:101")
    parser.add_argument("--max-steps", type=int, default=4)
    args = parser.parse_args()
    if args.sweep:
        cases = []
        for item in args.cases.split(","):
            mode, n, seed = item.split(":")
            cases.append((mode, int(n), int(seed)))
        summary = sweep(cases, args.max_steps)
        out = ROOT / "tuning_runs" / "choice_audit_summary.json"
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=1)
                       + "\n", encoding="utf-8")
        print("written %s" % out)
        return 0
    scenario = "random" if args.mode == "Q3" else "mixed"
    steps = [int(s) for s in args.steps.split(",")]
    variants = args.variants.split(",")

    base_report, scheduler = run_once(args.mode, args.seed, args.n, scenario,
                                      record_steps=steps)
    base_cost = base_report["metrics"]["T_total_virtual"]
    print("mode %s seed %d N %d: policy total %.1f s (%.2f s/source)" %
          (args.mode, args.seed, args.n, base_cost,
           base_report["metrics"]["t_per_source_s"]))
    recorded = {row["step"]: row for row in (scheduler.recorded if scheduler
                                             else [])}
    total_regret = 0.0
    audited = 0
    for step in steps:
        row = recorded.get(step)
        if row is None or not row["candidates"]:
            continue
        if row.get("chosen") is None:
            # The policy took the certificate stop here, so there is no joint
            # scan-set choice to audit at this step.
            print("  step %-4d policy took the certificate stop (no joint "
                  "choice to audit)" % step)
            continue
        chosen = row["chosen"]
        audited += 1
        print("  step %-4d policy chose %s   (candidates: %s)" %
              (step, chosen, ", ".join(c["variant"] for c in row["candidates"])))
        costs = {}
        for variant in variants:
            report, _ = run_once(args.mode, args.seed, args.n, scenario,
                                 force_step=step, force_variant=variant)
            costs[variant] = report["metrics"]["T_total_virtual"]
        best = min(costs, key=costs.get)
        regret = costs[chosen] - costs[best] if chosen in costs else float("nan")
        total_regret += max(0.0, regret)
        print("      realised totals: %s" %
              ", ".join("%s=%.0f" % (k, v) for k, v in costs.items()))
        print("      best %s (%.0f s), policy choice %s (%.0f s), regret %+.0f s"
              % (best, costs[best], chosen, costs.get(chosen, float("nan")),
                 regret))
    if audited:
        print("total regret over %d audited steps: %.0f s (%.1f%% of the run)" %
              (audited, total_regret, 100.0 * total_regret / base_cost))
    else:
        print("no auditable joint steps in %s" % steps)


if __name__ == "__main__":
    main()
