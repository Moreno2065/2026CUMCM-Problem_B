"""Rigorous lower bound for one case, with its justification recorded.

The only bound proved here is

    T >= 5N + M/5
      * 5N   : each source needs one successful /clear, which costs exactly 5 s
               (a /clear does not move the robot, so it cannot replace or be
               replaced by travel time);
      * M/5  : any feasible run enters every B(g_i, 20) ball, starting at the
               origin.  Ordering the sources by first entry, every consecutive
               pair of set entries costs at least the shortest distance between
               the two sets, so the path length is at least the minimum
               spanning tree weight M of the graph whose nodes are the origin
               and the N clear balls, with edge weights
                   w(0,i) = max(0, |g_i| - 20)
                   w(i,j) = max(0, |g_i - g_j| - 40)
               At 5 m/s that contributes M/5 seconds.

Both terms are additive because one is action time and the other is travel
time.  The bound uses true source positions, so it holds for every policy,
including one that knows everything in advance.

What this bound does NOT do (and previous drafts wrongly claimed):
  * it says nothing about how many measurements a policy needs - a policy may
    skip direction finding entirely and clear on a dense path;
  * it does not include any certificate route: absence can also be evidenced by
    other means, and the 7-point ring / 25-point mesh are implementation
    choices, not problem requirements;
  * movement that serves two purposes is counted once, so it is not the sum of
    a coverage route and a clearing route: only
        L_joint >= max(L_cover_bound, L_clear_bound)
    can be asserted without an extra non-sharing proof.
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "baseline" / "code"))
from experiment.simulator import make_sources   # noqa: E402


def mst_weight(points, origin=(0.0, 0.0), clear_radius=20.0):
    nodes = [origin] + [tuple(p) for p in points]

    def weight(a, b):
        if a is origin or b is origin:
            other = b if a is origin else a
            return max(0.0, math.hypot(other[0], other[1]) - clear_radius)
        return max(0.0, math.hypot(a[0] - b[0], a[1] - b[1])
                   - 2.0 * clear_radius)

    count = len(nodes)
    inside = [False] * count
    key = [float("inf")] * count
    key[0] = 0.0
    total = 0.0
    for _ in range(count):
        pick = min((i for i in range(count) if not inside[i]),
                   key=lambda i: key[i])
        inside[pick] = True
        total += key[pick]
        for other in range(count):
            if inside[other]:
                continue
            candidate = weight(nodes[pick], nodes[other])
            if candidate < key[other]:
                key[other] = candidate
    return total


def bound_for(mode, seed, n):
    sources = make_sources(mode, seed, n_sources=n,
                           scenario="random" if mode == "Q3" else "mixed")
    positions = [s.pos for s in sources]
    weight = mst_weight(positions)
    return 5.0 * len(sources) + weight / 5.0


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "Q3"
    seeds = [101, 202, 303, 404, 505, 606, 707, 808, 909, 1010, 1111, 1212]
    print("mode %s ; bound = 5N + M/5 (seconds, per run)" % mode)
    for n in (10, 13, 16):
        values = [bound_for(mode, seed, n) for seed in seeds]
        per_source = [v / n for v in values]
        print("  N=%-3d runs: %s" % (n, " ".join("%.0f" % v for v in values)))
        print("        per source: mean %.1f  min %.1f  max %.1f" %
              (statistics.mean(per_source), min(per_source),
               max(per_source)))


if __name__ == "__main__":
    main()
