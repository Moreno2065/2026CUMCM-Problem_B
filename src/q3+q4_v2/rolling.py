"""Small-horizon rolling candidate pool shared by the three v2 routes.

The planner intentionally does not alter the mathematical state or the
finite certificate.  It only keeps one not-yet-executed coverage mission and
compares it with READY clears and one ACTIVE localization mission.  After a
mission completes the KnowledgeState is observed again and the pool is
rebuilt, so a stale route never survives a measurement.
"""
from __future__ import annotations

import math

from geometry import constants as C
from geometry.mec import mec
from geometry.polygon import contains_point
from geometry.wedge import wedge_intersect
from policy.scheduler import Mission
from state.channel_state import ChannelStatus
from lookahead import measurement_branches, scan_branches


class _NullMission:
    """Minimal mission stand-in for a pure continuation-proxy evaluation."""

    def __init__(self, target):
        self.kind = "scan"
        self.target = (float(target[0]), float(target[1]))
        self.channel = None
        self.channels = []
        self.meta = {}


# Defaults of the two Q4 tail families (both OFF).  They are the contract
# values: 8-15 deg bias, 150-250 m bias step, 2-3 in-place shots ~30 m apart
# on a 20-35 m MEC.  ``_route_tail_configure`` clamps every override into the
# same window, so a mis-set flag cannot silently widen the action.
ROUTE_TAIL_DEFAULTS = {
    "bias_homing": False,
    "bias_offset_deg": 12.0,
    "bias_step_m": 200.0,
    "bias_min_mec_m": 150.0,
    "bias_max_travel_m": None,
    "inplace_shots": 0,
    "inplace_step_m": 30.0,
    "inplace_mec_min_m": 20.0,
    "inplace_mec_max_m": 35.0,
}

ROUTE_TAIL_ATTRS = {
    "bias_homing": "rolling_bias_homing",
    "bias_offset_deg": "rolling_bias_homing_deg",
    "bias_step_m": "rolling_bias_step_m",
    "bias_min_mec_m": "rolling_bias_min_mec_m",
    "bias_max_travel_m": "rolling_bias_max_travel_m",
    "inplace_shots": "rolling_inplace_shots",
    "inplace_step_m": "rolling_inplace_step_m",
    "inplace_mec_min_m": "rolling_inplace_mec_min_m",
    "inplace_mec_max_m": "rolling_inplace_mec_max_m",
}

ROUTE_TAIL_KWARGS = ("rolling_bias_homing", "rolling_bias_homing_deg",
                     "rolling_bias_step_m", "rolling_bias_min_mec_m",
                     "rolling_bias_max_travel_m",
                     "rolling_inplace_shots", "rolling_inplace_step_m",
                     "rolling_inplace_mec_min_m", "rolling_inplace_mec_max_m")

ROUTE_TAIL_PUBLIC = {attr: key for key, attr in ROUTE_TAIL_ATTRS.items()}


def _greedy_order(points, start):
    remaining = list(points)
    ordered = []
    here = (float(start[0]), float(start[1]))
    while remaining:
        i = min(range(len(remaining)), key=lambda j: math.dist(here, remaining[j]))
        here = remaining.pop(i)
        ordered.append(here)
    return ordered


class RollingCandidatePlanner:
    """Mixin for a bounded rolling (replan-after-every-action) policy."""

    def _init_rolling(self, enabled=False, horizon=3, coverage_period=3,
                      probe_radius_m=0.0, probe_max_distance_m=None,
                      joint_active_limit=1, ready_open_route=False,
                      probe_remeasure=False,
                      bias_homing=False, bias_offset_deg=12.0,
                      bias_step_m=200.0, bias_min_mec_m=150.0,
                      inplace_shots=0, inplace_step_m=30.0,
                      inplace_mec_min_m=20.0, inplace_mec_max_m=35.0):
        self.rolling_enabled = bool(enabled)
        self.rolling_horizon = max(2, int(horizon or 3))
        self.rolling_coverage_period = max(1, int(coverage_period or 3))
        # A probe is an opportunistic optical clear.  It is never a
        # certificate: after one attempt the channel returns to ordinary
        # localization or the finite 20 m fallback cover.
        self.rolling_probe_radius_m = max(0.0, float(probe_radius_m or 0.0))
        self.rolling_probe_max_distance_m = (
            None if probe_max_distance_m is None else
            max(0.0, float(probe_max_distance_m)))
        self.rolling_probe_remeasure = bool(probe_remeasure)
        self.rolling_joint_active_limit = max(0, int(joint_active_limit or 0))
        # Optional merge of the clear sweep into the discovery tour: a clear
        # whose detour off the route to the pending coverage stop is at most
        # this many metres is executed immediately.  Zero keeps the historical
        # two-pass behaviour.
        self.rolling_enroute_detour_m = 0.0
        # Short-horizon belief lookahead: expand observable outcomes on shadow
        # states instead of adding a hand-written continuation proxy.
        self.rolling_lookahead = False
        self.rolling_lookahead_step_m = 120.0
        self._lookahead_samples = None
        self.ready_open_route = bool(ready_open_route)
        self._rolling_probe_attempted = set()
        self._rolling_coverage = None
        self._rolling_coverage_age = 0
        self._rolling_decisions = 0
        # ------------------------------------------------------------------
        # Q4 tail families (both default OFF, both one opportunity per channel)
        #
        # ``bias_homing``: with a single bearing line and a still large MEC the
        # feasible region is a ~2 deg sliver whose MEC radius is dominated by
        # its length, so walking *along* the received bearing (the historical
        # forward chain) keeps the two lines nearly collinear (crossing angle
        # ~0) and barely shrinks it.  Stepping 150-250 m at an 8-15 deg offset
        # from the received bearing and re-measuring the same channel creates a
        # real crossing baseline instead, at a bounded travel cost.
        #
        # ``inplace_shots``: a failed clear at a point whose MEC is 20-35 m
        # leaves a small surviving region.  Up to ``inplace_shots`` (2-3) clears
        # ~``inplace_step_m`` apart, chosen to cover that surviving region, cost
        # ~6-9 s each, far less than walking off to re-measure (~26 s).
        #
        # Both are observation-only: channel status, MEC, own observations and
        # the executor's plan are the only inputs.  Every candidate is priced by
        # ``_rolling_action_cost`` -> the runner's ``plan_stop``.
        # ------------------------------------------------------------------
        self.rolling_bias_homing = bool(bias_homing)
        self.rolling_bias_homing_deg = 12.0
        self.rolling_bias_step_m = 200.0
        self.rolling_bias_min_mec_m = 150.0
        self.rolling_inplace_shots = 0
        self.rolling_inplace_step_m = 30.0
        self.rolling_inplace_mec_min_m = 20.0
        self.rolling_inplace_mec_max_m = 35.0
        self.rolling_inplace_at_point_m = 45.0
        self._route_tail_configure(
            bias_homing=bias_homing, bias_offset_deg=bias_offset_deg,
            bias_step_m=bias_step_m, bias_min_mec_m=bias_min_mec_m,
            inplace_shots=inplace_shots, inplace_step_m=inplace_step_m,
            inplace_mec_min_m=inplace_mec_min_m,
            inplace_mec_max_m=inplace_mec_max_m)
        self._route_bias_attempted = set()
        self._route_burst_shots = {}      # channel -> clears counted in burst
        self._route_burst_closed = set()  # channel -> burst already finished
        self._route_burst_closed_reason = {}
        self._route_pending_audit = {}    # id(mission) -> generation-time row
        self.route_tail_audit = {
            "bias_homing": {"candidates": 0, "chosen": 0, "violations": 0,
                            "rows": []},
            "inplace_shots": {"candidates": 0, "chosen": 0, "violations": 0,
                              "rows": [], "blocked_ready_recovered": 0},
        }
        self.route_tail_audit_row_limit = 400

    @staticmethod
    def _point_distance(position, target):
        return math.dist(position, target)

    def _rolling_ready_candidates(self, ks, position):
        out = []
        for ch in ks.by_status(ChannelStatus.READY):
            if ch.channel_id in self.blocked:
                continue
            target = self._clear_target(ch, position)
            out.append(Mission(
                "clear", target, channel=ch.channel_id,
                meta={"kind": "rolling_ready", "rolling": True,
                      "rolling_benefit": 260.0}))
        return out

    def _rolling_active_candidates(self, ks, position, current_channel):
        """Extension point for policies that keep >1 ACTIVE in the pool."""
        active = self._active_measure(ks, position, current_channel)
        return [active] if active is not None else []

    @staticmethod
    def _open_ready_order(items, start, max_passes=3):
        """Open-path 2-opt over guaranteed READY clear targets."""
        order = list(items)
        if len(order) < 3:
            return order
        dist = lambda a, b: math.dist(a, b)
        for _ in range(max(1, int(max_passes))):
            changed = False
            for i in range(len(order) - 1):
                left = start if i == 0 else order[i - 1][1]
                for j in range(i + 1, len(order)):
                    right = order[j + 1][1] if j + 1 < len(order) else None
                    before = dist(left, order[i][1])
                    after = dist(left, order[j][1])
                    if right is not None:
                        before += dist(order[j][1], right)
                        after += dist(order[i][1], right)
                    if after + 1e-7 < before:
                        order[i:j + 1] = reversed(order[i:j + 1])
                        changed = True
            if not changed:
                break
        return order

    def _ready_route_candidate(self, ks, position):
        ready = [ch for ch in ks.by_status(ChannelStatus.READY)
                 if ch.channel_id not in self.blocked]
        if not ready:
            return None
        items = [(ch.channel_id, self._clear_target(ch, position))
                 for ch in ready]
        ordered = self._open_ready_order(items, position)
        cid, target = ordered[0]
        return Mission("clear", target, channel=cid,
                       meta={"kind": "ready_open_route", "ready_route": True,
                             "ready_route_total": len(ordered)})

    def _rolling_probe_candidates(self, ks, position):
        """Return one-shot 140 m-class approach/clear opportunities.

        ``mec_radius <= 140`` only says that the source lies in a small
        feasible disk.  It does not imply that the MEC centre is within the
        20 m optical-clear radius, so failure leaves the channel ACTIVE and
        the exact fallback/certificate path intact.
        """
        radius_limit = self.rolling_probe_radius_m
        if radius_limit <= 0.0:
            return []
        out = []
        ladder = getattr(self, "_ladder_probe_point", None)
        attempts = getattr(self, "probe_attempts", None)
        limit = max(1, int(getattr(self, "probe_ladder_limit", 1) or 1))
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            cid = ch.channel_id
            if (cid in self._rolling_probe_attempted or
                    self.fallback.in_fallback(cid) or ch.mec is None or
                    ch.mec_radius > radius_limit):
                continue
            center = ch.mec[0]
            guaranteed = False
            if ladder is not None:
                # Use the failed-clear exclusions to place a better probe, and
                # recognise when the surviving set already guarantees a clear.
                point, guaranteed = ladder(ch)
                if point is None:
                    continue
                center = point
            if (not guaranteed and attempts is not None and
                    attempts(cid) >= limit):
                continue
            if (self.rolling_probe_max_distance_m is not None and
                    self._point_distance(position, center) >
                    self.rolling_probe_max_distance_m):
                continue
            # A smaller posterior disk makes the try more attractive, but
            # the score still charges its full travel and channel switch.
            benefit = 170.0 + max(0.0, radius_limit - ch.mec_radius)
            out.append(Mission(
                "clear", center, channel=cid,
                meta={"kind": "rolling_probe", "rolling": True,
                      "rolling_probe": True,
                      # A failed probe has already paid the trip to a
                      # potentially high-value view.  The runner may take one
                      # explicit same-channel measurement there; it remains
                      # opt-in because a directional source can still be on
                      # its blind side.
                      "post_clear_remeasure_channel": (
                          cid if self.rolling_probe_remeasure else None),
                      "rolling_benefit": benefit,
                      "probe_radius_m": (C.CLEAR_RADIUS if guaranteed
                                         else float(ch.mec_radius)),
                      "ladder_guaranteed": bool(guaranteed)}))
        return out

    # ------------------------------------------------------------------
    # Q4 tail families (default OFF; see _init_rolling)
    # ------------------------------------------------------------------

    def _route_tail_configure(self, **overrides):
        """Set the Q4 tail switches, clamped to the contracted windows.

        Called once from ``_init_rolling`` (so the attributes exist) and again
        by an experiment harness that flips a flag on an already built
        scheduler: keys left ``None`` keep their current value.
        """
        values = dict(ROUTE_TAIL_DEFAULTS)
        resolved = {}
        for key, value in overrides.items():
            # Accept both the short key ("bias_homing") and the attribute
            # spelling a harness passes as a scheduler kwarg
            # ("rolling_bias_homing").
            short = key
            if short not in ROUTE_TAIL_DEFAULTS:
                short = ROUTE_TAIL_PUBLIC.get(key, key)
            if short not in ROUTE_TAIL_DEFAULTS:
                raise TypeError("unknown route tail parameter %r" % (key,))
            resolved[short] = value
        for key, attr in ROUTE_TAIL_ATTRS.items():
            current = getattr(self, attr, None)
            if current is not None:
                values[key] = current
        for key, value in resolved.items():
            if value is not None:
                values[key] = value
        bias_deg = max(8.0, min(15.0, float(values["bias_offset_deg"])))
        bias_step = max(150.0, min(250.0, float(values["bias_step_m"])))
        bias_travel = values["bias_max_travel_m"]
        if bias_travel is None:
            # "Advance along the bearing by 150-250 m": the step starts where
            # the bearing was received, so the move itself is about one step.
            # A stale bearing point hundreds of metres away is a detour, not a
            # homing step, and it is where the family measured worse.
            bias_travel = bias_step
        bias_travel = max(0.0, float(bias_travel))
        min_mec = max(0.0, float(values["bias_min_mec_m"]))
        shots = int(values["inplace_shots"] or 0)
        step = max(1.0, float(values["inplace_step_m"]))
        low = max(0.0, float(values["inplace_mec_min_m"]))
        high = max(low, float(values["inplace_mec_max_m"]))
        self.rolling_bias_homing = bool(values["bias_homing"])
        self.rolling_bias_homing_deg = bias_deg
        self.rolling_bias_step_m = bias_step
        self.rolling_bias_min_mec_m = min_mec
        self.rolling_bias_max_travel_m = bias_travel
        self.rolling_inplace_shots = 0 if shots <= 0 else max(2, min(3, shots))
        self.rolling_inplace_step_m = step
        self.rolling_inplace_mec_min_m = low
        self.rolling_inplace_mec_max_m = high
        # "still at the clear point": the robot has not walked away since the
        # shot that failed (one and a half shot spacings of tolerance).
        self.rolling_inplace_at_point_m = 1.5 * step
        return {
            "bias_homing": self.rolling_bias_homing,
            "bias_offset_deg": bias_deg,
            "bias_step_m": bias_step,
            "bias_min_mec_m": min_mec,
            "inplace_shots": self.rolling_inplace_shots,
            "inplace_step_m": step,
            "inplace_mec_min_m": low,
            "inplace_mec_max_m": high,
            "inplace_at_point_m": self.rolling_inplace_at_point_m,
        }

    def _route_audit(self, family, row):
        """Record one candidate/choice row for the offline audit.

        Generation-time rows carry the raw observables the eligibility
        predicate reads, so a reviewer can re-check the predicate from the
        artifact instead of trusting the code path.
        """
        audit = self.route_tail_audit[family]
        if len(audit["rows"]) < self.route_tail_audit_row_limit:
            audit["rows"].append(row)
        self._route_pending_audit[row["row_id"]] = row
        return row

    def _route_audit_violation(self, family, row):
        audit = self.route_tail_audit[family]
        audit["violations"] += 1
        row["violation"] = True

    @staticmethod
    def _route_bearing_dirs(ch):
        return [obs for obs in ch.observations
                if obs.get("result") == "direction"
                and "position" in obs and obs.get("bearing") is not None]

    def _route_outside_region(self, ch, point):
        """Is ``point`` outside the channel's current feasible region?

        A wedge apex inside the region only re-cuts a sub-wedge of the same
        sliver; an apex outside it makes the new line a genuine baseline.
        """
        region = ch.feasible_region
        if not region:
            return False
        return not contains_point(region, point, eps=-C.EPS)

    def _route_predicted_mec_radius(self, ch, point):
        """Observable what-if: MEC radius after a bearing to the current centre.

        Mirrors ``ChannelState.update_direction`` (same ``wedge_intersect``)
        with the bearing the planner can actually predict, and mutates nothing.
        """
        if ch.mec is None or not ch.feasible_region:
            return None
        center = ch.mec[0]
        bearing = math.degrees(math.atan2(center[1] - point[1],
                                          center[0] - point[0])) % 360.0
        region = wedge_intersect(ch.feasible_region, point, bearing)
        if region is None:
            return None
        return float(mec(region)[1])

    def _route_bias_candidates(self, ks, position, current_channel):
        """One biased forward re-measure per single-bearing-line channel."""
        if not getattr(self, "rolling_bias_homing", False) or self.mode != "Q4":
            return []
        step = self.rolling_bias_step_m
        offset = math.radians(self.rolling_bias_homing_deg)
        min_mec = self.rolling_bias_min_mec_m
        out = []
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            cid = ch.channel_id
            if (cid in self._route_bias_attempted or ch.mec is None or
                    self.fallback.in_fallback(cid)):
                continue
            dirs = self._route_bearing_dirs(ch)
            radius = float(ch.mec_radius)
            if len(dirs) != 1 or radius < min_mec:
                continue
            if getattr(self, "_probe_failures", {}).get(cid):
                # A clear has already been gambled on this channel; the bias
                # step is a localization move, not a second gamble.
                continue
            last = dirs[-1]
            base = (float(last["position"][0]), float(last["position"][1]))
            theta = math.radians(float(last["bearing"]))
            for sign in (-1.0, 1.0):
                angle = theta + sign * offset
                point = (base[0] + step * math.cos(angle),
                         base[1] + step * math.sin(angle))
                travel = self._point_distance(position, point)
                row_id = "bias/%d/%.3f/%.3f/%d" % (cid, point[0], point[1],
                                                   int(len(out)))
                row = {
                    "row_id": row_id, "family": "bias_homing",
                    "channel": cid, "point": [round(point[0], 3),
                                              round(point[1], 3)],
                    "n_direction": len(dirs),
                    "n_no_signal": sum(1 for obs in ch.observations
                                       if obs.get("result") == "no_signal"),
                    "n_observations": len(ch.observations),
                    "mec_radius": round(radius, 3),
                    "mec_center": [round(ch.mec[0][0], 3),
                                   round(ch.mec[0][1], 3)],
                    "step_m": round(step, 3),
                    "offset_deg": round(self.rolling_bias_homing_deg, 3),
                    "sign": sign,
                    "travel_m": round(travel, 3),
                    "in_fallback": bool(self.fallback.in_fallback(cid)),
                    "min_mec_m": round(min_mec, 3),
                    "max_travel_m": round(self.rolling_bias_max_travel_m, 3),
                    "outside_region": self._route_outside_region(ch, point),
                    "inside_omega": math.hypot(point[0], point[1]) <=
                    C.OMEGA_RADIUS + 1e-9,
                    "at_current_position": self._point_distance(
                        position, point) < 1.0,
                    "attempted_before": cid in self._route_bias_attempted,
                    "predicted_mec_radius": None,
                    "predicted_gain_m": None,
                    "charged_cost_s": None, "score": None, "chosen": False,
                    "emitted": False, "rejected_reason": None,
                }
                reasons = []
                if not row["inside_omega"]:
                    reasons.append("outside_omega")
                if row["at_current_position"]:
                    reasons.append("at_current_position")
                if not row["outside_region"]:
                    reasons.append("apex_inside_region")
                if travel > self.rolling_bias_max_travel_m:
                    reasons.append("travel_over_cap")
                if reasons:
                    # Diagnostic only: the point was considered and rejected, so
                    # it never enters the candidate pool.
                    row["rejected_reason"] = ",".join(reasons)
                    self._route_audit("bias_homing", row)
                    if len(dirs) != 1 or radius < min_mec:
                        self._route_audit_violation("bias_homing", row)
                    continue
                predicted = self._route_predicted_mec_radius(ch, point)
                if predicted is not None:
                    row["predicted_mec_radius"] = round(predicted, 3)
                    row["predicted_gain_m"] = round(
                        max(0.0, radius - predicted), 3)
                gain = row["predicted_gain_m"]
                if gain is None:
                    gain = 0.5 * radius
                self._route_audit("bias_homing", row)
                if len(dirs) != 1 or radius < min_mec:
                    self._route_audit_violation("bias_homing", row)
                mission = Mission(
                    "measure", point, channel=cid,
                    meta={"kind": "bias_homing", "rolling": True,
                          "bias_homing": True,
                          "rolling_benefit": 170.0 + max(
                              0.0, min_mec - radius),
                          "gain": float(gain),
                          "route_audit_row": row_id})
                row["emitted"] = True
                row["charged_cost_s"] = round(self._rolling_action_cost(
                    mission, position, current_channel, ks), 3)
                row["score"] = round(self._rolling_score(
                    mission, ks, position, current_channel), 6)
                self.route_tail_audit["bias_homing"]["candidates"] += 1
                self._route_pending_audit[row_id] = row
                out.append(mission)
        return out

    def _route_burst_recover_ready(self, ks):
        """Re-enable a READY channel the retry heuristic has blocked.

        ``Scheduler.on_clear_failure`` adds a channel to ``blocked`` ("manual
        check") after more than ``CLEAR_RETRY_LIMIT`` failed clears, and every
        READY-clear path skips blocked channels.  Production never reaches that
        state because a channel gets at most one non-fallback clear attempt,
        but the in-place burst deliberately pays a *second* one, so a second
        failure could leave a channel that later becomes READY (R_MEC <= 20 m)
        permanently unscheduled -- the run would end with ``no_mission`` while
        a provably clearable channel is still live.

        The recovery is therefore flag-gated and narrower than the hazard: it
        only forgets the block for a channel whose MEC already proves the clear
        (``_clear_target`` returns a point of Z_c, so the clear cannot fail).
        It is not a retry of a failed gamble.
        """
        if self.rolling_inplace_shots <= 0 or self.mode != "Q4":
            return
        recovered = []
        for ch in ks.by_status(ChannelStatus.READY):
            if ch.channel_id in self.blocked:
                self.blocked.discard(ch.channel_id)
                recovered.append(ch.channel_id)
        if recovered:
            self.route_tail_audit["inplace_shots"]["blocked_ready_recovered"] += \
                len(recovered)
            self.route_tail_audit["inplace_shots"].setdefault(
                "blocked_ready_channels", []).extend(recovered)

    def _route_burst_close(self, cid, reason):
        self._route_burst_shots.pop(cid, None)
        self._route_burst_closed.add(cid)
        self._route_burst_closed_reason[cid] = reason

    def _route_burst_housekeeping(self, ks, position):
        """End a burst as soon as it can no longer continue in place."""
        for cid in list(self._route_burst_shots):
            ch = ks.channels.get(cid)
            if ch is None or ch.status != ChannelStatus.ACTIVE or ch.mec is None:
                self._route_burst_close(cid, "channel_terminal")
                continue
            radius = float(ch.mec_radius)
            if (radius < self.rolling_inplace_mec_min_m or
                    radius > self.rolling_inplace_mec_max_m):
                self._route_burst_close(cid, "mec_out_of_window")
                continue
            if self._route_burst_shots[cid] >= self.rolling_inplace_shots:
                self._route_burst_close(cid, "budget_spent")
                continue
            failed = list(getattr(self, "_probe_failures", {}).get(cid, ()))
            if not failed or self._point_distance(position, failed[-1]) > \
                    self.rolling_inplace_at_point_m:
                self._route_burst_close(cid, "left_clear_point")

    def _route_burst_samples(self, ch, failed, fine):
        """Area-uniform samples of the surviving feasible region.

        The region is convex; fan triangulation from one vertex keeps the
        sampling uniform inside it.  Sampling the MEC *disk* instead would miss
        a thin sliver (the MEC is only a bounding circle), which is exactly the
        geometry left behind by two nearly parallel bearings.
        """
        region = ch.feasible_region
        if not region:
            return []
        samples = []
        if len(region) < 3:
            samples = [(float(v[0]), float(v[1])) for v in region]
        else:
            origin = region[0]
            for index in range(1, len(region) - 1):
                b = region[index]
                c = region[index + 1]
                span = max(self._point_distance(origin, b),
                           self._point_distance(origin, c),
                           self._point_distance(b, c))
                steps = max(2, int(math.ceil(span / fine)) + 1)
                for u in range(steps + 1):
                    for v in range(steps + 1 - u):
                        fu = u / float(steps)
                        fv = v / float(steps)
                        samples.append((
                            origin[0] + fu * (b[0] - origin[0]) +
                            fv * (c[0] - origin[0]),
                            origin[1] + fu * (b[1] - origin[1]) +
                            fv * (c[1] - origin[1])))
        surviving = []
        for x, y in samples:
            if any((x - fx) ** 2 + (y - fy) ** 2 <= C.CLEAR_RADIUS ** 2
                   for fx, fy in failed):
                continue
            surviving.append((x, y))
        return surviving

    def _route_burst_point(self, ch, position, failed):
        """Next in-place shot and its observable success fraction.

        The surviving set is the feasible region minus the 20 m disks the
        failed clears have already excluded.  Candidate shots sit one (or half
        a) shot spacing from the current position; the one covering the most
        surviving mass wins.
        """
        fine = max(3.0, min(6.0, float(ch.mec_radius) / 10.0))
        samples = self._route_burst_samples(ch, failed, fine)
        if not samples:
            return None, 0.0, 0
        step = self.rolling_inplace_step_m
        best = None
        for fraction in (0.5, 1.0):
            for index in range(12):
                angle = 2.0 * math.pi * index / 12.0
                point = (position[0] + step * fraction * math.cos(angle),
                         position[1] + step * fraction * math.sin(angle))
                if math.hypot(point[0], point[1]) > C.OMEGA_RADIUS + 1e-9:
                    continue
                if any((point[0] - fx) ** 2 + (point[1] - fy) ** 2 <=
                       C.CLEAR_RADIUS ** 2 for fx, fy in failed):
                    # Provably outside the source set: a wasted shot.
                    continue
                covered = sum(1 for sample in samples
                              if (sample[0] - point[0]) ** 2 +
                              (sample[1] - point[1]) ** 2 <= C.CLEAR_RADIUS ** 2)
                if covered <= 0:
                    continue
                share = covered / float(len(samples))
                key = (-share, self._point_distance(position, point),
                       point[0], point[1])
                if best is None or key < best[0]:
                    best = (key, point, share)
        if best is None:
            return None, 0.0, len(samples)
        return best[1], best[2], len(samples)

    def _route_burst_candidates(self, ks, position, current_channel):
        """Up to 2-3 in-place clears on a small MEC after a failed shot."""
        if self.rolling_inplace_shots <= 0 or self.mode != "Q4":
            return []
        self._route_burst_housekeeping(ks, position)
        out = []
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            cid = ch.channel_id
            if cid in self._route_burst_closed or ch.mec is None:
                continue
            radius = float(ch.mec_radius)
            if (radius < self.rolling_inplace_mec_min_m or
                    radius > self.rolling_inplace_mec_max_m):
                continue
            failed = list(getattr(self, "_probe_failures", {}).get(cid, ()))
            if not failed:
                # The burst is a reaction to a shot that already failed; it is
                # never a first, unprovoked gamble.
                continue
            used = self._route_burst_shots.get(cid, 1)
            entering = cid not in self._route_burst_shots
            if entering and self.fallback.in_fallback(cid):
                continue
            if entering and cid in self.blocked:
                # The baseline retry rule already sent this channel to manual
                # check: no *new* burst may start on it.
                continue
            if used >= self.rolling_inplace_shots:
                continue
            anchor = failed[-1]
            distance = self._point_distance(position, anchor)
            if distance > self.rolling_inplace_at_point_m:
                # The robot has already walked away from the failed shot; the
                # burst is only "in place" while it is still standing there.
                continue
            point, share, n_samples = self._route_burst_point(ch, position,
                                                            failed)
            row_id = "burst/%d/%d" % (cid, used)
            row = {
                "row_id": row_id, "family": "inplace_shots",
                "channel": cid,
                "point": None if point is None else [round(point[0], 3),
                                                     round(point[1], 3)],
                "mec_radius": round(radius, 3),
                "mec_center": [round(ch.mec[0][0], 3),
                               round(ch.mec[0][1], 3)],
                "n_failed_clears": len(failed),
                "last_failure": [round(failed[-1][0], 3),
                                 round(failed[-1][1], 3)],
                "distance_to_anchor_m": round(distance, 3),
                "anchor": [round(anchor[0], 3), round(anchor[1], 3)],
                "mec_window": [round(self.rolling_inplace_mec_min_m, 3),
                               round(self.rolling_inplace_mec_max_m, 3)],
                "at_point_limit_m": round(self.rolling_inplace_at_point_m, 3),
                "shots_used": used,
                "shots_budget": self.rolling_inplace_shots,
                "blocked": bool(cid in self.blocked),
                "in_fallback": bool(self.fallback.in_fallback(cid)),
                "coverage_share": round(share, 6),
                "surviving_samples": n_samples,
                "travel_m": (None if point is None else
                             round(self._point_distance(position, point), 3)),
                "charged_cost_s": None, "score": None, "chosen": False,
                "emitted": False,
                "rejected_reason": (None if point is not None else
                                    "no_surviving_shot_point"),
            }
            violation = (not (self.rolling_inplace_mec_min_m <= radius <=
                              self.rolling_inplace_mec_max_m) or not failed)
            self._route_audit("inplace_shots", row)
            if violation:
                self._route_audit_violation("inplace_shots", row)
            if point is None or used >= self.rolling_inplace_shots:
                continue
            mission = Mission(
                "clear", point, channel=cid,
                meta={"kind": "inplace_shot", "rolling": True,
                      "inplace_shot": True,
                      "burst_probability": float(share),
                      "burst_shots_used": used,
                      "burst_shots_budget": self.rolling_inplace_shots,
                      "rolling_benefit": 170.0 + max(
                          0.0, self.rolling_inplace_mec_max_m - radius),
                      "route_audit_row": row_id})
            row["emitted"] = True
            row["charged_cost_s"] = round(self._rolling_action_cost(
                mission, position, current_channel, ks), 3)
            row["score"] = round(self._rolling_score(
                mission, ks, position, current_channel), 6)
            self.route_tail_audit["inplace_shots"]["candidates"] += 1
            self._route_pending_audit[row_id] = row
            out.append(mission)
        return out

    def _route_note_competition(self, chosen, ks, position, current_channel):
        """Log the tournament result for every decision a family entered.

        Diagnostic only: it shows the score a tail candidate had to beat, so a
        reviewer can tell "the family never fired" apart from "the family fired
        and lost".
        """
        if not self._route_pending_audit:
            return
        log = self.route_tail_audit.setdefault("competition", [])
        if len(log) >= self.route_tail_audit_row_limit:
            return
        winner_score = self._rolling_score(chosen, ks, position,
                                           current_channel)
        for row in self._route_pending_audit.values():
            log.append({
                "row_id": row.get("row_id"),
                "family": row.get("family"),
                "channel": row.get("channel"),
                "candidate_score": row.get("score"),
                "candidate_cost_s": row.get("charged_cost_s"),
                "winner_meta_kind": chosen.meta.get("kind"),
                "winner_channel": chosen.channel,
                "winner_score": round(float(winner_score), 6),
            })

    def _route_record_choice(self, mission, ks, position, current_channel):
        """Bookkeeping + audit row for a chosen tail-family mission.

        The charged cost is recomputed here from the runner's own ``plan_stop``
        (through ``_rolling_action_cost``), which is the same value the scoring
        used; the audit stores it next to the executed ledger for the
        plan-vs-execution check.
        """
        row_id = mission.meta.get("route_audit_row")
        if row_id is None:
            return
        family = ("bias_homing" if mission.meta.get("bias_homing")
                  else "inplace_shots")
        audit = self.route_tail_audit[family]
        audit["chosen"] += 1
        row = self._route_pending_audit.get(row_id)
        if row is None:
            return
        row["chosen"] = True
        row["charged_cost_s"] = round(self._rolling_action_cost(
            mission, position, current_channel, ks), 3)
        # Keep the plan-derived price on the mission itself so an audit runner
        # can compare it with the executed ledger rows of this very mission.
        mission.meta["charged_cost_s"] = row["charged_cost_s"]
        if family == "bias_homing":
            self._route_bias_attempted.add(mission.channel)
        else:
            cid = mission.channel
            self._route_burst_shots[cid] = self._route_burst_shots.get(cid, 1) + 1

    def _rolling_coverage_candidate(self, ks, position=None):
        """Get or refresh one coverage action without discarding it on a tie."""
        pending = self._rolling_coverage
        if pending is not None:
            if pending.kind == "measure":
                if (pending.channel not in ks.channels or
                        ks[pending.channel].status != ChannelStatus.ACTIVE):
                    self._rolling_coverage = None
                else:
                    return pending
            else:
                # UNKNOWN membership is observable and may shrink while the
                # action waits in the rolling pool.
                return Mission(
                    "scan", pending.target,
                    channels=[c.channel_id for c in ks.unknown],
                    meta=dict(pending.meta))
        if (position is not None and getattr(self, "rolling_replan_coverage", False)
                and self.mode == "Q4" and self._coverage_points is not None
                and self._coverage_index < len(self._coverage_points)):
            # Keep executed certificate points fixed, but choose the next
            # suffix from the current position. Every point remains in the
            # finite set, so this only changes open-path route order.
            prefix = self._coverage_points[:self._coverage_index]
            suffix = self._coverage_points[self._coverage_index:]
            self._coverage_points = prefix + _greedy_order(suffix, position)
        candidate = self._coverage_scan(ks)
        if candidate is not None:
            self._rolling_attach_joint_measure(ks, candidate)
            candidate.meta["rolling"] = True
            self._rolling_coverage = candidate
        return candidate

    def _rolling_attach_joint_measure(self, ks, mission):
        """Add at most one observable ACTIVE supplement to a scan stop.

        The runner executes this as an ordinary /measure at the same stop.
        Eligibility is only the conservative MEC/envelope intersection; no
        hidden source position or outcome is consulted.
        """
        # Q3's seven-point cover is already cheap; broad ACTIVE supplements
        # there cost more than the saved bearing detours on sparse cases.
        # Q4 keeps this hook because its certificate tour is the dominant
        # movement cost and the same stop can safely collect a second view.
        if (self.mode != "Q4" or mission.kind != "scan" or
                mission.meta.get("joint_channels") or
                self.rolling_joint_active_limit <= 0):
            return
        ranked = []
        gate = getattr(self, "joint_bearing_allowed", None)
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            if (self.fallback.in_fallback(ch.channel_id) or ch.mec is None or
                    any(math.dist(mission.target, obs["position"]) <= 1.0
                        for obs in ch.observations if "position" in obs)):
                continue
            center, radius = ch.mec
            overlap = C.R_EFF_MIN + float(radius) - math.dist(
                mission.target, center)
            if overlap < 0.0:
                continue
            min_mec = float(getattr(self, "q4_joint_min_mec_m", 0.0) or 0.0)
            if min_mec > 0.0 and float(radius) <= min_mec:
                # This channel is already in its endgame. Let the nearby
                # optical probe or finite cover finish it instead of paying a
                # further certificate-stop bearing.
                continue
            if gate is not None and not gate(ch, mission.target):
                # This stop sits almost on the bearing ray already received
                # for the channel, so a second measurement there would repeat
                # the same wedge instead of cutting a new baseline.
                continue
            min_signal = float(getattr(
                self, "q4_joint_min_signal_probability", 0.0) or 0.0)
            probability = getattr(self, "joint_signal_probability", None)
            if min_signal > 0.0 and callable(probability):
                # Geometric envelope overlap only says that reception is
                # possible.  For a directional source a witness can still be
                # almost certainly on the dark side, in which case paying a
                # same-stop measurement adds no bearing information.  Keep
                # the generic rolling planner agnostic of the posterior; a
                # Q4 policy may opt into this observable risk gate.
                if probability(ks, ch, mission.target) + 1e-12 < min_signal:
                    stats = getattr(self, "shadow_stats", None)
                    if isinstance(stats, dict):
                        stats["joint_signal_filtered"] = (
                            int(stats.get("joint_signal_filtered", 0)) + 1)
                    continue
            mec_limit = float(getattr(self, "q4_joint_max_mec_m", 0.0) or 0.0)
            if mec_limit > 0.0 and float(radius) > mec_limit:
                # Only spend the extra same-stop measurement on channels that
                # are already close to clearable: there the bearing usually
                # finishes the job and the en-route clear can fire at once.
                continue
            dirs = sum(obs["result"] == "direction"
                       for obs in ch.observations)
            value = overlap / (1.0 + dirs)
            if getattr(self, "q4_joint_angle_rank", False):
                # Rank by how much the new bearing can actually cut the region
                # (crossing angle against the last received bearing), not only
                # by how much of the envelope the stop covers.
                value *= getattr(self, "_bearing_cut_value", lambda c, p: 1.0)(
                    ch, mission.target)
            ranked.append((value, -ch.channel_id, ch.channel_id))
        if ranked:
            ranked.sort(reverse=True)
            mission.meta["joint_channels"] = [row[-1] for row in
                                               ranked[:self.rolling_joint_active_limit]]
            mission.meta["joint_route"] = True

    def _rolling_take_coverage(self):
        candidate = self._rolling_coverage
        self._rolling_coverage = None
        self._rolling_coverage_age = 0
        return candidate

    @staticmethod
    def _sequence_cost(channels, start_channel):
        """Seconds spent measuring an ordered channel list at one stop.

        Five seconds per measurement plus one second whenever the channel
        actually changes; the first measurement is charged against the
        channel already selected in the executor.
        """
        total = 0.0
        current = start_channel
        for channel in channels:
            total += C.MEASURE_TIME
            if channel != current:
                total += C.SWITCH_TIME
            current = channel
        return total

    def _clear_plan_probability(self, mission, ks):
        """Observable estimate of clear success for the branch weighting."""
        if mission.kind != "clear":
            return 1.0
        if mission.meta.get("burst_probability") is not None:
            # In-place burst shot: the probability is the observable fraction of
            # the surviving region the shot's 20 m clear disk covers (uniform
            # prior over the samples that no earlier failure has excluded), so
            # the branch-weighted clear cost is not assumed to succeed.
            return max(0.0, min(1.0, float(mission.meta["burst_probability"])))
        if mission.meta.get("rolling_probe"):
            radius = float(mission.meta.get("probe_radius_m") or 0.0)
            if radius <= 0.0:
                return 0.25
            return max(0.0, min(1.0, (C.CLEAR_RADIUS / radius) ** 2))
        if mission.meta.get("fallback"):
            radius = float(mission.meta.get("fallback_radius_m") or 0.0)
            if radius <= 0.0:
                return 1.0
            return max(0.0, min(1.0, (C.CLEAR_RADIUS / radius) ** 2))
        channel = ks[mission.channel] if mission.channel in ks.channels else None
        if channel is not None and channel.mec_radius <= C.CLEAR_RADIUS:
            return 1.0
        return 1.0 if mission.channel is not None else 1.0

    def _rolling_action_cost(self, mission, position, current_channel, ks):
        """Travel plus the *executed* action cost of one mission.

        The action part is taken from the runner's own stop plan, so a stop
        that appends an opportunistic scan, a joint ACTIVE supplement or a
        post-clear sweep is priced for what it will really do.  A clear never
        changes the measurement channel, and its cost is the expected value
        over the two outcome branches.
        """
        travel = self._point_distance(position, mission.target) / C.MOVE_SPEED
        planner = (getattr(self, "stop_planner", None)
                   if getattr(self, "rolling_plan_cost", True) else None)
        if planner is not None:
            plan = planner(mission)
            if plan.get("kind") == "clear":
                probability = self._clear_plan_probability(mission, ks)
                success = (C.CLEAR_SUCCESS_TIME + self._sequence_cost(
                    plan.get("success", ()), current_channel))
                failure = (C.CLEAR_FAIL_TIME + self._sequence_cost(
                    plan.get("failure", ()), current_channel))
                return travel + probability * success + (1.0 - probability) * failure
            return travel + self._sequence_cost(plan.get("measures", ()),
                                                current_channel)
        # Fallback estimate when no runner plan is attached (kept so the mixin
        # remains usable on its own): the legacy single-measurement view.
        if mission.kind == "scan":
            count = len(mission.channels)
            action = C.MEASURE_TIME * count + max(0, count - 1)
            channel = current_channel
        elif mission.kind == "clear":
            return travel + C.CLEAR_SUCCESS_TIME
        else:
            action = C.MEASURE_TIME
            channel = mission.channel
        switch = (C.SWITCH_TIME if channel is not None and
                  channel != current_channel else 0.0)
        return travel + switch + action

    def _rolling_future_proxy(self, ks, target, mission):
        """Cheap two-step continuation proxy, using only current state."""
        active = [c for c in ks.by_status(ChannelStatus.ACTIVE)
                  if not self.fallback.in_fallback(c.channel_id)]
        ready = list(ks.by_status(ChannelStatus.READY))
        unknown = len(ks.by_status(ChannelStatus.UNKNOWN))
        active_tail = sum(min(1800.0, c.mec_radius) / C.MOVE_SPEED
                          for c in active)
        ready_tail = sum(math.dist(target, self._clear_target(c, target)) /
                         C.MOVE_SPEED for c in ready)
        # UNKNOWN still needs either a rolling discovery stop or the finite
        # certificate.  Keep this term modest so one nearby informative stop
        # can beat a distant READY clear, but cap it to avoid starvation.
        unknown_tail = min(1200.0, 5.0 * unknown)
        benefit = float(mission.meta.get("rolling_benefit", 0.0))
        if mission.kind == "measure":
            benefit += min(240.0, max(0.0, float(
                mission.meta.get("gain", 0.0))))
        elif mission.kind == "scan":
            benefit += min(260.0, 14.0 * len(mission.channels))
        remaining = max(0.0, active_tail + ready_tail + unknown_tail - benefit)
        return remaining

    def _rolling_score(self, mission, ks, position, current_channel):
        if getattr(self, "rolling_lookahead", False):
            return self._lookahead_score(mission, ks, position,
                                         current_channel)
        immediate = self._rolling_action_cost(
            mission, position, current_channel, ks)
        future = self._rolling_future_proxy(ks, mission.target, mission)
        kind_bonus = {"clear": 0.0, "measure": -12.0, "scan": -18.0}.get(
            mission.kind, 0.0)
        # A short horizon is represented by immediate + one continuation;
        # the coverage age gate below prevents indefinitely postponing the
        # exact finite certificate.
        return immediate + 0.35 * future + kind_bonus

    def _rolling_enroute_clear(self, ks, position, coverage, detour_limit):
        """Clear (or probe) a source that lies on the way to the next stop.

        The discovery tour and the clear sweep otherwise cover the same disk
        twice.  When a guaranteed or opportunistic clear is reachable for a
        small detour off the route to the pending coverage stop, pay it now
        and keep the coverage stop pending; the observation obtained on the way
        is still processed by the normal runner.  Only observable geometry is
        used, and the detour is bounded so the finite cover cannot starve.
        """
        if coverage is None or detour_limit <= 0.0:
            return None
        best = None
        candidates = (self._rolling_ready_candidates(ks, position) +
                      self._rolling_probe_candidates(ks, position))
        base = self._point_distance(position, coverage.target)
        for mission in candidates:
            via = self._point_distance(position, mission.target)
            back = self._point_distance(mission.target, coverage.target)
            detour = via + back - base
            if detour > detour_limit:
                continue
            key = (detour, 0 if mission.kind == "clear" else 1,
                   mission.channel if mission.channel is not None else -1)
            if best is None or key < best[0]:
                best = (key, mission)
        if best is None:
            return None
        chosen = best[1]
        chosen.meta["enroute"] = True
        chosen.meta["enroute_detour_m"] = float(best[0][0])
        chosen.meta["rolling_horizon"] = self.rolling_horizon
        if chosen.meta.get("rolling_probe"):
            self._rolling_probe_attempted.add(chosen.channel)
        return chosen

    def _lookahead_grid(self):
        if self._lookahead_samples is None:
            step = self.rolling_lookahead_step_m
            samples = []
            y = -C.OMEGA_RADIUS
            while y <= C.OMEGA_RADIUS + 1e-9:
                x = -C.OMEGA_RADIUS
                while x <= C.OMEGA_RADIUS + 1e-9:
                    if x * x + y * y <= C.OMEGA_RADIUS ** 2:
                        samples.append((x, y))
                    x += step
                y += step
            self._lookahead_samples = samples
        return self._lookahead_samples

    def _rollout_value(self, shadow, position, current_channel):
        """Continuation value of a shadow state, priced with the real model.

        One greedy step of the same candidate families is evaluated so the
        value is expressed in the same seconds as the immediate cost.
        """
        best = None
        candidates = list(self._rolling_ready_candidates(shadow, position))
        if shadow.active:
            active = self._active_measure(shadow, position, current_channel)
            if active is not None:
                candidates.append(active)
        for mission in candidates:
            cost = self._rolling_action_cost(mission, position,
                                             current_channel, shadow)
            key = (cost, mission.channel if mission.channel is not None else -1)
            if best is None or key < best[0]:
                best = (key, mission)
        greedy = best[0][0] if best is not None else 0.0
        tail = self._rolling_future_proxy(shadow, position,
                                          _NullMission(position))
        return greedy + 0.35 * tail

    def _lookahead_score(self, mission, ks, position, current_channel):
        """Immediate cost plus the expected value of the continuation.

        The one-step expansion uses observable outcome probabilities and the
        runner's own update functions on shadow states, so the planner is
        priced in the same units as the action it chooses.
        """
        immediate = self._rolling_action_cost(mission, position,
                                              current_channel, ks)
        if mission.kind == "clear":
            return immediate + 0.35 * self._rolling_future_proxy(
                ks, mission.target, mission)
        grid = self._lookahead_grid()
        facing = 1.0
        if self.mode == "Q4":
            # Half of a mixed population faces away from any given stop; the
            # prior is observable only through the type mix seen so far, which
            # this keeps at its uninformed value.
            facing = 0.5
        if mission.kind == "measure" and mission.channel is not None:
            branches = measurement_branches(ks, mission.channel,
                                            mission.target, grid, facing)
        elif mission.kind == "scan":
            branches = scan_branches(ks, mission, grid, facing)
        else:
            return immediate + 0.35 * self._rolling_future_proxy(
                ks, mission.target, mission)
        total = 0.0
        mass = 0.0
        for probability, shadow in branches:
            total += probability * self._rollout_value(
                shadow, mission.target, current_channel)
            mass += probability
        if mass > 0.0:
            total /= mass
        return immediate + total

    def _emit_rolling_trace(self, ks, position, current_channel, candidates,
                            chosen, evaluated):
        """Record the rolling decision, its priced candidates and the choice.

        Without this the pool's decisions are invisible in the run artifacts:
        the executor's action rows show *what* ran, never *what was compared*.
        Each candidate carries the cost the planner actually charged it, which
        is the same value the runner's stop plan yields.
        """
        if self.decision_listener is None:
            return
        scores = {}
        if evaluated is not None:
            for score, _tie, _channel, mission in evaluated:
                scores[id(mission)] = score
        trace = self._trace_base(ks, "rolling")
        trace["candidates"] = []
        for mission in candidates:
            cost = self._rolling_action_cost(mission, position,
                                             current_channel, ks)
            trace["candidates"].append({
                "kind": mission.kind,
                "meta_kind": mission.meta.get("kind"),
                "channel": mission.channel,
                "point": [round(mission.target[0], 3),
                          round(mission.target[1], 3)],
                "immediate_cost": round(cost, 3),
                "score": round(scores.get(id(mission), float("nan")), 3),
            })
        trace["selected"] = {
            "kind": chosen.kind,
            "meta_kind": chosen.meta.get("kind"),
            "channel": chosen.channel,
            "point": [round(chosen.target[0], 3), round(chosen.target[1], 3)],
            "score": round(scores.get(id(chosen), float("nan")), 3),
        }
        trace["rolling_age"] = self._rolling_coverage_age
        trace["rolling_decisions"] = self._rolling_decisions
        trace["tie_break"] = ("min (score, kind rank, channel); coverage "
                              "deadline at age %d" % self.rolling_coverage_period)
        self._emit(trace)

    def _rolling_decide(self, ks, position, current_channel):
        if not self.rolling_enabled:
            return None
        self._route_burst_recover_ready(ks)
        coverage = self._rolling_coverage_candidate(ks, position)
        if coverage is None:
            self._rolling_coverage_age = 0
        candidates = []
        # Audit rows are per-decision: a mission that is not chosen keeps its
        # generation-time row in the family's log but is not linked here.
        self._route_pending_audit = {}
        candidates.extend(self._rolling_ready_candidates(ks, position))
        candidates.extend(self._rolling_probe_candidates(ks, position))
        # Q4 tail families (default OFF; empty lists when disabled).
        candidates.extend(self._route_bias_candidates(ks, position,
                                                      current_channel))
        candidates.extend(self._route_burst_candidates(ks, position,
                                                       current_channel))
        if ks.active:
            listener = getattr(self, "decision_listener", None)
            try:
                # Candidate generation must not emit traces for actions that
                # are not selected.
                self.decision_listener = None
                active_candidates = self._rolling_active_candidates(
                    ks, position, current_channel)
            finally:
                self.decision_listener = listener
            for active in active_candidates:
                active.meta["rolling"] = True
                candidates.append(active)
        if coverage is not None:
            candidates.append(coverage)
        if not candidates:
            return None
        self._rolling_decisions += 1
        self._rolling_coverage_age += 1
        # Q4 still needs its directional/absence coverage while UNKNOWN
        # channels are numerous.  Let the rolling pool exploit the stop via
        # the joint ACTIVE supplement, but do not replace the finite cover
        # with repeated local pursuit.
        force_threshold = max(0, int(getattr(
            self, "rolling_unknown_force_threshold", 4)))
        compete = bool(getattr(self, "rolling_compete_coverage", False))
        force = (not compete and self.mode == "Q4" and coverage is not None
                 and len(ks.by_status(ChannelStatus.UNKNOWN)) > force_threshold)
        if force and getattr(self, "q4_work_first", False):
            # Merged route for Q4: while live channels exist, working on them
            # already puts the robot in new places, so the coverage stop is
            # only taken when nothing live is left to do.
            if ks.active or ks.ready:
                force = False
        min_active = int(getattr(self, "q4_work_first_min_active", 0) or 0)
        if force and min_active > 0 and len(ks.active) >= min_active:
            # Conditional release of the coverage pre-emption: the offline
            # choice probe found its largest one-step regrets exactly at
            # states where many ACTIVE channels were pending while the
            # coverage stop was forced.  Both inputs are observable.
            force = False
        if force:
            override = getattr(self, "_rolling_forced_override", None)
            if override is not None:
                chosen = override(ks, position, current_channel,
                                  coverage, candidates)
                if chosen is not None:
                    chosen.meta["rolling_horizon"] = self.rolling_horizon
                    chosen.meta["rolling_age"] = self._rolling_coverage_age
                    return chosen
            enroute = self._rolling_enroute_clear(
                ks, position, coverage,
                max(0.0, float(getattr(self, "rolling_enroute_detour_m", 0.0))))
            if enroute is not None:
                return enroute
            chosen = self._rolling_take_coverage()
            chosen.meta["rolling_horizon"] = self.rolling_horizon
            chosen.meta["rolling_age"] = self._rolling_coverage_age
            return chosen
        # Coverage is a hard deadline inside the rolling horizon.  It remains
        # a normal /scan or certificate ACTIVE measurement, so this guard
        # never certifies anything by assumption.
        if (coverage is not None and
                self._rolling_coverage_age >= self.rolling_coverage_period):
            chosen = self._rolling_take_coverage()
            self._emit_rolling_trace(ks, position, current_channel,
                                     candidates, chosen, None)
        else:
            evaluated = []
            for mission in candidates:
                score = self._rolling_score(mission, ks, position,
                                            current_channel)
                evaluated.append(
                    (score,
                     0 if mission.kind == "measure" else
                     (1 if mission.kind == "clear" else 2),
                     mission.channel if mission.channel is not None else -1,
                     mission))
            _, _, _, chosen = min(evaluated, key=lambda item: item[:3])
            self._emit_rolling_trace(ks, position, current_channel,
                                     candidates, chosen, evaluated)
            if chosen is coverage:
                chosen = self._rolling_take_coverage()
            self._route_record_choice(chosen, ks, position, current_channel)
            self._route_note_competition(chosen, ks, position,
                                         current_channel)
        chosen.meta["rolling_horizon"] = self.rolling_horizon
        chosen.meta["rolling_age"] = self._rolling_coverage_age
        if chosen.meta.get("rolling_probe"):
            # Do not retry an unsuccessful opportunistic clear.  The next
            # decision will use the normal observation-driven route.
            self._rolling_probe_attempted.add(chosen.channel)
        return chosen
