"""Eight-stop Q3 ring that shares every stop across discovery and localisation.

The ring itself is a finite absence certificate: eight points at radius 940 m
cover the 1800 m search disk with guaranteed 1000 m reception disks.  No
simulator truth or source count is read.  After the ring (or the observable
16-channel cardinality stop), the existing observation-constrained macro
controller finishes localisation and clearing.
"""
from __future__ import annotations

import itertools
import math

from shapely.geometry import Point

from geometry import constants as C
from geometry.certificate import q3_certified
from geometry.fallback_cover import disk_lattice_cover, order_greedy
from policy import localization
from policy.scheduler import Mission
from state.channel_state import ChannelStatus
from constraint_search.macro import ConstraintMacroScheduler


class CompactRingScheduler(ConstraintMacroScheduler):
    """No-centre 8x940 route with ACTIVE measurements at the same stops."""

    def __init__(self, mode="Q3", *, compact_ring_radius=940.0,
                 compact_ring_points=8, compact_active_stop_radius=80.0,
                 compact_ring_active_max_directions=0,
                  compact_center_anchor=False,
                  compact_center_warmup_resultant_threshold=0.0,
                  compact_center_warmup_min_stops=3,
                  compact_coverage_optical_max_points=0,
                  compact_coverage_optical_max_entries=1,
                  compact_coverage_optical_max_entry_m=0.0,
                  compact_enroute_clear_radius=20.0,
                 compact_enroute_detour=350.0,
                 compact_probe_radius=0.0,
                 compact_optical_cover_points=10,
                 compact_truncate_active_at_cardinality=True,
                 compact_route_active=True,
                 compact_route_active_attempts=3,
                 compact_enroute_measure_detour=350.0,
                 compact_route_cluster_radius=0.0,
                 compact_route_cluster_max=0,
                 compact_route_cluster_min_saving=35.0,
                 compact_route_alternatives=False,
                 compact_route_quality_slack=5.0,
                 compact_route_point_passes=2,
                 compact_shape_cover=False,
                 compact_route_free_probe_radius=0.0,
                 compact_local_finish_steps=0,
                 compact_local_finish_budget=0.0,
                 compact_local_finish_max_radius=80.0,
                 compact_local_finish_min_shrink=0.05,
                 compact_local_finish_min_known=0,
                 compact_terminal_scan_radius=0.0,
                 compact_terminal_scan_worst=20.0,
                 compact_post_clear_worst=0.0,
                 compact_joint_ring_route=False,
                 compact_joint_ring_max_known=0,
                 compact_joint_ring_min_stops=0,
                 compact_joint_ring_active_radius=None,
                 compact_joint_ring_active_attempts=None,
                 compact_joint_ring_min_directions=1,
                  compact_joint_ring_service_worst=0.0,
                  compact_joint_ring_or_opt=False,
                  compact_joint_clear_witness=False,
                  compact_joint_clear_witness_useful_only=False,
                  compact_joint_clear_witness_max_unknown=0,
                  compact_joint_anchor_substitution=False,
                  compact_joint_anchor_substitution_max_unknown=0,
                  compact_service_certificate=False,
                 compact_service_certificate_radius=250.0,
                 compact_service_certificate_max_services=8,
                 compact_service_certificate_depth=2,
                 compact_service_certificate_max_anchor_drops=0,
                 compact_service_certificate_min_saving_m=35.0,
                 compact_service_certificate_active_candidates=1,
                 compact_service_certificate_rollout=False,
                 compact_tail_rollout_budget=0.0,
                 compact_tail_rollout_worlds=4,
                 compact_tail_rollout_candidates=10,
                 compact_tail_rollout_margin_s=15.0,
                 compact_tail_rollout_min_win_fraction=0.75,
                 compact_tail_rollout_objective="median",
                 compact_tail_rollout_step_limit=180,
                 compact_coverage_rollout_budget=0.0,
                 compact_coverage_rollout_worlds=3,
                 compact_coverage_rollout_candidates=5,
                 compact_coverage_rollout_points=3,
                 compact_coverage_rollout_service_scan=False,
                 compact_coverage_rollout_service_channels=0,
                 compact_coverage_rollout_post_service_scan=False,
                 compact_coverage_rollout_margin_s=10.0,
                 compact_coverage_rollout_min_win_fraction=0.75,
                 compact_coverage_branch_actions=2,
                 compact_coverage_branch_detour_m=350.0,
                 compact_coverage_rollout_step_limit=220,
                 compact_acif_translate_m=0.0,
                 compact_acif_translate_margin_m=0.0,
                 compact_acif_route_aware=False,
                 compact_acif_min_route_gain_m=1.0,
                 compact_acif_active_target_radius=0.0,
                 compact_adaptive_ring_points=0,
                 compact_adaptive_ring_radius=0.0,
                 compact_adaptive_ring_known_max=-1,
                 compact_adaptive_ring_rollout=False,
                 compact_fusion_budget=0.0,
                 compact_fusion_worlds=4,
                 compact_fusion_margin=10.0,
                 compact_fusion_views_only=False,
                 compact_clear_region_route=False, **kwargs):
        if mode != "Q3":
            raise ValueError("compact-ring currently supports Q3 only")
        # The post-ring READY branch uses an exact open path below.
        kwargs["ready_open_route"] = True
        # Compact-ring owns the one-shot probe lifecycle.  Leaving the
        # inherited 40 m probe enabled can retry the same channel and trip the
        # legacy two-failure manual block before exact localisation finishes.
        kwargs["q3_risky_clear_radius"] = 0.0
        kwargs["early_fallback_max_points"] = max(
            0, int(compact_optical_cover_points))
        kwargs["early_fallback_max_known"] = 0
        kwargs["early_fallback_suppress_failed_scan"] = True
        super().__init__(mode, **kwargs)
        self.compact_ring_radius = float(compact_ring_radius)
        self.compact_ring_outer_points = int(compact_ring_points)
        self.compact_center_anchor = bool(compact_center_anchor)
        # Optional centre-scan controller.  A centre anchor is already a
        # legal Q3 certificate station.  Once its *actual* direction replies
        # are known, a concentrated bearing fan signals that leaving the
        # coverage backbone immediately tends to make the joint route zigzag.
        # The gate only changes how many later anchors are protected from
        # service insertion; it never reads a source count or hidden position.
        self.compact_center_warmup_resultant_threshold = min(
            1.0, max(0.0, float(compact_center_warmup_resultant_threshold)))
        self.compact_center_warmup_min_stops = max(
            0, int(compact_center_warmup_min_stops))
        self._compact_center_warmup_done = False
        self._compact_center_warmup_min_stops = None
        # During the certificate tour, an ACTIVE feasible region can sometimes
        # already be covered by a few 20 m clear disks.  This is a bounded
        # source-completion branch, not a general fallback priority: a zero
        # point limit disables it and the finite entry count prevents coverage
        # starvation.
        self.compact_coverage_optical_max_points = max(
            0, int(compact_coverage_optical_max_points))
        self.compact_coverage_optical_max_entries = max(
            0, int(compact_coverage_optical_max_entries))
        self.compact_coverage_optical_max_entry_m = max(
            0.0, float(compact_coverage_optical_max_entry_m))
        self._compact_coverage_optical_entries = 0
        self.compact_active_stop_radius = float(compact_active_stop_radius)
        # UNKNOWN scans carry the absence certificate and are never capped.
        # This applies only to optional ACTIVE bearings at fixed ring stops;
        # later source-directed localisation may still request more views.
        self.compact_ring_active_max_directions = max(
            0, int(compact_ring_active_max_directions))
        self.compact_enroute_clear_radius = float(compact_enroute_clear_radius)
        self.compact_enroute_detour = float(compact_enroute_detour)
        self.compact_probe_radius = float(compact_probe_radius)
        self.compact_optical_cover_points = max(
            0, int(compact_optical_cover_points))
        self.compact_truncate_active_at_cardinality = bool(
            compact_truncate_active_at_cardinality)
        self.compact_route_active = bool(compact_route_active)
        self.compact_route_active_attempts = max(
            0, int(compact_route_active_attempts))
        self.compact_enroute_measure_detour = max(
            0.0, float(compact_enroute_measure_detour))
        self.compact_route_cluster_radius = max(
            0.0, float(compact_route_cluster_radius))
        self.compact_route_cluster_max = max(
            0, int(compact_route_cluster_max))
        self.compact_route_cluster_min_saving = max(
            0.0, float(compact_route_cluster_min_saving))
        self.compact_route_alternatives = bool(compact_route_alternatives)
        self.compact_route_quality_slack = max(
            0.0, float(compact_route_quality_slack))
        self.compact_route_point_passes = max(
            1, int(compact_route_point_passes))
        self.compact_shape_cover = bool(compact_shape_cover)
        self.compact_route_free_probe_radius = max(
            0.0, float(compact_route_free_probe_radius))
        self.compact_local_finish_steps = max(
            0, int(compact_local_finish_steps))
        self.compact_local_finish_budget = max(
            0.0, float(compact_local_finish_budget))
        self.compact_local_finish_max_radius = max(
            0.0, float(compact_local_finish_max_radius))
        self.compact_local_finish_min_shrink = max(
            0.0, float(compact_local_finish_min_shrink))
        self.compact_local_finish_min_known = max(
            0, int(compact_local_finish_min_known))
        self.compact_terminal_scan_radius = max(
            0.0, float(compact_terminal_scan_radius))
        self.compact_terminal_scan_worst = max(
            0.0, float(compact_terminal_scan_worst))
        self.compact_post_clear_worst = max(
            0.0, float(compact_post_clear_worst))
        self.compact_joint_ring_route = bool(compact_joint_ring_route)
        self.compact_joint_ring_max_known = max(
            0, int(compact_joint_ring_max_known))
        self.compact_joint_ring_min_stops = max(
            0, int(compact_joint_ring_min_stops))
        # Keep the radius that admits a source to the *route* separate from
        # compact_active_stop_radius, which controls whether a fixed coverage
        # station spends an ACTIVE measurement.  The old shared 80 m gate
        # made it impossible to test early global interleaving without also
        # removing useful ring observations.
        if compact_joint_ring_active_radius is None:
            compact_joint_ring_active_radius = compact_active_stop_radius
        self.compact_joint_ring_active_radius = max(
            0.0, float(compact_joint_ring_active_radius))
        if compact_joint_ring_active_attempts is None:
            compact_joint_ring_active_attempts = compact_route_active_attempts
        self.compact_joint_ring_active_attempts = max(
            0, int(compact_joint_ring_active_attempts))
        self.compact_joint_ring_min_directions = max(
            0, int(compact_joint_ring_min_directions))
        self.compact_joint_ring_service_worst = max(
            0.0, float(compact_joint_ring_service_worst))
        self.compact_joint_ring_or_opt = bool(compact_joint_ring_or_opt)
        self.compact_joint_clear_witness = bool(compact_joint_clear_witness)
        # A full UNKNOWN sweep at every READY clear was much more expensive
        # than the anchors it hoped to replace.  This optional gate makes the
        # clear-witness action admissible only when its *planned* position can
        # already delete an anchor after a real all-UNKNOWN scan.  It is still
        # only a planning check: the anchor is removed later, after every
        # required no_signal observation has actually returned.
        self.compact_joint_clear_witness_useful_only = bool(
            compact_joint_clear_witness_useful_only)
        self.compact_joint_clear_witness_max_unknown = max(
            0, int(compact_joint_clear_witness_max_unknown))
        # Stronger than deleting an anchor: retain eight certificate stations,
        # but let a READY clear location become one of them when the complete
        # visited + pending set still has an exact Q3 cover.  The clear then
        # performs that station's real UNKNOWN scan, fusing two paid visits.
        self.compact_joint_anchor_substitution = bool(
            compact_joint_anchor_substitution)
        self.compact_joint_anchor_substitution_max_unknown = max(
            0, int(compact_joint_anchor_substitution_max_unknown))
        # A source-service stop can replace one *future* certificate anchor
        # only after the runner really scanned every still-UNKNOWN channel at
        # that stop.  This is deliberately separate from joint_ring_route:
        # the latter orders both node sets, whereas this option removes an
        # anchor only when the replacement set still passes q3_certified().
        self.compact_service_certificate = bool(compact_service_certificate)
        self.compact_service_certificate_radius = max(
            0.0, float(compact_service_certificate_radius))
        self.compact_service_certificate_max_services = max(
            0, int(compact_service_certificate_max_services))
        self.compact_service_certificate_depth = min(
            3, max(1, int(compact_service_certificate_depth)))
        # ``0`` preserves the original one-for-one template search: a
        # depth-k service template may replace exactly k anchors.  A positive
        # cap exposes the genuinely useful case found in the offline audit:
        # several real source-service witnesses can jointly make more than
        # the same number of fixed certificate anchors redundant.
        self.compact_service_certificate_max_anchor_drops = max(
            0, int(compact_service_certificate_max_anchor_drops))
        self.compact_service_certificate_min_saving_m = max(
            0.0, float(compact_service_certificate_min_saving_m))
        # With one candidate this reproduces the historical template: each
        # ACTIVE source contributes only its normal next measurement point.
        # Larger values also expose coverage-friendly, information-safe
        # measurement points, so a service stop can genuinely replace an
        # anchor instead of merely hoping its local optimum happens to do so.
        self.compact_service_certificate_active_candidates = max(
            1, int(compact_service_certificate_active_candidates))
        self.compact_service_certificate_rollout = bool(
            compact_service_certificate_rollout)
        # Bounded posterior root rollout over the all-known tail. A zero
        # budget is intentionally inert and leaves the compact route unchanged.
        self.compact_tail_rollout_budget = max(
            0.0, float(compact_tail_rollout_budget))
        self.compact_tail_rollout_worlds = max(
            1, int(compact_tail_rollout_worlds))
        self.compact_tail_rollout_candidates = max(
            1, int(compact_tail_rollout_candidates))
        self.compact_tail_rollout_margin_s = max(
            0.0, float(compact_tail_rollout_margin_s))
        self.compact_tail_rollout_min_win_fraction = min(
            1.0, max(0.0, float(compact_tail_rollout_min_win_fraction)))
        if compact_tail_rollout_objective not in ("mean", "median"):
            raise ValueError("compact tail rollout objective must be mean or median")
        self.compact_tail_rollout_objective = compact_tail_rollout_objective
        self.compact_tail_rollout_step_limit = max(
            1, int(compact_tail_rollout_step_limit))
        # A coverage excursion is a finite source-service branch which must
        # reconnect to the exact next certificate anchor.  It is deliberately
        # distinct from joint_ring_route: the latter reorders a static pool;
        # this state machine caps repeated source chasing after real feedback.
        self.compact_coverage_rollout_budget = max(
            0.0, float(compact_coverage_rollout_budget))
        self.compact_coverage_rollout_worlds = max(
            1, int(compact_coverage_rollout_worlds))
        self.compact_coverage_rollout_candidates = max(
            1, int(compact_coverage_rollout_candidates))
        self.compact_coverage_rollout_points = max(
            1, int(compact_coverage_rollout_points))
        self.compact_coverage_rollout_service_scan = bool(
            compact_coverage_rollout_service_scan)
        # Zero preserves the historical all-UNKNOWN service scan. A positive
        # value also lets the rollout compare a small proximity-ranked subset
        # at the already-paid source-service stop.
        self.compact_coverage_rollout_service_channels = max(
            0, int(compact_coverage_rollout_service_channels))
        # Separate from the anchor-reconnect service branch: this more
        # aggressive zero-movement scan was not stable in initial tests.
        self.compact_coverage_rollout_post_service_scan = bool(
            compact_coverage_rollout_post_service_scan)
        self.compact_coverage_rollout_margin_s = max(
            0.0, float(compact_coverage_rollout_margin_s))
        self.compact_coverage_rollout_min_win_fraction = min(
            1.0, max(0.0, float(compact_coverage_rollout_min_win_fraction)))
        self.compact_coverage_branch_actions = max(
            1, int(compact_coverage_branch_actions))
        self.compact_coverage_branch_detour_m = max(
            0.0, float(compact_coverage_branch_detour_m))
        self.compact_coverage_rollout_step_limit = max(
            1, int(compact_coverage_rollout_step_limit))
        # ACIF (Adaptive Certificate--Information Field): while an absence
        # certificate is still needed, pull *unvisited* anchors toward an
        # observed source-service target.  A candidate move is committed only
        # if the actual visited witnesses plus the new pending anchors remain
        # an exact Q3 certificate.  The zero default is intentionally inert.
        self.compact_acif_translate_m = max(
            0.0, float(compact_acif_translate_m))
        self.compact_acif_translate_margin_m = max(
            0.0, float(compact_acif_translate_margin_m))
        self.compact_acif_route_aware = bool(compact_acif_route_aware)
        self.compact_acif_min_route_gain_m = max(
            0.0, float(compact_acif_min_route_gain_m))
        # Zero retains the conservative historical target set.  A positive
        # value may admit a moderately localised ACTIVE channel's *actual
        # next bearing point* as an ACIF route target; it is experimental and
        # still has to pass the exact coverage and route-gain gates.
        self.compact_acif_active_target_radius = max(
            0.0, float(compact_acif_active_target_radius))
        # A certificate starts as the compact eight-point ring.  After its
        # first *real* all-channel observation, a low observed discovery count
        # can justify a denser remaining ring.  This is intentionally an
        # observation gate, never a hidden ``n_sources`` branch: an UNKNOWN
        # channel is allowed to rely on the first station only when it really
        # returned ``no_signal`` there.
        self.compact_adaptive_ring_points = max(
            0, int(compact_adaptive_ring_points))
        self.compact_adaptive_ring_radius = max(
            0.0, float(compact_adaptive_ring_radius))
        self.compact_adaptive_ring_known_max = int(
            compact_adaptive_ring_known_max)
        self.compact_adaptive_ring_rollout = bool(
            compact_adaptive_ring_rollout)
        if self.compact_ring_outer_points < 3:
            raise ValueError("compact ring needs at least three points")
        outer_points = [
            (self.compact_ring_radius * math.cos(2.0 * math.pi * k /
                                                self.compact_ring_outer_points),
             self.compact_ring_radius * math.sin(2.0 * math.pi * k /
                                                self.compact_ring_outer_points))
            for k in range(self.compact_ring_outer_points)
        ]
        # A structural alternative to the no-centre 8x940 construction:
        # origin plus six 1150 m outer points is also an exact Q3 certificate.
        # It is optional because its pure certificate path is longer.
        self._coverage_points = ([(0.0, 0.0)] if self.compact_center_anchor
                                 else []) + outer_points
        self.compact_ring_points = len(self._coverage_points)
        verdict = q3_certified(self._coverage_points)
        if not verdict["certified"]:
            raise ValueError("compact ring is not a valid Q3 certificate: " +
                             str(verdict.get("reason")))
        self._coverage_index = 0
        self._coverage_remaining = set(range(self.compact_ring_points))
        # A generic point list is sufficient to prove that a geometric set is
        # covered, but is insufficient to prove that *each still-UNKNOWN
        # channel* was actually tested there.  Keep service witnesses by
        # channel as well.  The authoritative observation remains the channel
        # history; this map makes the replacement decision and its audit trail
        # explicit rather than inferring a common scan after the fact.
        self._certificate_service_channel_witnesses = {
            cid: [] for cid in range(1, C.NUM_CHANNELS + 1)}
        self._certificate_service_witnesses = []
        self._certificate_service_template = None
        self._certificate_service_followup = None
        self._compact_attempted = set()
        self._compact_inflight = None
        self._compact_failed_measure = None
        # A source-service mission has just paid the travel to this point.
        # At the following decision, a bounded rollout may compare an
        # UNKNOWN-only scan here against leaving immediately.  Keep the
        # arrived-at point separate from a newly issued mission's target.
        self._compact_service_pending = None
        self._compact_service_current = None
        self._compact_route_attempts = {}
        self._compact_enroute_measured = set()
        self._compact_local_finish = None
        self._compact_coverage_branch = None
        self._compact_acif_signature = None
        self._compact_initial_ring_points = self.compact_ring_points
        self._compact_adaptive_ring_done = False
        self.compact_fusion_budget = max(0.0, float(compact_fusion_budget))
        self.compact_fusion_worlds = max(1, int(compact_fusion_worlds))
        self.compact_fusion_margin = max(0.0, float(compact_fusion_margin))
        self.compact_fusion_views_only = bool(compact_fusion_views_only)
        self.compact_clear_region_route = bool(compact_clear_region_route)
        self.fusion_stats = dict(searches=0, overrides=0, branches=0,
                                incomplete_candidates=0, world_failures=0,
                                wall_s=0.0)
        self.fusion_log = []
        self.tail_rollout_stats = dict(searches=0, overrides=0, branches=0,
                                       incomplete_candidates=0,
                                       world_failures=0, wall_s=0.0)
        self.tail_rollout_log = []
        self.coverage_rollout_stats = dict(
            searches=0, overrides=0, branches=0, incomplete_candidates=0,
            world_failures=0, wall_s=0.0, branch_actions=0,
            forced_returns=0)
        self.coverage_rollout_log = []
        self.compact_stats = dict(ring_stops=0, joint_active_planned=0,
                                  early_stop=False, enroute_probes=0,
                                  post_ring_probes=0,
                                  failed_probe_measures=0,
                                  exact_ready_routes=0,
                                  active_route_measures=0,
                                  enroute_active_measures=0,
                                  clustered_active_measures=0,
                                  clustered_route_saving_m=0.0,
                                  alternative_route_uses=0,
                                   alternative_route_saving_m=0.0,
                                  shape_cover_uses=0,
                                  shape_cover_points_saved=0,
                                  route_free_probes=0,
                                  local_finish_measures=0,
                                  local_finish_clears=0,
                                  local_finish_releases=0,
                                  terminal_ring_measures=0,
                                  value_post_clear_measures=0,
                                  joint_ring_clears=0,
                                  joint_ring_active_measures=0,
                                  joint_ring_large_active_measures=0,
                                  joint_ring_service_measures=0,
                                   joint_clear_witness_scans=0,
                                   joint_clear_anchor_drops=0,
                                   joint_clear_witness_rejected=0,
                                   joint_clear_witness_admitted=0,
                                   joint_clear_witness_skipped=0,
                                   joint_anchor_substitutions=0,
                                   joint_anchor_substitution_measures=0,
                                   joint_anchor_substitution_skipped=0,
                                   center_warmup_adaptations=0,
                                   center_warmup_resultant=0.0,
                                   center_warmup_min_stops=0,
                                   coverage_optical_entries=0,
                                   coverage_optical_points=0,
                                   coverage_optical_rejected=0,
                                  service_certificate_candidates=0,
                                  service_certificate_templates=0,
                                  service_certificate_replacements=0,
                                  service_certificate_route_saving_m=0.0,
                                  service_certificate_rejected=0,
                                  service_certificate_actual_witnesses=0,
                                  service_certificate_incremental_drops=0,
                                  service_certificate_channel_proof_rejected=0,
                                  acif_rounds=0,
                                  acif_anchors_shifted=0,
                                  acif_total_shift_m=0.0,
                                  acif_route_gain_m=0.0,
                                  acif_rejected=0,
                                  adaptive_ring_uses=0,
                                  adaptive_ring_known=0,
                                  adaptive_ring_rejected=0,
                                  adaptive_ring_rollout_candidates=0,
                                  adaptive_ring_rollout_uses=0,
                                  clear_region_routes=0,
                                  clear_region_projected_saving_m=0.0,
                                  ring_direction="ccw")

    @staticmethod
    def _known_count(ks):
        return len(ks.active) + len(ks.ready) + len(ks.cleared)

    def _ring_finished(self, ks):
        exhausted = (not self._coverage_remaining
                     if (self.compact_joint_ring_route or
                         self.compact_service_certificate) else
                     self._coverage_index >= len(self._coverage_points))
        return (exhausted
                or not ks.unknown or self._known_count(ks) >= C.MAX_SOURCES)

    def _acif_targets(self, ks, position):
        """Observable service targets which a certificate stop may also serve."""
        targets = []
        for ch in ks.by_status(ChannelStatus.READY):
            targets.append(self._clear_target(ch, position))
        active_limit = (self.compact_acif_active_target_radius
                        if self.compact_acif_active_target_radius > 0.0
                        else self.compact_active_stop_radius)
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            # A broad first-bearing MEC is not a service target: chasing it
            # bends the certificate route toward a largely arbitrary centre
            # and then changes the next observation geometry.  Use precisely
            # the same radius gate as a compact ACTIVE service stop.
            if (ch.mec is not None and ch.mec_radius <= active_limit
                    and not self.fallback.in_fallback(ch.channel_id)):
                if self.compact_acif_active_target_radius > 0.0:
                    point = self._active_route_point(ch, position)
                    if point is not None:
                        targets.append(tuple(point))
                else:
                    targets.append(tuple(ch.mec[0]))
        return targets

    @staticmethod
    def _certificate_boundary_margin(points, samples=720):
        """Worst boundary distance; used only to demand extra ACIF slack."""
        if not points:
            return float("inf")
        worst = 0.0
        for index in range(samples):
            angle = 2.0 * math.pi * index / samples
            boundary = (C.OMEGA_RADIUS * math.cos(angle),
                        C.OMEGA_RADIUS * math.sin(angle))
            worst = max(worst, min(math.dist(boundary, point)
                                   for point in points))
        return worst

    def _acif_route_proxy(self, position, pending_indices, pending, targets):
        """Projected remaining movement for the route the scheduler executes.

        The normal compact route visits certificate anchors in index order and
        only then services currently actionable sources.  Joint-ring mode may
        interleave both types, so its proxy uses the same open-route optimiser.
        The value is deliberately distance-only: measurements at an anchor do
        not change when that anchor is translated.
        """
        anchors = [(-(index + 1), point, "anchor")
                   for index, point in zip(pending_indices, pending)]
        unique_targets = []
        for target in targets:
            if not any(math.dist(target, prior) < 1.0
                       for prior in unique_targets):
                unique_targets.append(target)
        services = [(index + 1, point, "service")
                    for index, point in enumerate(unique_targets)]
        def greedy_length(points, start):
            # This function sits inside the ACIF candidate loop.  Calling the
            # exact O(2^n n^2) path solver here makes one decision take minutes
            # once many sources are known.  Nearest-neighbour is deterministic,
            # evaluates the complete open path, and is only an acceptance proxy;
            # the executed route still uses the exact/hybrid optimiser.
            remaining = list(points)
            total = 0.0
            current = start
            while remaining:
                chosen = min(remaining,
                             key=lambda point: (math.dist(current, point),
                                                point[0], point[1]))
                total += math.dist(current, chosen)
                current = chosen
                remaining.remove(chosen)
            return total

        if self.compact_joint_ring_route:
            return greedy_length([item[1] for item in anchors + services],
                                 position)

        total = 0.0
        previous = position
        for point in pending:
            total += math.dist(previous, point)
            previous = point
        if services:
            total += greedy_length([item[1] for item in services], previous)
        return total

    def _adapt_certificate_field(self, ks, position):
        """Move pending anchors toward work, retaining an exact cover proof.

        The certificate state is channel-specific in the executor.  For every
        channel which remains UNKNOWN, however, every visited compact-ring
        anchor produced a ``no_signal`` observation; consequently their common
        visited-anchor set plus the remaining anchors is a sufficient absence
        certificate.  We never use a heuristic coverage score to accept a
        move: ``q3_certified`` decides each proposed point set.
        """
        if self.compact_acif_translate_m <= 0.0 or not self._coverage_remaining:
            return
        pending_indices = tuple(sorted(self._coverage_remaining))
        targets = self._acif_targets(ks, position)
        target_signature = tuple(sorted((round(point[0], 1), round(point[1], 1))
                                        for point in targets))
        signature = (pending_indices, target_signature)
        if signature == self._compact_acif_signature:
            return
        self._compact_acif_signature = signature
        if not targets:
            return

        visited = ([self._coverage_points[index]
                    for index in range(self.compact_ring_points)
                    if index not in self._coverage_remaining]
                   + list(self._certificate_service_witnesses))
        pending = [self._coverage_points[index] for index in pending_indices]
        shifts = []
        for offset, point in enumerate(pending):
            chosen = point
            shift = 0.0
            route_gain = 0.0
            base_route = None
            if self.compact_acif_route_aware:
                base_route = self._acif_route_proxy(
                    position, pending_indices, pending, targets)
            for target in sorted(targets, key=lambda value:
                                  (math.dist(point, value), value)):
                distance = math.dist(point, target)
                if distance <= 1.0:
                    continue
                length_limit = min(distance, self.compact_acif_translate_m)
                ux = (target[0] - point[0]) / distance
                uy = (target[1] - point[1]) / distance

                def certified_at(length):
                    trial = list(pending)
                    trial[offset] = (point[0] + ux * length,
                                     point[1] + uy * length)
                    result = q3_certified(visited + trial)
                    if not result["certified"]:
                        return False
                    if self.compact_acif_translate_margin_m > 0.0:
                        return self._certificate_boundary_margin(visited + trial) <= (
                            C.R_EFF_MIN - self.compact_acif_translate_margin_m)
                    return True

                if certified_at(length_limit):
                    certified_limit = length_limit
                else:
                    low, high = 0.0, length_limit
                    for _ in range(14):
                        middle = 0.5 * (low + high)
                        if certified_at(middle):
                            low = middle
                        else:
                            high = middle
                    certified_limit = low
                if certified_limit < 1.0:
                    continue
                if not self.compact_acif_route_aware:
                    shift = certified_limit
                    chosen = (point[0] + ux * shift,
                              point[1] + uy * shift)
                    break

                # The largest certificate-safe displacement need not be the
                # best route displacement.  Evaluate several interior points
                # and retain the one which most shortens the complete projected
                # route.  Every sampled point is certified independently.
                for fraction in (0.25, 0.5, 0.75, 1.0):
                    trial_shift = certified_limit * fraction
                    if trial_shift < 1.0 or not certified_at(trial_shift):
                        continue
                    trial_point = (point[0] + ux * trial_shift,
                                   point[1] + uy * trial_shift)
                    trial_pending = list(pending)
                    trial_pending[offset] = trial_point
                    trial_route = self._acif_route_proxy(
                        position, pending_indices, trial_pending, targets)
                    gain = base_route - trial_route
                    candidate = (gain, trial_shift, trial_point)
                    incumbent = (route_gain, shift, chosen)
                    if candidate[:2] > incumbent[:2]:
                        route_gain, shift, chosen = candidate
            if (self.compact_acif_route_aware
                    and route_gain + 1e-9 <
                    self.compact_acif_min_route_gain_m):
                shift = 0.0
                chosen = point
                route_gain = 0.0
            if shift < 1.0:
                self.compact_stats["acif_rejected"] += 1
                continue
            pending[offset] = chosen
            self._coverage_points[pending_indices[offset]] = chosen
            shifts.append(shift)
            self.compact_stats["acif_route_gain_m"] += route_gain

        self.compact_stats["acif_rounds"] += 1
        self.compact_stats["acif_anchors_shifted"] += len(shifts)
        self.compact_stats["acif_total_shift_m"] += sum(shifts)

    def _adaptive_ring_candidate(self, ks):
        """Return a legal denser suffix after the first observed station.

        The helper is pure with respect to policy state.  Both the simple
        low-discovery gate and a posterior rollout call it, so they use the
        same strict witness precondition and cannot disagree about whether a
        layout is legal.
        """
        target_count = self.compact_adaptive_ring_points
        if (target_count <= self._compact_initial_ring_points or
                self.compact_adaptive_ring_radius <= 0.0 or
                self.compact_center_anchor or
                self.compact_ring_points != self._compact_initial_ring_points):
            return None
        full_initial = set(range(self._compact_initial_ring_points))
        expected_remaining = set(range(1, self._compact_initial_ring_points))
        if self._coverage_remaining == full_initial:
            return None  # first scan is still only being planned
        if self._coverage_remaining != expected_remaining:
            return None
        first = tuple(self._coverage_points[0])
        for ch in ks.by_status(ChannelStatus.UNKNOWN):
            if not any(obs.get("result") == "no_signal" and
                       math.dist(tuple(obs["position"]), first) < 2.0
                       for obs in ch.observations):
                return None
        radius = self.compact_adaptive_ring_radius
        future = [
            (radius * math.cos(2.0 * math.pi * index / target_count),
             radius * math.sin(2.0 * math.pi * index / target_count))
            for index in range(1, target_count)
        ]
        points = [first] + future
        if not q3_certified(points)["certified"]:
            return None
        return points, self._known_count(ks)

    def _commit_adaptive_ring(self, points, known, rollout=False):
        """Commit a candidate returned by :meth:`_adaptive_ring_candidate`."""
        self._coverage_points = [tuple(point) for point in points]
        self.compact_ring_points = len(self._coverage_points)
        self.compact_ring_outer_points = self.compact_ring_points
        self._coverage_remaining = set(range(1, self.compact_ring_points))
        self._coverage_index = 1
        self._compact_adaptive_ring_done = True
        self.compact_stats["adaptive_ring_uses"] += 1
        self.compact_stats["adaptive_ring_known"] = int(known)
        if rollout:
            self.compact_stats["adaptive_ring_rollout_uses"] += 1

    def _adapt_ring_density(self, ks):
        """Apply the inexpensive, observation-only density gate if enabled."""
        if self._compact_adaptive_ring_done:
            return
        # Rollout mode leaves the immediate density-versus-service decision to
        # coverage_rollout.py.  It must not silently turn back into a fixed
        # count threshold if the rollout budget is exhausted.
        if self.compact_adaptive_ring_rollout:
            return
        if self.compact_adaptive_ring_known_max < 0:
            self._compact_adaptive_ring_done = True
            return
        candidate = self._adaptive_ring_candidate(ks)
        if candidate is None:
            full_initial = set(range(self._compact_initial_ring_points))
            if self._coverage_remaining != full_initial:
                self._compact_adaptive_ring_done = True
                self.compact_stats["adaptive_ring_rejected"] += 1
            return
        points, known = candidate
        self._compact_adaptive_ring_done = True
        if known > self.compact_adaptive_ring_known_max:
            return
        self._commit_adaptive_ring(points, known)

    def _observed_q3_risky_radius(self, ks):
        # q3_observation_adaptive normally replaces a configured zero with
        # 40/75 m. Compact-ring must suppress that implicit legacy retry too.
        return 0.0

    @staticmethod
    def _target(ch, position, policy):
        if ch.status == ChannelStatus.READY:
            return policy._clear_target(ch, position)
        return ch.mec[0]

    def _probe(self, ks, position, radius, kind, next_ring=None,
               max_detour=None):
        candidates = []
        for ch in ks.active + ks.ready:
            cid = ch.channel_id
            if cid in self._compact_attempted or cid in self.blocked:
                continue
            if ch.mec_radius > radius:
                continue
            point = self._target(ch, position, self)
            distance = math.dist(position, point)
            detour = distance
            if next_ring is not None:
                detour = (distance + math.dist(point, next_ring)
                          - math.dist(position, next_ring))
                if max_detour is not None and detour > max_detour + 1e-9:
                    continue
            candidates.append((detour, distance, cid, point))
        if not candidates:
            return None
        detour, distance, cid, point = min(candidates)
        self._compact_attempted.add(cid)
        self._compact_inflight = (cid, point)
        if next_ring is None:
            self.compact_stats["post_ring_probes"] += 1
        else:
            self.compact_stats["enroute_probes"] += 1
        return Mission("clear", point, channel=cid,
                       meta={"kind": kind, "risky_probe": True,
                             "compact_ring": True,
                             "detour_m": detour,
                             # A failed probe is followed by one explicit
                             # same-point measurement, so do not duplicate it.
                             "post_clear_channels": []})

    def _certificate_witness_points(self):
        """Actual or scheduled certificate stops already committed by evidence.

        Anchor points enter this set when their scan mission is issued, which
        is the historical compact-ring lifecycle.  A service point is added
        later by ``on_certificate_service_complete`` only after the runner has
        actually measured every channel that is still UNKNOWN there.
        """
        anchors = [self._coverage_points[index]
                   for index in range(self.compact_ring_points)
                   if index not in self._coverage_remaining]
        return anchors + list(self._certificate_service_witnesses)

    @staticmethod
    def _unique_points(points, tolerance=1.0):
        """Return deterministic point representatives with no near duplicates."""
        unique = []
        for point in points:
            point = (float(point[0]), float(point[1]))
            if not any(math.dist(point, prior) < tolerance for prior in unique):
                unique.append(point)
        return unique

    def _channel_no_signal_witnesses(self, ch):
        """All *observed* Q3 absence witnesses for one channel.

        The compact route visits a shared geometry, but the certificate is not
        a property of geometry alone: an anchor proves absence for channel c
        only if c was actually measured there and returned ``no_signal``.
        Reading the immutable observation history keeps this true after a
        service stop, a reordered anchor, or an interrupted scan.
        """
        observed = [tuple(obs["position"]) for obs in ch.observations
                    if obs.get("result") == "no_signal"]
        recorded = self._certificate_service_channel_witnesses.get(
            ch.channel_id, ())
        return self._unique_points(observed + list(recorded))

    def _record_service_witness(self, ch, point):
        """Record one verified service witness, returning whether it is new."""
        if not any(obs.get("result") == "no_signal" and
                   math.dist(obs["position"], point) < 2.0
                   for obs in ch.observations):
            return False
        witnesses = self._certificate_service_channel_witnesses.setdefault(
            ch.channel_id, [])
        if any(math.dist(point, prior) < 1.0 for prior in witnesses):
            return False
        witnesses.append(tuple(point))
        self.compact_stats["service_certificate_actual_witnesses"] += 1
        return True

    def _service_certificate_plan_valid(self, ks, remaining_indices,
                                        assumed_service_points=()):
        """Check the per-channel proof for a remaining *planned* route.

        ``assumed_service_points`` is allowed only while evaluating a future
        action.  It never changes evidence state.  The completion path calls
        this method without it, so an unexecuted service scan can never delete
        an anchor or certify a channel.
        """
        future = [self._coverage_points[index] for index in remaining_indices]
        for ch in ks.by_status(ChannelStatus.UNKNOWN):
            proof = (self._channel_no_signal_witnesses(ch) + future +
                     list(assumed_service_points))
            if not q3_certified(self._unique_points(proof))["certified"]:
                return False
        return True

    def _trim_service_anchors_from_actual_witnesses(self, ks):
        """Remove anchors only when every still-unknown channel retains a plan.

        This is intentionally recomputed after every completed service scan.
        It measures real anchor removal rather than a route estimate.  Future
        anchors may appear in the feasibility plan, but are not added to any
        channel's evidence until their scans return ``no_signal``.
        """
        removed = []
        for index in sorted(self._coverage_remaining):
            retained = set(self._coverage_remaining)
            retained.remove(index)
            if self._service_certificate_plan_valid(ks, retained):
                self._coverage_remaining.remove(index)
                removed.append(index)
        if removed:
            self._coverage_index = self.compact_ring_points - len(
                self._coverage_remaining)
            self.compact_stats["service_certificate_replacements"] += len(removed)
            self.compact_stats["service_certificate_incremental_drops"] += len(removed)
        return removed

    def _trim_anchors_from_witnesses(self):
        """Delete only anchors made redundant by real UNKNOWN witnesses."""
        removed = []
        # Recheck after every deletion: cover redundancy is not additive.
        for index in sorted(self._coverage_remaining):
            future = [self._coverage_points[other]
                      for other in self._coverage_remaining if other != index]
            if q3_certified(self._certificate_witness_points() + future)["certified"]:
                self._coverage_remaining.remove(index)
                removed.append(index)
        if removed:
            self._coverage_index = self.compact_ring_points - len(
                self._coverage_remaining)
            self.compact_stats["joint_clear_anchor_drops"] += len(removed)
        return removed

    def on_certificate_clear_witness_complete(self, mission, ks,
                                              measured_channels):
        """A clear stop substitutes anchors only after its scan is real."""
        if not mission.meta.get("certificate_clear_witness"):
            return
        expected = mission.meta.get("certificate_unknown_channels", ())
        for cid in expected:
            channel = ks[cid]
            if channel.status != ChannelStatus.UNKNOWN:
                continue
            if (cid in measured_channels or any(
                    obs["result"] == "no_signal" and
                    math.dist(obs["position"], mission.target) < 2.0
                    for obs in channel.observations)):
                continue
            self.compact_stats["joint_clear_witness_rejected"] += 1
            return
        if not any(math.dist(mission.target, point) < 1.0
                   for point in self._certificate_service_witnesses):
            self._certificate_service_witnesses.append(mission.target)
        self.compact_stats["joint_clear_witness_scans"] += 1
        self._trim_anchors_from_witnesses()

    def _certificate_service_candidates(self, ks, position):
        """Observable service stops that may also carry UNKNOWN witnesses."""
        if (self.compact_service_certificate_radius <= 0.0 or
                self.compact_service_certificate_max_services <= 0):
            return []
        ready_candidates = []
        active_candidates = []
        anchors = [self._coverage_points[index]
                   for index in self._coverage_remaining]
        for ch in ks.by_status(ChannelStatus.READY):
            if ch.channel_id in self.blocked:
                continue
            point = self._clear_target(ch, position)
            ready_candidates.append((math.dist(position, point), ch.channel_id,
                                     point, "clear"))
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            if (self.fallback.in_fallback(ch.channel_id) or ch.mec is None or
                    ch.mec_radius > self.compact_service_certificate_radius):
                continue
            point = self._active_route_point(ch, position)
            if point is None:
                continue
            points = [point]
            if self.compact_service_certificate_active_candidates > 1:
                try:
                    points.extend(localization.candidate_points(
                        ch, position,
                        failed_points=self.failed_points.get(ch.channel_id),
                        opportunistic_reuse=True))
                except Exception:
                    pass
            unique_points = []
            for candidate in points:
                candidate = tuple(candidate)
                if any(math.dist(candidate, prior) < 1.0
                       for prior in unique_points):
                    continue
                unique_points.append(candidate)
            if self.compact_service_certificate_active_candidates > 1:
                # A point near a pending anchor has a chance to alter the
                # cover; a purely local candidate is retained as a tie-break
                # through its route distance.  Full template enumeration,
                # not this ordering, still decides feasibility and cost.
                unique_points.sort(key=lambda candidate: (
                    min((math.dist(candidate, anchor) for anchor in anchors),
                        default=math.inf),
                    math.dist(position, candidate), candidate))
            for variant, candidate in enumerate(
                    unique_points[:self.compact_service_certificate_active_candidates]):
                coverage_distance = min(
                    (math.dist(candidate, anchor) for anchor in anchors),
                    default=math.inf)
                active_candidates.append((math.dist(position, candidate),
                                          ch.channel_id, candidate, "measure",
                                          coverage_distance, variant))
        # One source can have both a current target and an old identical point
        # in its history.  Retaining just the nearest deterministic candidate
        # bounds the certificate checks without hiding a different channel.
        unique = []
        if self.compact_service_certificate_active_candidates == 1:
            ranked = (sorted(ready_candidates, key=lambda item:
                             (item[0], item[1], item[2][0], item[2][1])) +
                      sorted(active_candidates, key=lambda item:
                             (item[0], item[1], item[2][0], item[2][1])))
        else:
            ranked = sorted(
                ready_candidates + active_candidates,
                key=lambda item: (item[4] if len(item) > 4 else 0.0,
                                  item[0], item[1], item[2][0], item[2][1]))
        for row in ranked:
            if any(math.dist(row[2], prior[2]) < 1.0 and
                   row[1] == prior[1] for prior in unique):
                continue
            unique.append(row)
            if len(unique) >= self.compact_service_certificate_max_services:
                break
        return unique

    def _certificate_template_order(self, position):
        """Order the still-pending nodes of a committed certificate template."""
        template = self._certificate_service_template
        if template is None:
            return []
        items = [(-(index + 1), self._coverage_points[index], "anchor")
                 for index in sorted(self._coverage_remaining)
                 if index not in template["remove_anchors"]]
        for node in template["services"]:
            if node["key"] in template["remaining_services"]:
                items.append((node["key"], node["point"], "service"))
        return self._exact_open_order(items, position)

    def _commit_certificate_template_if_ready(self, ks):
        template = self._certificate_service_template
        if template is None or template["remaining_services"]:
            return
        retained = (set(self._coverage_remaining) -
                    set(template["remove_anchors"]))
        # Every service point in this template has completed at this point,
        # so no hypothetical point is supplied here.  This is the final
        # per-channel contract, stronger than the historical global geometry
        # check and robust to a scan that discovered one channel en route.
        if not self._service_certificate_plan_valid(ks, retained):
            # Keep all original anchors if a rejected action or a future
            # executor change has broken the template's precondition.
            self.compact_stats["service_certificate_rejected"] += 1
            self.compact_stats["service_certificate_channel_proof_rejected"] += 1
            self._certificate_service_template = None
            return
        removed = template["remove_anchors"] & self._coverage_remaining
        self._coverage_remaining.difference_update(removed)
        self._coverage_index = self.compact_ring_points - len(
            self._coverage_remaining)
        self.compact_stats["service_certificate_replacements"] += len(removed)
        self._certificate_service_template = None
        # A completed service point can make more than the template's matched
        # anchors redundant.  Recheck using real channel evidence before the
        # next routing decision; this is still a plan check, not an early
        # certificate claim.
        self._trim_service_anchors_from_actual_witnesses(ks)

    def _service_template_mission(self, ks, position):
        """Continue a validated multi-stop replacement template."""
        template = self._certificate_service_template
        if template is None:
            return None
        if not ks.unknown:
            self._certificate_service_template = None
            return None
        ordered = self._certificate_template_order(position)
        if not ordered:
            self._commit_certificate_template_if_ready(ks)
            return None
        first = ordered[0]
        if first[2] == "anchor":
            return self._ring_scan(ks, anchor_index=-first[0] - 1)
        node = next(node for node in template["services"]
                    if node["key"] == first[0])
        if node["kind"] == "clear":
            # The clear is a real service action.  Its subsequent UNKNOWN
            # measurements are the certificate witnesses, so their cost is
            # planned and executed on the same clear mission rather than as a
            # separate zero-information revisit.
            unknown = [ch.channel_id for ch in ks.unknown
                       if not any(math.dist(obs["position"], node["point"]) < 2.0
                                  for obs in ch.observations)]
            return Mission(
                "clear", node["point"], channel=node["channel"],
                meta={"kind": "compact_service_certificate_clear",
                      "certificate_service_key": node["key"],
                      "certificate_service_channel": node["channel"],
                      "certificate_unknown_channels":
                      [ch.channel_id for ch in ks.unknown],
                      "post_clear_channels": unknown,
                      "truncate_at_cardinality":
                      self.compact_truncate_active_at_cardinality})
        joint = [node["channel"]] if (
            node["kind"] == "measure" and
            ks[node["channel"]].status == ChannelStatus.ACTIVE) else []
        return Mission(
            "scan", node["point"], channels=[ch.channel_id for ch in ks.unknown],
            meta={"kind": "compact_service_certificate",
                  "coverage_scan": True,
                  "joint_channels": joint,
                  "certificate_service_key": node["key"],
                  "certificate_service_channel": node["channel"],
                  "truncate_at_cardinality":
                  self.compact_truncate_active_at_cardinality})

    def _certificate_service_template_candidate(self, ks, position):
        """Return the best uncommitted service-certificate template.

        A tight eight-point ring rarely permits an arbitrary *single* source
        stop to replace an anchor.  This searches small matched subsets: the
        selected service points and retained anchors must themselves be a Q3
        cover.  No anchor is deleted until every planned service stop has
        executed its UNKNOWN scan.
        """
        if not self._coverage_remaining or not ks.unknown:
            return None
        anchors = tuple(sorted(self._coverage_remaining))
        anchor_items = [(-(index + 1), self._coverage_points[index], "anchor")
                        for index in anchors]
        # Score a certificate replacement against the route the controller
        # would otherwise execute, not against a fictional anchors-only tour.
        # The latter can select a one-metre anchor saving while pushing a READY
        # clear or an already-admissible ACTIVE visit far away.
        normal_services = {}
        for ch in ks.by_status(ChannelStatus.READY):
            if ch.channel_id not in self.blocked:
                normal_services[ch.channel_id] = (
                    self._clear_target(ch, position), "clear")
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            cid = ch.channel_id
            directions = sum(obs.get("result") == "direction"
                             for obs in ch.observations)
            if (self.fallback.in_fallback(cid)
                    or ch.mec_radius > self.compact_joint_ring_active_radius
                    or directions < self.compact_joint_ring_min_directions
                    or self._compact_route_attempts.get(cid, 0)
                    >= self.compact_joint_ring_active_attempts):
                continue
            point = self._active_route_point(ch, position)
            if point is not None:
                normal_services[cid] = (point, "measure")

        unknown_count = len(ks.unknown)

        def route_score(anchor_indices, overrides=()):
            """Conservative virtual-time proxy expressed in metres."""
            items = [(-(index + 1), self._coverage_points[index], "anchor")
                     for index in anchor_indices]
            service_map = dict(normal_services)
            # A template candidate replaces the ordinary service for the same
            # channel.  Repeated channel rows are excluded below, so one map
            # entry precisely represents one real source task.
            for row in overrides:
                _, cid, point, kind = row[:4]
                service_map[cid] = (point, kind)
            # Every retained anchor scans every current UNKNOWN channel.  Each
            # proposed service witness must do the same.  The old proxy ignored
            # both sweeps and therefore missed the only structural gain here:
            # multiple service scans jointly deleting more fixed anchors.
            # Switch time is intentionally not estimated; complete posterior
            # rollout remains the final selector when that mode is enabled.
            measures = len(anchor_indices) * unknown_count
            for cid, (point, kind) in service_map.items():
                key = 1000 + cid
                items.append((key, point, "service"))
                measures += int(kind == "measure")
            measures += len(overrides) * unknown_count
            ordered = self._hybrid_open_order(
                items, position, or_opt=self.compact_joint_ring_or_opt)
            return (self._open_route_length(ordered, position) +
                    C.MOVE_SPEED * 6.0 * measures)

        base_cost = route_score(anchors)
        candidates = self._certificate_service_candidates(ks, position)
        best = None
        max_depth = min(self.compact_service_certificate_depth, len(anchors),
                        len(candidates))
        for depth in range(1, max_depth + 1):
            for service_rows in itertools.combinations(candidates, depth):
                if len({row[1] for row in service_rows}) != len(service_rows):
                    continue
                service_points = [row[2] for row in service_rows]
                # Compatibility mode keeps the historic equal-cardinality
                # search.  With an explicit cap, search all legal removal
                # counts: two source-service stops can jointly replace three
                # or more fixed anchors, which the old loop could never
                # represent.
                if self.compact_service_certificate_max_anchor_drops > 0:
                    drop_counts = range(
                        1, min(self.compact_service_certificate_max_anchor_drops,
                               len(anchors)) + 1)
                else:
                    drop_counts = (depth,)
                for drop_count in drop_counts:
                    for removed in itertools.combinations(anchors, drop_count):
                        # These service points are future actions.  They may rank
                        # a candidate, but they are deliberately not recorded as
                        # channel evidence until the executor has returned a real
                        # no_signal for every channel still requiring proof.
                        if not self._service_certificate_plan_valid(
                                ks, set(anchors) - set(removed),
                                assumed_service_points=service_points):
                            continue
                        services = []
                        for offset, row in enumerate(service_rows):
                            _, cid, point, kind = row[:4]
                            key = 1000 + cid * 10 + offset
                            services.append(dict(key=key, channel=cid,
                                                 point=point, kind=kind))
                        score = route_score(set(anchors) - set(removed),
                                            overrides=service_rows)
                        candidate = (score, tuple(removed), services)
                        if (best is None or candidate[0] < best[0] - 1e-9 or
                                (abs(candidate[0] - best[0]) <= 1e-9 and
                                 candidate[1] < best[1])):
                            best = candidate
        if best is None:
            return None
        saving = base_cost - best[0]
        if saving + 1e-9 < self.compact_service_certificate_min_saving_m:
            return None
        _, removed, services = best
        return saving, tuple(removed), services

    def _certificate_service_mission(self, ks, position):
        """Commit a route-proxy-approved service-certificate template.

        The rollout variant calls the pure candidate builder instead and only
        commits a template after a full posterior replay selects its first
        service action.  This legacy path remains available for controlled
        comparisons and keeps the default behaviour unchanged.
        """
        if (not self.compact_service_certificate or
                not self._coverage_remaining or not ks.unknown):
            return None
        ongoing = self._service_template_mission(ks, position)
        if ongoing is not None or self._certificate_service_template is not None:
            return ongoing
        proposal = self._certificate_service_template_candidate(ks, position)
        if proposal is None:
            return None
        saving, removed, services = proposal
        self.compact_stats["service_certificate_candidates"] += 1
        self._certificate_service_template = {
            "remove_anchors": set(removed),
            "services": services,
            "remaining_services": {node["key"] for node in services},
        }
        self.compact_stats["service_certificate_templates"] += 1
        self.compact_stats["service_certificate_route_saving_m"] += saving
        return self._service_template_mission(ks, position)

    def on_certificate_service_complete(self, mission, ks, measured_channels):
        """Register a real witness; complete the template only when safe."""
        if mission.meta.get("kind") not in (
                "compact_service_certificate",
                "compact_service_certificate_clear"):
            return
        template = self._certificate_service_template
        key = mission.meta.get("certificate_service_key")
        if template is None or key not in template["remaining_services"]:
            self.compact_stats["service_certificate_rejected"] += 1
            return
        expected = mission.meta.get("certificate_unknown_channels",
                                    mission.channels)
        witnessed = True
        for cid in expected:
            ch = ks[cid]
            if ch.status != ChannelStatus.UNKNOWN:
                continue
            if self._record_service_witness(ch, mission.target):
                continue
            # A duplicate service point has already been recorded above; it
            # remains a valid real witness.  Merely appearing in
            # ``measured_channels`` is not enough: a callback or ordering bug
            # must never turn a direction/near observation into absence proof.
            if any(obs.get("result") == "no_signal" and
                   math.dist(obs["position"], mission.target) < 2.0
                   for obs in ch.observations):
                continue
            witnessed = False
            break
        if not witnessed:
            self.compact_stats["service_certificate_rejected"] += 1
            self._certificate_service_template = None
            return
        template["remaining_services"].remove(key)
        if not any(math.dist(mission.target, point) < 1.0
                   for point in self._certificate_service_witnesses):
            self._certificate_service_witnesses.append(mission.target)
        cid = mission.meta.get("certificate_service_channel")
        if (cid in ks.channels and ks[cid].status == ChannelStatus.READY):
            self._certificate_service_followup = cid
        # This makes replacement visible to the following routing decision
        # whenever one actual service scan already renders an anchor
        # redundant.  It cannot use later template points as if visited.
        self._trim_service_anchors_from_actual_witnesses(ks)
        self._commit_certificate_template_if_ready(ks)

    def _ring_scan(self, ks, anchor_index=None):
        if self._ring_finished(ks):
            if self._known_count(ks) >= C.MAX_SOURCES:
                self.compact_stats["early_stop"] = True
            return None
        if anchor_index is None:
            anchor_index = self._coverage_index
        point = self._coverage_points[anchor_index]
        def direction_count(channel):
            return sum(obs.get("result") == "direction"
                       for obs in channel.observations)
        active = [ch.channel_id for ch in ks.by_status(ChannelStatus.ACTIVE)
                  if ch.mec_radius > self.compact_active_stop_radius
                  and not self.fallback.in_fallback(ch.channel_id)
                  and (self.compact_ring_active_max_directions <= 0 or
                       direction_count(ch) <
                       self.compact_ring_active_max_directions)]
        if self.compact_terminal_scan_radius > 0.0:
            for ch in ks.by_status(ChannelStatus.ACTIVE):
                cid = ch.channel_id
                if (cid in active or self.fallback.in_fallback(cid)
                        or ch.mec is None
                        or ch.mec_radius > self.compact_terminal_scan_radius
                        or (self.compact_ring_active_max_directions > 0 and
                            direction_count(ch) >=
                            self.compact_ring_active_max_directions)
                        or any(math.dist(obs["position"], point) < 2.0
                               for obs in ch.observations)):
                    continue
                center, radius = ch.mec
                # This gate only spends a measurement when a direction result
                # is guaranteed at the stop.  The predicted terminal radius is
                # a value heuristic; actual READY still comes from state update.
                if math.dist(point, center) + radius > C.R_EFF_MIN + 1e-9:
                    continue
                try:
                    step = localization._adaptive_step(ch.feasible_region,
                                                       point)
                    worst = localization._eval_worst(
                        ch.feasible_region, point, step, mode="radius")
                except Exception:
                    continue
                if worst <= self.compact_terminal_scan_worst + 1e-9:
                    active.append(cid)
                    self.compact_stats["terminal_ring_measures"] += 1
        self._coverage_remaining.discard(anchor_index)
        if self.compact_joint_ring_route or self.compact_service_certificate:
            self._coverage_index = self.compact_ring_points - len(
                self._coverage_remaining)
        else:
            # The default ring normally follows index order.  A bounded local
            # rebuild may visit the next two anchors in the opposite order;
            # retain the earliest still-unvisited default index instead of
            # accidentally skipping it after that legal reordering.
            while (self._coverage_index not in self._coverage_remaining
                   and self._coverage_index < self.compact_ring_points):
                self._coverage_index += 1
        self.compact_stats["ring_stops"] += 1
        self.compact_stats["joint_active_planned"] += len(active)
        return Mission(
            "scan", point, channels=[ch.channel_id for ch in ks.unknown],
            meta={"kind": "compact_ring", "coverage_scan": True,
                  # With a joint route, ``_coverage_index`` is the count of
                  # consumed anchors, not the identity of this point.  Keep
                  # the identity on the mission so a later bounded branch can
                  # reconnect to this exact certificate stop.
                  "coverage_anchor_index": anchor_index,
                  "joint_channels": active,
                  # Optional strict interpretation: cut the whole stop at the
                  # 16th discovery. False still skips all now-terminal UNKNOWN
                  # channels, but finishes the ACTIVE localisation suffix.
                  "truncate_at_cardinality":
                      self.compact_truncate_active_at_cardinality})

    def on_probe_failure(self, channel_id, point):
        super().on_probe_failure(channel_id, point)
        if (self._compact_inflight is not None
                and self._compact_inflight[0] == int(channel_id)):
            self._compact_failed_measure = (int(channel_id), tuple(point))
            self._compact_inflight = None

    @staticmethod
    def _route_cost(points, position):
        if not points:
            return float("inf")
        distance = math.dist(position, points[0]) + sum(
            math.dist(a, b) for a, b in zip(points, points[1:]))
        return distance / C.MOVE_SPEED + 3.0 * (len(points) - 1) + 5.0

    @staticmethod
    def _strip_covers(poly, radius=C.CLEAR_RADIUS):
        """Guaranteed disk covers for convex regions narrower than 2r.

        For an axis, all polygon points lie in a strip of half-width h.  Disk
        centres on the strip centreline cover a longitudinal half-span
        sqrt(r^2-h^2).  Uniformly covering the projected interval therefore
        covers the entire polygon, not just its vertices.
        """
        if not poly or len(poly) < 2:
            return []
        covers = []
        safe_radius = max(0.0, float(radius) - 1e-6)
        seen_axes = set()
        for a, b in zip(poly, list(poly[1:]) + [poly[0]]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            norm = math.hypot(dx, dy)
            if norm <= 1e-9:
                continue
            ux, uy = dx / norm, dy / norm
            if ux < -1e-9 or (abs(ux) <= 1e-9 and uy < 0.0):
                ux, uy = -ux, -uy
            key = (round(ux, 6), round(uy, 6))
            if key in seen_axes:
                continue
            seen_axes.add(key)
            vx, vy = -uy, ux
            along = [p[0] * ux + p[1] * uy for p in poly]
            across = [p[0] * vx + p[1] * vy for p in poly]
            lo, hi = min(along), max(along)
            side_lo, side_hi = min(across), max(across)
            half_width = 0.5 * (side_hi - side_lo)
            if half_width >= safe_radius:
                continue
            half_span = math.sqrt(max(
                0.0, safe_radius * safe_radius - half_width * half_width))
            length = hi - lo
            count = max(1, int(math.ceil(length / (2.0 * half_span))))
            step = length / count
            side = 0.5 * (side_lo + side_hi)
            points = [
                ((lo + (i + 0.5) * step) * ux + side * vx,
                 (lo + (i + 0.5) * step) * uy + side * vy)
                for i in range(count)
            ]
            covers.append(points)
        return covers

    def _shape_cover_points(self, poly, position):
        lattice = order_greedy(disk_lattice_cover(poly), position)
        candidates = [lattice]
        for points in self._strip_covers(poly):
            candidates.append(points)
            candidates.append(list(reversed(points)))
        return min(candidates,
                   key=lambda points: (self._route_cost(points, position),
                                       len(points)))

    def _early_fallback_points(self, ch, position):
        if not self.compact_shape_cover:
            return super()._early_fallback_points(ch, position)
        return self._shape_cover_points(ch.feasible_region, position)

    def _enter_fallback(self, ch_state, position, trigger):
        super()._enter_fallback(ch_state, position, trigger)
        if not self.compact_shape_cover:
            return
        st = self.fallback._fallback.get(ch_state.channel_id)
        if st is None:
            return
        old_count = len(st["points"])
        points = self._shape_cover_points(ch_state.feasible_region, position)
        if not points:
            return
        st["points"] = points
        st["index"] = 0
        record = st["record"]
        record["n_points"] = len(points)
        record["points"] = [tuple(point) for point in points]
        if len(points) < old_count:
            self.compact_stats["shape_cover_uses"] += 1
            self.compact_stats["shape_cover_points_saved"] += (
                old_count - len(points))

    @staticmethod
    def _exact_open_order(items, start):
        """Held-Karp optimum for a fixed-start, free-end path."""
        items = sorted(items, key=lambda item: item[0])
        n = len(items)
        if n <= 1:
            return items
        points = [item[1] for item in items]
        costs = {}
        parents = {}
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

    def _ready_route_candidate(self, ks, position):
        ready = [ch for ch in ks.by_status(ChannelStatus.READY)
                 if ch.channel_id not in self.blocked]
        if not ready:
            return None
        items = [(ch.channel_id, self._clear_target(ch, position))
                 for ch in ready]
        ordered = self._exact_open_order(items, position)
        cid, target = ordered[0]
        self.compact_stats["exact_ready_routes"] += 1
        return Mission("clear", target, channel=cid,
                       meta={"kind": "ready_exact_open_route",
                             "ready_route": True,
                             "ready_route_total": len(ordered)})

    def _post_clear_channels(self, ks, target, exclude=None):
        """ACTIVE measurements whose worst bearing posterior is valuable.

        Returning ``None`` preserves the historical automatic post-clear
        sweep.  An enabled threshold returns an explicit (possibly empty)
        set, so planning and execution use the same value-gated action.
        """
        if self.compact_post_clear_worst <= 0.0:
            return None
        selected = []
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            cid = ch.channel_id
            if cid == exclude or ch.mec is None:
                continue
            if any(math.dist(obs["position"], target) < 2.0
                   for obs in ch.observations):
                continue
            center, radius = ch.mec
            # _eval_worst evaluates bearing outcomes. Require reception for
            # every feasible source point before trusting that estimate.
            if math.dist(target, center) + radius > C.R_EFF_MIN + 1e-9:
                continue
            try:
                step = localization._adaptive_step(ch.feasible_region, target)
                worst = localization._eval_worst(
                    ch.feasible_region, target, step, mode="radius")
            except Exception:
                continue
            if worst <= self.compact_post_clear_worst + 1e-9:
                selected.append((float(worst), cid))
        selected.sort()
        result = [cid for _, cid in selected]
        self.compact_stats["value_post_clear_measures"] += len(result)
        return result


    def _active_route_point(self, ch, position):
        point = ch.mec[0]
        seen = [tuple(obs["position"]) for obs in ch.observations]
        alternatives = [p for p in localization.candidate_points(
            ch, position, failed_points=self.failed_points.get(ch.channel_id),
            opportunistic_reuse=True)
            if not any(math.dist(obs, p) < 2.0 for obs in seen)]
        if not any(math.dist(obs, point) < 2.0 for obs in seen):
            return point
        if not alternatives:
            return None
        return min(alternatives,
                   key=lambda p: (math.dist(position, p), p[0], p[1]))

    def _start_local_finish(self, ch):
        if (self.compact_local_finish_steps <= 0
                or self.compact_local_finish_budget <= 0.0):
            self._compact_local_finish = None
            return
        # This is armed before the selected measurement runs.  The next
        # decide() sees that measurement's posterior and applies the radius
        # gate there; testing the pre-measure radius here misses the transition
        # into the local-completion regime.
        self._compact_local_finish = {
            "cid": ch.channel_id,
            "last_radius": float(ch.mec_radius),
            "spent_m": 0.0,
            "steps": 0,
        }

    def _local_finish_mission(self, ks, position):
        state = self._compact_local_finish
        if state is None:
            return None
        if self._known_count(ks) < self.compact_local_finish_min_known:
            self._compact_local_finish = None
            self.compact_stats["local_finish_releases"] += 1
            return None
        ch = ks[state["cid"]]
        if ch.status == ChannelStatus.READY:
            self._compact_local_finish = None
            self.compact_stats["local_finish_clears"] += 1
            post = self._post_clear_channels(ks, self._clear_target(ch, position),
                                             exclude=ch.channel_id)
            meta = {"kind": "compact_local_finish_clear",
                    "ready_route": True}
            if post is not None:
                meta["post_clear_channels"] = post
            return Mission(
                "clear", self._clear_target(ch, position),
                channel=ch.channel_id,
                meta=meta)
        if ch.status != ChannelStatus.ACTIVE:
            self._compact_local_finish = None
            return None
        previous = max(float(state["last_radius"]), 1e-9)
        shrink = (previous - float(ch.mec_radius)) / previous
        if (state["steps"] >= self.compact_local_finish_steps
                or ch.mec_radius > self.compact_local_finish_max_radius
                or shrink + 1e-12 < self.compact_local_finish_min_shrink):
            self._compact_local_finish = None
            self.compact_stats["local_finish_releases"] += 1
            return None
        point = self._active_route_point(ch, position)
        if point is None:
            self._compact_local_finish = None
            self.compact_stats["local_finish_releases"] += 1
            return None
        distance = math.dist(position, point)
        if state["spent_m"] + distance > self.compact_local_finish_budget + 1e-9:
            self._compact_local_finish = None
            self.compact_stats["local_finish_releases"] += 1
            return None
        state["spent_m"] += distance
        state["steps"] += 1
        state["last_radius"] = float(ch.mec_radius)
        self._compact_route_attempts[ch.channel_id] = (
            self._compact_route_attempts.get(ch.channel_id, 0) + 1)
        self.compact_stats["local_finish_measures"] += 1
        return Mission(
            "measure", point, channel=ch.channel_id,
            meta={"kind": "compact_local_finish_measure",
                  "scan_variant": "primary",
                  "local_finish_step": state["steps"],
                  "local_finish_spent_m": state["spent_m"]})

    def _active_route_candidates(self, ch, position):
        """Information-safe alternative stops for one ACTIVE channel."""
        baseline = self._active_route_point(ch, position)
        if baseline is None or not self.compact_route_alternatives:
            return [] if baseline is None else [baseline]
        points = localization.candidate_points(
            ch, position, failed_points=self.failed_points.get(ch.channel_id),
            opportunistic_reuse=True)
        if not points:
            return [baseline]
        scored = []
        try:
            for point in points:
                step = localization._adaptive_step(ch.feasible_region, point)
                worst = localization._eval_worst(
                    ch.feasible_region, point, step, mode="radius")
                scored.append((float(worst), point))
        except Exception:
            return [baseline]
        best_worst = min(value for value, _ in scored)
        allowed = [point for value, point in scored
                   if value <= best_worst + self.compact_route_quality_slack]
        if baseline not in allowed:
            allowed.append(baseline)
        unique = []
        for point in allowed:
            if not any(math.dist(point, prior) < 1.0 for prior in unique):
                unique.append(point)
        return unique

    @staticmethod
    def _open_route_length(items, start):
        total = 0.0
        previous = start
        for item in items:
            total += math.dist(previous, item[1])
            previous = item[1]
        return total

    @classmethod
    def _two_opt_open(cls, ordered, start):
        """Improve a fixed-start, free-end route using strict 2-opt moves."""
        ordered = list(ordered)
        improved = True
        while improved:
            improved = False
            base = cls._open_route_length(ordered, start)
            for i in range(len(ordered) - 1):
                for j in range(i + 1, len(ordered)):
                    candidate = (ordered[:i] +
                                 list(reversed(ordered[i:j + 1])) +
                                 ordered[j + 1:])
                    value = cls._open_route_length(candidate, start)
                    if value + 1e-9 < base:
                        ordered = candidate
                        improved = True
                        break
                if improved:
                    break
        return ordered

    @classmethod
    def _or_opt_open(cls, ordered, start, max_segment=2):
        """Strict Or-opt relocation after 2-opt for a free-end open route.

        A 2-opt local minimum can still contain a cheap one- or two-node
        relocation.  The pool is only a few dozen nodes, so exhaustive local
        insertion is negligible compared with one simulator action.  Every
        accepted move has a strictly shorter route; it is therefore safe as a
        route-only experimental polish.
        """
        current = list(ordered)
        while True:
            base = cls._open_route_length(current, start)
            best = None
            n = len(current)
            for size in range(1, min(max_segment, n) + 1):
                for index in range(n - size + 1):
                    block = current[index:index + size]
                    rest = current[:index] + current[index + size:]
                    for insert in range(len(rest) + 1):
                        candidate = rest[:insert] + block + rest[insert:]
                        value = cls._open_route_length(candidate, start)
                        key = (value, tuple(item[0] for item in candidate))
                        if value + 1e-9 < base and (best is None or key < best[0]):
                            best = (key, candidate)
            if best is None:
                return current
            current = cls._two_opt_open(best[1], start)

    @classmethod
    def _hybrid_open_order(cls, items, start, or_opt=False):
        """Exact small open TSP; 2-opt, optionally Or-opt, for large pools."""
        if len(items) <= 16:
            return cls._exact_open_order(items, start)
        remaining = sorted(items, key=lambda item: item[0])
        ordered = []
        current = start
        while remaining:
            chosen = min(remaining,
                         key=lambda item: (math.dist(current, item[1]),
                                           item[0]))
            ordered.append(chosen)
            remaining.remove(chosen)
            current = chosen[1]
        ordered = cls._two_opt_open(ordered, start)
        return cls._or_opt_open(ordered, start) if or_opt else ordered

    def _joint_clear_witness_drops(self, ks, target):
        """Future anchors an actual clear-stop scan could safely replace.

        The calculation is deliberately conservative.  It assumes every
        channel that is currently UNKNOWN will be measured at ``target`` and,
        if still unknown, return a real no-signal witness there.  A channel
        discovered by that scan no longer needs absence coverage, so this is
        still a safe *planning* test.  It does not mutate evidence or delete
        an anchor; :meth:`on_certificate_clear_witness_complete` repeats the
        check after the runner has returned the observations.
        """
        if not self.compact_joint_clear_witness:
            return ()
        unknown_count = len(ks.unknown)
        if (unknown_count == 0 or
                (self.compact_joint_clear_witness_max_unknown > 0 and
                 unknown_count > self.compact_joint_clear_witness_max_unknown)):
            return ()
        remaining = set(self._coverage_remaining)
        if len(remaining) <= 1:
            return ()
        visited = [self._coverage_points[index]
                   for index in range(self.compact_ring_points)
                   if index not in remaining]
        drops = []
        for index in sorted(remaining):
            future = [self._coverage_points[other]
                      for other in sorted(remaining) if other != index]
            if q3_certified(visited + [tuple(target)] + future)["certified"]:
                drops.append(index)
        return tuple(drops)

    def _joint_anchor_substitution(self, ks, target):
        """Return a certificate anchor that a READY stop can replace.

        Unlike a witness *deletion*, this keeps the certificate at eight
        stations.  It checks the full planned cover after replacing exactly
        one still-pending point by ``target``.  The caller only commits this
        change by issuing a clear mission whose post-clear suffix measures all
        still-UNKNOWN channels at that same point.
        """
        if not self.compact_joint_anchor_substitution:
            return None
        unknown_count = len(ks.unknown)
        if (unknown_count == 0 or
                (self.compact_joint_anchor_substitution_max_unknown > 0 and
                 unknown_count >
                 self.compact_joint_anchor_substitution_max_unknown)):
            return None
        remaining = set(self._coverage_remaining)
        if not remaining:
            return None
        visited = [self._coverage_points[index]
                   for index in range(self.compact_ring_points)
                   if index not in remaining]
        choices = []
        for index in sorted(remaining):
            future = [tuple(target) if other == index
                      else self._coverage_points[other]
                      for other in sorted(remaining)]
            if q3_certified(visited + future)["certified"]:
                choices.append((math.dist(self._coverage_points[index], target),
                                index))
        if not choices:
            self.compact_stats["joint_anchor_substitution_skipped"] += 1
            return None
        return min(choices)[1]

    def _issue_joint_anchor_substitution(self, ks, target, channel, index):
        """Commit one real clear-plus-certificate-station mission."""
        self._coverage_points[index] = tuple(target)
        self._coverage_remaining.discard(index)
        self._coverage_index = self.compact_ring_points - len(
            self._coverage_remaining)
        self.compact_stats["joint_anchor_substitutions"] += 1
        self._compact_service_pending = tuple(target)
        unknown = [ch.channel_id for ch in ks.unknown]
        return Mission(
            "clear", target, channel=channel.channel_id,
            meta={"kind": "compact_joint_anchor_substitution_clear",
                  "ready_route": True,
                  "coverage_scan": True,
                  "coverage_anchor_index": index,
                  "certificate_clear_witness": True,
                  "certificate_unknown_channels": unknown,
                  "certificate_anchor_substitution": True,
                  "post_clear_channels": unknown,
                  "truncate_at_cardinality":
                  self.compact_truncate_active_at_cardinality})

    def _issue_joint_anchor_measure_substitution(self, ks, target, channel,
                                                 index):
        """Fuse one ACTIVE bearing with a replacement certificate station."""
        self._coverage_points[index] = tuple(target)
        self._coverage_remaining.discard(index)
        self._coverage_index = self.compact_ring_points - len(
            self._coverage_remaining)
        self.compact_stats["joint_anchor_substitutions"] += 1
        self.compact_stats["joint_anchor_substitution_measures"] += 1
        self._compact_service_pending = tuple(target)
        self._compact_route_attempts[channel.channel_id] = (
            self._compact_route_attempts.get(channel.channel_id, 0) + 1)
        self.compact_stats["joint_ring_active_measures"] += 1
        if channel.mec_radius > self.compact_active_stop_radius:
            self.compact_stats["joint_ring_large_active_measures"] += 1
        joint = self._joint_ring_terminal_channels(
            ks, target, exclude=channel.channel_id)
        self.compact_stats["joint_ring_service_measures"] += len(joint)
        return Mission(
            "scan", target,
            channels=[ch.channel_id for ch in ks.unknown],
            meta={"kind": "compact_joint_anchor_substitution_measure",
                  "coverage_scan": True,
                  "coverage_anchor_index": index,
                  "joint_channels": [channel.channel_id] + joint,
                  "certificate_anchor_substitution": True,
                  "truncate_at_cardinality":
                  self.compact_truncate_active_at_cardinality})

    def _adapt_center_warmup(self, ks):
        """Use the completed centre scan to protect a short anchor prefix.

        ``compact_joint_ring_min_stops`` is otherwise static.  The centre
        scan supplies a small, directly observable density/dispersion signal:
        the length of the mean unit bearing vector is close to one when the
        seen sources occupy a narrow angular sector.  We compute it once, only
        after the real origin scan has been issued and executed.
        """
        if (self._compact_center_warmup_done or not self.compact_center_anchor
                or self.compact_center_warmup_resultant_threshold <= 0.0
                or 0 in self._coverage_remaining):
            return
        self._compact_center_warmup_done = True
        origin = self._coverage_points[0]
        bearings = []
        for ch in ks.channels.values():
            for obs in ch.observations:
                if (obs.get("result") == "direction" and
                        math.dist(tuple(obs["position"]), origin) < 2.0):
                    bearings.append(math.radians(float(obs["bearing"])))
        resultant = (math.hypot(sum(math.cos(a) for a in bearings),
                                sum(math.sin(a) for a in bearings)) /
                     len(bearings) if bearings else 0.0)
        runtime_min = self.compact_joint_ring_min_stops
        if resultant + 1e-12 >= self.compact_center_warmup_resultant_threshold:
            runtime_min = max(runtime_min, self.compact_center_warmup_min_stops)
            self.compact_stats["center_warmup_adaptations"] += 1
        self._compact_center_warmup_min_stops = runtime_min
        self.compact_stats["center_warmup_resultant"] = float(resultant)
        self.compact_stats["center_warmup_min_stops"] = int(runtime_min)

    def _joint_ring_min_stops_now(self):
        return (self.compact_joint_ring_min_stops
                if self._compact_center_warmup_min_stops is None else
                self._compact_center_warmup_min_stops)

    def _coverage_optical_mission(self, ks, position, current_channel):
        """Start one small exact optical finish before leaving coverage.

        A candidate's cost includes its whole finite clear route.  The method
        does not estimate a hit probability: the lattice cover contains the
        complete constrained feasible region, so a successful clear is
        guaranteed by the final point at latest.  Subsequent decisions route
        the active fallback to completion before considering another entry.
        """
        if (self.compact_coverage_optical_max_points <= 0 or
                self.compact_coverage_optical_max_entries <=
                self._compact_coverage_optical_entries or ks.ready):
            return None
        best = None
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            cid = ch.channel_id
            if self.fallback.in_fallback(cid) or not ch.feasible_region:
                continue
            points = self._early_fallback_points(ch, position)
            if (not points or len(points) >
                    self.compact_coverage_optical_max_points):
                continue
            ordered = order_greedy(points, position)
            entry = math.dist(position, ordered[0])
            if (self.compact_coverage_optical_max_entry_m > 0.0 and
                    entry > self.compact_coverage_optical_max_entry_m + 1e-9):
                continue
            route = entry + sum(math.dist(a, b)
                                for a, b in zip(ordered, ordered[1:]))
            # Worst case: all but the final disk miss.  This only chooses one
            # legal finite branch, and is deliberately conservative.
            cost = route / C.MOVE_SPEED + 3.0 * (len(ordered) - 1) + 5.0
            key = (cost, len(ordered), entry, cid)
            if best is None or key < best[0]:
                best = (key, ch, ordered)
        if best is None:
            return None
        _, ch, ordered = best
        self._compact_coverage_optical_entries += 1
        self._early_fallback_channels.add(ch.channel_id)
        self._enter_fallback(ch, position, "compact_coverage_small_exact_cover")
        self.compact_stats["coverage_optical_entries"] += 1
        self.compact_stats["coverage_optical_points"] += len(ordered)
        return self._fallback_route(ks, position, current_channel)

    def _joint_ring_mission(self, ks, position, include_services=True):
        """Plan certificate anchors and cheap source-service nodes together."""
        items = [(-(index + 1), self._coverage_points[index], "anchor")
                 for index in self._coverage_remaining]
        if include_services:
            for ch in ks.by_status(ChannelStatus.READY):
                if ch.channel_id not in self.blocked:
                    items.append((ch.channel_id,
                                  self._clear_target(ch, position), "clear"))
            for ch in ks.by_status(ChannelStatus.ACTIVE):
                cid = ch.channel_id
                direction_count = sum(
                    obs.get("result") == "direction"
                    for obs in ch.observations)
                if (self.fallback.in_fallback(cid)
                        or ch.mec_radius > self.compact_joint_ring_active_radius
                        or direction_count < self.compact_joint_ring_min_directions
                        or self._compact_route_attempts.get(cid, 0)
                        >= self.compact_joint_ring_active_attempts):
                    continue
                point = self._active_route_point(ch, position)
                if point is not None:
                    items.append((cid, point, "measure"))
        if not items:
            return None
        cid, target, kind = self._hybrid_open_order(
            items, position, or_opt=self.compact_joint_ring_or_opt)[0]
        if kind == "anchor":
            return self._ring_scan(ks, anchor_index=-cid - 1)
        if kind == "clear":
            self.compact_stats["joint_ring_clears"] += 1
            self._compact_service_pending = tuple(target)
            substitute = self._joint_anchor_substitution(ks, target)
            if substitute is not None:
                return self._issue_joint_anchor_substitution(
                    ks, target, ks[cid], substitute)
            unknown = [ch.channel_id for ch in ks.unknown]
            # Preserve the historical joint-ring clear exactly when the new
            # witness feature is off: it deliberately had no post-clear scan.
            witness_meta = {"post_clear_channels": []}
            planned_drops = self._joint_clear_witness_drops(ks, target)
            if (self.compact_joint_clear_witness and
                    (not self.compact_joint_clear_witness_useful_only or
                     planned_drops)):
                self.compact_stats["joint_clear_witness_admitted"] += 1
                witness_meta = {
                    "certificate_clear_witness": True,
                    "certificate_unknown_channels": unknown,
                    "certificate_clear_planned_drops": list(planned_drops),
                    # Every UNKNOWN channel is measured at this actual clear
                    # stop.  Later exact trimming may remove only anchors
                    # whose work this witnessed stop makes redundant.
                    "post_clear_channels": unknown,
                }
            elif self.compact_joint_clear_witness:
                self.compact_stats["joint_clear_witness_skipped"] += 1
            return Mission(
                "clear", target, channel=cid,
                meta={"kind": "compact_joint_ring_clear",
                      "ready_route": True, **witness_meta})
        substitute = self._joint_anchor_substitution(ks, target)
        if substitute is not None:
            return self._issue_joint_anchor_measure_substitution(
                ks, target, ks[cid], substitute)
        self._compact_route_attempts[cid] = (
            self._compact_route_attempts.get(cid, 0) + 1)
        self._compact_service_pending = tuple(target)
        self.compact_stats["joint_ring_active_measures"] += 1
        if ks[cid].mec_radius > self.compact_active_stop_radius:
            self.compact_stats["joint_ring_large_active_measures"] += 1
        joint = self._joint_ring_terminal_channels(ks, target, exclude=cid)
        self.compact_stats["joint_ring_service_measures"] += len(joint)
        return Mission(
            "measure", target, channel=cid,
            meta={"kind": "compact_joint_ring_measure",
                  "scan_variant": "primary", "joint_channels": joint})

    def _joint_ring_terminal_channels(self, ks, target, exclude):
        """ACTIVE channels a source service stop can finish without a detour.

        A general all-ACTIVE sweep at a service node repeatedly lost to switch
        costs.  This narrower action is admitted only when Q3 guarantees a
        direction result at the already-paid stop and the bounded-error worst
        posterior after that measurement is READY.  It therefore buys the
        removal of a future localisation visit rather than merely a smaller
        MEC number.
        """
        if self.compact_joint_ring_service_worst <= 0.0:
            return []
        selected = []
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            cid = ch.channel_id
            if (cid == exclude or self.fallback.in_fallback(cid)
                    or ch.mec is None
                    or any(math.dist(obs["position"], target) < 2.0
                           for obs in ch.observations)):
                continue
            center, radius = ch.mec
            if math.dist(target, center) + radius > C.R_EFF_MIN + 1e-9:
                continue
            try:
                step = localization._adaptive_step(ch.feasible_region, target)
                worst = localization._eval_worst(
                    ch.feasible_region, target, step, mode="radius")
            except Exception:
                continue
            if worst <= self.compact_joint_ring_service_worst + 1e-9:
                selected.append((float(worst), cid))
        selected.sort()
        return [cid for _, cid in selected]

    def _optimise_route_points(self, fixed, active, position):
        """Alternate exact ordering with route-local ACTIVE point selection."""
        selected = {cid: points[0] for cid, points in active.items() if points}
        initial = fixed + [(cid, point, "measure")
                           for cid, point in selected.items()]
        initial_order = self._exact_open_order(initial, position)
        initial_length = self._open_route_length(initial_order, position)
        for _ in range(self.compact_route_point_passes):
            items = fixed + [(cid, point, "measure")
                             for cid, point in selected.items()]
            ordered = self._exact_open_order(items, position)
            for index, item in enumerate(ordered):
                cid, _, kind = item
                if kind != "measure" or cid not in active:
                    continue
                previous = position if index == 0 else ordered[index - 1][1]
                following = (None if index + 1 == len(ordered)
                             else ordered[index + 1][1])
                def link_cost(point):
                    value = math.dist(previous, point)
                    if following is not None:
                        value += math.dist(point, following)
                    return (value, point[0], point[1])
                selected[cid] = min(active[cid], key=link_cost)
        final_items = fixed + [(cid, point, "measure")
                               for cid, point in selected.items()]
        final_order = self._exact_open_order(final_items, position)
        saving = max(0.0, initial_length -
                     self._open_route_length(final_order, position))
        if saving > 1e-9:
            self.compact_stats["alternative_route_uses"] += 1
            self.compact_stats["alternative_route_saving_m"] += saving
        return final_order

    def _clustered_route_channels(self, ordered, primary, target, ks,
                                  position):
        """ACTIVE nodes worth measuring at the primary node's stop.

        The score is measured in route metres: remove one future ACTIVE node
        from the current exact open path and compare the saved distance with
        the configured minimum.  Radius and MEC gates keep the substituted
        bearing close to the point the localisation policy actually requested.
        """
        if (self.compact_route_cluster_radius <= 0.0
                or self.compact_route_cluster_max <= 0):
            return []
        base = self._open_route_length(ordered, position)
        candidates = []
        for index, item in enumerate(ordered):
            cid, point, kind = item
            if cid == primary or kind != "measure":
                continue
            ch = ks[cid]
            if (ch.status != ChannelStatus.ACTIVE
                    or ch.mec_radius > self.compact_active_stop_radius
                    or any(math.dist(obs["position"], target) < 2.0
                           for obs in ch.observations)
                    or math.dist(point, target) >
                    self.compact_route_cluster_radius + 1e-9):
                continue
            reduced = ordered[:index] + ordered[index + 1:]
            saving = base - self._open_route_length(reduced, position)
            if saving + 1e-9 < self.compact_route_cluster_min_saving:
                continue
            candidates.append((-saving, math.dist(point, target), cid))
        candidates.sort()
        chosen = candidates[:self.compact_route_cluster_max]
        for neg_saving, _, cid in chosen:
            self._compact_route_attempts[cid] = (
                self._compact_route_attempts.get(cid, 0) + 1)
            self.compact_stats["clustered_route_saving_m"] += -neg_saving
        self.compact_stats["clustered_active_measures"] += len(chosen)
        return [cid for _, _, cid in chosen]

    def _joint_open_route(self, ks, position):
        """Exact open route over current READY clears and ACTIVE approaches."""
        fixed = []
        for ch in ks.by_status(ChannelStatus.READY):
            if ch.channel_id not in self.blocked:
                fixed.append((ch.channel_id,
                              self._clear_target(ch, position), "clear"))
        active = {}
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            cid = ch.channel_id
            if (self.fallback.in_fallback(cid)
                    or self._compact_route_attempts.get(cid, 0)
                    >= self.compact_route_active_attempts):
                continue
            points = self._active_route_candidates(ch, position)
            if points:
                active[cid] = points
        if not fixed and not active:
            return None
        if self.compact_route_alternatives and active:
            ordered = self._optimise_route_points(fixed, active, position)
        else:
            items = fixed + [(cid, points[0], "measure")
                             for cid, points in active.items()]
            ordered = self._exact_open_order(items, position)
        if self.compact_clear_region_route and fixed:
            from .region_route import optimise
            ordered = optimise(self, ordered, ks, position)
        cid, target, kind = ordered[0]
        if kind == "clear":
            self.compact_stats["exact_ready_routes"] += 1
            self._compact_service_pending = tuple(target)
            post = self._post_clear_channels(ks, target, exclude=cid)
            meta = {"kind": "compact_joint_route_clear",
                    "ready_route": True,
                    "ready_route_total": len(ordered)}
            if post is not None:
                meta["post_clear_channels"] = post
            return Mission("clear", target, channel=cid,
                           meta=meta)
        self._compact_route_attempts[cid] = (
            self._compact_route_attempts.get(cid, 0) + 1)
        self._compact_service_pending = tuple(target)
        self.compact_stats["active_route_measures"] += 1
        ch = ks[cid]
        if (self.compact_route_free_probe_radius > 0.0
                and ch.mec_radius <= self.compact_route_free_probe_radius
                and cid not in self._compact_attempted):
            self._compact_attempted.add(cid)
            self._compact_inflight = (cid, target)
            self.compact_stats["route_free_probes"] += 1
            return Mission(
                "clear", target, channel=cid,
                meta={"kind": "compact_joint_free_probe",
                      "risky_probe": True, "compact_ring": True,
                      "post_clear_channels": []})
        self._start_local_finish(ch)
        joint = self._clustered_route_channels(
            ordered, cid, target, ks, position)
        return Mission("measure", target, channel=cid,
                       meta={"kind": "compact_joint_route_measure",
                             "scan_variant": "primary",
                             "joint_channels": joint,
                             "joint_route_total": len(ordered)})

    def _enroute_active_measure(self, ks, position, next_ring):
        if self.compact_enroute_measure_detour <= 0.0:
            return None
        candidates = []
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            cid = ch.channel_id
            if (cid in self._compact_enroute_measured
                    or ch.mec_radius > self.compact_active_stop_radius
                    or self.fallback.in_fallback(cid)):
                continue
            point = self._active_route_point(ch, position)
            if point is None:
                continue
            detour = (math.dist(position, point) + math.dist(point, next_ring)
                      - math.dist(position, next_ring))
            if detour <= self.compact_enroute_measure_detour + 1e-9:
                candidates.append((detour, math.dist(position, point), cid,
                                   point))
        if not candidates:
            return None
        detour, _, cid, point = min(candidates)
        self._compact_enroute_measured.add(cid)
        self._compact_route_attempts[cid] = (
            self._compact_route_attempts.get(cid, 0) + 1)
        self.compact_stats["enroute_active_measures"] += 1
        return Mission("measure", point, channel=cid,
                       meta={"kind": "compact_enroute_measure",
                             "scan_variant": "primary",
                             "detour_m": detour})

    def _coverage_branch_mission(self, ks, position):
        """Continue a bounded source-service excursion, or return to coverage.

        Every branch stores the anchor it left for.  A new source action is
        allowed only while its *extra path via that anchor* stays inside the
        remaining detour budget.  Thus real feedback can change the local
        action but cannot repeatedly postpone the finite certificate route.
        """
        state = self._compact_coverage_branch
        if state is None:
            return None
        if self._ring_finished(ks):
            self._compact_coverage_branch = None
            return None
        # ``_ring_scan`` removes an anchor when it is issued, before the
        # executor performs its measurements.  On the next decision that
        # scheduled return leg is therefore complete and can be popped.
        issued = state.get('return_issued')
        if issued is not None and issued not in self._coverage_remaining:
            state['return_issued'] = None
        returns = state.setdefault('return_indices', [state['anchor_index']])
        while returns and returns[0] not in self._coverage_remaining:
            returns.pop(0)
        if not returns:
            self._compact_coverage_branch = None
            return None
        anchor_index = returns[0]
        anchor = self._coverage_points[anchor_index]
        cid = state['cid']
        channel = ks[cid]

        def afford(target):
            extra = (math.dist(position, target) + math.dist(target, anchor)
                     - math.dist(position, anchor))
            return (state['extra_spent_m'] + extra
                    <= state['extra_limit_m'] + 1e-9), extra

        if (not state.get('service_done') and state['remaining'] > 0
                and channel.status == ChannelStatus.READY):
            target = self._clear_target(channel, position)
            allowed, extra = afford(target)
            if allowed:
                state['remaining'] -= 1
                state['extra_spent_m'] += extra
                self._compact_attempted.add(cid)
                self._compact_inflight = (cid, target)
                self.coverage_rollout_stats['branch_actions'] += 1
                post = self._post_clear_channels(ks, target, exclude=cid)
                meta = {'kind': 'compact_coverage_branch_clear',
                        'risky_probe': True, 'compact_ring': True,
                        'coverage_branch_anchor': anchor_index,
                        'post_clear_channels': []}
                if post is not None:
                    meta['post_clear_channels'] = post
                return Mission('clear', target, channel=cid, meta=meta)
        if (not state.get('service_done') and state['remaining'] > 0
                and channel.status == ChannelStatus.ACTIVE):
            for rank, target in enumerate(self._active_route_candidates(
                    channel, position)[:2]):
                allowed, extra = afford(target)
                if not allowed:
                    continue
                state['remaining'] -= 1
                state['extra_spent_m'] += extra
                self._compact_route_attempts[cid] = (
                    self._compact_route_attempts.get(cid, 0) + 1)
                self.coverage_rollout_stats['branch_actions'] += 1
                return Mission(
                    'measure', target, channel=cid,
                    meta={'kind': 'compact_coverage_branch_measure',
                          'scan_variant': 'primary',
                          'coverage_branch_rank': rank,
                          'coverage_branch_anchor': anchor_index})

        state['service_done'] = True
        # The first element is the reconnect anchor.  A local rebuilt segment
        # may carry a second one, for example source -> B -> A instead of the
        # normal A -> B.  Both scans are real and the certificate bookkeeping
        # is updated only when their missions are issued.
        state['return_issued'] = returns.pop(0)
        self.coverage_rollout_stats['forced_returns'] += 1
        return self._ring_scan(ks, anchor_index=state['return_issued'])

    def decide(self, ks, position, current_channel):
        from .stop_fusion import snapshot

        # A failed branch probe has one explicitly scheduled same-stop bearing
        # feedback in _compact_decide.  Only resume the branch afterwards.
        before = snapshot(self)
        base = self._compact_decide(ks, position, current_channel)
        after = snapshot(self)
        if (self.compact_coverage_rollout_budget > 0.0
                and self._compact_coverage_branch is None):
            from .coverage_rollout import choose
            base = choose(self, before, after, ks, position, current_channel,
                          base)
        if self.compact_tail_rollout_budget > 0.0:
            from .tail_rollout import choose
            return choose(self, before, ks, position, current_channel, base)
        if self.compact_fusion_budget <= 0.0:
            return base
        from .stop_fusion import choose
        return choose(self, ks, position, current_channel, base)

    def _compact_decide(self, ks, position, current_channel):
        pending = self._compact_service_pending
        self._compact_service_pending = None
        self._compact_service_current = (
            tuple(pending) if pending is not None and
            math.dist(position, pending) < 2.0 else None)
        # Clear successful in-flight bookkeeping without consulting truth.
        if (self._compact_inflight is not None
                and ks[self._compact_inflight[0]].status in (
                    ChannelStatus.CLEARED, ChannelStatus.CERTIFIED_ABSENT)):
            self._compact_inflight = None

        if self._compact_failed_measure is not None:
            cid, point = self._compact_failed_measure
            self._compact_failed_measure = None
            if ks[cid].status == ChannelStatus.ACTIVE:
                self.compact_stats["failed_probe_measures"] += 1
                return Mission("measure", point, channel=cid,
                               meta={"kind": "compact_probe_feedback",
                                     "scan_variant": "primary"})

        branch = self._coverage_branch_mission(ks, position)
        if branch is not None:
            return branch

        if not self._ring_finished(ks):
            if self.fallback.active_fallbacks():
                return self._fallback_route(ks, position, current_channel)
            if self._certificate_service_followup is not None:
                cid = self._certificate_service_followup
                self._certificate_service_followup = None
                if cid in ks.channels and ks[cid].status == ChannelStatus.READY:
                    target = self._clear_target(ks[cid], position)
                    return Mission(
                        "clear", target, channel=cid,
                        meta={"kind": "compact_service_certificate_clear",
                              "certificate_service": True})
            self._adapt_ring_density(ks)
            self._adapt_certificate_field(ks, position)
            self._adapt_center_warmup(ks)
            optical = self._coverage_optical_mission(ks, position,
                                                      current_channel)
            if optical is not None:
                return optical
            if (self.compact_service_certificate_rollout and
                    self._certificate_service_template is not None):
                service = self._service_template_mission(ks, position)
            elif self.compact_service_certificate_rollout:
                service = None
            else:
                service = self._certificate_service_mission(ks, position)
            if service is not None:
                return service
            if self.compact_joint_ring_route:
                include_services = (
                    self._coverage_index >= self._joint_ring_min_stops_now()
                    and (self.compact_joint_ring_max_known <= 0
                         or self._known_count(ks) <
                         self.compact_joint_ring_max_known))
                joint = self._joint_ring_mission(
                    ks, position, include_services=include_services)
                if joint is not None:
                    return joint
            if self.compact_service_certificate:
                anchors = [(-(index + 1), self._coverage_points[index], "anchor")
                           for index in sorted(self._coverage_remaining)]
                next_anchor = self._exact_open_order(anchors, position)[0]
                next_ring = next_anchor[1]
                next_anchor_index = -next_anchor[0] - 1
            else:
                next_anchor_index = self._coverage_index
                next_ring = self._coverage_points[next_anchor_index]
            probe = self._probe(
                ks, position, self.compact_enroute_clear_radius,
                "compact_enroute_probe", next_ring=next_ring,
                max_detour=self.compact_enroute_detour)
            if probe is not None:
                return probe
            measure = self._enroute_active_measure(ks, position, next_ring)
            if measure is not None:
                return measure
            return self._ring_scan(ks, anchor_index=next_anchor_index)

        # The cardinality proof ends the ring even if it was reached at the
        # first channel of a stop. Remaining work is now localisation/clear.
        if self._known_count(ks) >= C.MAX_SOURCES:
            self.compact_stats["early_stop"] = (
                self._coverage_index < len(self._coverage_points))

        # One MEC-centre trial per channel; failure is retained as a 20 m
        # exclusion by ConstrainedChannelState before the feedback measure.
        probe = self._probe(ks, position, self.compact_probe_radius,
                            "compact_post_ring_probe")
        if probe is not None:
            return probe
        local = self._local_finish_mission(ks, position)
        if local is not None:
            return local
        if self.compact_route_active and not self.fallback.active_fallbacks():
            # Preserve the exact small-region optical finish before asking for
            # another bearing leg.
            if self._maybe_enter_early_fallback(ks, position):
                return self._fallback_route(ks, position, current_channel)
            route = self._joint_open_route(ks, position)
            if route is not None:
                return route
        return super().decide(ks, position, current_channel)
