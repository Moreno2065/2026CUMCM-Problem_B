"""Geometry-first joint route scheduler.

It keeps the legacy executor's strict fallback/证书 path, but chooses ACTIVE
measurements with a route-aware objective. The objective evaluates bearing
shrinkage and the next unlocalized cluster, so a locally attractive point that
creates a long isolated tail is penalized.
"""
from __future__ import annotations

import math

from geometry import constants as C
from geometry.diameter import diameter_value
from geometry.nbv import worst_case_radius, worst_case_diameter
from geometry.certificate import q4_lattice_points
from geometry.q4_sparse_mesh import q4_sparse25_points
from policy import localization
from policy.scheduler import Mission, Scheduler
from state.channel_state import ChannelStatus
from tuned_fallback import TunedFallbackTracker
from rolling import RollingCandidatePlanner


def _greedy_order(points, start=(0.0, 0.0)):
    """Order a fixed certificate set by nearest-neighbour travel."""
    remaining = list(points)
    ordered = []
    here = (float(start[0]), float(start[1]))
    while remaining:
        i = min(range(len(remaining)), key=lambda j: math.dist(here, remaining[j]))
        here = remaining.pop(i)
        ordered.append(here)
    return ordered


class GeometryJointScheduler(RollingCandidatePlanner, Scheduler):
    """Route-aware geometry policy with inherited certified completion."""

    Q4_ACTIVE_REPEAT_LIMIT = 2
    Q3_NO_SHRINK_LIMIT = 9
    Q4_NO_SHRINK_LIMIT = 8
    Q3_NO_SHRINK_LIMIT_HIGH = 18
    Q3_LIMIT_SWITCH_ACTIVE = 6

    def __init__(self, *args, rolling_enabled=False, rolling_horizon=3,
                 rolling_coverage_period=3, rolling_probe_radius_m=0.0,
                 rolling_probe_max_distance_m=None,
                 rolling_joint_active_limit=1,
                 ready_open_route=False,
                 q3_thirteen_point=False,
                 q3_adaptive_coverage=False,
                 q3_direct_center=False,
                 q3_direct_center_radius_m=None,
                 q3_direct_center_max_distance_m=None,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self._init_rolling(rolling_enabled, rolling_horizon,
                           rolling_coverage_period,
                           rolling_probe_radius_m,
                           rolling_probe_max_distance_m,
                           rolling_joint_active_limit, ready_open_route)
        self.q3_thirteen_point = bool(q3_thirteen_point)
        self.q3_adaptive_coverage = bool(q3_adaptive_coverage)
        self.q3_direct_center = bool(q3_direct_center)
        self.q3_direct_center_radius_m = (
            None if q3_direct_center_radius_m is None else
            max(0.0, float(q3_direct_center_radius_m)))
        self.q3_direct_center_max_distance_m = (
            None if q3_direct_center_max_distance_m is None else
            max(0.0, float(q3_direct_center_max_distance_m)))
        self._q3_adaptive_coverage_locked = False
        self.fallback = TunedFallbackTracker(
            self.Q3_NO_SHRINK_LIMIT if self.mode == "Q3"
            else self.Q4_NO_SHRINK_LIMIT)
        self._coverage_index = 0
        self._coverage_points = []
        self._coverage_pending_point = None
        self._coverage_pending_active = None
        self._q3_limit_locked = None

    def _coverage_scan(self, ks):
        """One deterministic source-discovery/absence-coverage stop.

        Q3 uses a center plus six 1200 m points, which the exact disk-cover
        predicate accepts. Q4 uses the official 31-point triangular lattice.
        Unknown channels are scanned once at each point; active channels then
        move to the joint bearing branch. This gives every channel a finite
        completion path before route optimization starts.
        """
        if not self._coverage_points:
            if self.mode == "Q3":
                radius, count = ((870.0, 12) if self.q3_thirteen_point
                                 else (1200.0, 6))
                self._coverage_points = [(0.0, 0.0)] + [
                    (radius * math.cos(2.0 * math.pi * k / count),
                     radius * math.sin(2.0 * math.pi * k / count))
                    for k in range(count)]
            else:
                raw = (q4_sparse25_points()
                       if self.q4_certificate_layout == "sparse25"
                       else q4_lattice_points())
                self._coverage_points = _greedy_order(raw)
        if (self.mode == "Q3" and self.q3_adaptive_coverage and
                not self.q3_thirteen_point and
                not self._q3_adaptive_coverage_locked and
                self._coverage_index == 1):
            active_count = len(ks.by_status(ChannelStatus.ACTIVE))
            radius, count = ((870.0, 12) if active_count >= 7
                             else (1200.0, 6))
            self._coverage_points = [(0.0, 0.0)] + [
                (radius * math.cos(2.0 * math.pi * k / count),
                 radius * math.sin(2.0 * math.pi * k / count))
                for k in range(count)]
            self._q3_adaptive_coverage_locked = True
        if self.mode == "Q4" and self._coverage_pending_point is not None:
            if self._coverage_pending_active is None:
                self._coverage_pending_active = ([ch.channel_id for ch in ks.active]
                                                 if self._coverage_index <= self.Q4_ACTIVE_REPEAT_LIMIT else [])
            while self._coverage_pending_active:
                cid = self._coverage_pending_active.pop(0)
                if ks[cid].status == ChannelStatus.ACTIVE and not self.fallback.in_fallback(cid):
                    return Mission("measure", self._coverage_pending_point,
                                   channel=cid,
                                   meta={"kind": "coverage_active", "coverage_scan": True})
            self._coverage_pending_point = None
            self._coverage_pending_active = None
        if self._coverage_index >= len(self._coverage_points) or not ks.unknown:
            return None
        point = self._coverage_points[self._coverage_index]
        self._coverage_index += 1
        if self.mode == "Q4":
            self._coverage_pending_point = point
            self._coverage_pending_active = None
        channels = [ch.channel_id for ch in ks.unknown]
        return Mission("scan", point, channels=channels,
                       meta={"coverage_scan": True, "kind": "coverage"})

    def _candidate_gain(self, channel, point):
        radius = channel.mec_radius
        try:
            span = localization._adaptive_step(channel.feasible_region, point)
            if self.nbv_mode == "radius":
                remaining = worst_case_radius(
                    channel.feasible_region, point, span, C.BEARING_ERROR_DEG,
                    n_circle=16)[0]
            else:
                remaining = worst_case_diameter(
                    channel.feasible_region, point, span, C.BEARING_ERROR_DEG,
                    n_circle=16)[0]
                radius = diameter_value(channel.feasible_region)
            return max(0.0, radius - remaining)
        except (ArithmeticError, ValueError, TypeError):
            return 0.0

    def _active_measure(self, ks, position, current_channel):
        active = [ch for ch in ks.by_status(ChannelStatus.ACTIVE)
                  if not self.fallback.in_fallback(ch.channel_id)]
        if not active:
            return None
        direct = [ch for ch in active if (
            self.q3_direct_center_radius_m is None or
            ch.mec_radius <= self.q3_direct_center_radius_m) and
            math.dist(position, ch.mec[0]) > 1.0 and
            (self.q3_direct_center_max_distance_m is None or
             math.dist(position, ch.mec[0]) <=
             self.q3_direct_center_max_distance_m) and
            not any(math.dist(ch.mec[0], obs["position"]) <= 1.0
                    for obs in ch.observations if "position" in obs)]
        if self.mode == "Q3" and self.q3_direct_center and direct:
            ch = min(direct, key=lambda item: (
                math.dist(position, item.mec[0]) / C.MOVE_SPEED
                + (C.SWITCH_TIME if item.channel_id != current_channel else 0.0),
                -item.mec_radius, item.channel_id))
            return Mission("measure", ch.mec[0], channel=ch.channel_id,
                           meta={"kind": "approach", "direct_center": True})
        best = None
        trace_candidates = []
        for ch in active:
            points = localization.candidate_points(
                ch, position,
                failed_points=self.failed_points.get(ch.channel_id),
                opportunistic_reuse=True)
            for point in points:
                move = math.dist(position, point)
                cost = move / C.MOVE_SPEED + C.MEASURE_TIME
                if ch.channel_id != current_channel:
                    cost += C.SWITCH_TIME
                gain = self._candidate_gain(ch, point)
                # Approximate one-step route continuation over the other
                # current MECs. The coefficient is deliberately small: bearing
                # information remains primary, route geometry breaks ties.
                future = min((math.dist(point, other.mec[0])
                              for other in active if other is not ch),
                             default=0.0)
                cluster = sum(1.0 for other in active if other is not ch
                              and math.dist(point, other.mec[0]) < 600.0)
                score = (gain + 18.0 * cluster) / max(cost + 0.15 * future / C.MOVE_SPEED, 1e-9)
                record = {"channel": ch.channel_id, "point": list(point),
                          "gain": gain, "cost": cost, "score": score,
                          "future_m": future, "cluster_count": cluster,
                          "kind": "geometry_joint"}
                trace_candidates.append(record)
                key = (score, gain, -cost, cluster, -ch.channel_id)
                if best is None or key > best[0]:
                    best = (key, ch, point, record)
        if best is None:
            return None
        _, ch, point, record = best
        if self.decision_listener is not None:
            base = self._trace_base(ks, "geometry_joint_active")
            base["candidates"] = trace_candidates
            base["selected"] = record
            base["tie_break"] = "max route-aware geometry score, gain, min cost"
            self._emit(base)
        return Mission("measure", point, channel=ch.channel_id,
                       meta={"kind": "nbv", "score": record["score"],
                             "gain": record["gain"], "cost": record["cost"]})

    def decide(self, ks, position, current_channel):
        if (self.mode == "Q3" and self._q3_limit_locked is None
                and self._coverage_index >= 1):
            self._q3_limit_locked = (
                self.Q3_NO_SHRINK_LIMIT_HIGH
                if len(ks.by_status(ChannelStatus.ACTIVE)) >= self.Q3_LIMIT_SWITCH_ACTIVE
                else self.Q3_NO_SHRINK_LIMIT)
            self.fallback.no_shrink_limit = self._q3_limit_locked
        # Inherited branch is authoritative for fallback, READY and final
        # certificates. It is also the finite-completion safety net.
        if self.fallback.active_fallbacks():
            return self._fallback_route(ks, position, current_channel)
        rolling = self._rolling_decide(ks, position, current_channel)
        if rolling is not None:
            return rolling
        if ks.ready and self.ready_open_route:
            ready_route = self._ready_route_candidate(ks, position)
            if ready_route is not None:
                return ready_route
        if ks.ready:
            return super().decide(ks, position, current_channel)
        coverage = self._coverage_scan(ks)
        if coverage is not None:
            return coverage
        if ks.active:
            mission = self._active_measure(ks, position, current_channel)
            if mission is not None:
                return mission
        return super().decide(ks, position, current_channel)

    def _fallback_route(self, ks, position, current_channel):
        """Interleave finite fallback covers by travel plus switch time."""
        best = None
        for cid in self.fallback.active_fallbacks():
            ch = ks[cid]
            if ch.status != ChannelStatus.ACTIVE:
                self.fallback.finish(cid)
                continue
            pt = self.fallback.optimize_remaining(cid, position, max_passes=2)
            if pt is None:
                continue
            idx, total = self.fallback.index_total(cid)
            travel = math.dist(position, pt) / C.MOVE_SPEED
            switch = C.SWITCH_TIME if cid != current_channel else 0.0
            key = (travel + switch, travel, cid)
            if best is None or key < best[0]:
                best = (key, cid, pt, idx, total)
        if best is None:
            return super().decide(ks, position, current_channel)
        _, cid, pt, idx, total = best
        if self.decision_listener is not None:
            tr = self._trace_base(ks, "fallback_clear")
            tr["selected"] = {"kind": "clear", "channel": cid,
                              "point": [pt[0], pt[1]]}
            tr["tie_break"] = "min travel+switch time across fallback channels"
            tr["fallback_trigger"] = "fallback sequence %d/%d" % (idx, total)
            self._emit(tr)
        return Mission("clear", pt, channel=cid,
                       meta={"fallback": True,
                             "fallback_index": idx,
                             "fallback_total": total})
