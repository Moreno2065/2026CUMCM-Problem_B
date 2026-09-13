"""Independent numerical checks for the Q4 midpoint-pair lemma."""
from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "baseline" / "code")]

from geometry import constants as C


def run(samples=200000, seed=20260912):
    rng = random.Random(seed)
    epsilon = math.radians(C.BEARING_ERROR_DEG)
    distance_bound = C.R_EFF_MAX / math.cos(math.pi / 128.0)
    midpoint = 0.5 * distance_bound
    offset = midpoint * math.tan(epsilon)
    probes = ((midpoint, -offset), (midpoint, offset))
    failures = []
    worst_distance = 0.0
    checked_far = 0
    for _ in range(int(samples)):
        radius = distance_bound * math.sqrt(rng.random())
        angle = rng.uniform(-epsilon, epsilon)
        source = (radius * math.cos(angle), radius * math.sin(angle))
        # Select a source orientation for which the anchor A=(0,0) is visible.
        source_to_anchor = math.atan2(-source[1], -source[0])
        orientation = source_to_anchor + rng.uniform(-math.pi / 2,
                                                     math.pi / 2)
        if source[0] + 1e-10 < midpoint:
            continue
        checked_far += 1
        visible = []
        for point in probes:
            distance = math.dist(point, source)
            worst_distance = max(worst_distance, distance)
            dot = (math.cos(orientation) * (point[0] - source[0]) +
                   math.sin(orientation) * (point[1] - source[1]))
            visible.append(distance <= C.R_EFF_MIN + 1e-9 and dot >= -1e-9)
        if not any(visible):
            failures.append((source, orientation, visible))
            break
    analytic_bound = (0.5 * distance_bound *
                      math.sqrt(1.0 + 9.0 * math.tan(epsilon) ** 2))
    if failures:
        raise AssertionError("midpoint pair counterexample: %r" % failures[0])
    if analytic_bound >= C.R_EFF_MIN:
        raise AssertionError("probe distance bound is not guaranteed")
    print({"samples": samples, "far_cases": checked_far,
           "max_sampled_probe_distance_m": worst_distance,
           "analytic_probe_distance_bound_m": analytic_bound,
           "pair_gap_m": 2.0 * offset, "failures": 0})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=200000)
    parser.add_argument("--seed", type=int, default=20260912)
    args = parser.parse_args()
    run(args.samples, args.seed)
