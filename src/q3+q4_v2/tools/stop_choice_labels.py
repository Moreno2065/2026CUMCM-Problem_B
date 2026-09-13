"""Collect labels for the stop choice: certificate point or live-channel work?

At each joint decision the policy may either take the next finite certificate
point or work on a live channel.  This script forces each alternative at that
step (re-running the episode, with the normal policy afterwards) and records
the realised total cost together with the observable state features at the
decision.  The result is a small labelled set: which choice was actually
cheaper, and what could have been seen at the time.

The point is to test whether an *observable* signal separates the two choices
before any value model is trained.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "baseline" / "code"))

from runtime import run_case                      # noqa: E402
from production import scheduler_kwargs           # noqa: E402
from learned_search.scheduler import LearnedSearchScheduler   # noqa: E402
from state.channel_state import ChannelStatus     # noqa: E402


class LabelScheduler(LearnedSearchScheduler):
    """Records the state at every joint decision and can force one choice."""

    def __init__(self, *args, force_step=None, force_choice=None,
                 record=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.force_step = force_step
        self.force_choice = force_choice
        self.record = record
        self.step_index = 0
        self.records = []

    def decide(self, ks, position, current_channel):
        self.step_index += 1
        mission = super().decide(ks, position, current_channel)
        rows = getattr(self, "_last_joint_rows", None) or []
        if not rows or not (self.q3_interleave and self.joint_action):
            return mission
        joint_won = bool(mission is not None
                         and mission.meta.get("interleaved"))
        ring_point = None
        if (self._coverage_index < len(self._coverage_points)
                and ks.unknown):
            ring_point = self._coverage_points[self._coverage_index]
        if self.record and ring_point is not None:
            work = min(rows, key=lambda row: row["score"])["mission"]
            confirmed = (len(ks.active) + len(ks.ready) + len(ks.cleared))
            self.records.append({
                "step": self.step_index,
                "joint_won": joint_won,
                "coverage_index": int(self._coverage_index),
                "n_unknown": len(ks.unknown),
                "n_active": len(ks.active),
                "n_ready": len(ks.ready),
                "n_confirmed": confirmed,
                "dist_work": round(math.dist(position, work.target), 1),
                "dist_ring": round(math.dist(position, ring_point), 1),
                "dist_ratio": round(math.dist(position, work.target)
                                    / max(1e-9, math.dist(position, ring_point)),
                                    3),
                "ring_work_ratio": round(math.dist(position, ring_point)
                                         / max(1e-9, math.dist(position,
                                                               work.target)), 3),
                "mean_mec_active": round(statistics.mean(
                    [c.mec_radius for c in ks.active]) if ks.active else 0.0, 1),
            })
        if (self.force_step is not None and self.step_index == self.force_step
                and self.force_choice == "certificate"
                and self._coverage_index < len(self._coverage_points)):
            forced = self._coverage_scan(ks)
            if forced is not None:
                return forced
        return mission


def run_once(mode, seed, n, scenario, force_step=None, force_choice=None,
             record=False):
    cfg = scheduler_kwargs(mode)
    cfg.update({"q3_interleave": True, "joint_action": True,
                "active_scan_angle_gate_deg": 30.0})
    holder = {}

    class Wrapped(LabelScheduler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, force_step=force_step,
                             force_choice=force_choice, record=record,
                             **kwargs)
            holder["scheduler"] = self

    out = ROOT / "tuning_runs" / "stop_labels" / (
        "%s_%d_%s" % (mode, seed, "forced" if force_step else "base"))
    report = run_case(mode, seed, n, scenario, Wrapped, out,
                      scheduler_kwargs=cfg)
    return report, holder.get("scheduler")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="Q3:16,Q3:13,Q3:10")
    parser.add_argument("--seeds", default="101,202,303,404,505")
    parser.add_argument("--max-steps", type=int, default=5)
    parser.add_argument("--out", default="tuning_runs/stop_choice_labels.jsonl")
    args = parser.parse_args()
    cases = []
    for item in args.cases.split(","):
        mode, n = item.split(":")
        cases.append((mode, int(n)))
    seeds = [int(s) for s in args.seeds.split(",")]

    rows = []
    for mode, n in cases:
        for seed in seeds:
            scenario = "random" if mode == "Q3" else "mixed"
            base_report, scheduler = run_once(mode, seed, n, scenario,
                                              record=True)
            base = base_report["metrics"]["T_total_virtual"]
            steps = [row["step"] for row in scheduler.records]
            # sample decisions spread over the run
            if len(steps) > args.max_steps:
                stride = len(steps) / float(args.max_steps)
                steps = [steps[int(i * stride)] for i in range(args.max_steps)]
            for step in steps:
                record = next((r for r in scheduler.records
                               if r["step"] == step), None)
                if record is None:
                    continue
                forced_report, _ = run_once(mode, seed, n, scenario,
                                            force_step=step,
                                            force_choice="certificate")
                forced = forced_report["metrics"]["T_total_virtual"]
                row = dict(record)
                row.update({"mode": mode, "n": n, "seed": seed,
                            "base": base, "certificate": forced,
                            "certificate_better": forced < base - 1e-9,
                            "certificate_gain": base - forced})
                rows.append(row)
            print("%s/%d seed %d: base %.0f s, %d joint decisions, %d audited"
                  % (mode, n, seed, base, len(scheduler.records), len(steps)),
                  flush=True)
    out = ROOT / args.out
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    better = [r for r in rows if r["certificate_better"]]
    print("\nlabelled decisions: %d ; certificate better in %d (%.0f%%)" %
          (len(rows), len(better), 100.0 * len(better) / max(1, len(rows))))
    if rows:
        print("mean gain when certificate wins: %+.0f s ; mean loss when it "
              "loses: %+.0f s" % (
                  statistics.mean(r["certificate_gain"] for r in better)
                  if better else 0.0,
                  statistics.mean(r["certificate_gain"] for r in rows
                                  if not r["certificate_better"])
                  if len(better) != len(rows) else 0.0))
    print("written %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
