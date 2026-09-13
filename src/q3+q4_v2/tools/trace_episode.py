"""Print the action window of the most expensive clearing episode.

Usage: python tools/trace_episode.py <trajectory.csv> [channel]
"""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path


def load(path):
    return list(csv.DictReader(open(path, encoding="utf-8")))


def episodes(rows):
    out = []
    start = 0
    for idx, r in enumerate(rows):
        if r["action"] == "clear":
            out.append((start, idx, r))
            start = idx + 1
    return out


def main():
    rows = load(sys.argv[1])
    want = int(sys.argv[2]) if len(sys.argv) > 2 else None
    eps = episodes(rows)
    if want is None:
        scored = []
        for s, e, r in eps:
            travel = 0.0
            prev = None
            for row in rows[s:e + 1]:
                pos = (float(row["x"]), float(row["y"]))
                if prev:
                    travel += math.dist(pos, prev)
                prev = pos
            scored.append((travel, s, e, r))
        scored.sort(reverse=True)
        travel, s, e, r = scored[0]
        print("worst episode: channel %s travel %.0f m (rows %d..%d)" %
              (r["channel"], travel, s, e))
    else:
        for s, e, r in eps:
            if int(r["channel"]) == want:
                print("episode channel %d rows %d..%d" % (want, s, e))
                break
        else:
            return
    prev = None
    for row in rows[max(0, s - 3):e + 2]:
        pos = (float(row["x"]), float(row["y"]))
        d = math.dist(pos, prev) if prev else 0.0
        prev = pos
        if row["action"] in ("measure", "clear") or d > 1:
            print("  t=%7.1f move=%6.0f (%.0f,%.0f) %-7s ch=%-2s %s" %
                  (float(row["virtual_time"]), d, pos[0], pos[1],
                   row["action"], row["channel"], row["result"]))


if __name__ == "__main__":
    main()
