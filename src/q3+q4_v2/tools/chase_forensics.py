"""Chase-phase forensics: leg lengths and channel switching behaviour."""
from __future__ import annotations

import csv
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "baseline" / "code"))
from geometry.q4_sparse_mesh import q4_sparse25_points   # noqa: E402


def tour_points(mode):
    if mode == "Q4":
        return q4_sparse25_points()
    pts = [(0.0, 0.0)]
    for k in range(6):
        pts.append((1200.0 * math.cos(2 * math.pi * k / 6),
                    1200.0 * math.sin(2 * math.pi * k / 6)))
    return pts


def analyze(path, mode):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    pts = tour_points(mode)
    seq = []          # (phase, channel, leg_distance)
    prev = None
    for r in rows:
        x, y = float(r["x"]), float(r["y"])
        d = math.hypot(x - prev[0], y - prev[1]) if prev else 0.0
        prev = (x, y)
        if r["action"] not in ("measure", "clear"):
            continue
        on_tour = any(math.dist((x, y), p) <= 1.0 for p in pts)
        phase = "clear" if r["action"] == "clear" else (
            "tour" if on_tour else "chase")
        seq.append((phase, r["channel"], d, r["result"]))
    chase = [s for s in seq if s[0] == "chase"]
    lens = sorted(s[2] for s in chase)
    switches = sum(1 for a, b in zip(chase, chase[1:]) if a[1] != b[1])
    hist = Counter()
    for _, _, d, _ in chase:
        hist[min(9, int(d // 100))] += 1
    return {
        "chase_legs": len(chase),
        "chase_km": sum(lens) / 1000.0,
        "chase_median": lens[len(lens) // 2] if lens else 0.0,
        "chase_max": lens[-1] if lens else 0.0,
        "channel_switches": switches,
        "hist": dict(sorted(hist.items())),
        "dir_frac": (sum(1 for s in chase if s[3] == "direction") /
                     max(1, len(chase))),
    }


def main():
    root = Path(sys.argv[1])
    mode = sys.argv[2] if len(sys.argv) > 2 else "Q4"
    print("hist buckets are 100 m; key 9 = >=900 m")
    for path in sorted(root.glob("%s_16_*" % mode)):
        traj = path / "trajectory.csv"
        if not traj.exists():
            continue
        r = analyze(traj, mode)
        print("%-28s legs=%3d km=%5.1f med=%5.1f max=%6.0f switch=%3d "
              "dirFrac=%.2f hist=%s" %
              (path.name, r["chase_legs"], r["chase_km"], r["chase_median"],
               r["chase_max"], r["channel_switches"], r["dir_frac"],
               r["hist"]))


if __name__ == "__main__":
    main()
