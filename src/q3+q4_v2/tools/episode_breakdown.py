"""Per-source clearing episode breakdown.

Between two consecutive clears, attribute travel and measurements to the
channel that was eventually cleared, so the cost of "one source" is visible:
how much chasing, how much scanning, and how the episodes chain.
"""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path


def episodes(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    out = []
    travel = 0.0
    measures = 0
    other = 0
    prev = None
    for r in rows:
        x, y = float(r["x"]), float(r["y"])
        d = math.dist((x, y), prev) if prev else 0.0
        prev = (x, y)
        if r["action"] == "measure":
            travel += d
            measures += 1
            if r["result"] == "direction":
                other += 1
        elif r["action"] == "clear":
            travel += d
            out.append({
                "channel": int(r["channel"]),
                "result": r["result"],
                "travel": travel,
                "measures": measures,
                "directions": other,
                "t": float(r["virtual_time"]),
            })
            travel = measures = other = 0
    return out


def main():
    root = Path(sys.argv[1])
    pattern = sys.argv[2] if len(sys.argv) > 2 else "Q4_16_*"
    for path in sorted(root.glob(pattern)):
        traj = path / "trajectory.csv"
        if not traj.exists():
            continue
        eps = episodes(traj)
        total = sum(e["travel"] for e in eps)
        good = [e for e in eps if e["result"] == "success"]
        print("%-24s clears=%2d success=%2d travel=%6.1fkm epMean=%4.0fm "
              "epMax=%5.0fm meas/ep=%4.1f" %
              (path.name, len(eps), len(good), total / 1000.0,
               total / max(1, len(eps)),
               max((e["travel"] for e in eps), default=0),
               sum(e["measures"] for e in eps) / max(1, len(eps))))
        print("      per-success travel: " + " ".join(
            "%d:%d" % (e["channel"], int(e["travel"])) for e in good))


if __name__ == "__main__":
    main()
