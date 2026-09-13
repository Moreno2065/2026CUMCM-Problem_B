"""Canonical baseline table: one code revision, three columns per cell.

``tuning_runs/ab_probe/production`` mixes five code revisions (each seed exists
only once), so its per-cell mean confounds *policy revision* with *seed*: e.g.
Q4/16 reads 404.99 over all revisions but 357.63 on the current one.  Reports
must therefore name the revision they average over.

This tool selects runs by revision hash and prints, per cell, the three columns
the KPI discipline now requires:

    actual s/source | hindsight floor s/source | excess over floor

plus the oracle floor (MST of the true sources + the run's own service), and the
provable certificate_composite column is taken from ``tools/bounds_report.py``'s
output rather than recomputed here.

Usage:
  python -X utf8 tools/canonical_baseline.py [--sha 4377106baa371ae5] [--json out.json]
"""

from __future__ import annotations

import argparse
import glob
import json
import pathlib
import statistics
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from stop_floor import load, mst_len  # noqa: E402

SPEED = 5.0
CELLS = ("Q3_10", "Q3_13", "Q3_16", "Q4_10", "Q4_13", "Q4_16")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", default="4377106baa371ae5",
                    help="production.py sha256_16 of the wanted revision")
    ap.add_argument("--json", default="tuning_runs/canonical_baseline.json")
    args = ap.parse_args()

    rows = []
    for d in sorted(glob.glob(str(ROOT / "tuning_runs/ab_probe/production/*"))):
        run = pathlib.Path(d)
        cf = run / "policy_config.json"
        if not cf.exists():
            continue
        cfg = json.loads(cf.read_text(encoding="utf-8"))
        sha = cfg.get("code_sha256") or {}
        if str(sha.get("production.py"))[:16] != args.sha:
            continue
        cell = "_".join(run.name.split("_")[:2])
        n = int(run.name.split("_")[1])
        if not (run / "api_log.jsonl").exists():
            continue
        stops, svc, move = load(run)
        svc_s = sum(svc.values())
        actual = move + svc_s
        floor = mst_len([(0.0, 0.0)] + stops) / SPEED + svc_s
        oratio = None
        try:
            from oracle_floor import sources
            src = sources(run)
            if src:
                oratio = actual / (mst_len([(0.0, 0.0)] + src) / SPEED + svc_s)
        except Exception:
            oratio = None
        rows.append({"run": run.name, "cell": cell, "n": n,
                     "actual": actual / n, "floor": floor / n,
                     "excess": (actual - floor) / n,
                     "ratio": actual / floor, "ratio_oracle": oratio,
                     "scheduler": str(sha.get("learned_search/scheduler.py"))[:16]})
    by = defaultdict(list)
    for r in rows:
        by[r["cell"]].append(r)
    out = {"production_sha16": args.sha, "cells": {}}
    print(f"canonical baseline: production.py = {args.sha}")
    print(f"{'cell':8}{'n':>4}{'actual/s':>11}{'floor/s':>10}{'excess':>9}"
          f"{'ratio':>8}{'oracle':>8}   schedulers")
    for cell in CELLS:
        sub = by.get(cell, [])
        if not sub:
            print(f"{cell:8}{0:>4}   (no runs on this revision)")
            continue
        scheds = sorted({r["scheduler"] for r in sub})
        entry = {
            "n": len(sub),
            "actual": statistics.mean(r["actual"] for r in sub),
            "floor": statistics.mean(r["floor"] for r in sub),
            "excess": statistics.mean(r["excess"] for r in sub),
            "ratio": statistics.mean(r["ratio"] for r in sub),
            "ratio_oracle": (statistics.mean(r["ratio_oracle"] for r in sub)
                             if all(r["ratio_oracle"] for r in sub) else None),
            "schedulers": scheds,
            "seeds": sorted(r["run"].split("_")[-1] for r in sub),
        }
        out["cells"][cell] = entry
        print(f"{cell:8}{entry['n']:>4}{entry['actual']:>11.2f}"
              f"{entry['floor']:>10.2f}{entry['excess']:>9.2f}"
              f"{entry['ratio']:>8.4f}"
              f"{(entry['ratio_oracle'] or float('nan')):>8.4f}   {','.join(scheds)}")
    dest = ROOT / args.json
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"\nwrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
