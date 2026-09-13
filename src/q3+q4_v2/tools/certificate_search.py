"""Search for a smaller Q4 detection-covering certificate.

Same contract as ``certificate_minimality.py``: a point set P covers every
(position, facing direction) state in Ω when some p ∈ P satisfies
``|g - p| <= R`` and ``u . (p - g) >= 0``.  This script runs a greedy set cover
over a dense candidate grid (several radii and angular steps, inside and just
outside Ω) with a safety margin on the reception radius, and reports the
smallest set it finds plus the points it selects.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "baseline" / "code"))
from geometry import constants as C                       # noqa: E402


def sample_states(step=100.0, directions=24):
    states = []
    y = -C.OMEGA_RADIUS
    while y <= C.OMEGA_RADIUS + 1e-9:
        x = -C.OMEGA_RADIUS
        while x <= C.OMEGA_RADIUS + 1e-9:
            if x * x + y * y <= C.OMEGA_RADIUS ** 2:
                for k in range(directions):
                    angle = 2.0 * math.pi * k / directions
                    states.append((x, y, math.cos(angle), math.sin(angle)))
            x += step
        y += step
    return states


def candidate_points(radii=(0.0, 900.0, 1100.0, 1300.0, 1500.0, 1700.0,
                           1900.0, 2100.0), angles=24):
    points = []
    for radius in radii:
        if radius == 0.0:
            points.append((0.0, 0.0))
            continue
        for k in range(angles):
            angle = 2.0 * math.pi * k / angles
            points.append((radius * math.cos(angle), radius * math.sin(angle)))
    return points


def state_masks(points, states, radius):
    masks = []
    for px, py in points:
        mask = 0
        for index, (gx, gy, ux, uy) in enumerate(states):
            dx, dy = px - gx, py - gy
            if dx * dx + dy * dy > radius * radius:
                continue
            if ux * dx + uy * dy >= 0.0:
                mask |= (1 << index)
        masks.append(mask)
    return masks


def greedy_cover(masks, total_states):
    full = (1 << total_states) - 1
    covered = 0
    chosen = []
    sizes = [bin(mask).count("1") for mask in masks]
    while covered != full:
        best_index = None
        best_gain = -1
        for index, mask in enumerate(masks):
            if index in chosen:
                continue
            gain = bin(mask & ~covered).count("1")
            if gain > best_gain:
                best_gain, best_index = gain, index
        if best_index is None or best_gain <= 0:
            break
        chosen.append(best_index)
        covered |= masks[best_index]
    return chosen, covered, full, sizes


def main():
    states = sample_states()
    print("states: %d" % len(states))
    for margin in (1000.0, 950.0, 900.0):
        points = candidate_points()
        masks = state_masks(points, states, margin)
        chosen, covered, full, sizes = greedy_cover(masks, len(states))
        complete = covered == full
        print("radius %.0f m: greedy set cover -> %2d points, covers %5.2f%% %s"
              % (margin, len(chosen),
                 100.0 * bin(covered).count("1") / len(states),
                 "" if complete else "(INCOMPLETE)"))
        if complete and margin == 1000.0:
            chosen_points = sorted((round(points[i][0], 1),
                                    round(points[i][1], 1)) for i in chosen)
            print("   selected:", chosen_points)
    # Lower bound: one point can cover at most this many states.
    points = candidate_points()
    masks = state_masks(points, states, 1000.0)
    best = max(bin(mask).count("1") for mask in masks)
    print("single-point upper bound: %d states -> at least %d points needed"
          % (best, math.ceil(len(states) / best)))


if __name__ == "__main__":
    main()
