"""Belief + probe + short-horizon search scheduler.

The state remains the observable KnowledgeState. This policy uses calibrated
surrogates (existence probability, angular uncertainty and probe value) to
rank legal candidate actions, then hands unresolved work to the inherited
finite certificate/fallback mechanism. No hidden source list is read.
"""
from __future__ import annotations

import math

from geometry import constants as C
from policy import localization
from geometry.certificate import q4_lattice_points
from geometry.q4_sparse_mesh import q4_sparse25_points
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


class BeliefProbeScheduler(RollingCandidatePlanner, Scheduler):
    """Posterior-style action ranking with explicit probe economics."""

    Q4_ACTIVE_REPEAT_LIMIT = 3
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

    @staticmethod
    def _existence_probability(channel):
        status = channel.status
        if status in (ChannelStatus.CLEARED, ChannelStatus.CERTIFIED_ABSENT):
            return 0.0
        if status in (ChannelStatus.ACTIVE, ChannelStatus.READY):
            return 1.0
        # Prior conditioned on 10..16 sources among 20 channels, mildly
        # adjusted by repeated no-signal evidence. This is a decision prior,
        # not an official source-count claim.
        no_signal = sum(obs["result"] == "no_signal" for obs in channel.observations)
        return max(0.04, min(0.80, 0.65 * (0.72 ** no_signal)))

    @staticmethod
    def _angular_uncertainty(channel):
        dirs = [obs for obs in channel.observations if obs["result"] == "direction"]
        if not dirs:
            return 1.0
        return min(1.0, 1.0 / math.sqrt(len(dirs)))

    def _candidate_points(self, ch, position):
        points = localization.candidate_points(
            ch, position,
            failed_points=self.failed_points.get(ch.channel_id),
            opportunistic_reuse=True)
        if self.mode == "Q4":
            dirs = [obs for obs in ch.observations if obs["result"] == "direction"]
            if dirs and math.dist(dirs[-1]["position"], position) > 100.0:
                points = [p for p in points if math.dist(p, position) >= 1.0]
        return points

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
            p_exist = self._existence_probability(ch)
            uncertainty = self._angular_uncertainty(ch)
            points = self._candidate_points(ch, position)
            for point in points:
                move = math.dist(position, point)
                cost = move / C.MOVE_SPEED + C.MEASURE_TIME
                if ch.channel_id != current_channel:
                    cost += C.SWITCH_TIME
                # Surrogate expected value of information: larger unresolved
                # region and fewer bearings increase the branch value.
                radius_value = min(1500.0, max(20.0, ch.mec_radius))
                local_information = p_exist * uncertainty * radius_value
                nearby = sum(1 for other in active if other is not ch
                             and math.dist(point, other.mec[0]) < 500.0)
                # Probe bonus is the exact local form 3+2p+E[V] folded into a
                # ranking: a likely clear opportunity gets a positive bonus,
                # while detours are charged in the denominator.
                probe_probability = min(0.98, p_exist * (0.25 + 0.50 * uncertainty))
                probe_bonus = max(0.0, 80.0 * probe_probability - 3.0)
                score = (local_information + 24.0 * nearby + probe_bonus) / max(cost, 1e-9)
                record = {"channel": ch.channel_id, "point": list(point),
                          "cost": cost, "existence_probability": p_exist,
                          "angular_uncertainty": uncertainty,
                          "probe_probability": probe_probability,
                          "probe_bonus": probe_bonus, "nearby_active": nearby,
                          "score": score, "kind": "belief_probe_search"}
                trace_candidates.append(record)
                key = (score, probe_probability, nearby, -cost, -ch.channel_id)
                if best is None or key > best[0]:
                    best = (key, ch, point, record)
        if best is None:
            return None
        _, ch, point, record = best
        if self.decision_listener is not None:
            base = self._trace_base(ks, "belief_probe_active")
            base["candidates"] = trace_candidates
            base["selected"] = record
            base["tie_break"] = "max calibrated probe/information score"
            self._emit(base)
        return Mission("measure", point, channel=ch.channel_id,
                       meta={"kind": "nbv", "score": record["score"],
                             "gain": record["probe_bonus"],
                             "cost": record["cost"]})

    def decide(self, ks, position, current_channel):
        if (self.mode == "Q3" and self._q3_limit_locked is None
                and self._coverage_index >= 1):
            self._q3_limit_locked = (
                self.Q3_NO_SHRINK_LIMIT_HIGH
                if len(ks.by_status(ChannelStatus.ACTIVE)) >= self.Q3_LIMIT_SWITCH_ACTIVE
                else self.Q3_NO_SHRINK_LIMIT)
            self.fallback.no_shrink_limit = self._q3_limit_locked
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
        """Choose the nearest pending finite-cover point globally."""
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

    def _coverage_scan(self, ks):
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
        return Mission("scan", point,
                       channels=[ch.channel_id for ch in ks.unknown],
                       meta={"coverage_scan": True, "kind": "coverage"})
