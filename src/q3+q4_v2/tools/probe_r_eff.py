"""What is the simulator's real detection radius, and is our certificate sound?

``ground_truth.json`` carries a per-source ``r_eff`` (and a ``directional`` flag),
so the "detection radius" is *not* a constant.  That matters twice:

1. **Certificate soundness.**  ``q4_channel_certified_sparse25`` treats a channel
   as absent when all 25 mesh points read ``no_signal``.  A source at g with
   radius r_eff(g) would hide from the mesh whenever
   ``min_w dist(w, g) > r_eff(g)``; the mesh's worst-case covering distance is
   562.3209605838152 m, so the predicate is only sound when *every* source
   radius exceeds that.  This tool measures the actual distribution.
2. **Search coverage.**  Any "visit these points and you are guaranteed to see
   every source" argument needs ``min_w dist(w, g) <= r_eff(g)`` for all g, i.e.
   it must use min r_eff, not the nominal 1000 m.  **CORRECTION (round 70):**
   radius is only half the story -- ``measure`` also gates on the *coverage
   angle* (``baseline/code/experiment/simulator.py``): omnidirectional sources
   accept 360 deg, **directional ones only their frontal closed half-plane
   (+-90 deg)**, and ~24.5% of observed sources are directional.  So a radial
   coverage argument is necessary but NOT sufficient for discovery: a witness
   behind a directional source reads ``no_signal`` even at 900 m.  This tool
   therefore validates the certificate's radial premise (r_eff >= 562.32 m),
   not any discovery guarantee.

Usage: python -X utf8 tools/probe_r_eff.py [--root tuning_runs/ab_probe/production]
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MESH_WORST_M = 562.3209605838152


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="tuning_runs/ab_probe/production")
    args = ap.parse_args()

    rows = []
    for d in sorted(glob.glob(str(ROOT / args.root / "*"))):
        p = Path(d) / "ground_truth.json"
        if not p.exists():
            continue
        try:
            truth = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(truth, list):
            continue
        name = Path(d).name
        mode = name.split("_")[0]
        n = int(name.split("_")[1])
        for src in truth:
            if "r_eff" not in src:
                continue
            rows.append({"run": name, "mode": mode, "n": n,
                         "channel": src.get("channel"),
                         "r_eff": float(src["r_eff"]),
                         "directional": bool(src.get("directional")),
                         "cleared": bool(src.get("cleared"))})
    if not rows:
        print("no ground-truth files with r_eff found")
        return 0

    vals = sorted(r["r_eff"] for r in rows)
    n = len(vals)
    print(f"sources with r_eff: {n}  (runs: {len({r['run'] for r in rows})})")
    print(f"  min    {vals[0]:8.1f} m")
    print(f"  p05    {vals[int(0.05 * n)]:8.1f} m")
    print(f"  median {statistics.median(vals):8.1f} m")
    print(f"  p95    {vals[int(0.95 * n)]:8.1f} m")
    print(f"  max    {vals[-1]:8.1f} m")
    for thr in (562.3209605838152, 700.0, 800.0, 916.0, 950.0, 1000.0):
        below = sum(1 for v in vals if v < thr)
        print(f"  r_eff < {thr:8.1f}: {below:5d} / {n}  ({100.0 * below / n:5.1f}%)")
    print()
    by_mode = {}
    for r in rows:
        by_mode.setdefault(r["mode"], []).append(r["r_eff"])
    for mode, sub in sorted(by_mode.items()):
        print(f"  {mode}: n={len(sub):4d} min {min(sub):7.1f} "
              f"median {statistics.median(sub):7.1f} max {max(sub):7.1f}")
    print()
    print("per-run minimum (a single low-radius source is enough to break a")
    print("coverage argument that assumes 1000 m):")
    per_run = {}
    for r in rows:
        per_run.setdefault(r["run"], []).append(r["r_eff"])
    mins = sorted((min(v), k) for k, v in per_run.items())
    for v, k in mins[:8]:
        print(f"  {k:16} min r_eff {v:8.1f} m")
    print(f"  ... ({len(mins)} runs)")
    worst = mins[0][0]
    print(f"\nWORST per-run minimum: {worst:.1f} m "
          f"-> mesh soundness needs r_eff >= {MESH_WORST_M:.1f}: "
          f"{'HOLDS' if worst >= MESH_WORST_M else 'VIOLATED'}")
    dirm = [r["r_eff"] for r in rows if r["directional"]]
    print(f"directional sources: {len(dirm)}/{n}; "
          f"min r_eff among them {min(dirm) if dirm else float('nan'):.1f} m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
