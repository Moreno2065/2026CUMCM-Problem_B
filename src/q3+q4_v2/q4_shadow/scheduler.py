"""Fast Q4 main policy with a risk-triggered robust shadow controller."""
from __future__ import annotations

import math
from functools import lru_cache

from geometry import constants as C
from geometry.q4_sparse_mesh import q4_sparse25_points
from compact_ring.region_route import clear_on_route
from policy.scheduler import Mission
from state.channel_state import ChannelStatus
from q4_bisect.scheduler import Q4BisectScheduler
from .belief import ShadowPosterior


class Q4ShadowScheduler(Q4BisectScheduler):
    """Keep the fast geometric path and invoke posterior work only on risk.

    Probability never changes ChannelState, absence certificates, READY, or
    exit.  It can only choose a different legal measurement point.  Thus a bad
    prior can cost time but cannot create a false all-clear result.
    """

    DISCOVERY_OPTIMIZED_ORDER = (
        0, 2, 14, 13, 24, 23, 22, 21, 20, 19, 18, 17, 4, 5, 6,
        7, 8, 9, 10, 11, 12, 1, 3, 16, 15)

    def __init__(self, mode="Q4", shadow_enabled=True,
                 shadow_min_spacing_m=0.0,
                 shadow_no_shrink_trigger=4,
                 shadow_measure_trigger=8,
                 shadow_no_signal_trigger=2,
                 shadow_min_takeover_gain_s=5.0,
                 shadow_min_signal_probability=0.20,
                 shadow_prior_directional=0.60,
                 shadow_prior_strength=8.0,
                 shadow_quantile_z=1.645,
                 shadow_route_enabled=False,
                 shadow_dynamic_scan_price=False,
                 shadow_max_takeovers_per_channel=1,
                 shadow_global_takeover_budget=4,
                 shadow_max_extra_immediate_s=100.0,
                 shadow_max_extra_at_cap_s=25.0,
                 q4_discovery_probability_threshold=0.01,
                 q4_discovery_probability_base_threshold=0.01,
                 q4_discovery_probability_trigger_known=0,
                 q4_discovery_max_channels_per_stop=1,
                 shadow_tail_pool_enabled=True,
                 shadow_tail_route_weight=1.00,
                 shadow_tail_pool_min_known=16,
                 shadow_tail_points_per_channel=1,
                 shadow_tail_gain_weight=0.35,
                 shadow_tail_region_route=False,
                 shadow_global_enroute=False,
                 shadow_global_enroute_horizon=3,
                 shadow_global_enroute_margin_m=0.0,
                 shadow_enroute_clear_region=False,
                 shadow_full_certificate_insert=False,
                 shadow_full_certificate_insert_min_saving_m=25.0,
                 shadow_full_certificate_insert_max_active=-1,
                 shadow_full_certificate_insert_scan=True,
                 shadow_certificate_dp_insert=True,
                 shadow_certificate_dp_max_active=2,
                 shadow_certificate_dp_max_ready=3,
                 shadow_certificate_dp_min_unknown=10,
                 shadow_certificate_dp_min_saving_m=0.0,
                 shadow_joint_min_signal_probability=0.30,
                 shadow_stop_channel_order=False,
                 shadow_coverage_deferral=False,
                 shadow_coverage_deferral_min_active=6,
                 shadow_coverage_deferral_budget=4,
                 shadow_coverage_deferral_margin_s=0.0,
                 shadow_segment_active=False,
                 shadow_segment_min_value=80.0,
                 shadow_discovery_order=False,
                 shadow_oriented_certificate_order=False,
                 shadow_oriented_certificate_mode="tail",
                 shadow_fallback_posterior=True,
                 **kwargs):
        if mode != "Q4":
            raise ValueError("q4-shadow supports Q4 only")
        # Step 3: continuously reprice the next certificate stop from the
        # remaining UNKNOWN-channel evidence.  The point set is unchanged.
        kwargs.setdefault("q4_discovery_nbv", shadow_dynamic_scan_price)
        # Once a Q4 run has confirmed many channels, repeated no-shrink
        # measurements on one directional source cost more than entering its
        # finite optical cover.  Callers can still override this for ablation.
        kwargs.setdefault("q4_no_shrink_limit_high", 5)
        self.shadow_discovery_order = bool(shadow_discovery_order)
        # The 25 sparse witnesses form a rotationally symmetric set.  The
        # ordinary production route fixes one arbitrary phase of its shortest
        # open traversal.  This optional selector chooses among the 24
        # equal-length rotations/reflections after the origin scan, using only
        # the ACTIVE feasible regions observed at that scan.  It never moves,
        # adds or omits a certificate witness.
        self.shadow_oriented_certificate_order = bool(
            shadow_oriented_certificate_order)
        self.shadow_oriented_certificate_mode = str(
            shadow_oriented_certificate_mode or "tail").lower()
        if self.shadow_oriented_certificate_mode not in ("tail", "front"):
            raise ValueError("shadow_oriented_certificate_mode must be tail or front")
        self.shadow_fallback_posterior = bool(shadow_fallback_posterior)
        if self.shadow_discovery_order:
            # A frozen observation-only order found by Monte-Carlo
            # combinatorial search.  Disable the later origin-conditioned
            # rewrite so this experiment tests exactly the searched route.
            kwargs["q4_point_order"] = self.DISCOVERY_OPTIMIZED_ORDER
            kwargs["q4_observed_order"] = False
        super().__init__(mode=mode, **kwargs)
        self.shadow_enabled = bool(shadow_enabled)
        self.shadow_min_spacing_m = max(0.0,
                                        float(shadow_min_spacing_m))
        self.shadow_no_shrink_trigger = max(
            1, int(shadow_no_shrink_trigger))
        self.shadow_measure_trigger = max(1, int(shadow_measure_trigger))
        self.shadow_no_signal_trigger = max(
            1, int(shadow_no_signal_trigger))
        self.shadow_min_takeover_gain_s = max(
            0.0, float(shadow_min_takeover_gain_s))
        self.shadow_min_signal_probability = min(
            1.0, max(0.0, float(shadow_min_signal_probability)))
        self.shadow_route_enabled = bool(shadow_route_enabled)
        self.shadow_max_takeovers_per_channel = max(
            1, int(shadow_max_takeovers_per_channel))
        self.shadow_global_takeover_budget = max(
            1, int(shadow_global_takeover_budget))
        self.shadow_max_extra_immediate_s = max(
            0.0, float(shadow_max_extra_immediate_s))
        self.shadow_max_extra_at_cap_s = max(
            0.0, float(shadow_max_extra_at_cap_s))
        self.q4_discovery_probability_threshold = min(
            1.0, max(0.0, float(q4_discovery_probability_threshold)))
        self.q4_discovery_probability_base_threshold = min(
            1.0, max(0.0, float(
                q4_discovery_probability_base_threshold)))
        self.q4_discovery_probability_trigger_known = max(
            0, int(q4_discovery_probability_trigger_known))
        self.q4_discovery_max_channels_per_stop = max(
            0, int(q4_discovery_max_channels_per_stop))
        self.shadow_tail_pool_enabled = bool(shadow_tail_pool_enabled)
        self.shadow_tail_route_weight = max(
            0.0, float(shadow_tail_route_weight))
        self.shadow_tail_pool_min_known = max(
            0, int(shadow_tail_pool_min_known))
        self.shadow_tail_points_per_channel = max(
            1, int(shadow_tail_points_per_channel))
        self.shadow_tail_gain_weight = max(
            0.0, float(shadow_tail_gain_weight))
        self.shadow_tail_region_route = bool(shadow_tail_region_route)
        self.shadow_global_enroute = bool(shadow_global_enroute)
        self.shadow_global_enroute_horizon = max(
            1, int(shadow_global_enroute_horizon))
        self.shadow_global_enroute_margin_m = max(
            0.0, float(shadow_global_enroute_margin_m))
        self.shadow_enroute_clear_region = bool(shadow_enroute_clear_region)
        # A local detour test answers only whether a clear is close to the
        # *next* certificate stop.  During low-cardinality Q4 runs the costly
        # part is often the route from the end of the whole 25-point mesh back
        # to several READY sources.  This optional gate prices that suffix as
        # well and only inserts a clear when the complete fixed-certificate
        # route becomes shorter.  It never removes or moves a witness stop.
        self.shadow_full_certificate_insert = bool(
            shadow_full_certificate_insert)
        self.shadow_full_certificate_insert_min_saving_m = max(
            0.0, float(shadow_full_certificate_insert_min_saving_m))
        self.shadow_full_certificate_insert_max_active = int(
            shadow_full_certificate_insert_max_active)
        self.shadow_full_certificate_insert_scan = bool(
            shadow_full_certificate_insert_scan)
        # Exact precedence-constrained insertion over the *fixed* certificate
        # order.  Unlike a free TSP rewrite, it cannot disturb the bearing
        # geometry supplied by later witness points.
        self.shadow_certificate_dp_insert = bool(
            shadow_certificate_dp_insert)
        self.shadow_certificate_dp_max_active = max(
            0, int(shadow_certificate_dp_max_active))
        # The route DP treats the current READY clear regions as fixed.  That
        # approximation is reliable only while the clear queue is short:
        # with several queued sources, later certificate observations can
        # substantially move the region targets and invalidate the predicted
        # suffix saving.  This is deliberately a conservative risk gate, not
        # another score term.
        self.shadow_certificate_dp_max_ready = max(
            0, int(shadow_certificate_dp_max_ready))
        self.shadow_certificate_dp_min_unknown = max(
            0, int(shadow_certificate_dp_min_unknown))
        self.shadow_certificate_dp_min_saving_m = max(
            0.0, float(shadow_certificate_dp_min_saving_m))
        # Filter the extra ACTIVE measurements appended to a mandatory
        # certificate stop.  The fixed witness itself is always visited and
        # all UNKNOWN channels are still measured there; this only avoids a
        # directional supplement that is unlikely to be audible.
        self.q4_joint_min_signal_probability = min(
            1.0, max(0.0, float(shadow_joint_min_signal_probability)))
        self.shadow_stop_channel_order = bool(shadow_stop_channel_order)
        self.shadow_coverage_deferral = bool(shadow_coverage_deferral)
        self.shadow_coverage_deferral_min_active = max(
            1, int(shadow_coverage_deferral_min_active))
        self.shadow_coverage_deferral_budget = max(
            0, int(shadow_coverage_deferral_budget))
        self.shadow_coverage_deferral_margin_s = max(
            0.0, float(shadow_coverage_deferral_margin_s))
        self._shadow_coverage_deferred = False
        self._shadow_coverage_deferrals_used = 0
        # At most one observation can be inserted onto each mandatory
        # certificate leg. The point itself must lie on that leg, so this
        # feature changes service time only, never witness geometry or travel.
        self.shadow_segment_active = bool(shadow_segment_active)
        self.shadow_segment_min_value = max(
            0.0, float(shadow_segment_min_value or 0.0))
        self._shadow_segment_serviced = set()
        # A one-step teacher can justify one temporary intervention, not a
        # permanent policy switch.  These budgets encode exactly that scope.
        self._shadow_evaluated_channels = set()
        self._shadow_takeovers_by_channel = {}
        self._shadow_pending = []
        self.shadow = ShadowPosterior(
            prior_directional=shadow_prior_directional,
            prior_strength=shadow_prior_strength,
            quantile_z=shadow_quantile_z)
        self.shadow_stats = {
            "fast_decisions": 0,
            "risk_decisions": 0,
            "shadow_takeovers": 0,
            "spacing_filtered": 0,
            "route_reprices": 0,
            "route_distance_saved_m": 0.0,
            "posterior_empty": 0,
            "budget_blocked": 0,
            "risk_evaluations": 0,
            "shadow_proposals_discarded": 0,
            "discovery_probability_calls": 0,
            "discovery_probability_selected": 0,
            "discovery_scan_stops": 0,
            "tail_pool_decisions": 0,
            "tail_pool_candidates": 0,
            "global_enroute_candidates": 0,
            "global_enroute_chosen": 0,
            "enroute_region_projected": 0,
            "full_certificate_insert_candidates": 0,
            "full_certificate_insert_chosen": 0,
            "full_certificate_insert_saved_m": 0.0,
            "certificate_dp_insert_candidates": 0,
            "certificate_dp_insert_chosen": 0,
            "certificate_dp_insert_saved_m": 0.0,
            "stop_channel_reorders": 0,
            "joint_signal_filtered": 0,
            "coverage_deferral_candidates": 0,
            "coverage_deferrals": 0,
            "segment_active_candidates": 0,
            "segment_active_selected": 0,
            "oriented_certificate_choices": 0,
            "oriented_certificate_tail_before_m": None,
            "oriented_certificate_tail_after_m": None,
            "oriented_certificate_end_angle_deg": None,
            "oriented_certificate_mode": self.shadow_oriented_certificate_mode,
            "posterior_fallbacks": 0,
            "takeovers_by_channel": {},
            "last_directional_fraction": None,
            "risk_by_channel": {},
        }

    def _enter_fallback(self, ch_state, position, trigger):
        """Optionally order the unchanged exact cover by posterior hit rate."""
        super()._enter_fallback(ch_state, position, trigger)
        if not self.shadow_fallback_posterior:
            return
        state = self.fallback._fallback.get(ch_state.channel_id)
        if not state or len(state["points"]) < 2:
            return
        remaining = list(state["points"])
        weights = {
            point: self.shadow.position_likelihood(ch_state, point)
            for point in remaining
        }
        peak = max(weights.values(), default=0.0)
        floor = max(1e-6, 0.03 * peak)
        current = (float(position[0]), float(position[1]))
        ordered = []
        while remaining:
            point = max(
                remaining,
                key=lambda candidate: (
                    (weights[candidate] + floor) /
                    (3.0 + math.dist(current, candidate) / C.MOVE_SPEED),
                    -math.dist(current, candidate)))
            remaining.remove(point)
            ordered.append(point)
            current = point
        state["points"] = ordered
        state["record"]["points"] = [tuple(point) for point in ordered]
        self.shadow_stats["posterior_fallbacks"] += 1

    def joint_signal_probability(self, knowledge, channel, point):
        """Conservative predicted reception probability for a joint scan.

        This uses only the channel's accumulated observations and the
        directional-fraction posterior.  Taking the lower value at the mean
        and upper directional fractions avoids accepting a certificate-stop
        supplement merely because one favourable type mixture sees it.
        """
        fraction = self.shadow.directional_fraction(knowledge)
        mean = self.shadow.candidate_stats(
            channel, point, fraction["mean"])["p_signal"]
        upper = self.shadow.candidate_stats(
            channel, point, fraction["upper"])["p_signal"]
        return min(float(mean), float(upper))
    def unknown_discovery_probability(self, knowledge, channel, point):
        """P(signal here | an as-yet unknown Q4 channel has a source).

        Unlike the old discovery-share shortcut, this conditions jointly on
        every no-signal witness and keeps antenna orientation latent.  It is a
        planning score only; hard state transitions and absence certificates
        remain unchanged.
        """
        fraction = self.shadow.directional_fraction(knowledge)
        mean = self.shadow.candidate_stats(channel, point, fraction["mean"])
        upper = self.shadow.candidate_stats(channel, point, fraction["upper"])
        # The larger directional fraction is the conservative model for
        # localization, but can either raise or lower reception probability.
        # Use the lower prediction so an opportunistic scan must pay under
        # both posterior summaries.
        probability = min(mean["p_signal"], upper["p_signal"])
        self.shadow_stats["discovery_probability_calls"] += 1
        return probability

    def record_unknown_discovery_selection(self, rows, threshold):
        if rows:
            self.shadow_stats["discovery_scan_stops"] += 1
            self.shadow_stats["discovery_probability_selected"] += len(rows)

    def order_stop_channels(self, knowledge, mission, sequence,
                            current_channel):
        """Put the likeliest UNKNOWN first without removing any witness."""
        sequence = list(sequence)
        if (not self.shadow_stop_channel_order or mission.kind != "scan" or
                not mission.meta.get("coverage_scan") or len(sequence) < 2):
            return sequence
        unknown = [channel_id for channel_id in sequence
                   if knowledge[channel_id].status == ChannelStatus.UNKNOWN]
        if len(unknown) < 2:
            return sequence
        fraction = self.shadow.directional_fraction(knowledge)
        ranked = []
        for channel_id in unknown:
            channel = knowledge[channel_id]
            mean = self.shadow.candidate_stats(
                channel, mission.target, fraction["mean"])["p_signal"]
            upper = self.shadow.candidate_stats(
                channel, mission.target, fraction["upper"])["p_signal"]
            ranked.append((min(mean, upper), channel_id))
        ranked.sort(key=lambda row: (-row[0], row[1]))
        order = [channel_id for _probability, channel_id in ranked]
        # ACTIVE supplements remain after discovery work.  The set is
        # unchanged, hence absence/certificate semantics are identical.
        order.extend(channel_id for channel_id in sequence
                     if channel_id not in set(unknown))
        if order != sequence:
            self.shadow_stats["stop_channel_reorders"] += 1
        return order

    def unknown_discovery_threshold(self, knowledge):
        """Choose the configured scan price from observable cardinality.

        Setting a positive trigger retains a conservative price until that
        many channels are observed.  The performance default uses trigger 0
        and caps the action at one channel per stop instead.  Neither form
        reads hidden source-count or scenario input.
        """
        known = (len(knowledge.by_status(ChannelStatus.ACTIVE)) +
                 len(knowledge.by_status(ChannelStatus.READY)) +
                 len(knowledge.by_status(ChannelStatus.CLEARED)))
        if known >= self.q4_discovery_probability_trigger_known:
            return self.q4_discovery_probability_threshold
        return self.q4_discovery_probability_base_threshold

    def decide(self, ks, position, current_channel):
        """Commit shadow state only for the mission that actually executes."""
        self._shadow_pending = []
        mission = super().decide(ks, position, current_channel)
        matched = None
        for pending in self._shadow_pending:
            if pending["mission"] is mission:
                matched = pending
            else:
                self.shadow_stats["shadow_proposals_discarded"] += 1
        if matched is not None:
            risky = matched["risky"]
            self._shadow_evaluated_channels.update(
                channel.channel_id for channel, _ in risky)
            self.shadow_stats["risk_decisions"] += 1
            if matched["takeover"]:
                self.shadow_stats["shadow_takeovers"] += 1
                cid = mission.channel
                self._shadow_takeovers_by_channel[cid] = (
                    self._shadow_takeovers_by_channel.get(cid, 0) + 1)
                self.shadow_stats["takeovers_by_channel"][str(cid)] = (
                    self._shadow_takeovers_by_channel[cid])
            self._emit_shadow_trace(
                ks, mission, matched["row"], matched["fraction"],
                matched["rows"],
                "q4_shadow_robust" if matched["takeover"] else
                "q4_shadow_fast_retained")
        self._shadow_pending = []
        return mission

    @staticmethod
    def _known_count(knowledge):
        return (len(knowledge.by_status(ChannelStatus.ACTIVE)) +
                len(knowledge.by_status(ChannelStatus.READY)) +
                len(knowledge.by_status(ChannelStatus.CLEARED)))

    def _tail_pool_active(self, knowledge):
        return (self.shadow_tail_pool_enabled and
                self._known_count(knowledge) >=
                self.shadow_tail_pool_min_known)

    def _rolling_active_candidates(self, knowledge, position,
                                   current_channel):
        if not self._tail_pool_active(knowledge):
            return super()._rolling_active_candidates(
                knowledge, position, current_channel)
        rows = []
        for channel in knowledge.by_status(ChannelStatus.ACTIVE):
            if self.fallback.in_fallback(channel.channel_id):
                continue
            mission = self._active_measure(
                knowledge, position, current_channel,
                active_override=[channel])
            if mission is not None:
                rows.append(mission)
            if self.shadow_tail_points_per_channel <= 1:
                continue
            alternatives = []
            for point in self._candidate_points(channel, position):
                if mission is not None and math.dist(point, mission.target) <= 1e-6:
                    continue
                immediate = (math.dist(position, point) / C.MOVE_SPEED +
                             C.MEASURE_TIME +
                             (C.SWITCH_TIME
                              if channel.channel_id != current_channel else 0.0))
                gain = (min(channel.mec_radius, 1800.0) /
                        (1.0 + len(channel.observations)) *
                        self._bearing_cut_value(channel, point))
                rank = immediate - self.shadow_tail_gain_weight * min(240.0, gain)
                candidate = Mission(
                    "measure", point, channel=channel.channel_id,
                    meta={"kind": "q4_tail_route_nbv", "gain": gain,
                          "tail_point_rank": rank})
                alternatives.append((rank, point[0], point[1], candidate))
            alternatives.sort(key=lambda row: row[:3])
            rows.extend(row[-1] for row in alternatives[
                :self.shadow_tail_points_per_channel - 1])
        self.shadow_stats["tail_pool_decisions"] += 1
        self.shadow_stats["tail_pool_candidates"] += len(rows)
        return rows

    def _tail_route_time(self, knowledge, start, mission):
        """Open 2-opt route through current READY and ACTIVE task regions."""
        if self.shadow_tail_region_route:
            tasks = []
            for channel in knowledge.by_status(ChannelStatus.READY):
                if channel.channel_id in self.blocked:
                    continue
                if (mission.kind == "clear" and
                        mission.channel == channel.channel_id):
                    continue
                representative = (channel.mec[0] if channel.mec is not None
                                  else channel.clear_position)
                tasks.append(("ready", channel, representative))
            for channel in knowledge.by_status(ChannelStatus.ACTIVE):
                if self.fallback.in_fallback(channel.channel_id):
                    continue
                tasks.append(("active", channel, channel.mec[0]))
            if not tasks:
                return 0.0
            remaining = list(tasks)
            ordered = []
            here = start
            while remaining:
                index = min(range(len(remaining)), key=lambda i:
                            math.dist(here, remaining[i][2]))
                task = remaining.pop(index)
                ordered.append(task)
                here = task[2]
            # 2-opt the representative order, then price each READY by its
            # actual nearest legal clear point from the preceding visit.
            reps = [task[2] for task in ordered]
            optimized = self._two_opt_open(reps, start, passes=3)
            buckets = {}
            for task in ordered:
                buckets.setdefault(task[2], []).append(task)
            ordered = [buckets[point].pop(0) for point in optimized]
            distance = 0.0
            here = start
            for kind, channel, representative in ordered:
                target = (self._clear_target(channel, here)
                          if kind == "ready" else representative)
                distance += math.dist(here, target)
                here = target
            route = distance / C.MOVE_SPEED
            active_service = 6.0 * len(
                knowledge.by_status(ChannelStatus.ACTIVE))
            ready_service = 5.0 * len(
                knowledge.by_status(ChannelStatus.READY))
            return route + active_service + ready_service
        points = []
        for channel in knowledge.by_status(ChannelStatus.READY):
            if channel.channel_id in self.blocked:
                continue
            if mission.kind == "clear" and mission.channel == channel.channel_id:
                continue
            points.append(self._clear_target(channel, start))
        for channel in knowledge.by_status(ChannelStatus.ACTIVE):
            if self.fallback.in_fallback(channel.channel_id):
                continue
            # A measurement does not finish the source.  Its current MEC
            # centre remains the route's best observation-only representative
            # for the eventual approach/clear region.
            points.append(channel.mec[0])
        if not points:
            return 0.0
        order = []
        remaining = list(points)
        here = start
        while remaining:
            index = min(range(len(remaining)),
                        key=lambda i: math.dist(here, remaining[i]))
            here = remaining.pop(index)
            order.append(here)
        order = self._two_opt_open(order, start, passes=3)
        route = self._path_length(order, start) / C.MOVE_SPEED
        # The route is geometric; retain a small service floor so it does not
        # prefer a path containing many unresolved ACTIVE tasks merely because
        # their centres cluster tightly.
        active_service = 6.0 * len(knowledge.by_status(ChannelStatus.ACTIVE))
        ready_service = 5.0 * len(knowledge.by_status(ChannelStatus.READY))
        return route + active_service + ready_service

    def _rolling_score(self, mission, knowledge, position, current_channel):
        if not self._tail_pool_active(knowledge):
            return super()._rolling_score(
                mission, knowledge, position, current_channel)
        immediate = self._rolling_action_cost(
            mission, position, current_channel, knowledge)
        tail = self._tail_route_time(knowledge, mission.target, mission)
        kind_bonus = {"clear": 0.0, "measure": -12.0,
                      "scan": -18.0}.get(mission.kind, 0.0)
        gain_credit = (self.shadow_tail_gain_weight * min(
            240.0, max(0.0, float(mission.meta.get("gain", 0.0))))
                       if (mission.kind == "measure" and
                           self.shadow_tail_points_per_channel > 1) else 0.0)
        return (immediate + self.shadow_tail_route_weight * tail +
                kind_bonus - gain_credit)

    def _ready_suffix_distance(self, start, fixed, ready_channels):
        distance = 0.0
        here = start
        for point in fixed:
            distance += math.dist(here, point)
            here = point
        items = [(channel.channel_id, channel.mec[0])
                 for channel in ready_channels]
        ordered = self._open_ready_order(items, here)
        by_id = {channel.channel_id: channel for channel in ready_channels}
        for channel_id, _representative in ordered:
            target = self._clear_target(by_id[channel_id], here)
            distance += math.dist(here, target)
            here = target
        return distance

    def _full_certificate_insert_clear(self, knowledge, position, coverage):
        """Return a READY clear whose insertion shortens the *full* suffix.

        ``_rolling_coverage_candidate`` has already reserved ``coverage`` and
        advanced the certificate index.  The untouched route is therefore
        ``position -> coverage.target -> remaining fixed witnesses -> READY
        tail``.  A clear before the first witness is admissible only if its
        added first-leg distance is repaid by removing that source from the
        eventual READY tail.  The calculation uses no truth or source count;
        it is a deterministic open-path comparison on the currently observed
        legal clear regions.
        """
        if not self.shadow_full_certificate_insert or coverage is None:
            return None
        max_active = self.shadow_full_certificate_insert_max_active
        if (max_active >= 0 and
                len(knowledge.by_status(ChannelStatus.ACTIVE)) > max_active):
            return None
        ready = [channel for channel in
                 knowledge.by_status(ChannelStatus.READY)
                 if channel.channel_id not in self.blocked]
        if not ready:
            return None
        fixed = [coverage.target] + list(
            self._coverage_points[self._coverage_index:])
        if not fixed:
            return None
        base = self._ready_suffix_distance(position, fixed, ready)
        best = None
        for channel in ready:
            # Project into the legal clear region against the two immediate
            # legs.  This has no bearing on validity; it only avoids charging
            # an unnecessarily central representative for a ready region.
            target = self._clear_target(channel, position)
            try:
                target = clear_on_route(channel.feasible_region, target,
                                        position, coverage.target)
            except ValueError:
                pass
            remaining = [other for other in ready
                         if other.channel_id != channel.channel_id]
            via = (math.dist(position, target) +
                   self._ready_suffix_distance(target, fixed, remaining))
            saving = base - via
            self.shadow_stats["full_certificate_insert_candidates"] += 1
            key = (-saving, channel.channel_id)
            if best is None or key < best[0]:
                best = (key, channel, target, saving, base, via)
        if (best is None or
                best[3] + 1e-9 < self.shadow_full_certificate_insert_min_saving_m):
            return None
        _key, channel, target, saving, base, via = best
        self.shadow_stats["full_certificate_insert_chosen"] += 1
        self.shadow_stats["full_certificate_insert_saved_m"] += saving
        meta = {
            "kind": "q4_full_certificate_insert", "enroute": True,
            "full_certificate_insert": True,
            "full_route_before_m": base,
            "full_route_after_m": via,
            "full_route_saving_m": saving,
        }
        # The clear location is an opportunistic scan point, not a certificate
        # witness.  Exposing this switch lets the route test distinguish its
        # geometric benefit from any incidental UNKNOWN-channel discovery.
        if not self.shadow_full_certificate_insert_scan:
            meta["post_clear_channels"] = []
        return Mission(
            "clear", target, channel=channel.channel_id,
            meta=meta)

    def _certificate_dp_insert_clear(self, knowledge, position, coverage):
        """First action of the optimal READY insertion into a fixed suffix.

        Certificate witnesses retain their existing order.  The dynamic
        program only decides in which gaps the already READY clear regions
        belong.  Thus it can recover a late clear-tail detour without changing
        the later cross-bearing geometry used to localise ACTIVE sources.
        """
        if (not self.shadow_certificate_dp_insert or coverage is None or
                len(knowledge.by_status(ChannelStatus.ACTIVE)) >
                self.shadow_certificate_dp_max_active or
                len(knowledge.by_status(ChannelStatus.UNKNOWN)) <
                self.shadow_certificate_dp_min_unknown):
            return None
        ready = [channel for channel in
                 knowledge.by_status(ChannelStatus.READY)
                 if channel.channel_id not in self.blocked]
        if (not ready or
                len(ready) > self.shadow_certificate_dp_max_ready):
            return None
        anchors = [coverage.target] + list(
            self._coverage_points[self._coverage_index:])
        if not anchors:
            return None
        # A READY MEC disk is at most 20 m across.  Its clear_position is a
        # legal representative for route topology; the committed first action
        # is projected again from the actual current position below.
        targets = [tuple(channel.clear_position or channel.mec[0])
                   for channel in ready]
        n_anchor = len(anchors)
        all_ready = (1 << len(ready)) - 1

        def here(i, last):
            if last == -1:
                return position
            if last == -2:
                return anchors[i - 1]
            return targets[last]

        @lru_cache(maxsize=None)
        def solve(i, mask, last):
            if i == n_anchor and mask == all_ready:
                return 0.0, None
            origin = here(i, last)
            best = None
            if i < n_anchor:
                tail, _next = solve(i + 1, mask, -2)
                best = (math.dist(origin, anchors[i]) + tail,
                        ("anchor", i))
            for index in range(len(ready)):
                bit = 1 << index
                if mask & bit:
                    continue
                tail, _next = solve(i, mask | bit, index)
                candidate = (math.dist(origin, targets[index]) + tail,
                             ("ready", index))
                if best is None or candidate < best:
                    best = candidate
            return best

        total, first = solve(0, 0, -1)
        if first is None or first[0] != "ready":
            return None
        baseline = self._ready_suffix_distance(position, anchors, ready)
        saving = baseline - total
        self.shadow_stats["certificate_dp_insert_candidates"] += len(ready)
        if saving + 1e-9 < self.shadow_certificate_dp_min_saving_m:
            return None
        index = first[1]
        channel = ready[index]
        target = self._clear_target(channel, position)
        self.shadow_stats["certificate_dp_insert_chosen"] += 1
        self.shadow_stats["certificate_dp_insert_saved_m"] += saving
        return Mission(
            "clear", target, channel=channel.channel_id,
            meta={"kind": "q4_certificate_dp_insert", "enroute": True,
                  "certificate_dp_insert": True,
                  "certificate_dp_route_before_m": baseline,
                  "certificate_dp_route_after_m": total,
                  "certificate_dp_route_saving_m": saving,
                  # The DP prices geometry only.  Do not let an incidental
                  # discovery scan mutate the remaining route it just scored.
                  "post_clear_channels": []})

    def _rolling_enroute_clear(self, knowledge, position, coverage,
                               detour_limit):
        dp_insert = self._certificate_dp_insert_clear(
            knowledge, position, coverage)
        if dp_insert is not None:
            return dp_insert
        full_insert = self._full_certificate_insert_clear(
            knowledge, position, coverage)
        if full_insert is not None:
            return full_insert
        if not self.shadow_global_enroute:
            if not self.shadow_enroute_clear_region:
                return super()._rolling_enroute_clear(
                    knowledge, position, coverage, detour_limit)
            if coverage is None or detour_limit <= 0.0:
                return None
            # The base policy projects a READY clear point toward the current
            # robot position only.  During a forced certificate step the next
            # leg is known, so project into the same legal clear zone against
            # *both* legs before deciding whether it is genuinely en route.
            candidates = []
            for channel in knowledge.by_status(ChannelStatus.READY):
                if channel.channel_id in self.blocked:
                    continue
                current = self._clear_target(channel, position)
                try:
                    target = clear_on_route(
                        channel.feasible_region, current, position,
                        coverage.target)
                except ValueError:
                    target = current
                candidates.append(Mission(
                    "clear", target, channel=channel.channel_id,
                    meta={"kind": "q4_enroute_region", "rolling": True,
                          "enroute_region": True,
                          "rolling_benefit": 260.0}))
            candidates.extend(self._rolling_probe_candidates(
                knowledge, position))
            base = math.dist(position, coverage.target)
            best = None
            for mission in candidates:
                detour = (math.dist(position, mission.target) +
                          math.dist(mission.target, coverage.target) - base)
                if detour > detour_limit + 1e-9:
                    continue
                key = (detour, 0 if mission.kind == "clear" else 1,
                       mission.channel if mission.channel is not None else -1)
                if best is None or key < best[0]:
                    best = (key, mission)
            if best is None:
                return None
            mission = best[1]
            mission.meta["enroute"] = True
            mission.meta["enroute_detour_m"] = float(best[0][0])
            if mission.meta.get("enroute_region"):
                self.shadow_stats["enroute_region_projected"] += 1
            if mission.meta.get("rolling_probe"):
                self._rolling_probe_attempted.add(mission.channel)
            return mission
        ready = [channel for channel in
                 knowledge.by_status(ChannelStatus.READY)
                 if channel.channel_id not in self.blocked]
        if coverage is None or not ready:
            return None
        # _coverage_scan has already advanced the index for the pending
        # mission.  Compare the same bounded certificate prefix in both
        # branches, then append the open READY route.
        extra = max(0, self.shadow_global_enroute_horizon - 1)
        fixed = [coverage.target] + list(
            self._coverage_points[self._coverage_index:
                                  self._coverage_index + extra])
        baseline = self._ready_suffix_distance(position, fixed, ready)
        best = None
        for channel in ready:
            target = self._clear_target(channel, position)
            if self.shadow_enroute_clear_region:
                try:
                    target = clear_on_route(channel.feasible_region, target,
                                            position, coverage.target)
                    self.shadow_stats["enroute_region_projected"] += 1
                except ValueError:
                    pass
            remaining = [other for other in ready
                         if other.channel_id != channel.channel_id]
            via = (math.dist(position, target) +
                   self._ready_suffix_distance(target, fixed, remaining))
            delta = via - baseline
            self.shadow_stats["global_enroute_candidates"] += 1
            key = (delta, channel.channel_id)
            if best is None or key < best[0]:
                best = (key, channel, target, baseline, via)
        if (best is None or
                best[0][0] > self.shadow_global_enroute_margin_m + 1e-9):
            return None
        _key, channel, target, baseline, via = best
        self.shadow_stats["global_enroute_chosen"] += 1
        return Mission(
            "clear", target, channel=channel.channel_id,
            meta={"kind": "q4_global_enroute", "enroute": True,
                  "global_enroute": True,
                  "global_route_before_m": baseline,
                  "global_route_after_m": via,
                  "global_route_delta_m": via - baseline})

    def _certificate_leg_active_measure(self, knowledge, position, coverage):
        """Pick one high-value ACTIVE observation on a mandatory leg.

        The pending sparse25 stop is retained by the rolling controller.  The
        inserted point is a projection onto the current straight segment, so
        travelling to it and then to the witness has exactly the original leg
        length.  Only a channel with a fresh, well-crossing and likely-visible
        direction is eligible; a blind-side Q4 no-signal otherwise costs a
        measurement with no corresponding localization benefit.
        """
        if not self.shadow_segment_active or coverage is None:
            return None
        end = tuple(coverage.target)
        dx = end[0] - position[0]
        dy = end[1] - position[1]
        length_sq = dx * dx + dy * dy
        if length_sq <= 200.0 * 200.0:
            return None
        token = (int(self._coverage_index), round(end[0], 3), round(end[1], 3))
        if token in self._shadow_segment_serviced:
            return None
        fraction = self.shadow.directional_fraction(knowledge)
        candidates = []
        for channel in knowledge.by_status(ChannelStatus.ACTIVE):
            if self.fallback.in_fallback(channel.channel_id) or channel.mec is None:
                continue
            center, radius = channel.mec
            if float(radius) <= 60.0:
                continue
            directions = [obs for obs in channel.observations
                          if obs.get("result") == "direction"]
            if not directions:
                continue
            projection = ((center[0] - position[0]) * dx +
                          (center[1] - position[1]) * dy) / length_sq
            # Fixed interior samples prevent an endpoint observation from
            # being duplicated; the projection exposes the source-specific
            # zero-detour point when it lies on the leg.
            samples = [0.2, 0.4, 0.6, 0.8,
                       min(0.85, max(0.15, projection))]
            for t in sorted(set(round(value, 8) for value in samples)):
                point = (position[0] + t * dx, position[1] + t * dy)
                if any(math.dist(point, obs["position"]) < 80.0
                       for obs in channel.observations
                       if obs.get("position") is not None):
                    continue
                if not self.joint_bearing_allowed(channel, point):
                    continue
                mean = self.shadow.candidate_stats(
                    channel, point, fraction["mean"])["p_signal"]
                upper = self.shadow.candidate_stats(
                    channel, point, fraction["upper"])["p_signal"]
                p_signal = min(mean, upper)
                if p_signal < self.shadow_min_signal_probability:
                    continue
                cut = self._bearing_cut_value(channel, point)
                value = (p_signal * cut * min(float(radius), 900.0) /
                         (1.0 + len(directions)))
                self.shadow_stats["segment_active_candidates"] += 1
                if value + 1e-9 < self.shadow_segment_min_value:
                    continue
                candidates.append((-value, t, channel.channel_id, point,
                                   p_signal, cut))
        if not candidates:
            return None
        _neg_value, t, channel_id, point, p_signal, cut = min(candidates)
        self._shadow_segment_serviced.add(token)
        self.shadow_stats["segment_active_selected"] += 1
        return Mission(
            "measure", point, channel=channel_id,
            meta={"kind": "q4_segment_active", "rolling": True,
                  "scan_variant": "primary", "segment_active": True,
                  "segment_coverage_target": end,
                  "segment_fraction": float(t),
                  "segment_p_signal": float(p_signal),
                  "segment_cut": float(cut),
                  "segment_value": float(-_neg_value)})

    def _rolling_forced_override(self, knowledge, position, current_channel,
                                 coverage, candidates):
        """Allow one scored ACTIVE action, then force the pending coverage."""
        segment = self._certificate_leg_active_measure(
            knowledge, position, coverage)
        if segment is not None:
            return segment
        if (not self.shadow_coverage_deferral or
                self._shadow_coverage_deferred or
                self._shadow_coverage_deferrals_used >=
                self.shadow_coverage_deferral_budget or
                len(knowledge.by_status(ChannelStatus.ACTIVE)) <
                self.shadow_coverage_deferral_min_active):
            return None
        work = [mission for mission in candidates
                if mission is not coverage and mission.kind == "measure" and
                mission.channel is not None and
                knowledge[mission.channel].status == ChannelStatus.ACTIVE]
        if not work:
            return None
        self.shadow_stats["coverage_deferral_candidates"] += len(work)
        base_score = super()._rolling_score
        coverage_score = base_score(
            coverage, knowledge, position, current_channel)
        ranked = [(base_score(
            mission, knowledge, position, current_channel), mission)
                  for mission in work]
        score, mission = min(ranked, key=lambda row: (
            row[0], row[1].channel, row[1].target))
        if score + self.shadow_coverage_deferral_margin_s >= coverage_score:
            return None
        self._shadow_coverage_deferred = True
        self._shadow_coverage_deferrals_used += 1
        self.shadow_stats["coverage_deferrals"] += 1
        mission.meta.update({
            "coverage_deferral": True,
            "coverage_score_s": coverage_score,
            "work_score_s": score,
            "coverage_deferrals_used": self._shadow_coverage_deferrals_used,
        })
        return mission

    def _rolling_take_coverage(self):
        mission = super()._rolling_take_coverage()
        self._shadow_coverage_deferred = False
        return mission

    # ------------------------------------------------------------------
    # Step 1: directional approach candidate hygiene
    # ------------------------------------------------------------------
    def _candidate_points(self, channel, position):
        points = super()._candidate_points(channel, position)
        if self.shadow_min_spacing_m <= 0.0:
            return points
        measured = [observation["position"]
                    for observation in channel.observations
                    if observation.get("result") in
                    ("direction", "no_signal", "near")
                    and observation.get("position") is not None]
        if not measured:
            return points
        filtered = [point for point in points
                    if all(math.dist(point, prior) + 1e-9 >=
                           self.shadow_min_spacing_m
                           for prior in measured)]
        self.shadow_stats["spacing_filtered"] += len(points) - len(filtered)
        # Do not manufacture a dead end if the finite candidate family has
        # collapsed below the spacing scale.
        return filtered if filtered else points

    # ------------------------------------------------------------------
    # Step 2: multi-start open route over the fixed certificate suffix
    # ------------------------------------------------------------------
    @staticmethod
    def _path_length(points, start):
        if not points:
            return 0.0
        return math.dist(start, points[0]) + sum(
            math.dist(left, right) for left, right in zip(points, points[1:]))

    @classmethod
    def _two_opt_open(cls, order, start, passes=3):
        order = list(order)
        for _ in range(max(1, int(passes))):
            changed = False
            for i in range(len(order) - 1):
                left = start if i == 0 else order[i - 1]
                for j in range(i + 1, len(order)):
                    right = order[j + 1] if j + 1 < len(order) else None
                    before = math.dist(left, order[i])
                    after = math.dist(left, order[j])
                    if right is not None:
                        before += math.dist(order[j], right)
                        after += math.dist(order[i], right)
                    if after + 1e-7 < before:
                        order[i:j + 1] = reversed(order[i:j + 1])
                        changed = True
            if not changed:
                break
        return order

    @classmethod
    def _multistart_open_route(cls, points, start, forced_first=None):
        points = list(points)
        if len(points) < 3:
            return points
        firsts = ([forced_first] if forced_first is not None else points)
        best = None
        for first in firsts:
            remaining = list(points)
            remaining.remove(first)
            order = [first]
            while remaining:
                nxt = min(remaining,
                          key=lambda point: (math.dist(order[-1], point),
                                             point[0], point[1]))
                remaining.remove(nxt)
                order.append(nxt)
            order = cls._two_opt_open(order, start)
            # A 2-opt reversal can dislodge the discovery-priced first point;
            # restore it and optimize the tail from that fixed observation.
            if forced_first is not None and order[0] != forced_first:
                order.remove(forced_first)
                order.insert(0, forced_first)
                tail = cls._two_opt_open(order[1:], forced_first)
                order = [forced_first] + tail
            key = (cls._path_length(order, start), tuple(order))
            if best is None or key < best[0]:
                best = (key, order)
        return best[1]

    @staticmethod
    def _oriented_sparse25_orders():
        """Yield the 24 dihedral copies of the shortest sparse25 route.

        The production order visits the centre, makes one full pass around
        the inner ring, and then one full pass around the outer ring.  Its
        twelve rotations and twelve mirror images have exactly the same
        certificate set and length.  Keeping this construction explicit is
        important: a generic reordering could silently trade certificate
        travel for poorer directional geometry, whereas these candidates only
        select the phase and handedness of the established shortest route.
        """
        for direction in (-1, 1):
            for start in range(12):
                inner = [1 + ((start + direction * step) % 12)
                         for step in range(12)]
                # The outer pass starts beside the final inner witness, then
                # follows the same handedness.  For start=0, direction=-1
                # this is exactly the production order.
                outer_start = (start - direction) % 12
                outer = [13 + ((outer_start + direction * step) % 12)
                         for step in range(12)]
                yield (0, *inner, *outer)

    def _lock_q4_observed_order(self, knowledge):
        """Optionally orient an equal-length certificate tour from the scan.

        At this moment the only source-related input is the set of channels
        that produced a direction at the origin.  Their feasible-region MECs
        are therefore legal observable proxies for where a later clear tail
        will lie.  For every equal-length tour, estimate the open route from
        its endpoint through those proxies; choose the shortest.  The first
        four witness positions only break exact score ties by favouring a
        larger cross-bearing baseline, so endpoint proximity never overrides
        the fixed certificate length.
        """
        if (not self.shadow_oriented_certificate_order or
                self.mode != "Q4" or self._q4_observed_order_locked or
                self._coverage_index != 1 or
                self.q4_certificate_layout != "sparse25"):
            return super()._lock_q4_observed_order(knowledge)
        active = [channel for channel in
                  knowledge.by_status(ChannelStatus.ACTIVE)
                  if channel.mec is not None]
        if not active:
            return super()._lock_q4_observed_order(knowledge)
        raw = q4_sparse25_points()
        proxies = [tuple(channel.mec[0]) for channel in active]
        production = tuple(self.q4_point_order or next(
            self._oriented_sparse25_orders()))

        def tail_length(order):
            endpoint = raw[order[-1]]
            route = self._multistart_open_route(proxies, endpoint)
            return self._path_length(route, endpoint)

        def front_cost(order):
            # The first four inner-ring witnesses are the only early places
            # where the fast path remeasures every ACTIVE channel.  A source
            # already heard at the centre benefits if one of those witnesses
            # is close to its observed feasible-region centre: it is then
            # much more likely to receive a second directional view instead
            # of a Q4 blind-side no-signal.  This is a geometry proxy only;
            # the actual signal still comes from the protocol response.
            early = [raw[index] for index in order[1:5]]
            return sum(min(math.dist(proxy, point) for point in early)
                       for proxy in proxies)

        def cross_value(order):
            # A point perpendicular to the initial centre bearing is more
            # likely to make the second directional observation informative.
            total = 0.0
            for proxy in proxies:
                base = math.hypot(proxy[0], proxy[1])
                if base <= 1e-9:
                    continue
                best = 0.0
                for index in order[1:5]:
                    point = raw[index]
                    vx, vy = proxy[0] - point[0], proxy[1] - point[1]
                    view = math.hypot(vx, vy)
                    if view <= 1e-9:
                        continue
                    best = max(best, abs(proxy[0] * vy - proxy[1] * vx) /
                               (base * view))
                total += best
            return total

        baseline_tail = tail_length(production)
        best = None
        for order in self._oriented_sparse25_orders():
            tail = tail_length(order)
            if self.shadow_oriented_certificate_mode == "front":
                # Localisation-first variant: the front arc is primary and
                # the tail estimate breaks only genuine front ties.
                key = (round(front_cost(order), 8), round(tail, 8),
                       -cross_value(order), order)
            else:
                # Tail variant: cross geometry never compensates a real route
                # loss in the endpoint proxy.
                key = (round(tail, 8), -cross_value(order), order)
            if best is None or key < best[0]:
                best = (key, order, tail)
        _key, order, selected_tail = best
        self._coverage_points = [raw[index] for index in order]
        self._q4_observed_order_locked = True
        endpoint = raw[order[-1]]
        self.shadow_stats["oriented_certificate_choices"] += 1
        self.shadow_stats["oriented_certificate_tail_before_m"] = baseline_tail
        self.shadow_stats["oriented_certificate_tail_after_m"] = selected_tail
        self.shadow_stats["oriented_certificate_end_angle_deg"] = (
            math.degrees(math.atan2(endpoint[1], endpoint[0])) % 360.0)

    def _reorder_q4_discovery(self, knowledge, position):
        # Step 3 first selects the highest current discovery value.  Step 2
        # then minimizes the complete fixed certificate suffix while keeping
        # that selected next point in front.
        super()._reorder_q4_discovery(knowledge, position)
        if (not self.shadow_route_enabled or self.mode != "Q4" or
                self._coverage_index >= len(self._coverage_points) - 1):
            return
        prefix = self._coverage_points[:self._coverage_index]
        suffix = list(self._coverage_points[self._coverage_index:])
        before = self._path_length(suffix, position)
        suffix = self._multistart_open_route(
            suffix, position, forced_first=suffix[0])
        after = self._path_length(suffix, position)
        self._coverage_points = prefix + suffix
        self.shadow_stats["route_reprices"] += 1
        self.shadow_stats["route_distance_saved_m"] += max(0.0,
                                                            before - after)

    # ------------------------------------------------------------------
    # Steps 4--6: risk gate, beta type ratio, upper-quantile action value
    # ------------------------------------------------------------------
    def _risk(self, channel):
        progress = self.fallback._progress.get(channel.channel_id, {})
        no_shrink = int(progress.get("no_shrink", 0))
        measures = int(progress.get("n_measures", 0))
        directions = sum(observation.get("result") == "direction"
                         for observation in channel.observations)
        no_signal = sum(observation.get("result") == "no_signal"
                        for observation in channel.observations)
        # no_signal shapes the robust posterior but cannot by itself request
        # control: certificate scans naturally create many such observations.
        # The shadow wakes only after the fast localizer has actually stalled.
        triggered = (no_shrink >= self.shadow_no_shrink_trigger or
                     measures >= self.shadow_measure_trigger)
        score = max(
            no_shrink / self.shadow_no_shrink_trigger,
            measures / self.shadow_measure_trigger,
            (no_signal / self.shadow_no_signal_trigger
             if directions and triggered else 0.0),
        )
        record = {"triggered": bool(triggered), "score": float(score),
                  "no_shrink": no_shrink, "measures": measures,
                  "directions": directions, "no_signal": no_signal}
        self.shadow_stats["risk_by_channel"][str(channel.channel_id)] = record
        return record

    def _mission_cost(self, mission, knowledge, position, current_channel):
        return self._rolling_action_cost(mission, position,
                                         current_channel, knowledge)

    def _remaining_cost_v2(self, channel, point, immediate, posterior,
                           crossing, risk_score):
        """Observable seconds-to-finish surrogate for one risky source."""
        radius_time = min(1500.0, float(channel.mec_radius)) / C.MOVE_SPEED
        positive_contraction = min(0.75, 0.55 * max(0.05, crossing))
        residual = radius_time * (
            1.0 - posterior["p_signal"] * positive_contraction)
        # A miss does not shrink the conservative Q4 polygon.  Penalize it
        # increasingly near the finite-fallback trigger.
        miss_penalty = posterior["p_no_signal"] * (
            12.0 + 12.0 * min(2.0, risk_score))
        # Balanced outcomes are useful only after accounting for the cost of
        # receiving no geometric update on the negative branch.
        split_credit = 10.0 * posterior["balanced_split"]
        return immediate + residual + miss_penalty - split_credit

    def _robust_candidate_row(self, channel, point, mission, knowledge,
                              position, current_channel, fraction, risk):
        """Score a legal action under posterior mean and upper risk tail.

        The maximum of the two costs is used for selection.  This prevents a
        candidate from winning only because the estimated directional-source
        share happened to be optimistic.
        """
        immediate = self._mission_cost(
            mission, knowledge, position, current_channel)
        crossing = self._bearing_cut_value(channel, point)
        mean_posterior = self.shadow.candidate_stats(
            channel, point, fraction["mean"])
        upper_posterior = self.shadow.candidate_stats(
            channel, point, fraction["upper"])
        mean_cost = self._remaining_cost_v2(
            channel, point, immediate, mean_posterior, crossing,
            risk["score"])
        upper_cost = self._remaining_cost_v2(
            channel, point, immediate, upper_posterior, crossing,
            risk["score"])
        return {
            "mission": mission,
            "channel": channel,
            "risk": risk,
            "immediate": immediate,
            "posterior": upper_posterior,
            "posterior_mean": mean_posterior,
            "crossing": crossing,
            "remaining": max(mean_cost, upper_cost),
            "remaining_mean": mean_cost,
            "remaining_upper": upper_cost,
        }

    def _shadow_action(self, knowledge, position, current_channel, base,
                       risky):
        fraction = self.shadow.directional_fraction(knowledge)
        self.shadow_stats["last_directional_fraction"] = fraction
        rows = []
        for channel, risk in risky:
            particles = self.shadow.particles(channel, fraction["upper"])
            if not particles:
                self.shadow_stats["posterior_empty"] += 1
                continue
            for point in self._candidate_points(channel, position):
                mission = Mission(
                    "measure", point, channel=channel.channel_id,
                    meta={"kind": "q4_shadow_robust", "shadow": True})
                rows.append(self._robust_candidate_row(
                    channel, point, mission, knowledge, position,
                    current_channel, fraction, risk))
        if not rows:
            return base, None, fraction, []
        best = min(rows, key=lambda row: (
            row["remaining"], -row["posterior"]["p_signal"],
            row["mission"].channel, row["mission"].target))

        base_row = None
        if base is not None and base.channel in knowledge.channels:
            channel = knowledge[base.channel]
            risk = self._risk(channel)
            base_row = self._robust_candidate_row(
                channel, base.target, base, knowledge, position,
                current_channel, fraction, risk)
        known = (len(knowledge.by_status(ChannelStatus.ACTIVE)) +
                 len(knowledge.by_status(ChannelStatus.READY)) +
                 len(knowledge.by_status(ChannelStatus.CLEARED)))
        # Before the cardinality cap, a detour can still discover another
        # source.  Once all 16 observed channels are known, that option value
        # vanishes and the shadow must remain close to the fast route.
        max_extra = (self.shadow_max_extra_at_cap_s if known >= 16 else
                     self.shadow_max_extra_immediate_s)
        immediate_ok = (base_row is None or
                        best["immediate"] <= base_row["immediate"] +
                        max_extra)
        takeover = (base_row is None or
                    (immediate_ok and
                     best["posterior"]["p_signal"] >=
                     self.shadow_min_signal_probability and
                     best["remaining"] + self.shadow_min_takeover_gain_s <=
                     base_row["remaining"]))
        if takeover:
            best["mission"].meta.update({
                "shadow_risk_score": best["risk"]["score"],
                "shadow_p_signal": best["posterior"]["p_signal"],
                "shadow_remaining_cost_s": best["remaining"],
                "shadow_remaining_mean_s": best["remaining_mean"],
                "shadow_remaining_upper_s": best["remaining_upper"],
                "shadow_directional_upper": fraction["upper"],
                "shadow_known_channels": known,
                "shadow_max_extra_immediate_s": max_extra,
            })
            return best["mission"], best, fraction, rows
        return base, base_row, fraction, rows

    def _emit_shadow_trace(self, knowledge, selected, selected_row,
                           fraction, rows, mode):
        if self.decision_listener is None or selected is None:
            return
        trace = self._trace_base(knowledge, mode)
        trace["directional_fraction"] = fraction
        trace["selected"] = {
            "kind": selected.meta.get("kind"),
            "channel": selected.channel,
            "point": [round(selected.target[0], 3),
                      round(selected.target[1], 3)],
        }
        if selected_row is not None:
            trace["selected"].update({
                "p_signal": round(selected_row["posterior"]["p_signal"], 6),
                "risk_score": round(selected_row["risk"]["score"], 6),
                "remaining_cost_s": round(selected_row["remaining"], 3),
                "remaining_mean_s": round(
                    selected_row["remaining_mean"], 3),
                "remaining_upper_s": round(
                    selected_row["remaining_upper"], 3),
            })
        trace["candidates"] = [{
            "channel": row["mission"].channel,
            "point": [round(row["mission"].target[0], 3),
                      round(row["mission"].target[1], 3)],
            "p_signal": round(row["posterior"]["p_signal"], 6),
            "p_directional": round(
                row["posterior"]["p_directional"], 6),
            "crossing": round(row["crossing"], 6),
            "immediate_cost_s": round(row["immediate"], 3),
            "remaining_cost_s": round(row["remaining"], 3),
            "remaining_mean_s": round(row["remaining_mean"], 3),
            "remaining_upper_s": round(row["remaining_upper"], 3),
            "risk_score": round(row["risk"]["score"], 6),
        } for row in rows]
        trace["tie_break"] = (
            "risk gate, then minimum upper-quantile remaining cost; "
            "posterior cannot certify completion")
        self._emit(trace)

    def _active_measure(self, knowledge, position, current_channel,
                        active_override=None):
        listener = self.decision_listener
        try:
            # Suppress the base trace: this method emits the actual fast or
            # shadow selection after the risk gate has resolved.
            self.decision_listener = None
            base = super()._active_measure(
                knowledge, position, current_channel,
                active_override=active_override)
        finally:
            self.decision_listener = listener
        if not self.shadow_enabled:
            return base
        active = (list(active_override) if active_override is not None else
                  [channel for channel in
                   knowledge.by_status(ChannelStatus.ACTIVE)
                   if not self.fallback.in_fallback(channel.channel_id)])
        risky = []
        for channel in active:
            risk = self._risk(channel)
            used = self._shadow_takeovers_by_channel.get(
                channel.channel_id, 0)
            if (risk["triggered"] and
                    channel.channel_id not in
                    self._shadow_evaluated_channels and
                    used < self.shadow_max_takeovers_per_channel):
                risky.append((channel, risk))
        if not risky:
            self.shadow_stats["fast_decisions"] += 1
            if listener is not None and base is not None:
                fraction = self.shadow.directional_fraction(knowledge)
                self._emit_shadow_trace(knowledge, base, None, fraction, [],
                                        "q4_shadow_fast")
            return base
        if (sum(self._shadow_takeovers_by_channel.values()) >=
                self.shadow_global_takeover_budget):
            self.shadow_stats["budget_blocked"] += 1
            return base
        # Candidate generation is side-effect free.  The outer rolling pool
        # may still choose coverage/clear; evaluation and takeover budgets are
        # committed by decide() only when this exact mission executes.
        self.shadow_stats["risk_evaluations"] += len(risky)
        selected, row, fraction, rows = self._shadow_action(
            knowledge, position, current_channel, base, risky)
        self._shadow_pending.append({
            "mission": selected,
            "risky": risky,
            "takeover": selected is not base,
            "row": row,
            "fraction": fraction,
            "rows": rows,
        })
        return selected



