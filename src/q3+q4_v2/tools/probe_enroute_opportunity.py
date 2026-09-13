"""Is there anything for Q3 "en-route clearing" to do?

``rolling_enroute_detour_m`` inserts a detour (<= X m) to clear a *pending* READY
source while travelling to the next **coverage** stop.  ROUND1 section 15.1 warns
that "a source becomes READY precisely because the robot is standing next to it,
so clearing immediately is already near-optimal" -- if that is right, there is
rarely a pending READY source at the moment a coverage leg starts and the
mechanism cannot fire on Q3.

This probe measures exactly that: at every moment the robot starts a leg toward a
coverage (certificate) stop, how many channels are in READY status?

Usage: python -X utf8 tools/probe_enroute_opportunity.py [--mode Q3]
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="tuning_runs/ab_probe/production")
    ap.add_argument("--mode", default="Q3")
    args = ap.parse_args()

    per_cell = {}
    for d in sorted(glob.glob(str(ROOT / args.root / f"{args.mode}_*_*"))):
        run = Path(d)
        acts = run / "actions.csv"
        hist = run / "channel_state_history.jsonl"
        if not (acts.exists() and hist.exists()):
            continue
        n = int(run.name.split("_")[1])
        states = {}
        for line in hist.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            chans = rec.get("channels") or {}
            states[rec.get("step")] = {
                "ready": sum(1 for c in chans.values()
                             if str(c.get("status")) == "READY"),
                "active": sum(1 for c in chans.values()
                              if str(c.get("status")) == "ACTIVE"),
                "unknown": sum(1 for c in chans.values()
                               if str(c.get("status")) == "UNKNOWN"),
            }
        steps = sorted(states)
        cov_ready = []
        all_ready = []
        with acts.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                try:
                    st = int(float(r["step"] or 0))
                except (TypeError, ValueError):
                    continue
                snap = states.get(st) or (states.get(min(steps, key=lambda s: abs(s - st))) if steps else None)
                if not snap:
                    continue
                all_ready.append(snap["ready"])
                if (r.get("reason_code") or "") in ("coverage", "certificate"):
                    cov_ready.append(snap["ready"])
        if not cov_ready:
            continue
        per_cell.setdefault(n, []).append({
            "run": run.name,
            "coverage_legs": len(cov_ready),
            "ready_at_coverage": cov_ready,
            "mean_ready_cov": statistics.mean(cov_ready),
            "max_ready_cov": max(cov_ready),
            "share_cov_with_ready": sum(1 for x in cov_ready if x > 0) / len(cov_ready),
            "mean_ready_all": statistics.mean(all_ready) if all_ready else 0.0,
        })

    for n in sorted(per_cell):
        sub = per_cell[n]
        print(f"{args.mode}/{n}: {len(sub)} runs")
        print(f"   coverage legs per run: mean "
              f"{statistics.mean(r['coverage_legs'] for r in sub):5.1f}")
        print(f"   READY channels at a coverage-leg start: mean "
              f"{statistics.mean(r['mean_ready_cov'] for r in sub):5.2f}  "
              f"max over runs {max(r['max_ready_cov'] for r in sub)}")
        print(f"   share of coverage legs with >=1 READY: "
              f"{statistics.mean(r['share_cov_with_ready'] for r in sub):5.2%}")
        print(f"   runs where the mechanism could ever fire "
              f"(any coverage leg with READY>=1): "
              f"{sum(1 for r in sub if r['max_ready_cov'] > 0)}/{len(sub)}")
        hist = Counter(x for r in sub for x in r["ready_at_coverage"])
        print(f"   distribution of READY count at coverage legs: "
              f"{dict(sorted(hist.items())[:8])}")
        print(f"   (context) READY averaged over ALL actions: "
              f"{statistics.mean(r['mean_ready_all'] for r in sub):5.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
