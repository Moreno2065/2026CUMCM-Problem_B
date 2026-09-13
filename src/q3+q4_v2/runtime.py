"""Shared execution adapter for the three independent v2 strategy folders.

The adapter deliberately reuses the already checked protocol, executor and
evidence writer. Strategy folders own their scheduler; this file only builds
the same simulator/backend and runs one case.
"""
from __future__ import annotations

import importlib
import math
import os
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
LEGACY_CODE = PACKAGE / "baseline" / "code"
if str(LEGACY_CODE) not in sys.path:
    sys.path.insert(0, str(LEGACY_CODE))

from executor.action_executor import ActionExecutor
from experiment.runner import GameRunner
from experiment.simulator import SimulatorBackend, SimulatorHTTPServer, SyntheticSimulator
from experiment.config import MainlineConfig
from geometry import constants as C
from geometry.fallback_cover import _point_polygon_distance as point_polygon_distance
from lookahead import discovery_share
from state.channel_state import ChannelStatus
import production
from policy.scheduler import plan_stop_measures


class V2GameRunner(GameRunner):
    """GameRunner variant with v2-only feedback and cardinality inference.

    The copied baseline under ``baseline/`` remains an immutable provenance
    snapshot.  v2-specific state transitions and verifier handling live here
    so the snapshot hash remains independently checkable.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._scan_value_grid = None

    def _apply_cardinality_cap(self, virtual_time):
        """Certify residual UNKNOWN channels after 16 positive channels.

        A direction or near result is positive existence evidence.  The
        problem statement bounds the total number of sources by 16, so once
        16 distinct channels are ACTIVE/READY/CLEARED, every remaining
        UNKNOWN channel is absent.  This never consults simulator truth and
        never marks a confirmed source as cleared.
        """
        confirmed = (len(self.ks.active) + len(self.ks.ready) +
                     len(self.ks.cleared))
        if confirmed < C.MAX_SOURCES:
            return []
        changed = []
        for ch in self.ks.unknown:
            ch.status = ChannelStatus.CERTIFIED_ABSENT
            ch.absent_basis = "cardinality"
            ch._record((0.0, 0.0), "cardinality_absent", virtual_time)
            changed.append(ch.channel_id)
        return changed

    def _apply_measure(self, outcome, primary, was_approach):
        super()._apply_measure(outcome, primary, was_approach)
        if outcome.accepted:
            self._apply_cardinality_cap(outcome.vtime_after)
        if not primary:
            callback = getattr(self.scheduler, "on_scan_measure_result", None)
            if callback is not None and outcome.accepted:
                callback(self.ks[outcome.channel], outcome.result,
                         position=outcome.position)

    def _cardinality_reached(self):
        """Terminal suffix check, driven only by observable channel states.

        The suffix short-circuit is a route optimization, not part of the
        certificate rule: once 16 distinct channels carry positive existence
        evidence, every remaining UNKNOWN channel is absent and cannot repay a
        measurement.  The predicate therefore reads the KnowledgeState only and
        behaves identically for a local synthetic run and a remote official
        run, where no scenario label exists at all.
        """
        return (len(self.ks.active) + len(self.ks.ready)
                + len(self.ks.cleared)) >= C.MAX_SOURCES

    def _valued_grid(self):
        if self._scan_value_grid is None:
            step = 120.0
            samples = []
            y = -C.OMEGA_RADIUS
            while y <= C.OMEGA_RADIUS + 1e-9:
                x = -C.OMEGA_RADIUS
                while x <= C.OMEGA_RADIUS + 1e-9:
                    if x * x + y * y <= C.OMEGA_RADIUS ** 2:
                        samples.append((x, y))
                    x += step
                y += step
            self._scan_value_grid = samples
        return self._scan_value_grid

    def _valued_scan_set(self, at_position):
        """UNKNOWN channels whose measurement here could still reveal a source.

        Q3 uses the share of the remaining hiding region intersected by the
        guaranteed reception disk.  A Q4 posterior hook may instead score the
        full latent orientation/radius hypothesis set.  Measurements below
        the scheduler's threshold are skipped at *opportunistic* stops only:
        coverage/certificate missions keep the complete scan set, so no
        absence witness is ever dropped from the certificate.
        """
        posterior_score = None
        if self.mode == "Q4":
            posterior_score = getattr(
                self.scheduler, "unknown_discovery_probability", None)
        threshold_provider = (getattr(
            self.scheduler, "unknown_discovery_threshold", None)
                              if posterior_score is not None else None)
        if threshold_provider is not None:
            threshold = float(threshold_provider(self.ks) or 0.0)
        else:
            threshold_name = ("q4_discovery_probability_threshold"
                              if posterior_score is not None else
                              "valued_scan_share")
            threshold = float(getattr(self.scheduler, threshold_name, 0.0)
                              or 0.0)
        if threshold <= 0.0:
            return None
        grid = None if posterior_score is not None else self._valued_grid()
        selected = []
        for channel in self.ks.channels.values():
            if channel.status != ChannelStatus.UNKNOWN:
                continue
            if self._measured_near(channel, at_position):
                continue
            # In Q4, no_signal is not a position-exclusion disk: a nearby
            # directional source may simply face away from the receiver.  A
            # scheduler with a Q4 posterior therefore scores the full joint
            # (position, radius, antenna type, orientation) hypothesis set.
            # The historical disk-share remains the Q3/default path.
            share = (posterior_score(self.ks, channel, at_position)
                     if posterior_score is not None else
                     discovery_share(channel, at_position, grid))
            if share >= threshold:
                selected.append((float(share), channel.channel_id))
        if posterior_score is not None:
            cap = max(0, int(getattr(
                self.scheduler, "q4_discovery_max_channels_per_stop", 0)
                             or 0))
            selected.sort(key=lambda row: (-row[0], row[1]))
            if cap:
                selected = selected[:cap]
            recorder = getattr(
                self.scheduler, "record_unknown_discovery_selection", None)
            if recorder is not None:
                recorder(selected, threshold)
        return [channel_id for _share, channel_id in selected]

    def _scan_set(self, at_position, scan_mode=None):
        """Apply an observation-only Q3 margin without changing the baseline.

        The historical runner remains byte-for-byte independent of v2
        experiments.  A v2 scheduler may expose a margin derived from the
        current KnowledgeState; it is applied only for this call and restored
        immediately afterwards.
        """
        if scan_mode == "active_only" and self.mode == "Q3":
            # Discovery has stalled: keep the opportunistic bearings that help
            # localize live channels, but stop paying for UNKNOWN channels that
            # the certificate ring will visit anyway.
            margin = self.config.active_scan_margin_m
            observed = getattr(getattr(self, "scheduler", None),
                               "observed_active_scan_margin", None)
            if observed is not None:
                candidate = observed(self.ks)
                if candidate is not None:
                    margin = float(candidate)
            return [c.channel_id for c in self.ks.channels.values()
                    if c.status == ChannelStatus.ACTIVE
                    and c.mec is not None
                    and math.hypot(c.mec[0][0] - at_position[0],
                                   c.mec[0][1] - at_position[1])
                    <= (C.R_EFF_MIN + c.mec[1] + margin + 1e-9)
                    and not self._measured_near(c, at_position)]
        if scan_mode == "valued" and self.mode == "Q3":
            valued = self._valued_scan_set(at_position)
            if valued is not None:
                active = [c.channel_id for c in self.ks.channels.values()
                          if c.status == ChannelStatus.ACTIVE
                          and not self._measured_near(c, at_position)]
                return active + valued
        opportunistic = getattr(self.scheduler, "valued_scan_opportunistic",
                                False)
        if (opportunistic and scan_mode is None and self.mode in ("Q3", "Q4")):
            # Intersect the configured opportunistic scan set with the
            # discovery-value filter: certificate missions never come through
            # here, so no absence witness is dropped from the certificate.
            base = super()._scan_set(at_position, scan_mode)
            valued = self._valued_scan_set(at_position)
            if valued is not None:
                keep = set(valued)
                return [cid for cid in base
                        if cid in keep
                        or self.ks[cid].status == ChannelStatus.ACTIVE]
        if scan_mode == "detectable" and self.mode == "Q3":
            # Opportunistic (non-certificate) stop: a channel whose feasible
            # region lies entirely outside the maximum reception radius cannot
            # return a signal here, so the measurement carries no discovery
            # information.  Certificate points keep the complete scan set.
            return [c.channel_id for c in self.ks.channels.values()
                    if c.status == ChannelStatus.UNKNOWN
                    and c.feasible_region
                    and point_polygon_distance(c.feasible_region,
                                               at_position) <= C.R_EFF_MAX
                    and not self._measured_near(c, at_position)]
        observed_margin = getattr(
            getattr(self, "scheduler", None),
            "observed_active_scan_margin", None)
        if self.mode == "Q3" and observed_margin is not None:
            candidate_margin = observed_margin(self.ks)
            if candidate_margin is not None:
                original_margin = self.config.active_scan_margin_m
                self.config.active_scan_margin_m = float(candidate_margin)
                try:
                    return self._gate_active_scan(
                        super()._scan_set(at_position, scan_mode), at_position)
                finally:
                    self.config.active_scan_margin_m = original_margin
        return self._gate_active_scan(
            super()._scan_set(at_position, scan_mode), at_position)

    def _gate_active_scan(self, channels, at_position):
        """Drop collinear ACTIVE re-measurements from an opportunistic stop.

        A second bearing adds position information only when its ray crosses
        the ray already received; a stop that sits almost on that ray repeats
        the same wedge.  The gate only filters *opportunistic* scans (the
        certificate missions never come through here), so no completion
        evidence is lost.
        """
        scheduler = getattr(self, "scheduler", None)
        gate = float(getattr(scheduler, "active_scan_angle_gate_deg", 0.0)
                     or 0.0)
        cut_value = getattr(scheduler, "_bearing_cut_value", None)
        if gate <= 0.0 or scheduler is None or cut_value is None:
            return channels
        threshold = math.sin(math.radians(gate))
        keep = []
        for cid in channels:
            channel = self.ks[cid]
            if channel.status != ChannelStatus.ACTIVE:
                keep.append(cid)
                continue
            if cut_value(channel, at_position) >= threshold:
                keep.append(cid)
                continue
            # Keep the channel if the stop lies inside its feasible region:
            # there the new bearing splits the region instead of repeating it.
            mec = channel.mec
            if mec is not None and math.dist(at_position, mec[0]) <= 0.5 * max(
                    float(mec[1]), 1.0):
                keep.append(cid)
        return keep

    def _scan_variant_set(self, at_position, variant, primary=None):
        """Explicit measurement set for a stop, chosen by the scheduler.

        The decision variable is the *joint* action (stop, channels, order):
        the scheduler names the variant in the mission, this function turns it
        into the exact channel list, and ``plan_stop`` prices the same list.
        Variants:
          ``primary``  - only the mission's own channel;
          ``active``   - plus ACTIVE channels this stop can still localise;
          ``discover`` - plus UNKNOWN channels this stop can still reveal;
          ``full``     - both (the historical automatic scan set).
        """
        channels = []
        if variant == "primary":
            return channels
        if variant in ("active", "full"):
            channels.extend(self._gate_active_scan(
                self._active_scan_candidates(at_position), at_position))
        if variant in ("discover", "full"):
            valued = self._valued_scan_set(at_position)
            if valued is None:
                valued = [c.channel_id for c in self.ks.channels.values()
                          if c.status == ChannelStatus.UNKNOWN
                          and not self._measured_near(c, at_position)]
            channels.extend(valued)
        seen = set()
        if primary is not None:
            seen.add(primary)
        unique = []
        for cid in channels:
            if cid in seen:
                continue
            seen.add(cid)
            unique.append(cid)
        return unique

    def _active_scan_candidates(self, at_position):
        """ACTIVE channels whose reception envelope can reach this stop."""
        margin = self.config.active_scan_margin_m
        observed = getattr(getattr(self, "scheduler", None),
                           "observed_active_scan_margin", None)
        if self.mode == "Q3" and observed is not None:
            candidate = observed(self.ks)
            if candidate is not None:
                margin = float(candidate)
        out = []
        for channel in self.ks.channels.values():
            if channel.status != ChannelStatus.ACTIVE or channel.mec is None:
                continue
            if self._measured_near(channel, at_position):
                continue
            center, radius = channel.mec
            if math.hypot(center[0] - at_position[0],
                          center[1] - at_position[1]) <= (
                    C.R_EFF_MIN + radius + margin + 1e-9):
                out.append(channel.channel_id)
        return out

    def _stop_sequence(self, mission):
        """Ordered measure channels this mission will visit at its stop.

        This is the single source of truth for both execution and planning: the
        executor iterates over it, and the scheduler prices exactly the same
        list through ``plan_stop``.  A stop therefore costs five seconds per
        channel plus one second per channel change, instead of the single
        measurement the old estimate assumed.
        """
        primary = mission.channel if mission.kind == "measure" else None
        variant = mission.meta.get("scan_variant")
        if variant and mission.kind == "measure" and primary is not None:
            channels = self._scan_variant_set(mission.target, variant, primary)
            channels.extend(cid for cid in mission.meta.get("joint_channels", ())
                            if cid in self.ks.channels
                            and self.ks[cid].status == ChannelStatus.ACTIVE)
            return plan_stop_measures(primary, channels,
                                      self.executor.current_channel)
        if mission.kind == "scan":
            channels = [c for c in mission.channels
                        if self.ks[c].status == ChannelStatus.UNKNOWN
                        and not self._measured_near(self.ks[c], mission.target)]
            joint = mission.meta.get("joint_channels", ())
            channels.extend(
                cid for cid in joint
                if cid in self.ks.channels
                and self.ks[cid].status == ChannelStatus.ACTIVE
                and not self._measured_near(self.ks[cid], mission.target))
        else:
            channels = self._scan_set(mission.target,
                                      mission.meta.get("scan_mode"))
            # A joint-route mission may request a small, observable-only set of
            # ACTIVE channels at the same stop.  These are ordinary /measure
            # calls; the finite certificate remains the completion fallback.
            if mission.kind == "measure":
                joint = mission.meta.get("joint_channels", ())
                channels.extend(
                    cid for cid in joint
                    if cid in self.ks.channels
                    and self.ks[cid].status == ChannelStatus.ACTIVE)
        seq = plan_stop_measures(primary, channels,
                                 self.executor.current_channel)
        orderer = getattr(self.scheduler, "order_stop_channels", None)
        if orderer is not None:
            seq = list(orderer(self.ks, mission, seq,
                               self.executor.current_channel))
        # Cross-stop measure linking (default OFF; only the Q3 coverage planner
        # sets the hint).  ``plan_stop_measures`` sorts the set and puts the
        # current channel first, so the hint can only take effect *after* it:
        # ending this stop on the channel the next ring stop will start with
        # makes that stop's first measurement free, at no extra switch here
        # (every consecutive pair already differs).
        measure_last = mission.meta.get("measure_last")
        if (measure_last is not None and len(seq) > 1 and
                measure_last in seq and seq[0] != measure_last):
            seq = [cid for cid in seq if cid != measure_last] + [measure_last]
        return seq

    def _scan_set_after_clear(self, position, channel_id, success):
        """Opportunistic scan set for the stop *after* a clear, branch-aware.

        The state change is evaluated as a what-if and fully restored, so the
        scheduler can price both clear outcomes without executing anything.
        """
        ch = self.ks[channel_id]
        saved = (ch.status, ch.absent_basis)
        capped = []
        try:
            if success:
                ch.status = ChannelStatus.CLEARED
                confirmed = (len(self.ks.active) + len(self.ks.ready)
                             + len(self.ks.cleared))
                if confirmed >= C.MAX_SOURCES:
                    for other in self.ks.unknown:
                        capped.append((other, other.status, other.absent_basis))
                        other.status = ChannelStatus.CERTIFIED_ABSENT
            return self._scan_set(position, self._clear_scan_mode(bool(success)))
        finally:
            ch.status, ch.absent_basis = saved
            for other, status, basis in capped:
                other.status, other.absent_basis = status, basis

    def _failed_probe_remeasure_channel(self, mission, success):
        """Return the one same-channel observation permitted after a probe miss.

        A rolling probe has already paid to visit its selected MEC point.  When
        it misses, a fresh bearing from that exact point can be valuable; the
        normal post-clear sweep only visits UNKNOWN channels and would discard
        it.  This is deliberately narrow: the scheduler must opt in, the
        mission must be a rolling probe, and the channel must still be ACTIVE.
        It never replaces a sparse25 witness measurement.
        """
        if success or not getattr(self.scheduler,
                                  "rolling_probe_remeasure", False):
            return None
        if not (mission.meta.get("rolling_probe") or
                mission.meta.get("kind") == "rolling_probe"):
            return None
        # Below the source-count cap, the next certificate stops can still
        # discover an unseen channel.  Spending an extra active measurement
        # there repeatedly lost to the coverage route in the ablation.  At
        # the observable cap, all remaining work is localization/clearing and
        # this is the only regime where the extra close bearing repaid itself.
        confirmed = (len(self.ks.active) + len(self.ks.ready) +
                     len(self.ks.cleared))
        if confirmed < C.MAX_SOURCES:
            return None
        channel_id = mission.channel
        channel = self.ks.channels.get(channel_id)
        if channel is None or channel.status != ChannelStatus.ACTIVE:
            return None
        return channel_id

    def plan_stop(self, mission):
        """Exact action plan a mission will execute, for cost estimation.

        The returned structure is produced by the same helpers the executor
        uses, so a planner that prices it is pricing the real action sequence
        rather than a proxy.  ``clear`` missions carry both outcome branches
        because the post-clear scan depends on whether the clear succeeded.
        """
        if mission.kind == "clear":
            channel_id = mission.channel
            position = mission.target
            if "post_clear_channels" in mission.meta:
                seq = plan_stop_measures(None, mission.meta["post_clear_channels"],
                                         self.executor.current_channel)
                return {"kind": "clear", "channel": channel_id,
                        "success": seq, "failure": seq}
            suppress_failure = bool(
                mission.meta.get("suppress_failed_post_clear_scan"))
            failure_channels = ([] if suppress_failure else
                                self._scan_set_after_clear(
                                    position, channel_id, False))
            failure = plan_stop_measures(
                None, failure_channels, self.executor.current_channel)
            remeasure = self._failed_probe_remeasure_channel(mission, False)
            if remeasure is not None:
                # The executor measures the probe channel first, then plans
                # the UNKNOWN sweep from that new radio state.  Represent the
                # same sequence here so rolling scores do not underprice it.
                failure = [remeasure] + plan_stop_measures(
                    None, failure_channels, remeasure)
            return {
                "kind": "clear",
                "channel": channel_id,
                "success": plan_stop_measures(
                    None,
                    self._scan_set_after_clear(position, channel_id, True),
                    self.executor.current_channel),
                "failure": failure,
            }
        return {"kind": mission.kind, "measures": self._stop_sequence(mission)}

    def attach_scheduler(self, scheduler):
        """Wire one scheduler to this runner (traces + plan access)."""
        initialize = getattr(scheduler, "initialize_knowledge", None)
        if initialize is not None:
            initialize(self.ks)
        scheduler.decision_listener = self._record_decision
        scheduler.stop_planner = self.plan_stop
        self.scheduler = scheduler
        return scheduler

    def _execute_clear(self, mission):
        """Baseline clear path, with the post-clear scan taken from the plan."""
        cid = mission.channel
        outcome = self.executor.clear_at(mission.target[0],
                                         mission.target[1], cid)
        self._traj("clear", cid, outcome.clear_result)
        self._action("clear", cid, outcome.position,
                     outcome.vtime_before, outcome.vtime_after,
                     outcome.dt_move * C.MOVE_SPEED, outcome.dt_move,
                     0.0, outcome.dt_clear)
        if not outcome.accepted:
            self.scheduler.anomalies.append(
                "clear rejected (accepted=false) channel %d" % cid)
            return
        ch = self.ks[cid]
        clear_outcome = outcome
        is_fallback = bool(mission.meta.get("fallback"))
        if outcome.success:
            ch.mark_cleared(outcome.vtime_after)
            if is_fallback:
                self.scheduler.on_fallback_clear_result(
                    ch, True, outcome.vtime_after)
        else:
            if is_fallback:
                # A fallback lattice point that hits nothing is expected.
                self.scheduler.on_fallback_clear_result(
                    ch, False, outcome.vtime_after)
            else:
                # A deliberately selected probe is an information-gathering
                # action.  Its miss proves a 20 m exclusion; it is not a
                # protocol or localisation anomaly and must not consume the
                # ordinary clear-retry budget.
                if not mission.meta.get("risky_probe"):
                    self.scheduler.on_clear_failure(cid)
                callback = getattr(self.scheduler, "on_probe_failure", None)
                if callback is not None:
                    # The failed clear proves the source is not inside the
                    # 20 m disk around this point; the decision layer uses it.
                    callback(cid, mission.target)
        pos = self.executor.position
        suppress_failure = bool(
            mission.meta.get("suppress_failed_post_clear_scan"))
        remeasure = self._failed_probe_remeasure_channel(
            mission, bool(outcome.success))
        if remeasure is not None:
            # This direct measurement is a new observation at the point just
            # reached by the failed clear.  It is not part of the UNKNOWN
            # certificate sweep and therefore remains explicitly labelled.
            probe = self.executor.move_and_measure(pos[0], pos[1], remeasure)
            if probe.accepted:
                self._action("measure", remeasure, probe.position,
                             probe.vtime_before, probe.vtime_after,
                             probe.dt_move * C.MOVE_SPEED, probe.dt_move,
                             probe.dt_switch, probe.dt_measure,
                             reason_suffix="post_clear_remeasure")
                self._apply_measure(probe, primary=True, was_approach=False)
        seq = (list(mission.meta["post_clear_channels"])
               if "post_clear_channels" in mission.meta else
               ([] if (not outcome.success and suppress_failure) else
                self._scan_set_after_clear(pos, cid, bool(outcome.success))))
        seq = plan_stop_measures(None, seq, self.executor.current_channel)
        self._note_opportunistic(seq)
        measured_channels = set()
        if remeasure is not None:
            measured_channels.add(remeasure)
        for uid in seq:
            if (mission.meta.get("truncate_at_cardinality") and
                    self._cardinality_reached()):
                break
            if (self._cardinality_reached() and
                    self.ks[uid].status in (
                        ChannelStatus.UNKNOWN, ChannelStatus.CERTIFIED_ABSENT,
                        ChannelStatus.CLEARED)):
                continue
            outcome = self.executor.move_and_measure(pos[0], pos[1], uid)
            if outcome.accepted:
                measured_channels.add(uid)
                self._action("measure", uid, outcome.position,
                             outcome.vtime_before, outcome.vtime_after,
                             outcome.dt_move * C.MOVE_SPEED,
                             outcome.dt_move, outcome.dt_switch,
                             outcome.dt_measure,
                             reason_suffix="opportunistic")
                self._apply_measure(outcome, primary=False,
                                    was_approach=False)

        update_failure = getattr(ch, "update_failed_clear", None)
        if not clear_outcome.success and update_failure is not None:
            # Finish the prepriced stop sequence, then publish the exclusion
            # before the next decision. This keeps plan/execute costs identical.
            update_failure(clear_outcome.position, clear_outcome.vtime_after)
            if ch.status == ChannelStatus.READY:
                self._ready_snapshots[cid] = {
                    "region": list(ch.feasible_region), "center": ch.mec[0],
                    "radius": ch.mec[1], "basis": "mec"}
        certificate_callback = getattr(
            self.scheduler, "on_certificate_service_complete", None)
        if certificate_callback is not None:
            certificate_callback(mission, self.ks, measured_channels)
        clear_witness_callback = getattr(
            self.scheduler, "on_certificate_clear_witness_complete", None)
        if clear_witness_callback is not None:
            clear_witness_callback(mission, self.ks, measured_channels)

    def _execute(self, mission):
        """Run the baseline measure path with V2 cardinality short-circuit.

        The immutable baseline plans a scan's channel list before execution.
        Once the V2 cardinality certificate is reached, the remaining UNKNOWN
        channels in that already-planned list are terminally absent and must
        not incur extra measurements.  All action accounting and state
        updates remain the baseline path; only this proven-terminal suffix is
        skipped.
        """
        if mission.kind == "clear":
            return self._execute_clear(mission)
        seq = self._stop_sequence(mission)
        measured_channels = set()
        if mission.kind == "measure":
            self._note_opportunistic([c for c in seq if c != mission.channel])
        for cid in seq:
            if (mission.meta.get("truncate_at_cardinality")
                    and self._cardinality_reached()):
                break
            if self._cardinality_reached() and self.ks[cid].status in (
                    ChannelStatus.UNKNOWN, ChannelStatus.CERTIFIED_ABSENT,
                    ChannelStatus.CLEARED):
                continue
            outcome = self.executor.move_and_measure(
                mission.target[0], mission.target[1], cid)
            if not outcome.accepted:
                self.scheduler.anomalies.append(
                    "measure rejected (accepted=false) channel %d" % cid)
                continue
            measured_channels.add(cid)
            is_primary = (mission.kind == "measure"
                          and cid == mission.channel)
            self._action("measure", cid, outcome.position,
                         outcome.vtime_before, outcome.vtime_after,
                         outcome.dt_move * C.MOVE_SPEED,
                         outcome.dt_move, outcome.dt_switch,
                         outcome.dt_measure,
                         reason_suffix=None if (is_primary
                                                or mission.kind == "scan")
                         else "opportunistic")
            self._apply_measure(
                outcome, primary=is_primary,
                was_approach=(is_primary and mission.meta.get("kind")
                              == "approach"))
            if (mission.kind == "scan"
                    and mission.meta.get("truncate_at_cardinality")
                    and self._cardinality_reached()):
                break
        certificate_callback = getattr(
            self.scheduler, "on_certificate_service_complete", None)
        if certificate_callback is not None:
            certificate_callback(mission, self.ks, measured_channels)

    def _serialized_certificate_result(self, ch):
        if ch.absent_basis == "cardinality":
            confirmed = (len(self.ks.active) + len(self.ks.ready) +
                         len(self.ks.cleared))
            return {"ok": confirmed >= C.MAX_SOURCES,
                    "basis": "cardinality",
                    "confirmed_source_channels": confirmed,
                    "cap": C.MAX_SOURCES}
        return super()._serialized_certificate_result(ch)

    def _verify(self):
        """Run the baseline verifier plus explicit cardinality checks."""
        cardinality_channels = [
            ch for ch in self.ks.certified_absent
            if ch.absent_basis == "cardinality"
        ]
        # The baseline verifier is intentionally unchanged and does not know
        # the v2 cardinality basis.  Temporarily hide only these channels,
        # then restore their terminal state before returning.
        for ch in cardinality_channels:
            ch.status = ChannelStatus.UNKNOWN
        try:
            report = super()._verify()
        finally:
            for ch in cardinality_channels:
                ch.status = ChannelStatus.CERTIFIED_ABSENT
        confirmed = (len(self.ks.active) + len(self.ks.ready) +
                     len(self.ks.cleared))
        checks = report.setdefault("cardinality", [])
        for ch in cardinality_channels:
            ok = confirmed >= C.MAX_SOURCES
            checks.append({"channel": ch.channel_id, "ok": ok,
                           "confirmed_source_channels": confirmed,
                           "cap": C.MAX_SOURCES})
            report["all_ok"] &= ok
        report["all_ok"] = bool(report["all_ok"])
        return report


def run_case(mode, seed, n_sources, scenario, scheduler_cls, output_dir,
             scheduler_kwargs=None, http_synthetic=False):
    """Run exactly one local case and return the normal GameRunner report."""
    mode = str(mode).upper()
    if mode not in ("Q3", "Q4"):
        raise ValueError("mode must be Q3 or Q4")
    sim = SyntheticSimulator(mode, int(seed), n_sources=int(n_sources),
                             scenario=str(scenario))
    server = SimulatorHTTPServer(sim).start() if http_synthetic else None
    try:
        # The HTTP wrapper is intentionally optional; the default comparison
        # uses the same in-process backend for all three strategies.
        if server is None:
            backend = SimulatorBackend(sim, robot_id="V2")
        else:
            from api.client import ApiClient
            from api.session import Session
            backend = Session(ApiClient(server.url, timeout=5.0,
                                        robot_id="V2"))
        executor = ActionExecutor(backend)
        # Default to the single production configuration so a benchmark call
        # and the official entry cannot silently use different policies.
        cfg = dict(scheduler_kwargs or production.scheduler_kwargs(mode))
        # Keep the runner's KnowledgeState and verifier on the same explicit
        # Q4 certificate layout as the strategy.  Other scheduler-only keys
        # (for example model_path) are intentionally not forwarded.
        config_keys = {
            "tau", "nbv_mode", "nbv_rule", "opportunistic_reuse",
            "channel_scan_mode", "cert_select", "q4_naive",
            "q4_certificate_layout", "q4_joint_rank", "cert_route_mode",
            "q4_residual_sparsify", "q3_ml_ranker", "q3_ml_model_path",
            "active_scan_margin_m", "max_steps",
        }
        runner_cfg_dict = production.runner_kwargs(mode)
        runner_cfg_dict.update({k: v for k, v in cfg.items()
                                if k in config_keys})
        runner_cfg = MainlineConfig(**runner_cfg_dict)
        runner = V2GameRunner(mode, executor, str(output_dir), simulator=sim,
                              config=runner_cfg)
        # Runner-only controls must stay out of strategy constructors.  This
        # lets the mainline entry select a scan policy without changing the
        # scheduler API or silently dropping model-specific options.
        scheduler_cfg = {k: v for k, v in cfg.items()
                         if k not in {"channel_scan_mode",
                                      "active_scan_margin_m", "max_steps",
                                      "rolling_unknown_force_threshold",
                                      "q4_scan_order"}}
        runner.scheduler = scheduler_cls(mode, **scheduler_cfg)
        if "rolling_unknown_force_threshold" in cfg:
            runner.scheduler.rolling_unknown_force_threshold = int(
                cfg["rolling_unknown_force_threshold"])
        runner.attach_scheduler(runner.scheduler)
        # Provenance: the run directory carries the resolved scheduler and
        # runner configuration plus code/model hashes, so a stored run can be
        # reproduced and audited instead of trusted by folder name.
        production.dump_policy_snapshot(output_dir, mode, scheduler_cfg,
                                        runner_cfg_dict)
        report = runner.run()
        return report
    finally:
        if server is not None:
            server.shutdown()


def report_line(report):
    metrics = report["metrics"]
    return {
        "complete": bool(report.get("complete")),
        "failure": report.get("failure"),
        "cleared": metrics.get("cleared_count"),
        "certified_absent": metrics.get("certified_absent_count"),
        "sources": metrics.get("sources_total"),
        "T_total_s": metrics.get("T_total_virtual"),
        "T_per_source_s": metrics.get("t_per_source_s"),
        "source_count_for_average": metrics.get("source_count_for_average"),
        "average_time_per_source_s": metrics.get(
            "average_time_per_source_s"),
        "average_time_per_source_basis": metrics.get(
            "average_time_per_source_basis"),
        "measures": metrics.get("n_measures"),
        "switches": metrics.get("n_switches"),
        "clear_success": metrics.get("n_clear_success"),
        "clear_attempts": metrics.get("n_clear_attempts"),
        "verifier_all_ok": report.get("verifier_all_ok"),
        "wall_clock_s": metrics.get("wall_clock_s"),
    }
