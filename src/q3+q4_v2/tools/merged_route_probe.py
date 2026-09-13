"""Offline feasibility probe: can discovery ride along a source-clearing route?

Simulates, per dev seed, a policy that only scans at the origin and at each
cleared source, then walks to the nearest already-detected source.  Reports the
travel this merged route costs, how many sources are still undetected when the
known ones run out, and the full-information TSP length for scale.  Ground
truth is used for the diagnostic only; it is never read by the policy under
test.
"""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "baseline" / "code"))
from experiment.simulator import make_sources   # noqa: E402


def detect(sources, point):
    """Channels giving a signal at ``point`` (omnidirectional Q3 semantics)."""
    out = []
    for s in sources:
        if s.cleared:
            continue
        if math.dist(point, s.pos) <= s.r_eff:
            out.append(s)
    return out


def simulated_run(sources, mode):
    for s in sources:
        s.cleared = False
    known = {}
    travel = 0.0
    here = (0.0, 0.0)
    for s in detect(sources, here):
        known[s.channel] = s
    order = []
    while known:
        cid, target = min(known.items(),
                          key=lambda kv: math.dist(here, kv[1].pos))
        travel += math.dist(here, target.pos)
        here = target.pos
        target.cleared = True
        order.append(cid)
        del known[cid]
        for s in detect(sources, here):
            known.setdefault(s.channel, s)
    remaining = [s for s in sources if not s.cleared]
    # greedy finish for the leftovers (they were never detected)
    while remaining:
        tgt = min(remaining, key=lambda s: math.dist(here, s.pos))
        travel += math.dist(here, tgt.pos)
        here = tgt.pos
        tgt.cleared = True
        remaining.remove(tgt)
    return travel, order


def tsp_length(sources):
    pts = [s.pos for s in sources]
    order = []
    here = (0.0, 0.0)
    left = list(pts)
    total = 0.0
    while left:
        p = min(left, key=lambda q: math.dist(here, q))
        total += math.dist(here, p)
        here = p
        left.remove(p)
        order.append(p)
    # 2-opt improvement (open path from the origin)
    improved = True
    passes = 0
    while improved and passes < 30:
        improved = False
        passes += 1
        for i in range(len(order) - 1):
            a = (0.0, 0.0) if i == 0 else order[i - 1]
            for j in range(i + 1, len(order)):
                b = order[j + 1] if j + 1 < len(order) else None
                before = math.dist(a, order[i]) + (
                    math.dist(order[j], b) if b else 0.0)
                after = math.dist(a, order[j]) + (
                    math.dist(order[i], b) if b else 0.0)
                if after + 1e-6 < before:
                    order[i:j + 1] = reversed(order[i:j + 1])
                    improved = True
        total = math.dist((0.0, 0.0), order[0])
        for a, b in zip(order, order[1:]):
            total += math.dist(a, b)
    return total


def main():
    seeds = [int(x) for x in (sys.argv[1:] or ["101", "202", "303", "404", "505"])]
    print("%6s %10s %10s %12s %10s" %
          ("seed", "merged_m", "tsp_m", "undetected", "clear_legs"))
    for seed in seeds:
        sources = make_sources("Q3", seed, n_sources=16, scenario="random")
        travel, order = simulated_run(sources, "Q3")
        leftovers = 16 - len(order)
        tsp = tsp_length(sources)
        print("%6d %10.0f %10.0f %12d %10d" %
              (seed, travel, tsp, leftovers, len(order)))


if __name__ == "__main__":
    main()
