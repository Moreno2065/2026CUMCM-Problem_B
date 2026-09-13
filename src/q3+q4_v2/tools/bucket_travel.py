"""Bucket Q4/Q3 travel per leg into tour / chase / clear phases.

A leg is a move between two executed actions.  It is charged to
``tour`` when the destination sits on a finite certificate point, to ``clear``
when the action is a clear, and to ``chase`` otherwise.  This separates the
fixed coverage tour from the per-source localization chase, which is where the
current policy spends its extra travel.
"""
from __future__ import annotations

import csv
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "baseline" / "code"))
from geometry.q4_sparse_mesh import q4_sparse25_points   # noqa: E402


def tour_points(mode):
    pts = [(0.0, 0.0)]
    if mode == "Q3":
        for k in range(6):
            pts.append((1200.0 * math.cos(2 * math.pi * k / 6),
                        1200.0 * math.sin(2 * math.pi * k / 6)))
    else:
        pts = q4_sparse25_points()
    return pts


def analyze(path, mode):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    pts = tour_points(mode)
    bucket = defaultdict(lambda: [0.0, 0])
    prev = None
    for r in rows:
        x, y = float(r["x"]), float(r["y"])
        if prev is not None:
            d = math.hypot(x - prev[0], y - prev[1])
            if d > 1.0:
                on_tour = any(math.dist((x, y), p) <= 1.0 for p in pts)
                if r["action"] == "clear":
                    key = "clear"
                elif on_tour:
                    key = "tour"
                else:
                    key = "chase"
                bucket[key][0] += d
                bucket[key][1] += 1
        prev = (x, y)
    return bucket


def main():
    roots = sys.argv[1:] or ["tuning_runs/ab_probe/baseline"]
    for root in roots:
        agg = defaultdict(lambda: defaultdict(float))
        cnt = defaultdict(lambda: defaultdict(int))
        n_runs = 0
        for mode in ("Q3", "Q4"):
            for path in sorted(Path(root).glob("%s_16_*" % mode)):
                traj = path / "trajectory.csv"
                if not traj.exists():
                    continue
                n_runs += 1
                for key, (dist, legs) in analyze(traj, mode).items():
                    agg[mode][key] += dist
                    cnt[mode][key] += legs
        print("== %s (%d runs) ==" % (root, n_runs))
        for mode in ("Q3", "Q4"):
            total = sum(agg[mode].values())
            if not total:
                continue
            parts = ", ".join(
                "%s %.1fkm/%d legs" % (k, agg[mode][k] / 1000.0, cnt[mode][k])
                for k in ("tour", "chase", "clear") if agg[mode][k])
            print("  %s: total %.1fkm | %s" % (mode, total / 1000.0, parts))


if __name__ == "__main__":
    main()
