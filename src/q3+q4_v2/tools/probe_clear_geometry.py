"""Clear-ladder geometry: did the failed clears ever get within the 20 m radius?

`clear` succeeds whenever the source is within 20 m (regardless of facing), so a
failed attempt means the firing point was >20 m away.  t27 (clear ledger) proved
that no *online observable* separates failures from successes -- but it never
asked the geometric question: **how close did the ladder actually get?**

- If failed ladders routinely reached <=20 m, the failure is not geometric and a
  finer ladder cannot help.
- If failures stopped far outside 20 m, the ladder's *step size* is the blocker
  and a denser pattern (each step costs 3 s + travel) could convert some of them.

Usage: python -X utf8 tools/probe_clear_geometry.py [--mode Q4]
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="tuning_runs/ab_probe/production")
    ap.add_argument("--mode", default="Q4")
    args = ap.parse_args()

    per_cell = {}
    for d in sorted(glob.glob(str(ROOT / args.root / f"{args.mode}_*_*"))):
        run = Path(d)
        acts = run / "actions.csv"
        gt = run / "ground_truth.json"
        if not (acts.exists() and gt.exists()):
            continue
        n = int(run.name.split("_")[1])
        truth = {}
        for s in json.loads(gt.read_text(encoding="utf-8")):
            truth[int(s["channel"])] = (float(s["x"]), float(s["y"]),
                                       float(s["r_eff"]),
                                       bool(s.get("directional")))
        attempts = {}
        with acts.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["action_type"] != "clear":
                    continue
                tx, ty = (r.get("target_x") or "").strip(), (r.get("target_y") or "").strip()
                if not tx or not ty:
                    continue
                try:
                    ch = int(r["channel"])
                    attempts.setdefault(ch, []).append((float(tx), float(ty)))
                except (TypeError, ValueError):
                    continue
        for ch, pts in attempts.items():
            if ch not in truth:
                continue
            gx, gy, _r, directional = truth[ch]
            dists = [math.dist(p, (gx, gy)) for p in pts]
            per_cell.setdefault(n, []).append({
                "run": run.name, "ch": ch, "attempts": len(dists),
                "min_d": min(dists), "last_d": dists[-1],
                "failed_d": dists[:-1],
                "directional": directional,
            })

    for n in sorted(per_cell):
        sub = per_cell[n]
        failed = [r for r in sub if r["attempts"] > 1]
        print(f"{args.mode}/{n}: {len(sub)} channels with >=1 clear attempt; "
              f"{len(failed)} needed more than one attempt")
        if not failed:
            continue
        mins = sorted(r["min_d"] for r in failed)
        print(f"   closest approach over ALL attempts of those channels: "
              f"median {statistics.median(mins):6.1f} m  p10 {mins[len(mins)//10]:6.1f}  "
              f"max {mins[-1]:6.1f}")
        bins = [(0, 20), (20, 30), (30, 45), (45, 70), (70, 1e9)]
        for lo, hi in bins:
            c = sum(1 for x in mins if lo < x <= hi) if lo else sum(1 for x in mins if x <= hi)
            print(f"     closest in ({lo:>3.0f}, {hi if hi < 1e8 else float('inf'):>4.0f}] m: {c:5d}"
                  f"  ({100.0 * c / len(mins):5.1f}%)")
        print(f"   attempts per such channel: median "
              f"{statistics.median(r['attempts'] for r in failed):.0f} "
              f"max {max(r['attempts'] for r in failed)}")
        # distances at the FAILED attempts (all but the last, which succeeded)
        fal = sorted(min(r["failed_d"]) for r in failed if r["failed_d"])
        if fal:
            print(f"   closest distance reached by a FAILED attempt: median "
                  f"{statistics.median(fal):6.1f} m  p10 {fal[len(fal)//10]:6.1f}  "
                  f"min {fal[0]:6.1f}")
            for lo, hi in ((0, 20), (20, 25), (25, 35), (35, 60), (60, 1e9)):
                c = sum(1 for x in fal if (x <= hi if lo == 0 else lo < x <= hi))
                print(f"     failed-attempt closest in "
                      f"({lo:>3.0f}, {hi if hi < 1e8 else float('inf'):>4.0f}] m: {c:5d}"
                      f"  ({100.0 * c / len(fal):5.1f}%)")
        dirn = [r for r in failed if r["directional"]]
        print(f"   directional share among them: {len(dirn)}/{len(failed)} "
              f"({100.0 * len(dirn) / len(failed):.0f}%) vs overall "
              f"{100.0 * sum(1 for r in sub if r['directional']) / len(sub):.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
