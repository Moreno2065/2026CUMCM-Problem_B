# -*- coding: utf-8 -*-
"""Q4 deterministic 25-point sparse triangular mesh."""

import math


INNER_RADIUS = 950.0
OUTER_RADIUS = 1870.0
RING_SIZE = 12
MATCH_TOL = 1e-6


def q4_sparse25_points():
    """Return center, staggered inner ring, then outer ring (25 points)."""
    points = [(0.0, 0.0)]
    for k in range(RING_SIZE):
        angle = math.radians(15.0 + 30.0 * k)
        points.append((INNER_RADIUS * math.cos(angle),
                       INNER_RADIUS * math.sin(angle)))
    for k in range(RING_SIZE):
        angle = math.radians(30.0 * k)
        points.append((OUTER_RADIUS * math.cos(angle),
                       OUTER_RADIUS * math.sin(angle)))
    return points


def q4_sparse25_triangles():
    """Return the 36 fixed triangle index triples for ``q4_sparse25_points``."""
    triangles = []
    for k in range(RING_SIZE):
        triangles.append((0, 1 + k, 1 + (k + 1) % RING_SIZE))
    for k in range(RING_SIZE):
        triangles.append((13 + k, 13 + (k + 1) % RING_SIZE, 1 + k))
    for k in range(RING_SIZE):
        triangles.append((13 + k, 1 + k, 1 + (k - 1) % RING_SIZE))
    return triangles


def q4_channel_certified_sparse25(no_signal_points):
    """Return whether all 25 fixed mesh points have no-signal witnesses.

    This is the production state-transition predicate.  The independent
    verifier deliberately reconstructs the same contract in
    ``verifier.q4_sparse_verifier`` without importing this function.
    """
    try:
        points = [(float(point[0]), float(point[1]))
                  for point in no_signal_points]
    except (TypeError, ValueError, IndexError, KeyError):
        return False
    if not all(math.isfinite(x) and math.isfinite(y) for x, y in points):
        return False
    return all(
        any(math.dist(expected, observed) <= MATCH_TOL
            for observed in points)
        for expected in q4_sparse25_points()
    )
