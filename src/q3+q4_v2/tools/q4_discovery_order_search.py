"""Search a fixed sparse25 order for early Q4 discovery.

This is deliberately a small combinatorial optimiser, not a learned policy.
It samples legal synthetic Q4 worlds, precomputes which certificate stops can
hear each source, then minimises the time at which the last of 16 sources is
first heard.  The surrogate charges both travel and the shrinking UNKNOWN
scan set, so a short tour is not automatically preferred over early discovery.
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "baseline" / "code"
for path in (ROOT, BASELINE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from experiment.simulator import make_sources  # noqa: E402
from geometry.q4_sparse_mesh import q4_sparse25_points  # noqa: E402


PRODUCTION = (0, 1, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2,
              14, 13, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15)


def audible(source, point):
    dx = point[0] - source.x
    dy = point[1] - source.y
    if math.hypot(dx, dy) > source.r_eff + 1e-9:
        return False
    angle = math.degrees(math.atan2(dy, dx)) % 360.0
    error = abs((angle - source.orientation + 180.0) % 360.0 - 180.0)
    return (not source.directional) or error <= 90.0 + 1e-9


def sample_masks(samples, seed):
    points = q4_sparse25_points()
    masks = np.zeros((samples, 16, 25), dtype=np.bool_)
    for row in range(samples):
        sources = make_sources("Q4", seed + row, n_sources=16,
                               scenario="random")
        for i, source in enumerate(sources):
            for j, point in enumerate(points):
                masks[row, i, j] = audible(source, point)
    if not np.all(np.any(masks, axis=2)):
        raise RuntimeError("sparse25 failed to hear a sampled source")
    return masks


def objective(order, masks, points):
    """Mean approximate virtual seconds until all 16 channels are heard."""
    seen = np.zeros(masks.shape[:2], dtype=np.bool_)
    done = np.zeros(masks.shape[0], dtype=np.bool_)
    total = np.zeros(masks.shape[0], dtype=np.float64)
    previous = points[order[0]]
    for step, index in enumerate(order):
        point = points[index]
        if step:
            total[~done] += math.dist(previous, point) / 5.0
        # Every still-unknown channel is measured at a certificate stop.  Six
        # seconds is the normal 5 s measurement plus a channel switch.  The
        # first channel can save one switch, which is order-independent here.
        total[~done] += 6.0 * np.sum(~seen[~done], axis=1)
        seen |= masks[:, :, index]
        done |= np.all(seen, axis=1)
        previous = point
        if np.all(done):
            break
    return float(np.mean(total))


def route_length(order, points):
    return sum(math.dist(points[a], points[b])
               for a, b in zip(order, order[1:]))


def mutate(order, rng):
    candidate = list(order)
    a, b = sorted(rng.sample(range(1, len(candidate)), 2))
    if rng.random() < 0.55:
        candidate[a:b + 1] = reversed(candidate[a:b + 1])
    else:
        candidate[a], candidate[b] = candidate[b], candidate[a]
    return tuple(candidate)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=4000)
    parser.add_argument("--iterations", type=int, default=60000)
    parser.add_argument("--seed", type=int, default=74021)
    parser.add_argument("--max-route-ratio", type=float, default=1.08)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    points = q4_sparse25_points()
    masks = sample_masks(args.samples, args.seed * 1000)
    current = PRODUCTION
    current_score = objective(current, masks, points)
    best, best_score = current, current_score
    start_score = current_score
    route_limit = route_length(PRODUCTION, points) * args.max_route_ratio
    for iteration in range(args.iterations):
        fraction = iteration / max(1, args.iterations - 1)
        temperature = 80.0 * (0.01 / 80.0) ** fraction
        candidate = mutate(current, rng)
        if route_length(candidate, points) > route_limit:
            continue
        score = objective(candidate, masks, points)
        delta = score - current_score
        if delta <= 0.0 or rng.random() < math.exp(-delta / temperature):
            current, current_score = candidate, score
        if score < best_score:
            best, best_score = candidate, score
    print("production_score_s=%.3f" % start_score)
    print("best_score_s=%.3f" % best_score)
    print("improvement_s=%.3f" % (start_score - best_score))
    print("route_length_m=%.3f" % route_length(best, points))
    print("order=%r" % (best,))


if __name__ == "__main__":
    main()
