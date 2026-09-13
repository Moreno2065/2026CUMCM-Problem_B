"""Q4 tail localizer using certified midpoint probe pairs."""
from __future__ import annotations

import math

from geometry import constants as C
from learned_search.scheduler import LearnedSearchScheduler
from policy.scheduler import Mission
from state.channel_state import ChannelStatus


class Q4BisectScheduler(LearnedSearchScheduler):
    """Keep production discovery/certification and accelerate its live tail.

    The midpoint-pair localizer starts only after no UNKNOWN channel remains.
    Thus it cannot postpone the finite Q4 absence certificate.  A first miss
    commits the second probe, which is at most about 26.2 m away in the first
    round.  Positive results immediately release the pair and replan globally.
    """

    def __init__(self, mode="Q4", q4_bisect_enabled=True,
                 q4_bisect_tail_only=False, q4_bisect_max_axial_m=1600.0,
                 q4_bisect_min_mec_m=20.0, q4_bisect_ready_first=True,
                 q4_bisect_min_no_shrink=4, q4_bisect_max_rounds=2,
                 q4_bisect_enroute_detour_m=500.0,
                 q4_bisect_min_known=16,
                 q4_bisect_min_area_m2=5000.0,
                 q4_bisect_global_round_budget=6,
                 **kwargs):
        if mode != "Q4":
            raise ValueError("q4-bisect supports Q4 only")
        super().__init__(mode, **kwargs)
        self.q4_bisect_enabled = bool(q4_bisect_enabled)
        self.q4_bisect_tail_only = bool(q4_bisect_tail_only)
        self.q4_bisect_max_axial_m = max(
            1.0, float(q4_bisect_max_axial_m))
        self.q4_bisect_min_mec_m = max(
            C.CLEAR_RADIUS, float(q4_bisect_min_mec_m))
        self.q4_bisect_ready_first = bool(q4_bisect_ready_first)
        self.q4_bisect_min_no_shrink = max(
            0, int(q4_bisect_min_no_shrink))
        self.q4_bisect_max_rounds = max(1, int(q4_bisect_max_rounds))
        self.q4_bisect_enroute_detour_m = max(
            0.0, float(q4_bisect_enroute_detour_m))
        self.q4_bisect_min_known = max(0, int(q4_bisect_min_known))
        self.q4_bisect_min_area_m2 = max(0.0, float(q4_bisect_min_area_m2))
        self.q4_bisect_global_round_budget = max(
            1, int(q4_bisect_global_round_budget))
        self._q4_bisect_plan = None
        self._q4_bisect_rounds = {}
        self.q4_bisect_stats = {
            "first_probes": 0,
            "second_probes": 0,
            "positive_results": 0,
            "double_no_signal_cuts": 0,
            "invalidated_plans": 0,
            "max_pair_gap_m": 0.0,
            "gated_by_detour": 0,
            "gated_by_progress": 0,
        }

    def initialize_knowledge(self, ks):
        from q4_bisect.state import Q4BisectChannelState
        if any(ch.observations for ch in ks.channels.values()):
            raise ValueError("install Q4 bisect state before the first action")
        ks.channels = {
            cid: Q4BisectChannelState(
                cid, mode="Q4",
                q4_certificate_layout=ks.q4_certificate_layout)
            for cid in ks.channels
        }

    @staticmethod
    def _last_direction(ch):
        for observation in reversed(ch.observations):
            if (observation.get("result") == "direction" and
                    observation.get("bearing") is not None):
                return observation
        return None

    @staticmethod
    def _same_point(a, b, tolerance=1e-5):
        return a is not None and b is not None and math.dist(a, b) <= tolerance

    def _pair_geometry(self, ch, position):
        observation = self._last_direction(ch)
        if observation is None or not ch.feasible_region:
            return None
        anchor = tuple(observation["position"])
        bearing = float(observation["bearing"]) % 360.0
        theta = math.radians(bearing)
        axis = (math.cos(theta), math.sin(theta))
        side = (-axis[1], axis[0])
        axial = [axis[0] * (p[0] - anchor[0]) +
                 axis[1] * (p[1] - anchor[1])
                 for p in ch.feasible_region]
        if not axial:
            return None
        distance_bound = max(axial)
        if (distance_bound <= 2.0 * C.CLEAR_RADIUS or
                distance_bound > self.q4_bisect_max_axial_m):
            return None
        midpoint = 0.5 * distance_bound
        offset = midpoint * math.tan(math.radians(C.BEARING_ERROR_DEG))
        centre = (anchor[0] + midpoint * axis[0],
                  anchor[1] + midpoint * axis[1])
        points = [
            (centre[0] - offset * side[0],
             centre[1] - offset * side[1]),
            (centre[0] + offset * side[0],
             centre[1] + offset * side[1]),
        ]
        points.sort(key=lambda point: (math.dist(position, point),
                                       point[0], point[1]))
        return {
            "channel": ch.channel_id,
            "anchor": anchor,
            "bearing": bearing,
            "distance_bound": distance_bound,
            "cutoff": midpoint,
            "first": points[0],
            "second": points[1],
            "stage": 0,
        }

    def _recorded_no_signal_at(self, ch, point):
        return any(observation.get("result") == "no_signal" and
                   self._same_point(observation.get("position"), point)
                   for observation in ch.observations)

    def on_measure_result(self, ch_state, result, r_before, r_after,
                          was_approach, position=None):
        plan = self._q4_bisect_plan
        if plan is not None and ch_state.channel_id == plan["channel"]:
            expected = plan["first"] if plan["stage"] == 0 else plan["second"]
            if not self._same_point(position, expected):
                self.q4_bisect_stats["invalidated_plans"] += 1
                self._q4_bisect_plan = None
            elif result in ("direction", "near"):
                self.q4_bisect_stats["positive_results"] += 1
                self._q4_bisect_rounds[plan["channel"]] = (
                    self._q4_bisect_rounds.get(plan["channel"], 0) + 1)
                self._q4_bisect_plan = None
            elif not self._recorded_no_signal_at(ch_state, expected):
                # The baseline maps an inconsistent direction to the hook's
                # no_signal result.  Such a result is not physical negative
                # evidence and must never trigger the certified cut.
                self.q4_bisect_stats["invalidated_plans"] += 1
                self._q4_bisect_plan = None
            elif plan["stage"] == 0:
                plan["stage"] = 1
            else:
                try:
                    ch_state.apply_midpoint_pair_no_signal(
                        plan["anchor"], plan["bearing"], plan["cutoff"],
                        virtual_time=(ch_state.observations[-1]
                                      .get("virtual_time")))
                    self.q4_bisect_stats["double_no_signal_cuts"] += 1
                    self._q4_bisect_rounds[plan["channel"]] = (
                        self._q4_bisect_rounds.get(plan["channel"], 0) + 1)
                    r_after = ch_state.mec_radius
                except ValueError as exc:
                    self.anomalies.append(str(exc))
                    self.q4_bisect_stats["invalidated_plans"] += 1
                self._q4_bisect_plan = None
        super().on_measure_result(ch_state, result, r_before, r_after,
                                  was_approach, position=position)

    def _active_plan_valid(self, ks):
        plan = self._q4_bisect_plan
        if plan is None:
            return False
        if plan["channel"] not in ks.channels:
            return False
        ch = ks[plan["channel"]]
        return (ch.status == ChannelStatus.ACTIVE and
                not self.fallback.in_fallback(ch.channel_id))

    def _next_pair_mission(self, ks, position):
        if not self._active_plan_valid(ks):
            if self._q4_bisect_plan is not None:
                self.q4_bisect_stats["invalidated_plans"] += 1
            self._q4_bisect_plan = None

        if self._q4_bisect_plan is None:
            if sum(self._q4_bisect_rounds.values()) >= \
                    self.q4_bisect_global_round_budget:
                return None
            candidates = []
            next_coverage = None
            if (ks.unknown and self._coverage_index <
                    len(self._coverage_points)):
                next_coverage = self._coverage_points[self._coverage_index]
            for ch in ks.by_status(ChannelStatus.ACTIVE):
                if (self.fallback.in_fallback(ch.channel_id) or
                        ch.mec_radius < self.q4_bisect_min_mec_m or
                        ch.feasible_area < self.q4_bisect_min_area_m2 or
                        self._q4_bisect_rounds.get(ch.channel_id, 0) >=
                        self.q4_bisect_max_rounds):
                    continue
                progress = self.fallback._progress.get(ch.channel_id, {})
                no_shrink = int(progress.get("no_shrink", 0))
                if no_shrink < self.q4_bisect_min_no_shrink:
                    self.q4_bisect_stats["gated_by_progress"] += 1
                    continue
                plan = self._pair_geometry(ch, position)
                if plan is None:
                    continue
                travel = math.dist(position, plan["first"])
                detour = travel
                if next_coverage is not None:
                    detour += (math.dist(plan["first"], next_coverage) -
                               math.dist(position, next_coverage))
                    if detour > self.q4_bisect_enroute_detour_m + 1e-9:
                        self.q4_bisect_stats["gated_by_detour"] += 1
                        continue
                plan["insertion_detour_m"] = detour
                candidates.append((detour, travel, -no_shrink,
                                   ch.mec_radius, ch.channel_id, plan))
            if not candidates:
                return None
            self._q4_bisect_plan = min(candidates,
                                       key=lambda item: item[:-1])[-1]

        plan = self._q4_bisect_plan
        stage = plan["stage"]
        target = plan["first"] if stage == 0 else plan["second"]
        if stage == 0:
            self.q4_bisect_stats["first_probes"] += 1
        else:
            self.q4_bisect_stats["second_probes"] += 1
        gap = math.dist(plan["first"], plan["second"])
        self.q4_bisect_stats["max_pair_gap_m"] = max(
            self.q4_bisect_stats["max_pair_gap_m"], gap)
        if self.decision_listener is not None:
            trace = self._trace_base(ks, "q4_midpoint_bisect")
            trace.update({
                "selected": {"kind": "measure",
                             "channel": plan["channel"],
                             "point": [round(target[0], 3),
                                       round(target[1], 3)]},
                "stage": stage,
                "anchor": [round(plan["anchor"][0], 3),
                           round(plan["anchor"][1], 3)],
                "bearing_deg": round(plan["bearing"], 6),
                "axial_bound_m": round(plan["distance_bound"], 6),
                "cutoff_m": round(plan["cutoff"], 6),
                "pair_gap_m": round(gap, 6),
                "insertion_detour_m": round(
                    plan.get("insertion_detour_m", 0.0), 6),
            })
            self._emit(trace)
        return Mission(
            "measure", target, channel=plan["channel"],
            meta={"kind": "q4_midpoint_bisect",
                  "scan_variant": "primary",
                  "bisect_stage": stage,
                  "bisect_axial_bound_m": plan["distance_bound"]})

    def decide(self, ks, position, current_channel):
        if not self.q4_bisect_enabled:
            return super().decide(ks, position, current_channel)
        if self.fallback.active_fallbacks():
            self._q4_bisect_plan = None
            return super().decide(ks, position, current_channel)
        known = (len(ks.by_status(ChannelStatus.ACTIVE)) +
                 len(ks.by_status(ChannelStatus.READY)) +
                 len(ks.by_status(ChannelStatus.CLEARED)))
        if known < self.q4_bisect_min_known:
            self._q4_bisect_plan = None
            return super().decide(ks, position, current_channel)
        if self.q4_bisect_tail_only and ks.unknown:
            self._q4_bisect_plan = None
            return super().decide(ks, position, current_channel)
        if self.q4_bisect_ready_first and ks.ready:
            self._q4_bisect_plan = None
            return super().decide(ks, position, current_channel)
        mission = self._next_pair_mission(ks, position)
        if mission is not None:
            return mission
        return super().decide(ks, position, current_channel)
