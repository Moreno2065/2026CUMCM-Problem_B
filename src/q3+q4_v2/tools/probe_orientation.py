"""Which way do Q4's directional sources face?  (inner-first vs outer-first mesh)

~50.9% of Q4 sources are ``directional``: ``measure`` only answers from inside
their frontal closed half-plane (+-90 deg around ``orientation``), while Q3
sources are all omnidirectional (0/32087).  The production mesh walks its
**inner** ring (12 @950 m) before the **outer** one (12 @1870 m).

If the directional sources face *radially outward*, then the inner ring is
structurally blind to them and only the outer ring can find them -- which would
make "outer-first" a cheap, principled reordering.  If orientations are uniform,
no ordering helps and two-sided coverage is genuinely required.

Usage: python -X utf8 tools/probe_orientation.py [--root tuning_runs/ab_probe]
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="tuning_runs/ab_probe")
    ap.add_argument("--mode", default="Q4")
    args = ap.parse_args()

    diffs = []
    radii = []
    orient_all = []
    for p in sorted(glob.glob(str(ROOT / args.root / "*" / f"{args.mode}_*_*"
                                        / "ground_truth.json"))):
        try:
            truth = json.loads(Path(p).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for s in truth:
            if not s.get("directional"):
                continue
            x, y = float(s["x"]), float(s["y"])
            o = float(s.get("orientation") or 0.0)
            radial = math.degrees(math.atan2(y, x)) % 360.0
            d = abs((o - radial + 180.0) % 360.0 - 180.0)
            diffs.append(d)
            radii.append(math.hypot(x, y))
            orient_all.append(o)
    if not diffs:
        print("no directional sources found")
        return 0
    n = len(diffs)
    within = lambda t: sum(1 for d in diffs if d <= t)
    print(f"{args.mode}: {n} directional sources")
    print(f"  |orientation - radial bearing|: median {statistics.median(diffs):6.1f} deg"
          f"  mean {statistics.mean(diffs):6.1f} deg")
    for t in (10, 30, 45, 60, 90):
        print(f"    within {t:3d} deg of radial: {within(t):6d} / {n} "
              f"({100.0 * within(t) / n:5.1f}%)")
    print(f"  radii: min {min(radii):6.1f}  median {statistics.median(radii):6.1f} "
          f" max {max(radii):6.1f} m")
    print("  orientation histogram (30 deg bins):")
    hist = Counter(int(o // 30) for o in orient_all)
    for b in sorted(hist):
        print(f"    {b * 30:3d}-{b * 30 + 29:3d}: {hist[b]:5d} "
              f"{'#' * max(1, hist[b] * 60 // max(hist.values()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
