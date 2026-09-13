"""Choose guaranteed clear positions using both adjacent route legs."""
import math

from geometry.clear_zone import closest_clear_point
from geometry import constants as C


def clear_on_route(vertices, current, previous, following=None):
    """Projected Weiszfeld steps on the convex legal-clear region.

    Each accepted point covers every vertex of the conservative feasible
    polygon and reduces the two-leg distance. No source truth is used.
    """
    if not vertices:
        return current

    def cost(p):
        return math.dist(previous, p) + (math.dist(p, following)
                                         if following is not None else 0.0)

    best = tuple(current)
    for _ in range(8):
        if following is None:
            reference = previous
        else:
            left = max(1e-8, math.dist(best, previous))
            right = max(1e-8, math.dist(best, following))
            reference = tuple((a * right + b * left) / (left + right)
                              for a, b in zip(previous, following))
        candidate = closest_clear_point(vertices, reference)
        # Numeric tolerance never licenses a point outside the legal radius.
        if any(math.dist(candidate, v) > C.CLEAR_RADIUS for v in vertices):
            break
        if cost(candidate) >= cost(best) - 1e-7:
            break
        best = tuple(candidate)
    return best


def optimise(policy, ordered, ks, position):
    initial = policy._open_route_length(ordered, position)
    for _ in range(2):
        before = policy._open_route_length(ordered, position)
        for index, (cid, point, kind) in enumerate(ordered):
            if kind != 'clear' or ks[cid].mec_radius > C.CLEAR_RADIUS:
                continue
            previous = position if index == 0 else ordered[index - 1][1]
            following = ordered[index + 1][1] if index + 1 < len(ordered) else None
            target = clear_on_route(ks[cid].feasible_region, point, previous, following)
            ordered[index] = (cid, target, kind)
        ordered = policy._exact_open_order(ordered, position)
        if before - policy._open_route_length(ordered, position) < 1e-5:
            break
    saving = initial - policy._open_route_length(ordered, position)
    if saving > 1e-5:
        policy.compact_stats['clear_region_routes'] += 1
        policy.compact_stats['clear_region_projected_saving_m'] += saving
    return ordered
