"""Route-quality diagnostic: observed clear/mission sequence vs 2-opt on the
same visited targets.

Only the executed trajectory is used (no ground truth), so the comparison is a
pure ordering diagnostic: it answers "how much travel did the online ordering
waste relative to a 2-opt pass over the very same stops".
"""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path


def path_length(points, start=(0.0, 0.0)):
    total = math.dist(start, points[0]) if points else 0.0
    for a, b in zip(points, points[1:]):
        total += math.dist(a, b)
    return total


def two_opt(points, start=(0.0, 0.0), passes=40):
    order = list(points)
    best = path_length(order, start)

    def d(a, b):
        return math.dist(a, b)

    for _ in range(passes):
        improved = False
        for i in range(len(order) - 1):
            left = start if i == 0 else order[i - 1]
            for j in range(i + 1, len(order)):
                right = order[j + 1] if j + 1 < len(order) else None
                before = d(left, order[i])
                after = d(left, order[j])
                if right is not None:
                    before += d(order[j], right)
                    after += d(order[i], right)
                if after + 1e-6 < before:
                    order[i:j + 1] = reversed(order[i:j + 1])
                    improved = True
        new = path_length(order, start)
        if not improved or new >= best - 1e-6:
            break
        best = new
    return order, best


def analyze(path, kind):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    seq = []
    for r in rows:
        if r["action"] != kind:
            continue
        point = (float(r["x"]), float(r["y"]))
        if seq and math.dist(seq[-1], point) < 1.0:
            continue
        seq.append(point)
    if len(seq) < 2:
        return None
    observed = path_length(seq)
    _, improved = two_opt(seq)
    return len(seq), observed, improved


def main():
    root = Path(sys.argv[1])
    pattern = sys.argv[2] if len(sys.argv) > 2 else "Q3_16_*"
    print("%-24s %-6s %5s %10s %10s %8s" %
          ("run", "kind", "stops", "observed_m", "2opt_m", "waste%"))
    for path in sorted(root.glob(pattern)):
        traj = path / "trajectory.csv"
        if not traj.exists():
            continue
        for kind in ("clear", "measure"):
            res = analyze(traj, kind)
            if res is None:
                continue
            stops, observed, improved = res
            print("%-24s %-6s %5d %10.0f %10.0f %7.1f%%" %
                  (path.name, kind, stops, observed, improved,
                   (observed - improved) / observed * 100.0))


if __name__ == "__main__":
    main()
