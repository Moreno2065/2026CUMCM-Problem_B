"""Verify a triangular-lattice Q4 certificate and refine it.

Certificate contract (same as sparse25, restated): a point set P certifies
every possible Q4 source state (position ``g`` in Ω, facing direction ``u``)
when for each state some ``p ∈ P`` satisfies ``|p - g| <= 1000`` (guaranteed
reception) and ``u . (p - g) >= 0`` (visible side).  Equivalently, ``g`` must
lie in the convex hull of the certificate points within 1000 m of it.

A triangular lattice of spacing ``s`` has circumradius ``s / sqrt(3)``, so every
position sits inside a triangle whose three vertices are that close: any
``s <= 1000 * sqrt(3)`` gives a valid certificate, with the margin controlled by
using a smaller spacing.  This script verifies that claim on a dense state grid
and then greedily prunes the lattice.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "baseline" / "code"))
from geometry import constants as C                       # noqa: E402


def triangular_lattice(spacing, margin=1100.0):
    """Equilateral triangular lattice covering the disk of radius Ω+margin."""
    points = []
    height = spacing * math.sqrt(3.0) / 2.0
    radius = C.OMEGA_RADIUS + margin
    rows = int(math.ceil(2.0 * radius / height)) + 1
    for row in range(-rows, rows + 1):
        y = row * height
        offset = (spacing / 2.0) if (row % 2) else 0.0
        columns = int(math.ceil(2.0 * radius / spacing)) + 1
        for column in range(-columns, columns + 1):
            x = column * spacing + offset
            if x * x + y * y <= radius * radius:
                points.append((x, y))
    return points


def sample_states(step=60.0, directions=36):
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


def coverage(points, states, radius=C.R_EFF_MIN):
    """Return (uncovered state indices, per-point masks)."""
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
    union = 0
    for mask in masks:
        union |= mask
    full = (1 << len(states)) - 1
    return full & ~union, masks


def main():
    states = sample_states()
    print("states: %d (60 m grid x 36 directions)" % len(states))
    for spacing in (1700.0, 1600.0, 1500.0, 1400.0, 1300.0):
        points = triangular_lattice(spacing)
        missing, masks = coverage(points, states)
        count = bin(missing).count("1")
        print("spacing %5.0f m (%d points): uncovered %d states (%.4f%%)" %
              (spacing, len(points), count, 100.0 * count / len(states)))
        if count == 0:
            # Greedy pruning: drop points whose states are covered by others.
            keep = list(range(len(points)))
            changed = True
            while changed:
                changed = False
                for index in list(keep):
                    others = 0
                    for other in keep:
                        if other != index:
                            others |= masks[other]
                    if others == (1 << len(states)) - 1:
                        keep.remove(index)
                        changed = True
            print("    locally minimal after pruning: %d points" % len(keep))


if __name__ == "__main__":
    main()
