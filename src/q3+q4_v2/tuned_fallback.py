"""Per-strategy fallback patience without changing the frozen baseline file."""
from __future__ import annotations

import math

from policy.fallback import FallbackTracker
import policy.fallback as _fallback_module
from geometry.fallback_cover import disk_lattice_cover, order_greedy


def _open_path_2opt(points, start, max_passes=2, preserve_existing=False):
    """Improve a finite clear route with fixed start and free endpoint.

    The fallback set is a certificate, so this only permutes pending points;
    it never drops or invents a point.  The endpoint is intentionally free:
    the robot may finish at the last useful clear point instead of returning
    to the first point or to the depot.
    """
    order = list(points) if preserve_existing else order_greedy(points, start)
    n = len(order)
    if n < 3:
        return order
    # Fallback regions are normally small.  Keep a long pathological cover
    # bounded so replanning after each failed clear cannot dominate runtime.
    head_n = min(n, 160)
    # The first few nearest points are the most likely to contain the source
    # (and the old tracker deliberately starts there).  Keep that prefix
    # fixed; optimize only after those safe opportunities have failed.
    guard = min(80, head_n)
    prefix = order[:guard]
    head = order[guard:head_n]
    tail = order[head_n:]
    if len(head) < 2:
        return order

    def d(a, b):
        return math.dist(a, b)

    for _ in range(max(1, int(max_passes))):
        changed = False
        for i in range(len(head) - 1):
            before_node = prefix[-1] if i == 0 else head[i - 1]
            for j in range(i + 1, len(head)):
                after_node = head[j + 1] if j + 1 < len(head) else None
                before = d(before_node, head[i])
                after = d(before_node, head[j])
                if after_node is not None:
                    before += d(head[j], after_node)
                    after += d(head[i], after_node)
                if after + 1e-7 < before:
                    head[i:j + 1] = reversed(head[i:j + 1])
                    changed = True
        if not changed:
            break
    return prefix + head + tail


class TunedFallbackTracker(FallbackTracker):
    """FallbackTracker with an explicit no-shrink threshold for one run.

    The legacy tracker remains byte-for-byte frozen for provenance checks. The
    strategy-owned wrapper temporarily supplies the threshold only while the
    inherited progress update executes; all cover generation and completion
    semantics stay in the baseline implementation.
    """

    def __init__(self, no_shrink_limit, order_mode="greedy"):
        super().__init__()
        self.no_shrink_limit = int(no_shrink_limit)
        self.order_mode = str(order_mode or "greedy")

    def enter_fallback(self, ch_state, position, trigger):
        """Use the inherited finite cover with an optional center-first order."""
        if self.order_mode == "greedy":
            return super().enter_fallback(ch_state, position, trigger)
        poly = ch_state.feasible_region
        points = disk_lattice_cover(poly)
        center = ch_state.mec[0]
        current = (float(position[0]), float(position[1]))
        if self.order_mode == "center":
            points.sort(key=lambda p: (math.dist(p, center),
                                       math.dist(p, current), p[0], p[1]))
        elif self.order_mode == "center_route":
            # Blend center likelihood with travel so the first few points stay
            # cheap without abandoning the posterior center prior.
            points.sort(key=lambda p: (math.dist(p, center)
                                       + 0.35 * math.dist(p, current),
                                       math.dist(p, current), p[0], p[1]))
        elif self.order_mode == "route_center":
            points = order_greedy(points, current)
            points.sort(key=lambda p: (0.65 * math.dist(p, current)
                                       + math.dist(p, center),
                                       math.dist(p, center), p[0], p[1]))
        elif self.order_mode == "bearing":
            dirs = [obs for obs in ch_state.observations
                    if obs.get("result") == "direction"
                    and obs.get("bearing") is not None]
            if not dirs:
                points = order_greedy(points, current)
            else:
                last = dirs[-1]
                theta = math.radians(float(last["bearing"]))
                ux, uy = math.cos(theta), math.sin(theta)
                ox, oy = last["position"]

                def bearing_key(p):
                    dx, dy = p[0] - ox, p[1] - oy
                    cross = abs(dx * uy - dy * ux)
                    along = dx * ux + dy * uy
                    # Stay close to the observed ray first, then prefer a
                    # forward point and a short move from the current robot.
                    return (cross, 0.0 if along >= 0.0 else 1.0,
                            abs(along), math.dist(p, current), p[0], p[1])
                points.sort(key=bearing_key)
        else:
            return super().enter_fallback(ch_state, position, trigger)
        from geometry.fallback_cover import cover_point_estimate
        from geometry.polygon import area
        rec = {
            "channel": ch_state.channel_id,
            "trigger": trigger,
            "region_area": area(poly) if poly else 0.0,
            "estimated_points": cover_point_estimate(poly),
            "n_points": len(points),
            "used": 0,
            "result": None,
            "region": [tuple(v) for v in poly] if poly else None,
            "points": [tuple(p) for p in points],
        }
        self._fallback[ch_state.channel_id] = {
            "points": points, "index": 0, "record": rec,
        }
        return rec

    def note_measure(self, ch_state, r_before, r_after, signal):
        old = _fallback_module.NO_SHRINK_LIMIT
        _fallback_module.NO_SHRINK_LIMIT = self.no_shrink_limit
        try:
            return super().note_measure(ch_state, r_before, r_after, signal)
        finally:
            _fallback_module.NO_SHRINK_LIMIT = old

    def optimize_remaining(self, channel_id, position, max_passes=2):
        """Replan pending points as an open path from ``position``.

        The already attempted prefix stays fixed.  Returning the first point
        lets every scheduler use this without peeking into tracker internals.
        """
        st = self._fallback.get(channel_id)
        if st is None:
            return None
        idx = int(st["index"])
        pending = list(st["points"][idx:])
        if not pending:
            return None
        ordered = _open_path_2opt(
            pending, (float(position[0]), float(position[1])), max_passes,
            preserve_existing=True)
        st["points"][idx:] = ordered
        return ordered[0]
