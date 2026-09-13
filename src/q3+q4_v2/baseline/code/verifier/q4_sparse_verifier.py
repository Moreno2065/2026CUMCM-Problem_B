# -*- coding: utf-8 -*-
"""Independent verifier for the Q4 deterministic 25-point sparse mesh.

This module deliberately reconstructs the expected points and triangles instead
of importing a production mesh or certificate predicate.
"""

import math
from collections.abc import Mapping
from numbers import Real

from geometry.constants import OMEGA_RADIUS, R_EFF_MIN


INNER_RADIUS = 950.0
OUTER_RADIUS = 1870.0
RING_SIZE = 12
CANDIDATE_DOMAIN_RADIUS = 5000.0
DEFAULT_MATCH_TOL = 1e-6
RADIUS_TOL = 1e-6
ANGLE_TOL_RAD = 2e-9
EDGE_TOL = 1e-9
DOMAIN_TOL = 1e-9


def _expected_points():
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


_EXPECTED = _expected_points()
# Certificate tolerance is part of the frozen proof contract.  A caller may
# demand stricter matching, but cannot expand the verifier's acceptance region.
MAX_SAFE_MATCH_TOL = DEFAULT_MATCH_TOL


def _coerce_points(points):
    if isinstance(points, (Mapping, str, bytes)):
        raise TypeError("points must be an iterable of coordinate pairs")
    converted = []
    for point in points:
        if isinstance(point, (Mapping, str, bytes)):
            raise TypeError("each point must be a coordinate pair")
        coordinates = tuple(point)
        if len(coordinates) != 2:
            raise ValueError("each point must contain exactly two coordinates")
        converted.append((float(coordinates[0]), float(coordinates[1])))
    return converted


def _maximum_bipartite_matching(adjacency, n_right):
    """Return a deterministic maximum left-to-right matching.

    ``adjacency[left]`` contains candidate right-side indices.  Kuhn's
    augmenting-path algorithm prevents an early ambiguous choice from stranding
    a later expected point.
    """
    right_owner = {}

    def augment(left, visited):
        for right in adjacency[left]:
            if right < 0 or right >= n_right or right in visited:
                continue
            visited.add(right)
            owner = right_owner.get(right)
            if owner is None or augment(owner, visited):
                right_owner[right] = left
                return True
        return False

    for left in range(len(adjacency)):
        augment(left, set())
    return {left: right for right, left in right_owner.items()}


def _one_to_one_matches(points, match_tol):
    """Map expected points to observations using maximum bipartite matching."""
    adjacency = []
    for expected in _EXPECTED:
        candidates = [
            (math.dist(point, expected), input_index)
            for input_index, point in enumerate(points)
            if math.dist(point, expected) <= match_tol
        ]
        candidates.sort()
        adjacency.append([input_index for _, input_index in candidates])
    mapping = _maximum_bipartite_matching(adjacency, len(points))
    missing = [index for index in range(len(_EXPECTED))
               if index not in mapping]
    return mapping, missing


def _angle_error(actual, expected):
    delta = math.atan2(actual[1], actual[0]) - expected
    return abs((delta + math.pi) % (2.0 * math.pi) - math.pi)


def _point_line_distance(origin, a, b):
    edge_x = b[0] - a[0]
    edge_y = b[1] - a[1]
    denominator = math.hypot(edge_x, edge_y)
    if denominator == 0.0:
        return 0.0
    cross = abs(edge_x * (origin[1] - a[1])
                - edge_y * (origin[0] - a[0]))
    return cross / denominator


def _polar_angle(point):
    return math.atan2(point[1], point[0]) % (2.0 * math.pi)


def _signed_triangle_area(a, b, c):
    return 0.5 * ((b[0] - a[0]) * (c[1] - a[1])
                  - (b[1] - a[1]) * (c[0] - a[0]))


def _polygon_area(points):
    return 0.5 * abs(sum(
        points[k][0] * points[(k + 1) % len(points)][1]
        - points[k][1] * points[(k + 1) % len(points)][0]
        for k in range(len(points))
    ))


def _triangles_from_geometry(points, center_index, inner_indices,
                             outer_indices):
    """Derive mesh adjacency from radial classes and cyclic angular order."""
    inner = sorted(inner_indices, key=lambda index: _polar_angle(points[index]))
    outer = sorted(outer_indices, key=lambda index: _polar_angle(points[index]))
    triangles = []

    # Center fan: adjacent inner-ring vertices in counter-clockwise order.
    for k in range(RING_SIZE):
        triangles.append((center_index, inner[k], inner[(k + 1) % RING_SIZE]))

    for k, outer_index in enumerate(outer):
        next_outer = outer[(k + 1) % RING_SIZE]
        outer_angle = _polar_angle(points[outer_index])

        # The inner vertex immediately counter-clockwise from O_k lies between
        # O_k and O_(k+1), so it closes the outer-edge triangle.
        after = min(
            inner,
            key=lambda index: ((_polar_angle(points[index]) - outer_angle)
                               % (2.0 * math.pi), index),
        )
        before = min(
            inner,
            key=lambda index: ((outer_angle - _polar_angle(points[index]))
                               % (2.0 * math.pi), index),
        )
        triangles.append((outer_index, next_outer, after))
        triangles.append((outer_index, after, before))
    return triangles, inner, outer


def _mesh_failure_result(n_points, failures):
    return {"ok": False, "n_points": n_points, "n_triangles": 0,
            "outer_inradius": None, "max_triangle_edge": None,
            "triangles_unique": False,
            "triangles_nondegenerate": False,
            "triangles_consistently_oriented": False,
            "triangle_area": None, "outer_area": None,
            "failures": failures}


def verify_q4_sparse25_mesh(points):
    """Verify the fixed 25-point geometry and its 36 intended triangles."""
    failures = []
    try:
        pts = _coerce_points(points)
    except Exception as exc:
        return _mesh_failure_result(
            0, ["invalid point input: %s" % exc])

    if len(pts) != 25:
        failures.append("expected exactly 25 points, got %d" % len(pts))
    if not all(math.isfinite(x) and math.isfinite(y) for x, y in pts):
        return _mesh_failure_result(
            len(pts), ["all point coordinates must be finite"])

    duplicate_pairs = []
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            if math.dist(pts[i], pts[j]) <= DEFAULT_MATCH_TOL:
                duplicate_pairs.append((i, j))
    if duplicate_pairs:
        failures.append("points are not unique: %s" % duplicate_pairs[:3])

    outside = [i for i, point in enumerate(pts)
               if math.hypot(*point) > CANDIDATE_DOMAIN_RADIUS + DOMAIN_TOL]
    if outside:
        failures.append("points outside B(0,5000): %s" % outside)

    mapping, missing = _one_to_one_matches(pts, DEFAULT_MATCH_TOL)
    if missing:
        failures.append("expected-point match missing at indices: %s" % missing)

    if 0 in mapping and math.hypot(*pts[mapping[0]]) > RADIUS_TOL:
        failures.append("center is outside center tolerance")
    for k in range(RING_SIZE):
        canonical_index = 1 + k
        if canonical_index not in mapping:
            continue
        point = pts[mapping[canonical_index]]
        if abs(math.hypot(*point) - INNER_RADIUS) > RADIUS_TOL:
            failures.append("inner radius mismatch at k=%d" % k)
        expected_angle = math.radians(15.0 + 30.0 * k)
        if _angle_error(point, expected_angle) > ANGLE_TOL_RAD:
            failures.append("inner angular stagger mismatch at k=%d" % k)
    for k in range(RING_SIZE):
        canonical_index = 13 + k
        if canonical_index not in mapping:
            continue
        point = pts[mapping[canonical_index]]
        if abs(math.hypot(*point) - OUTER_RADIUS) > RADIUS_TOL:
            failures.append("outer radius mismatch at k=%d" % k)
        expected_angle = math.radians(30.0 * k)
        if _angle_error(point, expected_angle) > ANGLE_TOL_RAD:
            failures.append("outer angle mismatch at k=%d" % k)

    radii = [math.hypot(*point) for point in pts]
    center_indices = [i for i, radius in enumerate(radii)
                      if radius <= RADIUS_TOL]
    inner_indices = [i for i, radius in enumerate(radii)
                     if abs(radius - INNER_RADIUS) <= RADIUS_TOL]
    outer_indices = [i for i, radius in enumerate(radii)
                     if abs(radius - OUTER_RADIUS) <= RADIUS_TOL]
    if len(center_indices) != 1:
        failures.append("geometry classification found %d centers"
                        % len(center_indices))
    if len(inner_indices) != RING_SIZE:
        failures.append("geometry classification found %d inner points"
                        % len(inner_indices))
    if len(outer_indices) != RING_SIZE:
        failures.append("geometry classification found %d outer points"
                        % len(outer_indices))

    reconstructed = []
    ordered_outer = []
    if (len(center_indices) == 1 and len(inner_indices) == RING_SIZE
            and len(outer_indices) == RING_SIZE):
        reconstructed, _, ordered_outer = _triangles_from_geometry(
            pts, center_indices[0], inner_indices, outer_indices)
    if len(reconstructed) != 36:
        failures.append("reconstructed %d of 36 intended triangles"
                        % len(reconstructed))

    normalized_triangles = [frozenset(triangle)
                            for triangle in reconstructed]
    triangles_unique = (len(normalized_triangles) == 36
                        and len(set(normalized_triangles)) == 36)
    if not triangles_unique:
        failures.append("reconstructed triangles are not 36 unique cells")

    signed_areas = [
        _signed_triangle_area(*(pts[index] for index in triangle))
        for triangle in reconstructed
    ]
    triangles_nondegenerate = (len(signed_areas) == 36
                               and all(abs(value) > 1e-9
                                       for value in signed_areas))
    triangles_oriented = (len(signed_areas) == 36
                          and all(value > 1e-9 for value in signed_areas))
    if not triangles_nondegenerate:
        failures.append("reconstructed mesh contains degenerate triangles")
    if not triangles_oriented:
        failures.append("reconstructed triangles are not consistently CCW")

    max_edge = None
    for triangle in reconstructed:
        a, b, c = (pts[index] for index in triangle)
        for edge in ((a, b), (b, c), (c, a)):
            length = math.dist(*edge)
            max_edge = length if max_edge is None else max(max_edge, length)
    if max_edge is not None and max_edge > R_EFF_MIN + EDGE_TOL:
        failures.append("maximum triangle edge exceeds R_EFF_MIN")

    outer_inradius = None
    outer_area = None
    triangle_area = (sum(abs(value) for value in signed_areas)
                     if signed_areas else None)
    if len(ordered_outer) == RING_SIZE:
        outer = [pts[index] for index in ordered_outer]
        outer_inradius = min(
            _point_line_distance((0.0, 0.0), outer[k],
                                 outer[(k + 1) % RING_SIZE])
            for k in range(RING_SIZE)
        )
        if outer_inradius < OMEGA_RADIUS - EDGE_TOL:
            failures.append("outer dodecagon inradius is below OMEGA_RADIUS")
        outer_area = _polygon_area(outer)
        area_tolerance = max(1e-6, outer_area * 1e-12)
        if (triangle_area is None
                or abs(triangle_area - outer_area) > area_tolerance):
            failures.append("triangle area does not equal outer dodecagon area")

    return {"ok": not failures,
            "n_points": len(pts),
            "n_triangles": len(reconstructed),
            "outer_inradius": outer_inradius,
            "max_triangle_edge": max_edge,
            "triangles_unique": triangles_unique,
            "triangles_nondegenerate": triangles_nondegenerate,
            "triangles_consistently_oriented": triangles_oriented,
            "triangle_area": triangle_area,
            "outer_area": outer_area,
            "failures": failures}


def verify_q4_sparse25_channel(no_signal_points,
                               match_tol=DEFAULT_MATCH_TOL):
    """Verify that every expected mesh point has a distinct observation.

    Input order is irrelevant and additional no-signal observations are allowed.
    """
    invalid = {"ok": False, "matched_count": 0,
               "missing_indices": list(range(25)), "failures": []}
    if isinstance(match_tol, bool) or not isinstance(match_tol, Real):
        invalid["failures"].append("match tolerance must be a finite number")
        return invalid
    tolerance = float(match_tol)
    if not math.isfinite(tolerance) or tolerance < 0.0:
        invalid["failures"].append("match tolerance must be finite and nonnegative")
        return invalid
    if tolerance > MAX_SAFE_MATCH_TOL:
        invalid["failures"].append(
            "match tolerance exceeds fixed certificate limit %.12g"
            % MAX_SAFE_MATCH_TOL)
        return invalid

    try:
        points = _coerce_points(no_signal_points)
    except Exception as exc:
        invalid["failures"].append("invalid point input: %s" % exc)
        return invalid
    if not all(math.isfinite(x) and math.isfinite(y) for x, y in points):
        invalid["failures"].append("all point coordinates must be finite")
        return invalid
    outside = [index for index, point in enumerate(points)
               if math.hypot(*point) > CANDIDATE_DOMAIN_RADIUS + DOMAIN_TOL]
    if outside:
        invalid["failures"].append("observations outside B(0,5000): %s"
                                   % outside[:10])
        return invalid

    mapping, missing = _one_to_one_matches(points, tolerance)
    failures = []
    if missing:
        failures.append("expected-point match missing at indices: %s" % missing)
    return {"ok": not failures,
            "matched_count": len(mapping),
            "missing_indices": missing,
            "failures": failures}
