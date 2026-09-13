"""Split a run into discovery (until the 16th channel is confirmed) and tail.

The cardinality cap only fires once 16 distinct channels have positive
evidence, so everything after that point is localization + clearing of already
known sources.  The split shows how much of the budget the discovery tour takes
and how much the tail costs.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path


def analyze(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    seen = {}
    confirm_t = None
    for r in rows:
        if r["action"] == "measure" and r["result"] in ("direction", "near"):
            if r["channel"] not in seen:
                seen[r["channel"]] = float(r["virtual_time"])
            if len(seen) >= 16 and confirm_t is None:
                confirm_t = float(r["virtual_time"])
    total = float(rows[-1]["virtual_time"])
    # travel before / after confirmation
    move_before = move_after = 0.0
    prev = None
    for r in rows:
        x, y = float(r["x"]), float(r["y"])
        if prev is not None:
            d = ((x - prev[0]) ** 2 + (y - prev[1]) ** 2) ** 0.5
            if confirm_t is not None and float(r["virtual_time"]) > confirm_t:
                move_after += d
            else:
                move_before += d
        prev = (x, y)
    return confirm_t, total, move_before, move_after


def main():
    root = Path(sys.argv[1])
    pattern = sys.argv[2] if len(sys.argv) > 2 else "Q4_16_*"
    print("%-26s %8s %8s %8s %9s %9s" %
          ("run", "confirm", "total", "tail%", "km_before", "km_after"))
    for path in sorted(root.glob(pattern)):
        traj = path / "trajectory.csv"
        if not traj.exists():
            continue
        confirm, total, before, after = analyze(traj)
        tail = (total - confirm) / total * 100.0 if confirm else float("nan")
        print("%-26s %8.0f %8.0f %7.1f%% %9.1f %9.1f" %
              (path.name, confirm or -1, total, tail, before / 1000.0,
               after / 1000.0))


if __name__ == "__main__":
    main()
