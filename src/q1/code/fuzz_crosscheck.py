#!/usr/bin/env python3
"""Deterministic randomized cross-check between main chain A and verifier B."""

from __future__ import annotations

import argparse
import math
import random

from q1_geometry import Measurement, STATUS_OK, solve_q1
from q1_verify import verify_measurements


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--realizable", type=int, default=600)
    ap.add_argument("--arbitrary", type=int, default=800)
    ap.add_argument("--seed", type=int, default=20260910)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    status_mismatch = 0
    diameter_mismatch = 0
    worst_rel = 0.0
    counts: dict[str, int] = {}

    # Realizable: construct measurements from a hidden true source with errors in [-1,1].
    for t in range(args.realizable):
        n = 2 + (t % 5)
        gx, gy = rng.uniform(-500, 500), rng.uniform(-500, 500)
        ms = []
        for _ in range(n):
            true_bearing = rng.uniform(0, 360)
            r = rng.uniform(100, 900)
            sx = gx - r * math.cos(math.radians(true_bearing))
            sy = gy - r * math.sin(math.radians(true_bearing))
            ms.append(Measurement(sx, sy, true_bearing + rng.uniform(-1, 1)))
        a = solve_q1(ms)
        b = verify_measurements(ms, main=a)
        counts[a.status] = counts.get(a.status, 0) + 1
        if not b.get("status_agrees", False):
            status_mismatch += 1
        if a.status == STATUS_OK:
            rel = float(b["diameter_rel_diff"])
            worst_rel = max(worst_rel, rel)
            diameter_mismatch += int(rel > 1e-8)

    # Arbitrary: exercises EMPTY and UNBOUNDED heavily.
    for _ in range(args.arbitrary):
        n = rng.randint(1, 5)
        ms = [
            Measurement(rng.uniform(-1000, 1000), rng.uniform(-1000, 1000), rng.uniform(-720, 720))
            for _ in range(n)
        ]
        a = solve_q1(ms)
        b = verify_measurements(ms, main=a)
        counts[a.status] = counts.get(a.status, 0) + 1
        if not b.get("status_agrees", False):
            status_mismatch += 1
        if a.status == STATUS_OK:
            rel = float(b["diameter_rel_diff"])
            worst_rel = max(worst_rel, rel)
            diameter_mismatch += int(rel > 1e-8)

    print(
        {
            "seed": args.seed,
            "cases": args.realizable + args.arbitrary,
            "status_counts": counts,
            "status_mismatch": status_mismatch,
            "diameter_mismatch_gt_1e-8": diameter_mismatch,
            "worst_diameter_rel_diff": worst_rel,
        }
    )
    if status_mismatch or diameter_mismatch:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
