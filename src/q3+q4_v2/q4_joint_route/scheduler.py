"""Observation-only Q4 tail planner over ACTIVE and READY tasks.

The sparse25 certificate and cardinality completion rules remain unchanged.
Once every channel is resolved as present/absent, the planner asks the
existing bounded-error Q4 geometry model for one legal measurement point per
ACTIVE source.  Those points and guaranteed READY clear points are jointly
ordered by an exact fixed-start, free-end Held-Karp path.  Only the first
action is executed before replanning from the new observation.
"""
from __future__ import annotations

import math

from geometry import constants as C
from learned_search.scheduler import LearnedSearchScheduler
from policy import localization
from policy.scheduler import Mission
from state.channel_state import ChannelStatus


class Q4JointRouteScheduler(LearnedSearchScheduler):
    def __init__(self, mode="Q4", *, q4jr_active_attempts=3,
                 q4jr_optical_cover_points=0,
                 q4jr_share_coverage=False,
                 q4jr_coverage_active_limit=3,
                 q4jr_coverage_min_mec=80.0,
                 q4jr_tail_enabled=True,
                 q4jr_route_ready=False,
                 q4jr_include_nbv=False, **kwargs):
        if mode != "Q4":
            raise ValueError("q4-joint-route only supports Q4")
        super().__init__(mode, **kwargs)
        self.q4jr_optical_cover_points = max(
            0, int(q4jr_optical_cover_points))
        self.q4jr_active_attempts = max(0, int(q4jr_active_attempts))
        self.q4jr_share_coverage = bool(q4jr_share_coverage)
        self.q4jr_coverage_active_limit = max(
            0, int(q4jr_coverage_active_limit))
        self.q4jr_coverage_min_mec = max(
            0.0, float(q4jr_coverage_min_mec))
        self.q4jr_tail_enabled = bool(q4jr_tail_enabled)
        self.q4jr_route_ready = bool(q4jr_route_ready)
        self.q4jr_include_nbv = bool(q4jr_include_nbv)
        self._q4jr_attempts = {}
        self.q4jr_stats = dict(route_decisions=0, active_measures=0,
                               ready_clears=0, exact_nodes_max=0,
                               coverage_joint_planned=0,
                               coverage_joint_stops=0)

    @staticmethod
    def _known_count(ks):
        return len(ks.active) + len(ks.ready) + len(ks.cleared)

    @staticmethod
    def _exact_open_order(items, start):
        """Exact path through fixed points, with fixed start and free end."""
        items = sorted(items, key=lambda item: (item[0], item[2]))
        n = len(items)
        if n <= 1:
            return items
        points = [item[1] for item in items]
        costs, parents = {}, {}
        for j in range(n):
            key = (1 << j, j)
            costs[key] = math.dist(start, points[j])
            parents[key] = None
        for mask in range(1, 1 << n):
            if mask & (mask - 1) == 0:
                continue
            for j in range(n):
                bit = 1 << j
                if not mask & bit:
                    continue
                previous = mask ^ bit
                best = None
                for k in range(n):
                    if previous & (1 << k):
                        candidate = (costs[(previous, k)]
                                     + math.dist(points[k], points[j]), k)
                        if best is None or candidate < best:
                            best = candidate
                costs[(mask, j)] = best[0]
                parents[(mask, j)] = best[1]
        mask = (1 << n) - 1
        end = min(range(n), key=lambda j: (costs[(mask, j)], items[j][0]))
        reverse = []
        while end is not None:
            reverse.append(end)
            previous = parents[(mask, end)]
            mask ^= 1 << end
            end = previous
        return [items[i] for i in reversed(reverse)]

    def _active_task(self, ks, ch, position, current_channel):
        cid = ch.channel_id
        if (self.fallback.in_fallback(cid)
                or self._q4jr_attempts.get(cid, 0)
                >= self.q4jr_active_attempts):
            return None
        choice = localization.choose_observation(
            ks, [ch], position, current_channel,
            approach_tracker=self.approach,
            failed_points=self.failed_points,
            mode=self.nbv_mode,
            opportunistic_reuse=self.opportunistic_reuse)
        if choice is None:
            return None
        if choice.get("kind") != "approach" and not self.q4jr_include_nbv:
            return None
        return (cid, tuple(choice["point"]), "measure", choice)

    def _joint_tail_action(self, ks, position, current_channel):
        items = []
        if self.q4jr_route_ready:
            for ch in ks.by_status(ChannelStatus.READY):
                if ch.channel_id not in self.blocked:
                    items.append((ch.channel_id,
                                  self._clear_target(ch, position), "clear", None))
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            task = self._active_task(ks, ch, position, current_channel)
            if task is not None:
                items.append(task)
        if not items:
            return None
        ordered = self._exact_open_order(items, position)
        cid, target, kind, detail = ordered[0]
        self.q4jr_stats["route_decisions"] += 1
        self.q4jr_stats["exact_nodes_max"] = max(
            self.q4jr_stats["exact_nodes_max"], len(ordered))
        if kind == "clear":
            self.q4jr_stats["ready_clears"] += 1
            return Mission("clear", target, channel=cid,
                           meta={"kind": "q4jr_joint_clear",
                                 "ready_route": True,
                                 "ready_route_total": len(ordered)})
        self._q4jr_attempts[cid] = self._q4jr_attempts.get(cid, 0) + 1
        self.q4jr_stats["active_measures"] += 1
        return Mission("measure", target, channel=cid,
                       meta={"kind": "q4jr_joint_measure",
                             "scan_variant": "primary",
                             "joint_route_total": len(ordered),
                             "nbv_kind": detail.get("kind")})

    def _coverage_joint_channels(self, ks, point):
        ranked = []
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            if (self.fallback.in_fallback(ch.channel_id)
                    or ch.mec_radius <= self.q4jr_coverage_min_mec
                    or not self.joint_bearing_allowed(ch, point)):
                continue
            center, radius = ch.mec
            if math.dist(point, center) > C.R_EFF_MAX + radius:
                continue
            n_dir = sum(obs["result"] == "direction"
                        for obs in ch.observations)
            n_no = sum(obs["result"] == "no_signal"
                       for obs in ch.observations)
            if n_no >= 3 and n_no > 2 * n_dir:
                continue
            value = (ch.mec_radius * self._bearing_cut_value(ch, point)
                     / (1.0 + n_dir + n_no))
            ranked.append((-value, ch.channel_id))
        ranked.sort()
        return [cid for _, cid in ranked[:self.q4jr_coverage_active_limit]]

    def _standard_coverage_scan(self, ks):
        if not self.q4jr_share_coverage:
            return super()._standard_coverage_scan(ks)
        # Replace the legacy first-few-stops repeat queue with an explicitly
        # priced same-stop joint suffix.
        self._coverage_pending_point = None
        self._coverage_pending_active = None
        mission = super()._standard_coverage_scan(ks)
        self._coverage_pending_point = None
        self._coverage_pending_active = None
        if mission is not None and mission.kind == "scan":
            joint = self._coverage_joint_channels(ks, mission.target)
            if joint:
                mission.meta["joint_channels"] = joint
                mission.meta["q4jr_joint_coverage"] = True
                self.q4jr_stats["coverage_joint_stops"] += 1
                self.q4jr_stats["coverage_joint_planned"] += len(joint)
        return mission

    def decide(self, ks, position, current_channel):
        self._decision_position = position
        self._joint_route_position = position
        known = self._known_count(ks)
        self._q4_known_channels = known
        self.fallback.no_shrink_limit = (
            self.Q4_NO_SHRINK_LIMIT_HIGH
            if known >= self.Q4_LIMIT_SWITCH_KNOWN
            else self.Q4_NO_SHRINK_LIMIT)

        # Before absence/cardinality closure, retain the complete production
        # discovery/certificate controller.
        if ks.unknown:
            return super().decide(ks, position, current_channel)
        if not self.q4jr_tail_enabled:
            return super().decide(ks, position, current_channel)
        if self.fallback.active_fallbacks():
            return self._fallback_route(ks, position, current_channel)
        if ks.ready and not self.q4jr_route_ready:
            return super().decide(ks, position, current_channel)
        if self.q4jr_optical_cover_points > 0:
            saved = (self.early_fallback_max_points,
                     self.early_fallback_max_known,
                     self.early_fallback_suppress_failed_scan)
            self.early_fallback_max_points = self.q4jr_optical_cover_points
            self.early_fallback_max_known = 0
            self.early_fallback_suppress_failed_scan = True
            try:
                entered = self._maybe_enter_early_fallback(ks, position)
            finally:
                (self.early_fallback_max_points,
                 self.early_fallback_max_known,
                 self.early_fallback_suppress_failed_scan) = saved
            if entered:
                return self._fallback_route(ks, position, current_channel)
        action = self._joint_tail_action(ks, position, current_channel)
        if action is not None:
            return action
        return super().decide(ks, position, current_channel)
