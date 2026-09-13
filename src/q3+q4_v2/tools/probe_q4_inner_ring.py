"""Why does the Q4 cardinality cap fire so late?

The inner mesh ring (12 points @950 m, 30 deg apart) covers Omega within
916 m <= min observed r_eff (1000.1 m, tools/probe_r_eff.py), so *every* present
source is detectable from at least one inner-ring point.  If the cap fired right
after those 12 visits, the outer ring (~11 600 m of travel) could be skipped at
N=16 -- worth ~145 s/source.

This probe measures the shortfall on existing runs: at the step where the last
inner-ring point has been visited, how many sources that *should* already be
detectable are still UNKNOWN?  A large shortfall means the blocker is the scan
policy (which channels get measured where), not the geometry.

Usage: python -X utf8 tools/probe_q4_inner_ring.py [--root ...] [--n 16]
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "baseline" / "code"))
CONFIRMED = {"ACTIVE", "READY", "CLEARED"}


def mesh_points():
    from geometry.q4_sparse_mesh import q4_sparse25_points
    pts = [tuple(map(float, p)) for p in q4_sparse25_points()]
    inner = [p for p in pts if abs(math.hypot(*p) - 950.0) < 1.0]
    outer = [p for p in pts if abs(math.hypot(*p) - 1870.0) < 1.0]
    centre = [p for p in pts if math.hypot(*p) < 1.0]
    return pts, inner, outer, centre


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="tuning_runs/ab_probe/production")
    ap.add_argument("--n", type=int, default=16)
    args = ap.parse_args()
    pts, inner, outer, centre = mesh_points()
    print(f"mesh: {len(pts)} points -> inner {len(inner)} @950, "
          f"outer {len(outer)} @1870, centre {len(centre)}")

    rows = []
    for d in sorted(glob.glob(str(ROOT / args.root / f"Q4_{args.n}_*"))):
        run = Path(d)
        actions = run / "actions.csv"
        hist = run / "channel_state_history.jsonl"
        truth_f = run / "ground_truth.json"
        if not (actions.exists() and hist.exists() and truth_f.exists()):
            continue
        visited = {}
        with actions.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if (row.get("reason_code") or "") not in ("coverage", "certificate"):
                    continue
                try:
                    x, y = float(row["target_x"]), float(row["target_y"])
                    st = int(float(row.get("step") or 0))
                except (TypeError, ValueError):
                    continue
                j = min(range(len(pts)), key=lambda i: math.dist((x, y), pts[i]))
                if math.dist((x, y), pts[j]) < 5.0:
                    visited.setdefault(j, st)
                if len({i for i in visited if pts[i] in inner}) >= len(inner):
                    last_inner_step = st
        inner_idx = [i for i, p in enumerate(pts) if p in inner]
        if not all(i in visited for i in inner_idx):
            rows.append({"run": run.name, "inner_done": False})
            continue
        last_inner_step = max(visited[i] for i in inner_idx)
        states = None
        for line in hist.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("step") == last_inner_step:
                states = rec.get("channels") or {}
                break
        if states is None:
            rows.append({"run": run.name, "inner_done": False})
            continue
        confirmed = sum(1 for c in states.values()
                        if str(c.get("status")) in CONFIRMED)
        truth = json.loads(truth_f.read_text(encoding="utf-8"))
        detectable = 0
        missed = 0
        for src in truth:
            g = (float(src["x"]), float(src["y"]))
            if min(math.dist(g, p) for p in inner) <= 916.0:
                detectable += 1
                st = str((states.get(str(src["channel"])) or {}).get("status"))
                if st not in CONFIRMED:
                    missed += 1
        outer_after = sum(1 for i in (i for i, p in enumerate(pts) if p in outer)
                          if visited.get(i, 0) > last_inner_step)
        rows.append({"run": run.name, "inner_done": True,
                     "last_inner_step": last_inner_step,
                     "confirmed_at_last_inner": confirmed,
                     "detectable": detectable, "missed": missed,
                     "outer_visited_after": outer_after})
    ok = [r for r in rows if r.get("inner_done")]
    print(f"\nQ4/{args.n}: {len(rows)} runs, inner ring completed in {len(ok)}")
    for r in ok:
        print(f"  {r['run']:16} last inner visit step {r['last_inner_step']:>4} | "
              f"confirmed {r['confirmed_at_last_inner']:>2} | detectable "
              f"{r['detectable']:>2} missed {r['missed']:>2} | outer visited after "
              f"{r['outer_visited_after']:>2}")
    if ok:
        print(f"\nmean confirmed at last inner visit: "
              f"{statistics.mean(r['confirmed_at_last_inner'] for r in ok):.1f}/16")
        print(f"mean detectable-but-missed: "
              f"{statistics.mean(r['missed'] for r in ok):.1f}")
        print(f"mean outer points visited after the inner ring: "
              f"{statistics.mean(r['outer_visited_after'] for r in ok):.1f}/12")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
