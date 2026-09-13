"""How small can the Q4 detection-covering certificate be?

A Q4 certificate point set must see every possible source: for every position
``g`` in Ω and every facing direction ``u``, at least one certificate point
``p`` must satisfy ``|g - p| <= 1000`` (guaranteed reception) and
``u . (p - g) >= 0`` (visible side).  This script measures the cover of the
current 25-point sparse mesh on a discretised (g, u) grid and then greedily
removes points that no (g, u) depends on, reporting the smallest subset that
still covers everything.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "baseline" / "code"))
from geometry.q4_sparse_mesh import q4_sparse25_points   # noqa: E402
from geometry import constants as C                       # noqa: E402


def sample_states(step=80.0, directions=24):
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


def coverage_mask(points, states, radius=C.R_EFF_MIN):
    """Bitmask per certificate point of the states it can see."""
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


def main():
    states = sample_states()
    print("states sampled: %d (position grid 80 m x 24 directions)" % len(states))
    full = (1 << len(states)) - 1
    points = q4_sparse25_points()
    masks = coverage_mask(points, states)
    union = 0
    for mask in masks:
        union |= mask
    print("25-point mesh covers %.2f%% of the state space" %
          (100.0 * bin(union).count("1") / len(states)))
    # Greedy removal: drop any point whose states are covered by the others.
    keep = list(range(len(points)))
    changed = True
    while changed:
        changed = False
        for index in list(keep):
            others = 0
            for other in keep:
                if other != index:
                    others |= masks[other]
            if others == full:
                keep.remove(index)
                changed = True
    covered = 0
    for index in keep:
        covered |= masks[index]
    print("minimal subset keeping full cover: %d points" % len(keep))
    print("   indices:", keep)
    print("   points :", [tuple(round(v) for v in points[i]) for i in keep])
    print("   still covers %.4f%%" %
          (100.0 * bin(covered).count("1") / len(states)))
    # How much of the state space each point uniquely owns (removal impact).
    for index in range(len(points)):
        others = 0
        for other in range(len(points)):
            if other != index:
                others |= masks[other]
        lost = bin(full & ~others).count("1")
        print("   point %2d at %-18s uniquely covers %5d states" %
              (index, tuple(round(v) for v in points[index]), lost))


if __name__ == "__main__":
    main()
