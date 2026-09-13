"""Learning-guided search scheduler.

The online policy is a tiny, transparent linear value model. Its input is
derived only from observable geometry/state; a later ``fit_model.py`` can fit
the same feature schema from independent run decision traces. The inherited
fallback and certificate branch remains the hard all-clear completion path.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from geometry import constants as C
from geometry.mec import mec
from geometry.polygon import contains_point
from policy import localization
from geometry.certificate import q3_certified, q4_lattice_points
from geometry.q4_sparse_mesh import q4_sparse25_points
from geometry.fallback_cover import disk_lattice_cover, order_greedy
from policy.scheduler import Mission, Scheduler
from state.channel_state import ChannelStatus
from tuned_fallback import TunedFallbackTracker
from lookahead import discovery_share
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


DEFAULT_MODEL = {
    "schema": "learned_search_v1",
    "features": ["gain_per_cost", "cluster", "radius_norm", "distance_norm",
                  "bearing_count", "unknown_pressure", "same_channel"],
    "weights": [1.00, 0.08, 0.20, -0.18, 0.12, 0.05, 0.04],
    "bias": 0.0,
    "source": "hand-initialized prior; fit_model.py replaces this after data collection"
}


class LearnedSearchScheduler(RollingCandidatePlanner, Scheduler):
    """Feature policy chooses the root action; search/certification stays exact."""

    Q4_ACTIVE_REPEAT_LIMIT = 3
    Q4_ACTIVE_REPEAT_LIMIT_MID = 4
    Q4_ACTIVE_REPEAT_LIMIT_HIGH = 0
    Q3_NO_SHRINK_LIMIT = 9
    Q4_NO_SHRINK_LIMIT = 8
    Q3_NO_SHRINK_LIMIT_HIGH = 20
    Q3_LIMIT_SWITCH_ACTIVE = 6
    Q3_LOW_DENSITY_MODEL_WEIGHTS = (
        1.0, 0.1, 0.0, -0.8, 0.40, 0.00, 0.00)
    Q3_HIGH_DENSITY_MODEL_WEIGHTS = (
        1.0, 1.2, 0.1, -3.0, 0.05, 0.03, 0.40)
    Q4_NO_SHRINK_LIMIT_HIGH = 14
    Q4_LIMIT_SWITCH_KNOWN = 12
    Q4_WARM_START_M = 50.0
    Q4_FORWARD_DISTANCES = (400.0, 700.0)
    # Six ring centers plus the origin cover Ω with the frozen 1000 m
    # no-signal disk certificate.  Keep the conservative 1200 m radius as
    # the default; a density-gated 1130 m variant is evaluated separately.
    Q3_COVERAGE_RADIUS = 1200.0
    # For dense Q3 scenes, the first origin scan provides a cheap observable
    # density signal.  The recommended entry enables this only for the
    # 16-source regime; the default remains the fixed certificate order so
    # equal-budget strategy comparisons stay unchanged.
    Q3_DYNAMIC_ORDER_THRESHOLD = 7
    Q3_DYNAMIC_ORDER_START = 2
    Q3_DYNAMIC_ORDER_DIRECTION = 1

    def __init__(self, *args, model_path=None, q3_dynamic_order=False,
                 q3_ring_order=None, q3_coverage_radius=None,
                 q3_adaptive_radius=False,
                 q3_adaptive_radius_high_threshold=9,
                 q3_adaptive_radius_mid_threshold=7,
                 q3_observation_adaptive=False,
                 q3_thirteen_point=False,
                 q3_adaptive_coverage=False,
                 q3_direct_center=False,
                 q3_direct_center_radius_m=None,
                 q3_direct_center_max_distance_m=None,
                 q3_direct_center_compete=False,
                 q3_center_value=False,
                 q3_risky_clear_radius=0.0,
                 q3_risky_clear_max_distance_m=None,
                 q3_work_first=False,
                 q3_work_first_max_mec_m=None,
                 q3_work_first_max_distance_m=None,
                 q3_work_first_min_spread_m=None,
                 q3_target_commit=False,
                 q3_target_max_steps=6,
                 avoid_remeasure=False, remeasure_epsilon_m=1.0,
                 remeasure_penalty=0.0,
                 q3_adaptive_ring_order=False,
                 q4_risky_clear_radius=0.0,
                 q4_active_first=False,
                 q4_preprobe_once=False,
                 q4_coverage_order="greedy",
                 q4_point_order=None,
                 q4_observed_order=False,
                 q4_observed_order_fraction=0.20,
                 q4_cross_angle_gain=False,
                 q4_joint_angle_gate_deg=0.0,
                 q4_joint_min_mec_m=0.0,
                 q4_joint_max_mec_m=0.0,
                 q4_joint_angle_rank=False,
                 q4_discovery_ring=False,
                 q4_discovery_threshold=6,
                 q4_discovery_ring_radius_m=870.0,
                 q4_discovery_ring_points=12,
                 fallback_order_mode="greedy",
                 q4_side_distances=None,
                 q4_active_repeat_limit_high=None,
                 q4_no_shrink_limit=None,
                 q4_no_shrink_limit_high=None,
                 q4_warm_start_m=None,
                 q4_forward_distances=None,
                 q4_no_signal_escape_distances=None,
                 q4_direct_center_radius_m=0.0,
                 q4_direct_center_max_no_signal=None,
                 joint_active_measure_limit=0,
                 joint_active_margin_m=0.0,
                 q4_joint_coverage_limit=0,
                 q4_joint_min_directions=0,
                 q4_joint_max_no_signal=None,
                 q4_joint_min_direction_fraction=0.0,
                 rolling_enabled=False, rolling_horizon=3,
                 rolling_coverage_period=3,
                 rolling_probe_radius_m=0.0,
                 rolling_probe_max_distance_m=None,
                 rolling_probe_remeasure=False,
                 rolling_inplace_shots=0,
                 rolling_joint_active_limit=1,
                 rolling_enroute_detour_m=0.0,
                 rolling_plan_cost=True,
                 rolling_compete_coverage=False,
                 rolling_lookahead=False,
                 rolling_lookahead_step_m=120.0,
                 q4_work_first=False,
                 q4_work_first_min_active=0,
                 q3_interleave=False,
                 q3_interleave_bias=1.0,
                 q3_scan_spacing_m=0.0,
                 joint_action=False,
                 joint_active_value_scale=1.0,
                 joint_discovery_value_s=200.0,
                 joint_continuation_weight=0.35,
                 active_scan_angle_gate_deg=0.0,
                 true_gain=False,
                 q3_perp_factor=0.0,
                 teacher_family=None,
                 teacher_score="cost",
                 teacher_observe=False,
                 teacher_dominated_offset=1e6,
                 teacher_value_scale=1.0,
                 teacher_value_ref_s=240.0,
                 q3_ring_translate_m=0.0,
                 q3_ring_translate_max_active=0,
                 q3_ring_translate_margin_m=0.0,
                 q3_ring_trim=False,
                 q3_ring_trim_min_keep=1,
                 q3_ring_seven_point=False,
                 q3_ring_seven_radius=997.3,
                 q3_order_tail_only=False,
                 q3_order_tail_margin_s=0.0,
                 measure_link=False,
                 order_plan=False,
                 order_exact_max=10,
                 order_plan_q4=False,
                 order_plan_margin_s=3.0,
                 order_live_budget=0,
                 order_net_gate=False,
                 order_joint=False,
                 order_joint_merge_m=250.0,
                 q4_pair=False,
                 q4_pair_baseline_m=300.0,
                 q4_pair_max_radius_m=900.0,
                 q4_pair_max_distance_m=1500.0,
                 q4_covtrim=False,
                 q4_covtrim_min_known=16,
                 ready_batch_min=1,
                 q4_discovery_nbv=False,
                 q4_discovery_nbv_step_m=90.0,
                 q3_discovery_nbv=False,
                 valued_scan_share=0.0,
                 probe_ladder_limit=1,
                 valued_scan_opportunistic=False,
                 q3_merged_switch_after_misses=0,
                 q3_merged_density_gate=0,
                 q3_merged_gate_after_points=3,
                 q3_scan_stop_after_misses=0,
                 rolling_replan_coverage=False,
                 ready_open_route=False,
                 early_fallback_max_points=0,
                 early_fallback_max_entry_m=None,
                 early_fallback_max_known=0,
                 early_fallback_suppress_failed_scan=False,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self._init_rolling(rolling_enabled, rolling_horizon,
                           rolling_coverage_period,
                           rolling_probe_radius_m,
                           rolling_probe_max_distance_m,
                           rolling_joint_active_limit, ready_open_route,
                           rolling_probe_remeasure,
                           inplace_shots=rolling_inplace_shots)
        self.rolling_replan_coverage = bool(rolling_replan_coverage)
        self.rolling_enroute_detour_m = max(
            0.0, float(rolling_enroute_detour_m or 0.0))
        # Price missions with the runner's own stop plan (real measure
        # sequence, branch-weighted clear cost) instead of the legacy
        # single-measurement estimate.
        self.rolling_plan_cost = bool(rolling_plan_cost)
        # Let the coverage stop compete on cost instead of pre-empting every
        # other action while UNKNOWN channels are numerous.  The certificate
        # deadline (coverage_period) still bounds how long it can wait.
        self.rolling_compete_coverage = bool(rolling_compete_coverage)
        self.rolling_lookahead = bool(rolling_lookahead)
        # Q4 merged route: work live channels before forcing a coverage stop.
        self.q4_work_first = bool(q4_work_first)
        # Conditional release of the Q4 coverage pre-emption (0 = never).
        self.q4_work_first_min_active = max(
            0, int(q4_work_first_min_active or 0))
        # Proximity-interleaved Q3 route: certificate points and live channels
        # are visited in one travel-ordered pass instead of ring-then-sweep.
        self.q3_interleave = bool(q3_interleave)
        self.q3_interleave_bias = max(0.5, float(q3_interleave_bias or 1.0))
        # Joint (stop, channel set) action: a stop at least this far from the
        # previous discovery survey carries the full scan set; nearer stops
        # carry only the ACTIVE bearings that can still cut a region.
        self.q3_scan_spacing_m = max(0.0, float(q3_scan_spacing_m or 0.0))
        self._last_full_scan_position = None
        # Joint (stop, scan set) comparison: every scan variant of the chosen
        # stop is priced with the runner's plan and scored with an explicit
        # continuation term plus an observable value term.
        self._last_joint_rows = []
        self.joint_action = bool(joint_action)
        self.joint_active_value_scale = float(joint_active_value_scale or 1.0)
        self.joint_discovery_value_s = float(joint_discovery_value_s or 0.0)
        self.joint_continuation_weight = float(joint_continuation_weight
                                               or 0.0)
        # Drop opportunistic ACTIVE re-measurements whose bearing ray is already
        # covered (crossing angle below this threshold).
        self.active_scan_angle_gate_deg = max(
            0.0, min(90.0, float(active_scan_angle_gate_deg or 0.0)))
        # Score Q3 candidates with the real worst-case MEC contraction instead
        # of a proxy that is constant across a channel's candidate points.
        self.true_gain = bool(true_gain)
        # Add a perpendicular-baseline candidate for Q3 directed channels
        # (offset = factor x current MEC radius); 0 keeps the historical set.
        self.q3_perp_factor = max(0.0, float(q3_perp_factor or 0.0))
        # ------------------------------------------------------------------
        # Offline-teacher candidate family.  DEFAULT OFF: the production
        # configuration never sets ``teacher_family``, so this block is inert
        # unless an A/B probe asks for it.  The offline teacher's winning
        # actions (ROUND1_MERGED_ROUTING.md sections 20/26) are not in the
        # production candidate set: they are perpendicular-baseline stops and
        # non-default scan sets.  The family is injected into the ordinary
        # measure pool, priced by the executor's own ``plan_stop``, and an
        # injected member replaces the production pick only on a strictly
        # higher score (ties keep production).
        #   teacher_family: None | "perp" | "variant" | "full"
        #   teacher_score : "cost" (production scoring only, plan_stop priced)
        #                   "value" (adds the scan-set value term)
        #                   "inert" (score + dominating offset, never wins)
        #   teacher_observe: extra trace payload only; it never changes a
        #                    decision, so observe on/off runs must be identical.
        # ------------------------------------------------------------------
        self.teacher_family = (str(teacher_family).strip().lower()
                               if teacher_family else None)
        if self.teacher_family not in (None, "perp", "variant", "full"):
            raise ValueError("unknown teacher_family %r" % (teacher_family,))
        self.teacher_score = str(teacher_score or "cost").strip().lower()
        if self.teacher_score not in ("cost", "value", "inert"):
            raise ValueError("unknown teacher_score %r" % (teacher_score,))
        self.teacher_observe = bool(teacher_observe)
        self.teacher_dominated_offset = max(
            0.0, float(teacher_dominated_offset or 0.0))
        self.teacher_value_scale = float(teacher_value_scale or 0.0)
        self.teacher_value_ref_s = max(
            1.0, float(teacher_value_ref_s or 240.0))
        # ------------------------------------------------------------------
        # Q3 finite-certificate ring: two independent, DEFAULT-OFF switches.
        #
        # ``q3_ring_translate_m`` lets a ring anchor move up to this many
        # metres toward a channel that still needs work (a READY clear target
        # or an ACTIVE source's MEC centre), so a certificate stop can double
        # as a useful stop.  Every translated set is re-checked with the exact
        # ``q3_certified`` decider before it is used, and a translation that
        # would break coverage is reverted (the ring is never used with a
        # missing proof).
        #
        # ``measure_link`` chains the measurement order across stops: the last
        # channel measured at one ring stop is placed first at the next one,
        # which removes one 1 s channel switch per linked transition.
        #
        # Both are Q3-only; the Q4 path never reads them.
        # ------------------------------------------------------------------
        self.q3_ring_translate_m = max(
            0.0, float(q3_ring_translate_m or 0.0))
        # Observable density gate for the translation: move anchors only while
        # the run still has at most this many ACTIVE channels (0 = no gate).
        # The count comes from the knowledge state, never from N, the scenario
        # or any truth value.
        self.q3_ring_translate_max_active = max(
            0, int(q3_ring_translate_max_active or 0))
        # Certificate safety margin: an accepted shift must keep the worst
        # sampled Omega-boundary distance at least this many metres below
        # R_EFF_MIN.  The independent verifier samples 7200 boundary points,
        # so a shifted set that only *just* passes can be at the edge of its
        # validity; 0 keeps the historical behaviour (exact decider only).
        self.q3_ring_translate_margin_m = max(
            0.0, float(q3_ring_translate_margin_m or 0.0))
        # ------------------------------------------------------------------
        # ``q3_ring_trim`` (DEFAULT OFF, Q3 only): skip *redundant* ring
        # anchors.  Before walking to a still-unvisited anchor the scheduler
        # asks the exact decider whether every channel that still needs an
        # absence certificate would stay certifiable without that anchor:
        #
        #     promise_ok(r) := for every UNKNOWN channel c
        #                      q3_certified(W_c u (U \ {r})) is true
        #
        # where ``W_c`` are the no-signal witnesses already recorded for that
        # channel and ``U`` the still-unvisited anchors.  A skipped anchor is
        # never visited and never measured, so the only saving is travel; the
        # coverage proof is re-validated with the *exact* decider before the
        # skip is committed (sampled margins are reported, never used to
        # decide).  The last covering anchor is never dropped and an uncertain
        # case keeps the anchor.
        # ------------------------------------------------------------------
        self.q3_ring_trim = bool(q3_ring_trim)
        self.q3_ring_trim_min_keep = max(1, int(q3_ring_trim_min_keep or 1))
        # ------------------------------------------------------------------
        # ``q3_ring_seven_point`` (DEFAULT OFF, Q3 only): replace the
        # production cover "origin + 6 anchors @r=1200" with a pure
        # **7-anchor ring at r = 997.3** (no centre stop is needed: the t=0
        # origin scan already leaves a no_signal witness there).  The seven
        # anchors are equally spaced (360/7 deg); radius 997.3 is the smallest
        # value whose boundary gap (999.9384 m) still passes the *exact*
        # ``q3_certified`` decider with a positive margin, and it shortens the
        # open certificate path from 7 200 m to 6 189.85 m (Held-Karp).
        # Orthogonal to the order / translation / trim switches: the layout is
        # selected here, the order is still chosen by ``q3_ring_order`` /
        # ``_adaptive_q3_ring_order`` (generalised to the ring size) and the
        # translation/trim logic keeps operating on ``_coverage_points``.
        # ------------------------------------------------------------------
        self.q3_ring_seven_point = bool(q3_ring_seven_point)
        self.q3_ring_seven_count = 7
        self.q3_ring_seven_radius = max(200.0, float(q3_ring_seven_radius
                                                     or 997.3))
        # ------------------------------------------------------------------
        # ``q3_order_tail_only`` (DEFAULT OFF, Q3 only): enable the global
        # stop-order planner **only after the certificate phase is over**, and
        # plan over **live stops only** (one best measurement stop per ACTIVE
        # channel + READY clear points).  Certificate anchors are never tasks
        # here, so the order phase cannot interleave with the certificate phase
        # -- the failure mode of every earlier order variant.
        # Activation reads observables only: all planned ring anchors consumed,
        # or no channel still needs a certificate.
        # ------------------------------------------------------------------
        self.q3_order_tail_only = bool(q3_order_tail_only)
        self.q3_order_tail_margin_s = max(0.0, float(
            q3_order_tail_margin_s or 0.0))
        self._q3_tail_activated = False
        self.q3_tail_audit = {
            "activated": False, "activated_step": None,
            "activated_virtual_time": None, "confirmed_at_activation": None,
            "tasks_at_activation": None, "certificate_tasks": 0,
            "decisions": 0, "switched": 0, "refused": 0,
        }
        self._q3_trim_skipped = set()
        self.q3_ring_trim_audit = {
            "calls": 0, "checks": 0, "skipped": 0, "rejected": 0,
            "violations": 0, "skipped_points": [], "worst_margin_m": None,
        }
        self.measure_link = bool(measure_link)
        # ------------------------------------------------------------------
        # Global stop-order planning.  DEFAULT OFF.
        #
        # Instead of picking the next stop with a local rule, plan an open path
        # from the current position through every *executable, unfinished* stop
        # task (pending certificate points and one measurement stop per live
        # ACTIVE channel) and execute the first stop of that plan.  The plan is
        # recomputed at every decision, so it re-plans after every observation.
        #
        # Tasks are priced with the executor's own ``plan_stop`` (travel plus
        # the stop's measurement sequence), so the plan costs what the executor
        # will charge.  With ``n <= order_exact_max`` tasks the open path is
        # solved exactly (Held-Karp); above it a nearest-neighbour seed is
        # improved by 2-opt and or-opt with O(1) move deltas.
        #
        # Only currently-executable tasks are admitted, which is what keeps the
        # precedence rules (a clear needs its own localisation first) intact.
        # ------------------------------------------------------------------
        self.order_plan = bool(order_plan)
        self.order_exact_max = max(2, int(order_exact_max or 10))
        # Q4 is a cardinally capped case: the certificate mesh is often skipped
        # before the cap fires, so reordering it is only noise (measured
        # +2.1% move / +6.3 s-per-source on 12 merged seeds).  It therefore has
        # its own switch, default OFF, so that ``order_plan`` is a Q3-only
        # change and Q4 stays bit-identical to production.
        self.order_plan_q4 = bool(order_plan_q4)
        # Pre-declared accept-if-better margin (seconds of planned whole-path
        # cost, the *same* plan_stop pricing for both orders): the global order
        # replaces the production-priority order only if it wins by at least
        # this margin.  0 disables the gate (always switch; the historical
        # behaviour of the first revision).
        self.order_plan_margin_s = max(0.0, float(order_plan_margin_s or 0.0))
        # ------------------------------------------------------------------
        # t23: four-ledger net gate + live-stop budget.
        #
        # t15's gate compared *orders over the same task set*, and an optimal
        # order over a richer task set is always cheaper, so it never fired
        # (measured: 51/51 identical).  The failure mode is not the order, it
        # is that the planner carries **more measurement stops** than
        # production would (t11: Q3/16 -493 s move vs +393 s measure + 74 s
        # switch).  ``order_live_budget`` caps how many live/ACTIVE measurement
        # stops the plan may carry (0 = uncapped, the t11 behaviour), which
        # makes the two ledgers price the same work; the gate then only
        # intervenes when the plan's ``travel + service`` beats the
        # production-priority order by ``order_plan_margin_s`` seconds or more.
        # ------------------------------------------------------------------
        self.order_live_budget = max(0, int(order_live_budget or 0))
        # ``order_net_gate`` is the t23 switch name: when on, the plan is only
        # allowed through if its four-ledger path cost beats the
        # production-priority reference by ``order_plan_margin_s`` (>= 5 s in
        # the pre-registered configuration).
        self.order_net_gate = bool(order_net_gate)
        self._order_gate_stats = {"evaluated": 0, "blocked": 0,
                                  "blocked_loss_s": 0.0, "switched": 0,
                                  "by_n": {}}
        # ------------------------------------------------------------------
        # Joint (stop x demand-set) planning.  DEFAULT OFF.
        #
        # t11 showed that reordering a *fixed* task set trades movement for
        # extra measurements (Q3/16: -493 s move vs +393 s measure + 74 s
        # switch).  This switches the task unit from "one measurement stop per
        # ACTIVE channel" to "(stop, demand set)": every stop carries the
        # demands it can serve at once - its own measurement plus, via the
        # runner's existing ``joint_channels`` mechanism, the ACTIVE channels
        # whose *current* best measurement point lies within
        # ``order_joint_merge_m`` of the stop.  One stop then closes several
        # demands instead of each demand paying its own leg and its own
        # channel switches.
        #
        # The objective stays the four-ledger sum (travel + measurement +
        # switch + clear), priced with the executor's own ``plan_stop``, and
        # only demands that are executable now are admitted, so the precedence
        # rules are unchanged.  Q4 is deliberately out of scope here (t17).
        # ------------------------------------------------------------------
        self.order_joint = bool(order_joint)
        self.order_joint_merge_m = max(0.0, float(order_joint_merge_m or 0.0))
        # ------------------------------------------------------------------
        # Q4/16 structural switches.  BOTH DEFAULT OFF.
        #
        # (a) q4_pair - pairing re-arrangement template.  Instead of chasing a
        #     channel with scattered micro-jumps, measure it twice in a row on
        #     purpose (a short crossing baseline around its current MEC) and
        #     then clear it in place.  The template is a small state machine on
        #     the scheduler side; every stage is an ordinary measure/clear
        #     mission, so the executor and the verifier see nothing new.
        # (b) q4_covtrim - probe-coverage oriented trimming.  While fewer than
        #     ``q4_covtrim_min_known`` channels are confirmed, a Q4 run is a
        #     "find MAX_SOURCES sources" search, not an absence proof, so the
        #     finite certificate tour is not forced; the fallback cover and the
        #     cardinality cap still end every case, and no completion criterion
        #     is relaxed.
        # ------------------------------------------------------------------
        self.q4_pair = bool(q4_pair)
        self.q4_pair_baseline_m = max(50.0, float(q4_pair_baseline_m or 300.0))
        self.q4_pair_max_radius_m = max(
            0.0, float(q4_pair_max_radius_m or 0.0))
        self.q4_pair_max_distance_m = max(
            0.0, float(q4_pair_max_distance_m or 0.0))
        self._q4_pair_plan = None
        self.q4_covtrim = bool(q4_covtrim)
        self.q4_covtrim_min_known = max(0, int(q4_covtrim_min_known or 16))
        self._q3_ring_trace = None
        self.rolling_lookahead_step_m = max(
            40.0, float(rolling_lookahead_step_m or 120.0))
        self.ready_batch_min = max(1, int(ready_batch_min or 1))
        self.q4_discovery_nbv = bool(q4_discovery_nbv)
        self.q3_discovery_nbv = bool(q3_discovery_nbv)
        # Opportunistic stops skip UNKNOWN measurements whose discovery share
        # falls below this value; coverage/certificate scans are unaffected.
        self.valued_scan_share = max(0.0, float(valued_scan_share or 0.0))
        # Failed clears are exclusions the convex region cannot hold; the
        # ladder uses them to place the next probe and to recognise a
        # guaranteed clear.  One attempt reproduces the historical behaviour.
        self.probe_ladder_limit = max(1, int(probe_ladder_limit or 1))
        self._probe_failures = {}
        # Apply the discovery-value share to *opportunistic* stops only;
        # certificate scans keep the complete channel list.
        self.valued_scan_opportunistic = bool(valued_scan_opportunistic)
        # Merged discovery/clear route is abandoned after this many decisions
        # without a newly confirmed channel: when sources stop appearing, the
        # finite certificate ring is the cheaper way to close the case.
        self.q3_merged_switch_after_misses = max(
            0, int(q3_merged_switch_after_misses or 0))
        self._q3_known_prev = 0
        self._q3_known_at_clear = 0
        self._q3_cleared_prev = 0
        self._q3_misses = 0
        self._q3_merged_disabled = False
        self._q3_scan_disabled = False
        # Stop paying for opportunistic UNKNOWN scans at merged-route stops
        # once clearing sources stops exposing new ones.
        self.q3_scan_stop_after_misses = max(
            0, int(q3_scan_stop_after_misses or 0))
        # Observable density gate for the merged route: after this many
        # certificate stops, a confirmed-channel count at or above the
        # threshold means the case is dense enough that clearing known sources
        # keeps exposing new ones, so the merged route replaces the rest of
        # the ring.  Below it the ring stays the discovery vehicle.  Both
        # quantities are counted from observations only.
        self.q3_merged_density_gate = max(0, int(q3_merged_density_gate or 0))
        self.q3_merged_gate_after_points = max(
            0, int(q3_merged_gate_after_points or 0))
        self._q3_merged_enabled = False
        self.q4_discovery_nbv_step_m = max(30.0,
                                           float(q4_discovery_nbv_step_m or 90.0))
        self._nbv_samples = None
        self._nbv_masks = None
        self._nbv_masks_key = None
        self._decision_position = (0.0, 0.0)
        self.q3_dynamic_order = bool(q3_dynamic_order)
        self.q3_ring_order = (tuple(int(v) for v in q3_ring_order)
                              if q3_ring_order is not None else None)
        # The 1200 m seven-point ring is the exact Q3 absence certificate.
        # A smaller radius is a discovery-only optimization: the shared
        # runner can close a known 16-source case by cardinality before an
        # incomplete discovery ring is used as an absence claim.
        self.q3_coverage_radius = (
            self.Q3_COVERAGE_RADIUS if q3_coverage_radius is None else
            float(q3_coverage_radius))
        self.q3_adaptive_radius = bool(q3_adaptive_radius)
        self.q3_adaptive_radius_high_threshold = max(
            0, int(q3_adaptive_radius_high_threshold))
        self.q3_adaptive_radius_mid_threshold = max(
            0, int(q3_adaptive_radius_mid_threshold))
        self.q3_observation_adaptive = bool(q3_observation_adaptive)
        self.q3_thirteen_point = bool(q3_thirteen_point)
        self.q3_adaptive_coverage = bool(q3_adaptive_coverage)
        self.q3_direct_center = bool(q3_direct_center)
        self.q3_direct_center_radius_m = (
            None if q3_direct_center_radius_m is None else
            max(0.0, float(q3_direct_center_radius_m)))
        self.q3_direct_center_max_distance_m = (
            None if q3_direct_center_max_distance_m is None else
            max(0.0, float(q3_direct_center_max_distance_m)))
        self.q3_direct_center_compete = bool(q3_direct_center_compete)
        self.q3_center_value = bool(q3_center_value)
        # Optional observable-only ordering: after the origin scan, use the
        # bearings already seen at the origin to choose which adjacent ring
        # direction to visit first.  It reorders the same six certificate
        # points and never changes the finite cover or state transitions.
        self.q3_adaptive_ring_order = bool(q3_adaptive_ring_order)
        self._q3_adaptive_coverage_locked = False
        # Optional Q3-only probe: once the observable MEC is small enough,
        # try one optical clear at its centre before spending another bearing
        # measurement.  A failed probe is cheap (3 s) and is never repeated;
        # the inherited finite completion path remains unchanged.
        self.q3_risky_clear_radius = float(q3_risky_clear_radius or 0.0)
        self.q3_risky_clear_max_distance_m = (
            None if q3_risky_clear_max_distance_m is None else
            float(q3_risky_clear_max_distance_m))
        # Work-first discovery: run live-channel localization before advancing
        # the fixed ring, so the ring stops being the only discovery vehicle.
        self.q3_work_first = bool(q3_work_first)
        self.q3_work_first_max_mec_m = (
            None if q3_work_first_max_mec_m is None else
            float(q3_work_first_max_mec_m))
        self.q3_work_first_max_distance_m = (
            None if q3_work_first_max_distance_m is None else
            float(q3_work_first_max_distance_m))
        self.q3_work_first_min_spread_m = (
            None if q3_work_first_min_spread_m is None else
            float(q3_work_first_min_spread_m))
        self._q3_scan_points = []
        self.q3_target_commit = bool(q3_target_commit)
        self.q3_target_max_steps = max(1, int(q3_target_max_steps or 6))
        self._q3_target = None
        self._q3_target_steps = 0
        self.avoid_remeasure = bool(avoid_remeasure)
        self.remeasure_epsilon_m = float(remeasure_epsilon_m)
        self.remeasure_penalty = float(remeasure_penalty)
        self._q3_risky_clear_attempted = set()
        # Optional Q4 probe is deliberately disabled by default.  The
        # recommended selector enables it only for scenario labels where the
        # equal-budget holdout showed a repeatable gain.
        self.q4_risky_clear_radius = float(q4_risky_clear_radius or 0.0)
        self._q4_risky_clear_attempted = set()
        # Q4 can exploit an already observed directional source before
        # spending the long finite certificate tour.  The certificate remains
        # the completion fallback; this only changes the order of legal
        # measurements and is disabled unless the production selector opts in.
        self.q4_active_first = bool(q4_active_first)
        self.q4_preprobe_once = bool(q4_preprobe_once)
        self._q4_preprobe_done = set()
        self.q4_coverage_order = str(q4_coverage_order or "greedy")
        self.q4_point_order = (tuple(int(v) for v in q4_point_order)
                               if q4_point_order is not None else None)
        self.q4_observed_order = bool(q4_observed_order)
        self.q4_observed_order_fraction = max(
            0.0, min(1.0, float(q4_observed_order_fraction or 0.0)))
        # Observation-only bearing quality gate.  A measurement whose bearing
        # ray is nearly parallel to the last received bearing re-measures the
        # same wedge and adds almost no location information; a measurement
        # taken inside the feasible region splits it instead.  The switch only
        # rescales a candidate's gain proxy.
        self.q4_cross_angle_gain = bool(q4_cross_angle_gain)
        self.q4_joint_angle_gate_deg = max(
            0.0, min(90.0, float(q4_joint_angle_gate_deg or 0.0)))
        # A certificate stop can donate an additional bearing to an ACTIVE
        # channel. Once its feasible disk is already small, that extra 5 s
        # often does not repay a later localization leg. Zero preserves the
        # historical unrestricted path.
        self.q4_joint_min_mec_m = max(
            0.0, float(q4_joint_min_mec_m or 0.0))
        self.q4_joint_max_mec_m = max(0.0, float(q4_joint_max_mec_m or 0.0))
        self.q4_joint_angle_rank = bool(q4_joint_angle_rank)
        self.q4_discovery_ring = bool(q4_discovery_ring)
        self.q4_discovery_threshold = max(0, int(q4_discovery_threshold or 0))
        self.q4_discovery_ring_radius_m = max(
            1.0, float(q4_discovery_ring_radius_m or 870.0))
        self.q4_discovery_ring_points = max(
            3, int(q4_discovery_ring_points or 12))
        self._q4_discovery_active = False
        self._q4_discovery_switched = False
        self._q4_observed_order_locked = not self.q4_observed_order
        self.fallback_order_mode = str(fallback_order_mode or "greedy")
        # Optional exact short-cover action.  When an ACTIVE feasible region
        # has already shrunk enough to need only a handful of guaranteed
        # radius-20 clear disks, finish it directly instead of buying another
        # bearing and a separate return trip.  Zero keeps production unchanged.
        self.early_fallback_max_points = max(
            0, int(early_fallback_max_points or 0))
        self.early_fallback_max_entry_m = (
            None if early_fallback_max_entry_m is None else
            max(0.0, float(early_fallback_max_entry_m)))
        self.early_fallback_max_known = max(
            0, int(early_fallback_max_known or 0))
        self.early_fallback_suppress_failed_scan = bool(
            early_fallback_suppress_failed_scan)
        self._early_fallback_channels = set()
        self.Q4_SIDE_DISTANCES = tuple(float(x) for x in
                                       (q4_side_distances or ()))
        if q4_active_repeat_limit_high is not None:
            self.Q4_ACTIVE_REPEAT_LIMIT_HIGH = int(q4_active_repeat_limit_high)
        if q4_no_shrink_limit is not None:
            self.Q4_NO_SHRINK_LIMIT = int(q4_no_shrink_limit)
        if q4_no_shrink_limit_high is not None:
            self.Q4_NO_SHRINK_LIMIT_HIGH = int(q4_no_shrink_limit_high)
        if q4_warm_start_m is not None:
            self.Q4_WARM_START_M = float(q4_warm_start_m)
        if q4_forward_distances is not None:
            self.Q4_FORWARD_DISTANCES = tuple(
                float(x) for x in q4_forward_distances)
        self.Q4_NO_SIGNAL_ESCAPE_DISTANCES = tuple(
            float(x) for x in (q4_no_signal_escape_distances or ()))
        self.q4_direct_center_radius_m = max(
            0.0, float(q4_direct_center_radius_m or 0.0))
        self.q4_direct_center_max_no_signal = (
            None if q4_direct_center_max_no_signal is None else
            max(0, int(q4_direct_center_max_no_signal)))
        self.joint_active_measure_limit = max(0, int(
            joint_active_measure_limit or 0))
        self.joint_active_margin_m = float(joint_active_margin_m or 0.0)
        self.q4_joint_coverage_limit = max(0, int(
            q4_joint_coverage_limit or 0))
        self._q4_joint_points_used = 0
        self._joint_route_position = (0.0, 0.0)
        self.q4_joint_min_directions = max(0, int(
            q4_joint_min_directions or 0))
        self.q4_joint_max_no_signal = (
            None if q4_joint_max_no_signal is None else
            max(0, int(q4_joint_max_no_signal)))
        self.q4_joint_min_direction_fraction = max(0.0, min(1.0, float(
            q4_joint_min_direction_fraction or 0.0)))
        self._q4_joint_gate_locked = False
        self._q4_joint_route_disabled = False
        self._explicit_model_path = model_path is not None
        self.fallback = TunedFallbackTracker(
            self.Q3_NO_SHRINK_LIMIT if self.mode == "Q3"
            else self.Q4_NO_SHRINK_LIMIT,
            order_mode=self.fallback_order_mode)
        self.model_path = (Path(model_path) if model_path else
                           Path(__file__).with_name(
                               "model_q4.json" if self.mode == "Q4"
                               else "model_q3.json"))
        self.model = dict(DEFAULT_MODEL)
        if self.model_path.exists():
            loaded = json.loads(self.model_path.read_text(encoding="utf-8"))
            if loaded.get("schema") != DEFAULT_MODEL["schema"]:
                raise ValueError("unsupported learned model schema")
            if len(loaded.get("weights", [])) != len(DEFAULT_MODEL["features"]):
                raise ValueError("learned model feature count mismatch")
            self.model.update(loaded)
        self._coverage_index = 0
        self._coverage_points = []
        self._coverage_pending_point = None
        self._coverage_pending_active = None
        self._q3_dynamic_order_locked = not (
            self.mode == "Q3" and self.q3_dynamic_order)
        self._q3_adaptive_radius_locked = not (
            self.mode == "Q3" and self.q3_adaptive_radius)
        self._q4_repeat_limit_locked = None
        self._q3_limit_locked = None
        self._q4_known_channels = 0
        self._q3_known_channels = 0

    def observed_active_scan_margin(self, ks):
        """Return a Q3 scan margin inferred from observed channel density."""
        if self.mode != "Q3" or not self.q3_observation_adaptive:
            return None
        known = (len(ks.by_status(ChannelStatus.ACTIVE)) +
                 len(ks.by_status(ChannelStatus.READY)) +
                 len(ks.by_status(ChannelStatus.CLEARED)) )
        return 60.0 if known >= self.Q3_DYNAMIC_ORDER_THRESHOLD else 175.0

    def _observed_q3_risky_radius(self, ks):
        if not self.q3_observation_adaptive:
            return self.q3_risky_clear_radius
        known = (len(ks.by_status(ChannelStatus.ACTIVE)) +
                 len(ks.by_status(ChannelStatus.READY)) +
                 len(ks.by_status(ChannelStatus.CLEARED)) )
        return 40.0 if known >= self.Q3_DYNAMIC_ORDER_THRESHOLD else 75.0

    def _q3_ring_layout(self, radius, count):
        """Ring anchor points for the active Q3 layout (origin excluded).

        Production is ``origin + 6 x r = 1200``.  With ``q3_ring_seven_point``
        the ring becomes seven equally spaced anchors at ``q3_ring_seven_radius``
        (the origin stays the index-0 stop of the same list, and is visited by
        the t=0 scan, so it is not an extra stop).
        """
        if self.q3_ring_seven_point:
            return [(self.q3_ring_seven_radius *
                     math.cos(2.0 * math.pi * k / self.q3_ring_seven_count),
                     self.q3_ring_seven_radius *
                     math.sin(2.0 * math.pi * k / self.q3_ring_seven_count))
                    for k in range(self.q3_ring_seven_count)]
        return [(radius * math.cos(2.0 * math.pi * k / count),
                 radius * math.sin(2.0 * math.pi * k / count))
                for k in range(count)]

    @staticmethod
    def _adaptive_q3_ring_order(ks, count=6):
        """Pick an adjacent ring traversal from origin bearings.

        Every candidate is a rotation of the clockwise or counter-clockwise
        six-point ring, so all candidates have identical certificate coverage
        and the same shortest ring travel.  The observable bearings only
        decide which likely source directions are visited earlier.  A small
        angular penalty makes ties deterministic while keeping the objective
        insensitive to the exact one-degree bearing noise.
        """
        bearings = []
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            dirs = [obs for obs in ch.observations
                    if obs["result"] == "direction"
                    and math.dist(obs["position"], (0.0, 0.0)) <= 1.0]
            if dirs:
                bearings.append(float(dirs[-1]["bearing"]) % 360.0)
        if not bearings:
            return None
        ring_angles = [360.0 * k / float(count) for k in range(count)]

        def angular_gap(a, b):
            d = abs((a - b) % 360.0)
            return min(d, 360.0 - d)

        candidates = []
        for direction in (1, -1):
            for start in range(6):
                order = tuple((start + direction * j) % 6
                              for j in range(6))
                rank_cost = 0.0
                angle_cost = 0.0
                for bearing in bearings:
                    nearest = min(
                        range(6),
                        key=lambda idx: angular_gap(
                            bearing, ring_angles[order[idx]]))
                    rank_cost += nearest
                    angle_cost += angular_gap(
                        bearing, ring_angles[order[nearest]]) / 360.0
                # Earlier visits dominate; angular mismatch is only a tie
                # stabilizer.  The tuple makes the choice reproducible.
                candidates.append(((rank_cost, angle_cost, order), order))
        return min(candidates, key=lambda item: item[0])[1]

    def _coverage_scan_available(self, ks):
        """Whether a finite coverage stop is still pending (no side effects)."""
        if self.mode == "Q4" and self.q4_joint_coverage_limit > 0:
            self._ensure_q4_joint_points()
        return self._coverage_index < len(self._coverage_points)

    # ------------------------------------------------------------------
    # Q4 discovery next-best-view
    # ------------------------------------------------------------------

    def _nbv_grid(self):
        """Deterministic sample grid over Ω, used only for scoring."""
        if self._nbv_samples is None:
            step = self.q4_discovery_nbv_step_m
            samples = []
            y = -C.OMEGA_RADIUS
            while y <= C.OMEGA_RADIUS + 1e-9:
                x = -C.OMEGA_RADIUS
                while x <= C.OMEGA_RADIUS + 1e-9:
                    if x * x + y * y <= C.OMEGA_RADIUS ** 2:
                        samples.append((x, y))
                    x += step
                y += step
            self._nbv_samples = samples
        return self._nbv_samples

    def _nbv_point_masks(self, points):
        """For each certificate point: bitmask of grid samples it can cover.

        A stop can return a signal from an omnidirectional source anywhere
        within the guaranteed reception radius, so the mask is the set of grid
        samples inside that radius.  The certificate points are fixed, so the
        table is computed once per run.
        """
        key = tuple(points)
        if self._nbv_masks_key == key:
            return self._nbv_masks
        samples = self._nbv_grid()
        radius = C.R_EFF_MIN
        masks = []
        for px, py in points:
            mask = 0
            for index, (sx, sy) in enumerate(samples):
                dx, dy = sx - px, sy - py
                if dx * dx + dy * dy <= radius * radius:
                    mask |= (1 << index)
            masks.append(mask)
        self._nbv_masks_key = key
        self._nbv_masks = masks
        return masks

    def _q4_discovery_nbv(self, ks, position, remaining_indices):
        """Rank remaining certificate points by expected new-source discovery.

        For an omnidirectional source, a no-signal witness at ``w`` excludes
        ``B(w, 1000)``; the region where channel ``c`` can still hide is
        therefore the set of grid samples not covered by any of its witnesses.
        A stop is valuable in proportion to the share of that hiding region it
        can see, so the score is the summed *fraction* of each undiscovered
        channel's region made visible, divided by travel plus the stop's own
        measurement cost.

        Q3 sources are omnidirectional, so the region is exact.  For Q4 the
        same region is a superset (a directional source can also hide on the
        blind side of every witness), so the ranking is a discovery heuristic
        and never a certificate: every certificate point is still visited
        unless the cardinality cap ends the search.
        """
        points = self._coverage_points
        masks = self._nbv_point_masks(points)
        samples = self._nbv_grid()
        radius = C.R_EFF_MIN
        hidden = []
        unknown = ks.by_status(ChannelStatus.UNKNOWN)
        if not unknown:
            return None
        for channel in unknown:
            witnesses = list(channel.certificate_region)
            reachable = 0
            for index, (sx, sy) in enumerate(samples):
                excluded = False
                for wx, wy in witnesses:
                    dx, dy = sx - wx, sy - wy
                    if dx * dx + dy * dy <= radius * radius:
                        excluded = True
                        break
                if not excluded:
                    reachable |= (1 << index)
            size = bin(reachable).count("1")
            if size:
                hidden.append((reachable, float(size)))
        if not hidden:
            return None
        scored = []
        for point_index in remaining_indices:
            mask = masks[point_index]
            if mask == 0:
                continue
            share = 0.0
            for reachable, size in hidden:
                covered = bin(reachable & mask).count("1")
                if covered:
                    share += covered / size
            if share <= 0.0:
                continue
            travel = math.dist(position, points[point_index])
            cost = travel / C.MOVE_SPEED + C.MEASURE_TIME
            scored.append((-(share / max(cost, 1e-9)), travel, point_index))
        if not scored:
            return None
        scored.sort()
        return scored[0][2]

    def _reorder_q4_discovery(self, ks, position):
        """Put the most informative remaining certificate point first."""
        if not (self.q4_discovery_nbv or self.q3_discovery_nbv):
            return
        if self.mode == "Q3" and not self.q3_discovery_nbv:
            return
        if self.mode == "Q4" and not self.q4_discovery_nbv:
            return
        remaining = list(range(self._coverage_index,
                               len(self._coverage_points)))
        if len(remaining) < 2:
            return
        best = self._q4_discovery_nbv(ks, position, remaining)
        if best is None or best == self._coverage_index:
            return
        pending = self._coverage_points[self._coverage_index:]
        chosen = self._coverage_points[best]
        rest = [p for index, p in
                zip(range(self._coverage_index, len(self._coverage_points)),
                    pending) if index != best]
        self._coverage_points = (self._coverage_points[:self._coverage_index]
                                 + [chosen] + rest)

    def _coverage_scan(self, ks):
        if self.mode == "Q4" and self.q4_joint_coverage_limit > 0:
            mission = self._q4_joint_coverage_scan(ks)
        else:
            mission = self._standard_coverage_scan(ks)
        if mission is not None and mission.kind == "scan":
            self._note_q3_scan_point(mission.target)
        return mission

    def _standard_coverage_scan(self, ks):
        if not self._coverage_points:
            if self.mode == "Q3":
                radius, count = ((870.0, 12) if self.q3_thirteen_point
                                 else (self.q3_coverage_radius, 6))
                self._coverage_points = [(0.0, 0.0)] + self._q3_ring_layout(
                    radius, count)
            else:
                if self.q4_discovery_ring:
                    radius = self.q4_discovery_ring_radius_m
                    count = self.q4_discovery_ring_points
                    self._coverage_points = [(0.0, 0.0)] + [
                        (radius * math.cos(2.0 * math.pi * k / count),
                         radius * math.sin(2.0 * math.pi * k / count))
                        for k in range(count)]
                    self._q4_discovery_active = True
                else:
                    raw = (q4_sparse25_points()
                           if self.q4_certificate_layout == "sparse25"
                           else q4_lattice_points())
                    self._coverage_points = self._ordered_q4_coverage(raw)
        # The compact Q4 discovery ring is a deliberate pre-certificate
        # search phase.  It has its own radial geometry, so applying the
        # sparse25 observed-order lock after the first ring stop silently
        # replaced the ring with the certificate mesh.  Lock a sparse25 order
        # only after this phase has either been skipped or has explicitly
        # switched back to the finite certificate.
        if not (self.mode == "Q4" and self._q4_discovery_active):
            self._lock_q4_observed_order(ks)
        if (self.mode == "Q4" and self._q4_discovery_active and
                self._coverage_index == 1):
            known = (len(ks.by_status(ChannelStatus.ACTIVE)) +
                     len(ks.by_status(ChannelStatus.READY)) +
                     len(ks.by_status(ChannelStatus.CLEARED)))
            if known < self.q4_discovery_threshold:
                self._q4_discovery_active = False
                self._q4_discovery_switched = True
                raw = (q4_sparse25_points()
                       if self.q4_certificate_layout == "sparse25"
                       else q4_lattice_points())
                self._coverage_points = self._ordered_q4_coverage(raw)
                self._coverage_index = 0
        if (self.mode == "Q4" and self._q4_discovery_active and
                self._coverage_index >= len(self._coverage_points)):
            known = (len(ks.by_status(ChannelStatus.ACTIVE)) +
                     len(ks.by_status(ChannelStatus.READY)) +
                     len(ks.by_status(ChannelStatus.CLEARED)))
            if known < 16 and not self._q4_discovery_switched:
                self._q4_discovery_active = False
                self._q4_discovery_switched = True
                raw = (q4_sparse25_points()
                       if self.q4_certificate_layout == "sparse25"
                       else q4_lattice_points())
                self._coverage_points = self._ordered_q4_coverage(raw)
                self._coverage_index = 0
        if (self.mode == "Q3" and self.q3_adaptive_coverage
                and not self.q3_thirteen_point
                and not self._q3_adaptive_coverage_locked
                and self._coverage_index == 1):
            active_count = len(ks.by_status(ChannelStatus.ACTIVE))
            radius, count = ((870.0, 12) if active_count >= 7
                             else (self.q3_coverage_radius, 6))
            self._coverage_points = [(0.0, 0.0)] + self._q3_ring_layout(
                radius, count)
            self._q3_adaptive_coverage_locked = True
        if (self.mode == "Q3" and self.q3_adaptive_radius
                and not self._q3_adaptive_radius_locked
                and self._coverage_index == 1):
            # The origin stop gives an observable density signal.  The
            # smaller rings are discovery routes only; the shared runner's
            # cardinality certificate is required before they can terminate
            # an all-clear 16-source case.
            active_count = len(ks.by_status(ChannelStatus.ACTIVE))
            self.q3_coverage_radius = (
                850.0 if active_count >= self.q3_adaptive_radius_high_threshold else
                (900.0 if active_count >= self.q3_adaptive_radius_mid_threshold else
                 self.Q3_COVERAGE_RADIUS))
            self._q3_adaptive_radius_locked = True
        if (self.mode == "Q3" and not self.q3_thirteen_point
                and not self.q3_adaptive_coverage
                and self.q3_dynamic_order
                and not self._q3_dynamic_order_locked
                and self._coverage_index == 1):
            active_count = len(ks.by_status(ChannelStatus.ACTIVE))
            dynamic_threshold = (self.Q3_DYNAMIC_ORDER_THRESHOLD
                                 if self.q3_observation_adaptive else
                                 self.Q3_DYNAMIC_ORDER_THRESHOLD)
            if active_count >= dynamic_threshold:
                radius = self.q3_coverage_radius
                count = (self.q3_ring_seven_count if self.q3_ring_seven_point
                         else 6)
                ring = self._q3_ring_layout(radius, count)
                adaptive_order = (self._adaptive_q3_ring_order(ks, count)
                                  if self.q3_adaptive_ring_order else None)
                if adaptive_order is not None and len(adaptive_order) == count:
                    order = adaptive_order
                elif (self.q3_ring_order is not None and
                        len(self.q3_ring_order) == count and
                        sorted(self.q3_ring_order) == list(range(count))):
                    order = self.q3_ring_order
                elif self.q3_ring_seven_point:
                    # Deterministic default for the 7-anchor ring: the natural
                    # counter-clockwise order (all chords are equal, so any
                    # rotation has the same travel; index 0 is the anchor on
                    # the +x axis).
                    order = list(range(count))
                else:
                    order = [
                        (self.Q3_DYNAMIC_ORDER_START
                         + self.Q3_DYNAMIC_ORDER_DIRECTION * j) % 6
                        for j in range(6)
                    ]
                self._coverage_points[1:] = [ring[i] for i in order]
            # Lock after the origin result; later scans must not oscillate the
            # finite cover order as new channels are discovered.
            self._q3_dynamic_order_locked = True
        if self.mode == "Q4" and self._coverage_pending_point is not None:
            if self._coverage_pending_active is None:
                if self._q4_repeat_limit_locked is None:
                    known = (len(ks.by_status(ChannelStatus.ACTIVE))
                             + len(ks.by_status(ChannelStatus.READY))
                             + len(ks.by_status(ChannelStatus.CLEARED)))
                    # The first centre stop is an observable estimate of
                    # source density. Lock the inexpensive repeat budget once
                    # so later discoveries cannot oscillate the route policy.
                    self._q4_repeat_limit_locked = (
                        self.Q4_ACTIVE_REPEAT_LIMIT_HIGH
                        if known >= 6 else
                        (self.Q4_ACTIVE_REPEAT_LIMIT_MID
                         if known >= 2 else self.Q4_ACTIVE_REPEAT_LIMIT))
                repeat_limit = self._q4_repeat_limit_locked
                self._coverage_pending_active = (
                    [ch.channel_id for ch in ks.active]
                    if self._coverage_index <= repeat_limit else [])
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
        if self.mode == "Q4":
            self._reorder_q4_discovery(ks, self._decision_position)
        elif self.mode == "Q3":
            self._reorder_q4_discovery(ks, self._decision_position)
        # Q3 ring translation (default OFF): pull pending anchors toward the
        # channels that still need work, but only while the *exact* decider
        # still accepts the whole ring as a proof of Omega.
        if self.mode == "Q3" and self.q3_ring_translate_m > 0.0:
            self._coverage_points, ring_info = self._q3_translated_ring(ks)
        else:
            ring_info = None
        if self.mode == "Q3" and ring_info is not None:
            self._q3_ring_cert_trace(ks, ring_info)
        if self.mode == "Q3" and self.q3_ring_trim:
            # Reverse trim: skip anchors the exact decider no longer needs.
            self._q3_ring_trim_apply(ks)
            if (self._coverage_index >= len(self._coverage_points)
                    or not ks.unknown):
                return None
        point = self._coverage_points[self._coverage_index]
        self._coverage_index += 1
        if self.mode == "Q4":
            self._coverage_pending_point = point
            self._coverage_pending_active = None
        mission = Mission("scan", point,
                          channels=[ch.channel_id for ch in ks.unknown],
                          meta={"coverage_scan": True, "kind": "coverage"})
        link = self._q3_attach_measure_link(ks, mission)
        if link is not None and self.decision_listener is not None:
            trace = self._trace_base(ks, "q3_measure_link")
            trace.update(link)
            trace["point"] = [round(point[0], 3), round(point[1], 3)]
            self._emit(trace)
        return mission

    def _ensure_q4_joint_points(self):
        if not self._coverage_points:
            raw = (q4_sparse25_points()
                   if self.q4_certificate_layout == "sparse25"
                   else q4_lattice_points())
            self._coverage_points = self._ordered_q4_coverage(raw)

    def _lock_q4_observed_order(self, ks):
        """Choose a certificate traversal from the first observed signal mix.

        The branch is driven only by observations already recorded at the
        centre stop.  A strong directional fraction permits the validated
        mixed-density order; a weak fraction keeps the nearest-neighbour
        order, which is safer for blind-side and sparse cases.
        """
        if (self.mode != "Q4" or not self.q4_observed_order or
                self._q4_observed_order_locked or self._coverage_index != 1):
            return
        directions = sum(
            obs["result"] == "direction"
            for ch in ks.channels.values() for obs in ch.observations)
        observed = sum(
            obs["result"] in ("direction", "no_signal", "near")
            for ch in ks.channels.values() for obs in ch.observations)
        fraction = directions / float(observed) if observed else 0.0
        raw = (q4_sparse25_points()
               if self.q4_certificate_layout == "sparse25"
               else q4_lattice_points())
        use_candidate = (self.q4_point_order is not None and
                         fraction >= self.q4_observed_order_fraction)
        if use_candidate and len(self.q4_point_order) == len(raw):
            self._coverage_points = [raw[i] for i in self.q4_point_order]
        else:
            self._coverage_points = _greedy_order(raw)
        self._q4_observed_order_locked = True

    @staticmethod
    def _observed_at_point(ch, point):
        return any(math.dist(point, obs["position"]) <= 1.0
                   for obs in ch.observations if "position" in obs)

    def _q4_joint_primary(self, ks, point):
        if self._q4_joint_points_used >= self.q4_joint_coverage_limit:
            return None
        best = None
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            if (self.fallback.in_fallback(ch.channel_id) or
                    self._observed_at_point(ch, point) or ch.mec is None):
                continue
            n_dir = sum(obs["result"] == "direction"
                        for obs in ch.observations)
            n_no_signal = sum(obs["result"] == "no_signal"
                              for obs in ch.observations)
            if n_dir < self.q4_joint_min_directions:
                continue
            if (self.q4_joint_max_no_signal is not None and
                    n_no_signal > self.q4_joint_max_no_signal):
                continue
            # Repeated no-signal without a direction is an observable
            # warning that a Q4 directional source is being probed from its
            # blind side.  Do not spend more joint stops on it; the normal
            # certificate and NBV/fallback path remains available.
            if ((n_dir == 0 and n_no_signal >= 2) or
                    (n_no_signal >= 3 and n_no_signal > 2 * n_dir)):
                continue
            center, radius = ch.mec
            distance = math.dist(point, center)
            overlap = C.R_EFF_MIN + float(radius) - distance
            if overlap < 0.0:
                continue
            value = overlap * max(20.0, float(radius)) / (1.0 + n_dir)
            key = (value, -distance, -ch.channel_id)
            if best is None or key > best[0]:
                best = (key, ch)
        return best[1] if best else None

    def _q4_joint_coverage_scan(self, ks):
        """Visit each finite certificate point once, using ACTIVE as primary.

        A joint point is still executed by the normal runner: the primary
        ACTIVE channel is measured and the same stop scans UNKNOWN channels.
        Thus no certificate point is skipped and no source truth is used.
        """
        self._ensure_q4_joint_points()
        self._lock_q4_observed_order(ks)
        if (self.q4_joint_min_direction_fraction > 0.0 and
                not self._q4_joint_gate_locked and self._coverage_index >= 1):
            directions = sum(
                obs["result"] == "direction"
                for ch in ks.channels.values() for obs in ch.observations)
            observed = sum(
                obs["result"] in ("direction", "no_signal", "near")
                for ch in ks.channels.values() for obs in ch.observations)
            if observed:
                self._q4_joint_route_disabled = (
                    directions / float(observed)
                    < self.q4_joint_min_direction_fraction)
                self._q4_joint_gate_locked = True
        if self._q4_joint_route_disabled:
            return self._standard_coverage_scan(ks)
        if (self._coverage_index >= len(self._coverage_points)
                or not ks.unknown):
            return None
        point = self._coverage_points[self._coverage_index]
        self._coverage_index += 1
        ch = self._q4_joint_primary(ks, point)
        if ch is not None:
            self._q4_joint_points_used += 1
            return Mission("measure", point, channel=ch.channel_id,
                           meta={"kind": "joint_coverage",
                                 "coverage_scan": True,
                                 "joint_route": True})
        return Mission("scan", point,
                       channels=[c.channel_id for c in ks.unknown],
                       meta={"coverage_scan": True, "kind": "coverage"})

    def _ordered_q4_coverage(self, raw):
        """Return the same finite Q4 certificate points in a chosen order."""
        if (self.q4_point_order is not None
                and len(self.q4_point_order) == len(raw)
                and sorted(self.q4_point_order) == list(range(len(raw)))):
            return [raw[i] for i in self.q4_point_order]
        if self.q4_coverage_order == "greedy":
            return _greedy_order(raw)
        if self.q4_certificate_layout != "sparse25":
            return _greedy_order(raw)
        # sparse25 is center + 12 inner (indices 1..12) + 12 outer
        # (indices 13..24).  The alternative orders only change discovery
        # timing; the verifier still requires the complete fixed point set.
        center = list(raw[:1])
        inner = list(raw[1:13])
        outer = list(raw[13:25])
        if self.q4_coverage_order == "outer_first":
            return center + outer + inner
        if self.q4_coverage_order == "alternating":
            out = list(center)
            for i in range(12):
                out.extend((inner[i], outer[i]))
            return out
        if self.q4_coverage_order == "outer_inner_alternating":
            out = list(center)
            for i in range(12):
                out.extend((outer[i], inner[i]))
            return out
        if self.q4_coverage_order == "inner_then_outer_reverse":
            return center + inner + list(reversed(outer))
        if self.q4_coverage_order == "outer_then_inner_reverse":
            return center + outer + list(reversed(inner))
        return _greedy_order(raw)

    def _features(self, ks, ch, point, position, current_channel, gain, cost):
        active = [other for other in ks.by_status(ChannelStatus.ACTIVE)
                  if other is not ch and not self.fallback.in_fallback(other.channel_id)]
        cluster = sum(math.dist(point, other.mec[0]) < 600.0 for other in active)
        bearings = sum(obs["result"] == "direction" for obs in ch.observations)
        unknown = len(ks.unknown)
        return [gain / max(cost, 1e-9), cluster / 8.0,
                min(ch.mec_radius, 1800.0) / 1800.0,
                min(math.dist(point, position), 3600.0) / 3600.0,
                min(bearings, 8) / 8.0, min(unknown, 20) / 20.0,
                float(ch.channel_id == current_channel)]

    def _score(self, features):
        weights = self.model["weights"]
        if (not self._explicit_model_path and self.mode == "Q3" and
                self._q3_known_channels < self.Q3_LIMIT_SWITCH_ACTIVE * 2):
            # Sparse Q3 runs benefit from a modest cluster preference and a
            # strong distance penalty.  This is only the low-density prefix;
            # once twelve channels are exposed, switch to the separately
            # tuned dense policy below.
            weights = self.Q3_LOW_DENSITY_MODEL_WEIGHTS
        elif (not self._explicit_model_path and self.mode == "Q3" and
              self._q3_known_channels >= self.Q3_LIMIT_SWITCH_ACTIVE * 2):
            # Dense Q3 cases benefit from a stronger uncertainty/distance
            # tradeoff after the run has exposed twelve channels.
            weights = self.Q3_HIGH_DENSITY_MODEL_WEIGHTS
        return float(self.model.get("bias", 0.0)) + sum(
            w * x for w, x in zip(weights, features))

    def _bearing_cut_value(self, ch, point):
        """How much a new bearing measured at ``point`` can cut the MEC.

        Only observations already recorded for the channel are used.  Two
        regimes matter:

        * the observation point lies inside (or near) the current feasible
          region, so the new wedge apex splits the region and the enclosing
          radius shrinks roughly by half;
        * the observation point is outside, where only the crossing angle
          against the last received bearing matters.  Walking further along a
          received bearing re-measures almost the same wedge, so it is worth
          close to nothing, while a perpendicular baseline cuts the region.

        The returned factor rescales a candidate's gain proxy; it never
        changes geometric state, the certificate or the completion standard.
        """
        if ch.mec is None:
            return 1.0
        center, radius = ch.mec
        dirs = [obs for obs in ch.observations if obs["result"] == "direction"]
        if not dirs:
            return 1.0
        offset = math.dist(point, center)
        if offset <= 0.5 * max(float(radius), 1.0):
            return 1.0
        last = dirs[-1]["position"]
        ax, ay = point[0] - center[0], point[1] - center[1]
        bx, by = last[0] - center[0], last[1] - center[1]
        na, nb = math.hypot(ax, ay), math.hypot(bx, by)
        if na < 1e-6 or nb < 1e-6:
            return 1.0
        cos_phi = max(-1.0, min(1.0, (ax * bx + ay * by) / (na * nb)))
        return math.sqrt(max(0.0, 1.0 - cos_phi * cos_phi))

    def joint_bearing_allowed(self, ch, point):
        """Observable gate for an extra ACTIVE measurement at a shared stop."""
        if self.q4_joint_angle_gate_deg <= 0.0:
            return True
        if self.mode != "Q4":
            return True
        factor = self._bearing_cut_value(ch, point)
        return factor >= math.sin(math.radians(
            self.q4_joint_angle_gate_deg))

    def _candidate_points(self, ch, position):
        points = localization.candidate_points(
            ch, position,
            failed_points=self.failed_points.get(ch.channel_id),
            opportunistic_reuse=self.opportunistic_reuse)
        if self.avoid_remeasure and ch.observations:
            observed_positions = [obs["position"] for obs in ch.observations
                                  if "position" in obs]
            filtered = [
                point for point in points
                if all(math.dist(point, prior) > self.remeasure_epsilon_m
                       for prior in observed_positions)]
            if filtered:
                points = filtered
        dirs = [obs for obs in ch.observations if obs["result"] == "direction"]
        if self.mode != "Q4":
            if self.q3_perp_factor > 0.0 and dirs and ch.mec is not None:
                # Perpendicular baseline: the offline teacher repeatedly picks
                # this point for omnidirectional channels, but the policy never
                # generated it.  A bearing taken sideways of the received ray
                # cuts the region instead of repeating it; the offset scales
                # with the current uncertainty.
                last = dirs[-1]
                offset = min(900.0, max(200.0,
                                        self.q3_perp_factor * float(
                                            ch.mec_radius)))
                theta = math.radians(last["bearing"])
                for sign in (-1.0, 1.0):
                    angle = theta + sign * math.pi / 2.0
                    point = (last["position"][0] + offset * math.cos(angle),
                             last["position"][1] + offset * math.sin(angle))
                    if all(math.dist(point, q) >= 1.0 for q in points):
                        points.append(point)
            return points
        if not dirs:
            return points
        center = ch.mec[0]
        last = dirs[-1]
        if math.dist(last["position"], position) > 100.0:
            # A current-position remeasure after moving away from the last
            # bearing has little directional value; force a geometric move.
            points = [p for p in points if math.dist(p, position) >= 1.0]
        theta = math.radians(last["bearing"])
        # A short forward step stays on the received side for the common case
        # and supplies a second intersection at little travel cost.
        for distance in self.Q4_FORWARD_DISTANCES:
            p = (last["position"][0] + distance * math.cos(theta),
                 last["position"][1] + distance * math.sin(theta))
            if all(math.dist(p, q) >= 1.0 for q in points):
                points.append(p)
        # Perpendicular baselines can collapse a directional MEC faster than
        # walking repeatedly along the same bearing.  They are opt-in because
        # a side move is not uniformly beneficial across Q4 mixtures.
        for distance in self.Q4_SIDE_DISTANCES:
            for sign in (-1.0, 1.0):
                ang = theta + sign * math.pi / 2.0
                p = (last["position"][0] + distance * math.cos(ang),
                     last["position"][1] + distance * math.sin(ang))
                if all(math.dist(p, q) >= 1.0 for q in points):
                    points.append(p)
        # A Q4 no-signal is not a location exclusion by itself: a directional
        # source may simply face away.  It is nevertheless useful for choosing
        # the next legal view.  Try points on the opposite side of the current
        # MEC from the latest no-signal witness; state/certificate semantics
        # remain unchanged if the escape view also returns no_signal.
        if self.Q4_NO_SIGNAL_ESCAPE_DISTANCES:
            no_signals = [obs for obs in ch.observations
                          if obs.get("result") == "no_signal"
                          and "position" in obs]
            if no_signals:
                witness = no_signals[-1]["position"]
                dx, dy = center[0] - witness[0], center[1] - witness[1]
                norm = math.hypot(dx, dy)
                if norm > 1.0:
                    ux, uy = dx / norm, dy / norm
                    for distance in self.Q4_NO_SIGNAL_ESCAPE_DISTANCES:
                        p = (center[0] + distance * ux,
                             center[1] + distance * uy)
                        if math.hypot(*p) <= C.OMEGA_RADIUS + 1e-6 and \
                                all(math.dist(p, q) >= 1.0 for q in points):
                            points.append(p)
        # Forward/side candidates are appended after the generic candidate
        # filter above.  Apply the same observable remeasure guard again so a
        # previously visited 200/400 m bearing stop cannot be selected over
        # fresh geometry and measured repeatedly at zero movement cost.
        if self.avoid_remeasure and ch.observations:
            observed_positions = [obs["position"] for obs in ch.observations
                                  if "position" in obs]
            filtered = [
                point for point in points
                if all(math.dist(point, prior) > self.remeasure_epsilon_m
                       for prior in observed_positions)]
            if filtered:
                points = filtered
        return points

    def _enter_fallback(self, ch_state, position, trigger):
        """Enter the exact fallback cover with a directional warm start.

        Once the Q4 run has already exposed at least ``Q4_LIMIT_SWITCH_KNOWN``
        channels, a directional ACTIVE channel has a useful local prior: the
        source lies on the received bearing side of its latest direction
        observation.  Reordering the *same* finite cover from a 50 m forward
        offset cuts expected first-hit travel while preserving the baseline
        cover and completion semantics.  Low-density cases keep the inherited
        nearest-from-current order because the directional prior is weaker.
        """
        super()._enter_fallback(ch_state, position, trigger)
        if self.mode != "Q4":
            return
        # The fallback callback only receives a channel state.  ``decide``
        # snapshots the current run-wide known-channel count for the density
        # gate below.
        if self._q4_known_channels < self.Q4_LIMIT_SWITCH_KNOWN:
            return
        dirs = [obs for obs in ch_state.observations
                if obs["result"] == "direction"]
        if not dirs:
            return
        st = self.fallback._fallback.get(ch_state.channel_id)
        if not st:
            return
        last = dirs[-1]
        theta = math.radians(last["bearing"])
        start = (last["position"][0] + self.Q4_WARM_START_M * math.cos(theta),
                 last["position"][1] + self.Q4_WARM_START_M * math.sin(theta))
        st["points"] = order_greedy(st["points"], start)

    def _maybe_enter_early_fallback(self, ks, position):
        """Start the cheapest small exact clear cover, if one exists.

        READY work keeps priority, and an unused one-shot center probe keeps
        priority when it is currently legal.  Thus this action replaces an
        additional localization leg, rather than replacing a cheaper clear.
        """
        limit = self.early_fallback_max_points
        if limit <= 0 or ks.ready:
            return False
        known = (len(ks.by_status(ChannelStatus.ACTIVE))
                 + len(ks.by_status(ChannelStatus.READY))
                 + len(ks.by_status(ChannelStatus.CLEARED)))
        if (self.early_fallback_max_known > 0 and
                known > self.early_fallback_max_known):
            return False
        q3_risky_radius = self._observed_q3_risky_radius(ks)
        best = None
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            cid = ch.channel_id
            if self.fallback.in_fallback(cid) or not ch.feasible_region:
                continue
            # Preserve the existing cheap one-shot attempts.  On their next
            # decision after a miss, the exact cover may take over.
            if self.mode == "Q3" and q3_risky_radius > 0.0:
                probe, guaranteed = self._ladder_probe_point(ch)
                if (probe is not None and
                        (guaranteed or
                         self.probe_attempts(cid) < self.probe_ladder_limit) and
                        (guaranteed or ch.mec_radius <= q3_risky_radius) and
                        (self.q3_risky_clear_max_distance_m is None or
                         math.dist(position, probe) <=
                         self.q3_risky_clear_max_distance_m)):
                    continue
            if (self.mode == "Q4" and self.rolling_enabled and
                    cid not in self._rolling_probe_attempted and
                    self.rolling_probe_radius_m > 0.0 and
                    ch.mec_radius <= self.rolling_probe_radius_m and
                    (self.rolling_probe_max_distance_m is None or
                     math.dist(position, ch.mec[0]) <=
                     self.rolling_probe_max_distance_m)):
                continue
            points = self._early_fallback_points(ch, position)
            n_points = len(points)
            if n_points == 0 or n_points > limit:
                continue
            ordered = order_greedy(points, position)
            entry = math.dist(position, ordered[0])
            if (self.early_fallback_max_entry_m is not None and
                    entry > self.early_fallback_max_entry_m):
                continue
            route = entry + sum(math.dist(a, b)
                                for a, b in zip(ordered, ordered[1:]))
            # Worst-case virtual cost: every preceding shot misses and the
            # final shot succeeds.  It is used only to choose among channels.
            cost = route / C.MOVE_SPEED + 3.0 * (n_points - 1) + 5.0
            key = (cost, n_points, entry, cid)
            if best is None or key < best[0]:
                best = (key, ch)
        if best is None:
            return False
        ch = best[1]
        self._early_fallback_channels.add(ch.channel_id)
        self._enter_fallback(ch, position, "early_small_exact_cover")
        return self.fallback.in_fallback(ch.channel_id)

    def _early_fallback_points(self, ch, position):
        """Finite clear cover considered by the early-completion gate."""
        return disk_lattice_cover(ch.feasible_region)

    def _active_measure(self, ks, position, current_channel,
                        active_override=None):
        active = list(active_override) if active_override is not None else [
            ch for ch in ks.by_status(ChannelStatus.ACTIVE)
            if not self.fallback.in_fallback(ch.channel_id)]
        if not active:
            return None
        if self.mode == "Q4" and self.q4_direct_center_radius_m > 0.0:
            direct_q4 = []
            for candidate in active:
                n_dir = sum(obs.get("result") == "direction"
                            for obs in candidate.observations)
                n_no = sum(obs.get("result") == "no_signal"
                           for obs in candidate.observations)
                if (n_dir >= 2 and
                        (self.q4_direct_center_max_no_signal is None or
                         n_no <= self.q4_direct_center_max_no_signal) and
                        candidate.mec_radius <= self.q4_direct_center_radius_m
                        and math.dist(position, candidate.mec[0]) > 1.0):
                    direct_q4.append(candidate)
            if direct_q4:
                candidate = min(direct_q4, key=lambda item: (
                    math.dist(position, item.mec[0]) / C.MOVE_SPEED
                    + (C.SWITCH_TIME if item.channel_id != current_channel
                       else 0.0),
                    -item.mec_radius, item.channel_id))
                return Mission("measure", candidate.mec[0],
                               channel=candidate.channel_id,
                               meta={"kind": "approach",
                                     "q4_direct_center": True})
        direct = [ch for ch in active if (
            (self.q3_direct_center_radius_m is None or
             ch.mec_radius <= self.q3_direct_center_radius_m) and
            math.dist(position, ch.mec[0]) > 1.0 and
            (self.q3_direct_center_max_distance_m is None or
             math.dist(position, ch.mec[0]) <=
             self.q3_direct_center_max_distance_m) and
            not any(math.dist(ch.mec[0], obs["position"]) <= 1.0
                    for obs in ch.observations if "position" in obs))]
        if (self.mode == "Q3" and self.q3_direct_center and direct and
                not self.q3_direct_center_compete):
            ch = min(direct, key=lambda item: (
                math.dist(position, item.mec[0]) / C.MOVE_SPEED
                + (C.SWITCH_TIME if item.channel_id != current_channel else 0.0),
                -item.mec_radius, item.channel_id))
            return Mission("measure", ch.mec[0], channel=ch.channel_id,
                           meta={"kind": "approach", "direct_center": True})
        trace_candidates = []
        best = None
        if (self.mode == "Q3" and self.q3_direct_center and
                self.q3_direct_center_compete):
            # Treat the mathematically valid MEC-center contraction as one
            # candidate among the ordinary NBV points.  This avoids the
            # all-or-nothing force rule, which can trade a cheap local view
            # for a long channel switch in a tail scenario.
            for ch in direct:
                move = math.dist(position, ch.mec[0])
                cost = move / C.MOVE_SPEED + C.MEASURE_TIME
                if ch.channel_id != current_channel:
                    cost += C.SWITCH_TIME
                gain = min(ch.mec_radius, 1800.0) * 0.5
                features = self._features(ks, ch, ch.mec[0], position,
                                          current_channel, gain, cost)
                score = self._score(features)
                record = {"channel": ch.channel_id,
                          "point": list(ch.mec[0]), "cost": cost,
                          "gain_proxy": gain, "features": features,
                          "repeat_count": 0, "score": score,
                          "kind": "direct_center_candidate"}
                trace_candidates.append(record)
                key = (score, -cost, -ch.channel_id)
                if best is None or key > best[0]:
                    best = (key, ch, ch.mec[0], record)
        for ch in active:
            points = self._candidate_points(ch, position)
            for point in points:
                move = math.dist(position, point)
                cost = move / C.MOVE_SPEED + C.MEASURE_TIME
                if ch.channel_id != current_channel:
                    cost += C.SWITCH_TIME
                # A cheap deterministic gain proxy keeps online inference fast;
                # the actual feedback and certificate geometry are unchanged.
                gain = min(ch.mec_radius, 1800.0) / (1.0 + len(ch.observations))
                if (self.true_gain and self.mode == "Q3"
                        and ch.feasible_region):
                    # Score with the real worst-case MEC contraction instead of
                    # a proxy that returns the same value for every point of a
                    # channel.  This is the quantity the offline teacher uses
                    # when it prefers a perpendicular baseline over the region
                    # centre; only the scoring changes, never the state update.
                    worst = localization._eval_worst(
                        ch.feasible_region, point,
                        localization._adaptive_step(ch.feasible_region, point))
                    gain = max(0.0, float(ch.mec_radius) - float(worst))
                if self.q4_cross_angle_gain and self.mode == "Q4":
                    # Discount candidates whose bearing ray is already covered
                    # by the last received bearing (see _bearing_cut_value).
                    gain *= self._bearing_cut_value(ch, point)
                if (self.mode == "Q3" and self.q3_center_value and
                        ch.mec is not None and
                        math.dist(point, ch.mec[0]) <= 1.0):
                    # After a direction, the MEC-centre chain has a
                    # deterministic <=1/2 contraction in Q3.  Treat that
                    # as its true value while retaining travel/switch cost.
                    gain = min(ch.mec_radius, 1800.0) * 0.5
                features = self._features(ks, ch, point, position,
                                          current_channel, gain, cost)
                score = self._score(features)
                repeat_count = 0
                if self.remeasure_penalty:
                    repeat_count = sum(
                        math.dist(point, obs["position"]) <=
                        self.remeasure_epsilon_m
                        for obs in ch.observations
                        if "position" in obs)
                    score -= self.remeasure_penalty * math.log1p(
                        repeat_count)
                record = {"channel": ch.channel_id, "point": list(point),
                          "cost": cost, "gain_proxy": gain, "features": features,
                          "repeat_count": repeat_count, "score": score,
                          "kind": "learned_search"}
                trace_candidates.append(record)
                key = (score, -cost, -ch.channel_id)
                if best is None or key > best[0]:
                    best = (key, ch, point, record)
        teacher_block = None
        if self.teacher_family and best is not None:
            # Offline-teacher family: extra members are appended to the pool
            # and priced with the executor's plan; production keeps its pick
            # unless an appended member scores strictly higher.
            best, teacher_block = self._teacher_inject(
                ks, position, current_channel, active, best, trace_candidates)
        if best is None:
            return None
        _, ch, point, record = best
        if self.decision_listener is not None:
            base = self._trace_base(ks, "learned_search_active")
            base["candidates"] = trace_candidates
            base["selected"] = record
            base["tie_break"] = "max learned value, min cost, channel id"
            if teacher_block is not None:
                base["teacher_family"] = teacher_block
            self._emit(base)
        return Mission("measure", point, channel=ch.channel_id,
                       meta={"kind": "nbv", "score": record["score"],
                             "gain": record["gain_proxy"], "cost": record["cost"]})

    # ------------------------------------------------------------------
    # Offline-teacher candidate family (default OFF, see __init__)
    # ------------------------------------------------------------------
    TEACHER_VARIANTS = ("primary", "active", "discover", "full")

    def _teacher_perp_point(self, ch, position):
        """Perpendicular-baseline stop, identical to the offline teacher.

        ``tools/teacher_probe.py`` builds this candidate as ``last bearing + 90
        degrees`` at an offset of ``max(200 m, 2 x MEC radius)`` capped at
        900 m.  Only observations and the current MEC are used; no source
        count, scenario label or truth value is read anywhere here.
        """
        if ch.mec is None:
            return None
        dirs = [obs for obs in ch.observations
                if obs.get("result") == "direction" and "position" in obs]
        if not dirs:
            return None
        last = dirs[-1]
        offset = min(900.0, max(200.0, 2.0 * float(ch.mec[1])))
        angle = math.radians(float(last["bearing"])) + math.pi / 2.0
        return (last["position"][0] + offset * math.cos(angle),
                last["position"][1] + offset * math.sin(angle))

    def _teacher_family_candidates(self, ks, position, active):
        """Joint members ``(point_name, point, variant, mission)`` of a family.

        ``perp``    - the only *stop* family production never generates
                      (perpendicular baseline), with the production scan set.
        ``variant`` - production's own candidate points crossed with the
                      non-default scan sets (the settings the teacher used).
        ``full``    - ``{region centre, perp, NBV}`` x all four scan sets.
        """
        out = []
        for ch in active:
            specs = []
            perp = self._teacher_perp_point(ch, position)
            if self.teacher_family == "perp":
                if perp is not None:
                    specs.append(("perp", perp, None))
            elif self.teacher_family == "variant":
                for point in self._candidate_points(ch, position):
                    for variant in self.TEACHER_VARIANTS:
                        specs.append(("prod_point", point, variant))
            elif self.teacher_family == "full":
                points = []
                if ch.mec is not None:
                    points.append(("center", ch.mec[0]))
                if perp is not None:
                    points.append(("perp", perp))
                for cand in localization.candidate_points(
                        ch, position,
                        opportunistic_reuse=self.opportunistic_reuse):
                    points.append(("nbv", cand))
                    break
                for name, point in points:
                    for variant in self.TEACHER_VARIANTS:
                        specs.append((name, point, variant))
            for name, point, variant in specs:
                if math.dist(point, position) < 1.0:
                    continue
                meta = {"kind": "teacher_family",
                        "teacher_family": self.teacher_family,
                        "teacher_point": name}
                if variant is not None:
                    meta["scan_variant"] = variant
                out.append((name, point, variant,
                            Mission("measure", point, channel=ch.channel_id,
                                    meta=meta)))
        return out

    def _teacher_inject(self, ks, position, current_channel, active, best,
                        trace_candidates, show_limit=25):
        """Let the teacher family compete inside the measure pool.

        The production pool is left byte-identical: members are only appended,
        and an appended member replaces the production pick only on a
        *strictly* higher score, so ties keep production.  Every appended
        member is priced by the executor's own ``plan_stop`` (the same helper
        the executor uses), which is what makes the extra measurements of a
        non-default scan set visible in the cost feature.

        ``teacher_score="inert"`` subtracts a dominating offset from every
        appended member (maximisation: smaller score = worse), so those members
        can never win.  That is the C0 sanity control: C0 must reproduce
        production bit-for-bit.

        Returns ``(best, trace_block)``.  The trace block is observation only;
        nothing in this method writes scheduler state.
        """
        planner = getattr(self, "stop_planner", None)
        specs = self._teacher_family_candidates(ks, position, active)
        dominated = (self.teacher_score == "inert")
        want_value = (self.teacher_score == "value")
        offset = -self.teacher_dominated_offset if dominated else 0.0
        discovery_cache = {}
        rows = []
        prod_best = best
        prod_score = None if prod_best is None else float(prod_best[3]["score"])
        for name, point, variant, mission in specs:
            ch = ks[mission.channel]
            plan = planner(mission) if planner is not None else None
            measures = list(plan.get("measures", ())) if plan else []
            cost = (math.dist(position, point) / C.MOVE_SPEED
                    + self._sequence_cost(measures, current_channel))
            gain = min(ch.mec_radius, 1800.0) / (1.0 + len(ch.observations))
            features = self._features(ks, ch, point, position, current_channel,
                                      gain, cost)
            score = self._score(features)
            value = 0.0
            if want_value:
                value = self._variant_value(ks, point, variant,
                                            discovery_cache=discovery_cache)
            total = (score + self.teacher_value_scale * value
                     / self.teacher_value_ref_s + offset)
            record = {"channel": ch.channel_id, "point": list(point),
                      "cost": cost, "gain_proxy": gain, "features": features,
                      "repeat_count": 0, "score": total,
                      "score_base": score, "value_s": value,
                      "dominated_offset": offset,
                      "plan_measures": len(measures),
                      "point_name": name, "scan_variant": variant,
                      "kind": "teacher_family"}
            rows.append(record)
            trace_candidates.append(record)
            key = (total, -cost, -ch.channel_id)
            if best is None or key > best[0]:
                best = (key, ch, point, record)
        winner_score = None if best is None else float(best[3]["score"])
        won = (best is not None and
               (prod_score is None or (winner_score is not None
                                       and winner_score > prod_score)))
        block = {
            "family": self.teacher_family,
            "score_mode": self.teacher_score,
            "observe": bool(self.teacher_observe),
            "candidates_total": len(rows),
            "candidates_shown": min(len(rows), int(show_limit)),
            "injected_win": bool(won),
            "dominated_offset": offset,
            "value_ref_s": self.teacher_value_ref_s,
            "value_scale": self.teacher_value_scale,
            "production_pick": (None if prod_best is None else {
                "channel": prod_best[3]["channel"],
                "point": [round(prod_best[3]["point"][0], 3),
                          round(prod_best[3]["point"][1], 3)],
                "score": round(prod_score, 6),
                "plan_measures": prod_best[3].get("plan_measures"),
            }),
            "winner": (None if best is None else {
                "channel": best[1].channel_id,
                "point": [round(best[2][0], 3), round(best[2][1], 3)],
                "point_name": best[3].get("point_name"),
                "scan_variant": best[3].get("scan_variant"),
                "source": ("teacher_family" if won else "production"),
                "score": round(winner_score, 6),
            }),
            "margin_vs_production": (None if (prod_score is None or
                                              winner_score is None)
                                     else round(winner_score - prod_score, 6)),
        }
        if self.teacher_observe:
            block["candidates"] = [
                {"channel": row["channel"], "point": [round(row["point"][0], 3),
                                                      round(row["point"][1], 3)],
                 "point_name": row["point_name"],
                 "scan_variant": row["scan_variant"],
                 "plan_measures": row["plan_measures"],
                 "cost_s": round(row["cost"], 3),
                 "score_base": round(row["score_base"], 6),
                 "value_s": round(row["value_s"], 3),
                 "dominated_offset": row["dominated_offset"],
                 "score": round(row["score"], 6)}
                for row in sorted(rows, key=lambda r: -r["score"])
                [:int(show_limit)]]
        return best, block

    # ------------------------------------------------------------------
    # Q3 ring translation + cross-stop measure linking (default OFF)
    # ------------------------------------------------------------------
    def _q3_ring_targets(self, ks):
        """Observable anchors a certificate stop may be pulled toward.

        A READY channel is the next clear to execute; an ACTIVE channel still
        needs localisation.  Both positions come from the knowledge state or a
        clear target only - no source count, scenario label or truth value is
        read.
        """
        targets = []
        for ch in ks.by_status(ChannelStatus.READY):
            target = getattr(ch, "clear_position", None) or ch.mec[0]
            if target is not None:
                targets.append((float(target[0]), float(target[1])))
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            if ch.mec is not None:
                targets.append((float(ch.mec[0][0]), float(ch.mec[0][1])))
        return targets

    def _q3_translated_ring(self, ks):
        """Ring points, optionally translated, always under an exact proof.

        Only *pending* anchors are moved (a visited stop already produced its
        witnesses), and a shift is accepted only while the set that will really
        carry the proof - the no-signal witnesses already recorded plus the
        pending anchors - is still accepted by ``q3_certified``.  The search
        along each direction is a bisection, because the exact decider allows
        only a fraction of the distance in most directions (measured slack of
        the production ring: ~130 m inward, ~65 m tangential, unbounded
        outward).

        Returns ``(points, info)``; ``info`` is trace material only.
        """
        base = [tuple(point) for point in self._coverage_points]
        start = self._coverage_index
        active_count = len(ks.by_status(ChannelStatus.ACTIVE))
        gated = (self.q3_ring_translate_max_active > 0 and
                 active_count > self.q3_ring_translate_max_active)
        if (self.mode != "Q3" or self.q3_ring_translate_m <= 0.0
                or not base or start >= len(base) or gated):
            return base, {"translate_m": self.q3_ring_translate_m,
                          "enabled": False, "shifts": [], "certified": None,
                          "active_channels": active_count,
                          "gate_max_active": self.q3_ring_translate_max_active,
                          "gated_out": bool(gated)}
        visited = self._q3_no_signal_points(ks)
        pending = list(base[start:])
        targets = self._q3_ring_targets(ks)
        shifts = []
        for offset, point in enumerate(pending):
            chosen = point
            shift = 0.0
            if targets:
                # Nearest target first: the closest live channel is the one a
                # stop can realistically help, and outward targets (free for
                # the decider) are usually farther out.
                ordered = sorted(targets,
                                 key=lambda t: (math.dist(point, t), t))
                for target in ordered:
                    distance = math.dist(point, target)
                    if distance <= 1.0 or distance > self.q3_ring_translate_m:
                        continue
                    ux = (target[0] - point[0]) / distance
                    uy = (target[1] - point[1]) / distance

                    def certified_at(length, offset=offset, point=point,
                                     ux=ux, uy=uy):
                        trial = list(pending)
                        trial[offset] = (point[0] + ux * length,
                                         point[1] + uy * length)
                        return q3_certified(visited + trial)["certified"]

                    if certified_at(distance):
                        shift = distance
                    else:
                        low, high = 0.0, distance
                        for _ in range(12):
                            mid = 0.5 * (low + high)
                            if certified_at(mid):
                                low = mid
                            else:
                                high = mid
                        if low < 1.0:
                            continue
                        shift = low
                    # Optional safety margin: keep real slack against the
                    # independent verifier's finer boundary sampling.
                    if self.q3_ring_translate_margin_m > 0.0:
                        limit = 1000.0 - self.q3_ring_translate_margin_m
                        for _ in range(4):
                            trial = list(pending)
                            trial[offset] = (point[0] + ux * shift,
                                             point[1] + uy * shift)
                            if self._q3_boundary_margin(visited + trial) <= limit:
                                break
                            shift *= 0.5
                        if shift < 1.0:
                            continue
                    chosen = (point[0] + ux * shift, point[1] + uy * shift)
                    break
            pending[offset] = chosen
            shifts.append({"index": start + offset,
                           "from": [round(point[0], 3), round(point[1], 3)],
                           "to": [round(chosen[0], 3), round(chosen[1], 3)],
                           "shift_m": round(shift, 3)})
        points = base[:start] + pending
        info = {"translate_m": self.q3_ring_translate_m, "enabled": True,
                "targets": len(targets), "visited_points": len(visited),
                "active_channels": active_count,
                "gate_max_active": self.q3_ring_translate_max_active,
                "gated_out": False,
                "shifted": sum(1 for row in shifts if row["shift_m"] > 0.0),
                "max_shift_m": round(max([row["shift_m"] for row in shifts]
                                         or [0.0]), 3),
                "shifts": shifts,
                "certified": bool(q3_certified(visited + pending)["certified"])}
        return points, info

    def _q3_no_signal_points(self, ks):
        """Deduplicated no-signal witness positions already recorded.

        Pure read of the knowledge state; the same list feeds both the
        translation gate and the per-stop certificate trace.
        """
        visited = []
        for ch in ks.channels.values():
            for obs in getattr(ch, "observations", ()):
                if obs.get("result") == "no_signal" and "position" in obs:
                    point = (float(obs["position"][0]),
                             float(obs["position"][1]))
                    if all(math.dist(point, prior) > 1.0 for prior in visited):
                        visited.append(point)
        return visited

    @staticmethod
    def _q3_boundary_margin(points, samples=360):
        """Worst Omega-boundary distance to the nearest witness (metres).

        A coarse but smooth proxy for the independent verifier's 7200-sample
        check: it is used only to *require slack*, never to certify anything.
        """
        worst = 0.0
        radius = 1800.0
        for index in range(samples):
            angle = 2.0 * math.pi * index / samples
            px = radius * math.cos(angle)
            py = radius * math.sin(angle)
            best = min(math.hypot(px - point[0], py - point[1])
                       for point in points)
            worst = max(worst, best)
        return worst

    def _q3_ring_trim_promise(self, ks):
        """Channels that still need an absence certificate, with their witnesses.

        Only the knowledge state is read: UNKNOWN channels need the cover,
        ACTIVE/READY/CLEARED channels have existence evidence and an already
        certified channel is done.  ``certificate_region`` holds exactly the
        no-signal witness positions recorded so far.
        """
        pending = []
        for ch in ks.channels.values():
            if ch.status != ChannelStatus.UNKNOWN:
                continue
            witnesses = [(float(p[0]), float(p[1]))
                         for p in (ch.certificate_region or ())]
            pending.append((ch.channel_id, witnesses))
        return pending

    @staticmethod
    def _q3_ring_future_witnesses(witnesses, anchor_points):
        """Witnesses a channel would hold *if* the remaining anchors are visited.

        An anchor only yields a witness when the runner would actually measure
        that channel there; the runner skips a channel already measured within
        1 m of the stop (``_measured_near``), so such an anchor is not counted.
        Being conservative here can only keep more anchors.
        """
        future = list(witnesses)
        for point in anchor_points:
            if any(math.dist(point, prior) < 1.0 for prior in witnesses):
                continue
            future.append(point)
        return future

    def _q3_ring_trim_pending(self, ks, index):
        """Anchors that can be skipped from ``index`` on, and the kept ones.

        Greedy, deterministic: try the anchors in order of the travel they
        would save (farthest from the current decision position first) and drop
        one whenever *every* pending channel still certifies with the anchors
        that remain plus its own recorded witnesses.  The exact decider
        ``q3_certified`` is the only judge; the last covering anchor is never
        dropped and any uncertainty keeps the anchor.
        """
        points = [tuple(p) for p in self._coverage_points]
        pending = len(points)
        if index >= pending:
            return [], []
        keep = list(range(index, pending))
        if len(keep) <= self.q3_ring_trim_min_keep:
            return [], [points[i] for i in keep]
        obligations = self._q3_ring_trim_promise(ks)
        if not obligations:
            return [], [points[i] for i in keep]
        order = sorted(keep,
                       key=lambda i: (-math.dist(self._decision_position,
                                                 points[i]), i))
        skipped = []
        for candidate in order:
            if len(keep) <= self.q3_ring_trim_min_keep:
                break
            trial = [i for i in keep if i != candidate]
            trial_points = [points[i] for i in trial]
            self.q3_ring_trim_audit["checks"] += 1
            ok = True
            for _cid, witnesses in obligations:
                future = self._q3_ring_future_witnesses(witnesses, trial_points)
                if not q3_certified(future)["certified"]:
                    ok = False
                    break
            if not ok:
                self.q3_ring_trim_audit["rejected"] += 1
                continue
            keep = trial
            skipped.append(candidate)
        return skipped, [points[i] for i in keep]

    def _q3_ring_trim_margin(self, ks, keep_points, step=50.0):
        """Audit-only coverage margin of the kept plan (never used to decide).

        Returns ``(worst_uncovered_m, margin_m)`` for the tightest pending
        channel: the largest distance from an Omega sample to the nearest of
        that channel's witnesses plus the kept anchors.
        """
        obligations = self._q3_ring_trim_promise(ks)
        if not obligations:
            return None, None
        samples = []
        radius = int(math.ceil(C.OMEGA_RADIUS / step))
        for i in range(-radius, radius + 1):
            for j in range(-radius, radius + 1):
                x, y = i * step, j * step
                if x * x + y * y <= C.OMEGA_RADIUS ** 2:
                    samples.append((x, y))
        worst_overall = None
        for _cid, witnesses in obligations:
            future = self._q3_ring_future_witnesses(witnesses, keep_points)
            if not future:
                return None, None
            worst = 0.0
            for sample in samples:
                d = min(math.dist(sample, point) for point in future)
                if d > worst:
                    worst = d
            if worst_overall is None or worst > worst_overall:
                worst_overall = worst
        return worst_overall, C.R_EFF_MIN - worst_overall

    def _q3_ring_trim_trace(self, ks, skipped, kept, index, violations,
                            margin=None):
        block = {
            "policy": "q3_ring_trim",
            "index": int(index),
            "planned_certified": bool(q3_certified(kept)["certified"])
            if kept else None,
            "skipped_anchors": [[round(p[0], 3), round(p[1], 3)]
                                for p in skipped],
            "remaining_anchors": [[round(p[0], 3), round(p[1], 3)]
                                  for p in kept],
            "skipped_count": len(skipped),
            "remaining_count": len(kept),
            "checks": self.q3_ring_trim_audit["checks"],
            "rejected": self.q3_ring_trim_audit["rejected"],
            "violations": violations,
            "coverage_margin_m": None if margin is None else round(margin, 1),
            "worst_margin_m": self.q3_ring_trim_audit["worst_margin_m"],
            "skipped_points_total": self.q3_ring_trim_audit["skipped"],
        }
        if self.decision_listener is not None:
            trace = self._trace_base(ks, "q3_ring_trim")
            trace.update(block)
            self._emit(trace)
        return block

    def _q3_ring_trim_apply(self, ks):
        """Commit the skips for the next ring anchor (exact check + audit).

        Nothing is removed when the post-check fails: ``violations`` counts
        those cases and the ring is walked exactly as production would.
        """
        index = self._coverage_index
        skipped, kept = self._q3_ring_trim_pending(ks, index)
        self.q3_ring_trim_audit["calls"] += 1
        if not skipped:
            # Nothing was droppable: still record the evaluation (with the
            # audit-only coverage margin, 100 m sampling) so the trace shows
            # the exact decider ran and why the ring was kept whole.
            _worst, margin = self._q3_ring_trim_margin(ks, kept, step=100.0)
            if margin is not None:
                current = self.q3_ring_trim_audit["worst_margin_m"]
                self.q3_ring_trim_audit["worst_margin_m"] = (
                    margin if current is None else min(current, margin))
            self._q3_ring_trim_trace(ks, [], kept, index, 0, margin)
            return kept
        # Post-check on the exact keeper set: the committed plan must pass the
        # same promise, otherwise nothing is skipped at all.
        obligations = self._q3_ring_trim_promise(ks)
        violations = 0
        for _cid, witnesses in obligations:
            future = self._q3_ring_future_witnesses(witnesses, kept)
            if not q3_certified(future)["certified"]:
                violations += 1
        self.q3_ring_trim_audit["violations"] += violations
        if violations:
            self._q3_ring_trim_trace(ks, [], [tuple(p)
                                              for p in self._coverage_points],
                                     index, violations)
            return [tuple(p) for p in self._coverage_points]
        _worst, margin = self._q3_ring_trim_margin(ks, kept)
        if margin is not None:
            current = self.q3_ring_trim_audit["worst_margin_m"]
            self.q3_ring_trim_audit["worst_margin_m"] = (
                margin if current is None else min(current, margin))
        self._q3_trim_skipped.update(skipped)
        self.q3_ring_trim_audit["skipped"] += len(skipped)
        self.q3_ring_trim_audit["skipped_points"].extend(
            [[round(self._coverage_points[i][0], 3),
              round(self._coverage_points[i][1], 3)] for i in skipped])
        self._q3_ring_trim_trace(ks, [self._coverage_points[i] for i in skipped],
                                 kept, index, 0)
        # Drop the skipped anchors from the plan; visited entries (indices
        # below the cursor) are untouched, so every index stays valid.
        drop = set(skipped)
        self._coverage_points = [
            point for position, point in enumerate(self._coverage_points)
            if position < index or position not in drop]
        return [tuple(p) for p in kept]

    def _q3_ring_cert_trace(self, ks, info):
        """Record whether the pending ring still carries a valid proof.

        ``visited`` are the no-signal witnesses the runner has actually
        recorded; ``remaining`` are the anchors still to visit.  The pair
        ``visited_plus_remaining`` must be certified after *every* stop - that
        is the "no game passes by a missing proof" check.
        """
        planned = [tuple(point) for point in self._coverage_points]
        remaining = planned[self._coverage_index:]
        visited = self._q3_no_signal_points(ks)
        planned_check = q3_certified(planned)
        union_check = q3_certified(visited + remaining)
        block = {
            "enabled": True,
            "index": int(self._coverage_index),
            "planned_certified": bool(planned_check["certified"]),
            "planned_reason": planned_check["reason"],
            "visited_points": len(visited),
            "remaining_points": len(remaining),
            "visited_plus_remaining_certified": bool(union_check["certified"]),
            "visited_plus_remaining_reason": union_check["reason"],
            "translation": info,
        }
        if self.decision_listener is not None:
            trace = self._trace_base(ks, "q3_ring_cert")
            trace.update(block)
            self._emit(trace)
        return block

    def _q3_attach_measure_link(self, ks, mission):
        """Order this stop's measurements so the next stop starts for free.

        The next pending ring anchor is priced with the *same* runner planner
        the executor uses; a channel present in both stops' measure sequences
        is measured last here, which makes it ``current_channel`` for the next
        stop and removes one 1 s channel switch.  The channel that is already
        free (the current one, which ``plan_stop_measures`` puts first) is
        never moved.
        """
        if not self.measure_link or self.mode != "Q3" or mission is None:
            return None
        planner = getattr(self, "stop_planner", None)
        if planner is None or self._coverage_index >= len(self._coverage_points):
            return None
        next_point = self._coverage_points[self._coverage_index]
        next_mission = Mission(
            "scan", next_point,
            channels=[ch.channel_id for ch in ks.unknown],
            meta={"coverage_scan": True, "kind": "coverage"})
        now = list(planner(mission).get("measures", ()))
        after = set(planner(next_mission).get("measures", ()))
        if len(now) < 2:
            return None
        # The first measurement is already free (it is the current channel,
        # which plan_stop_measures puts first), so only a *different* shared
        # channel buys the one-second saving at the next stop.
        shared = [cid for cid in now if cid in after and cid != now[0]]
        if not shared:
            return None
        chosen = shared[0]
        mission.meta["measure_last"] = chosen
        return {"measure_last": chosen, "shared": len(shared),
                "measures_now": len(now), "measures_next": len(after)}

    # ------------------------------------------------------------------
    # Global stop-order planning (default OFF, see __init__)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # t35: tail-only stop-order planning (certificate phase already over)
    # ------------------------------------------------------------------
    def _q3_tail_ready(self, ks):
        """Observable test: has the certificate phase ended?  (t35)

        Either every planned ring anchor has been consumed, or no channel still
        needs an absence certificate.  Both inputs are the policy's own
        observables (anchor cursor, channel statuses); no source count, scenario
        or truth value is read.
        """
        if self.mode != "Q3" or not self.q3_order_tail_only:
            return False
        anchors_done = self._coverage_index >= len(self._coverage_points)
        nothing_pending = not ks.unknown
        return bool(anchors_done or nothing_pending)

    def _order_tail_tasks(self, ks, position):
        """Live-stop task set for the tail plan: **certificate points excluded**.

        One best measurement stop per live ACTIVE channel plus the READY clear
        points.  This is the structural difference from ``order_plan`` (t11),
        whose task set carried the pending certificate anchors and therefore
        re-phased the certificate ring.
        """
        tasks = []
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            if self.fallback.in_fallback(ch.channel_id):
                continue
            points = self._candidate_points(ch, position)
            if not points:
                continue
            point = points[0]
            if math.dist(point, position) <= 1.0 and len(points) > 1:
                point = points[1]
            tasks.append({
                "kind": "active", "channel": ch.channel_id,
                "point": (float(point[0]), float(point[1])),
                "mission": Mission("measure", point, channel=ch.channel_id,
                                   meta={"kind": "order_tail_measure",
                                         "order_planned": True})})
        for ch in ks.by_status(ChannelStatus.READY):
            if ch.channel_id in self.blocked:
                continue
            point = self._clear_target(ch, position)
            if point is None:
                continue
            tasks.append({
                "kind": "ready", "channel": ch.channel_id,
                "point": (float(point[0]), float(point[1])),
                "mission": Mission("clear", point, channel=ch.channel_id,
                                   meta={"kind": "order_tail_ready",
                                         "order_planned": True})})
        return tasks

    def _order_tail_step(self, ks, position, current_channel):
        """First stop of the live-only tail plan, or None (keep the local rule)."""
        if not self._q3_tail_ready(ks):
            return None
        tasks = self._order_tail_tasks(ks, position)
        certificate_tasks = sum(1 for task in tasks
                                if task["kind"] == "certificate")
        self.q3_tail_audit["certificate_tasks"] += certificate_tasks
        self.q3_tail_audit["decisions"] += 1
        if len(tasks) < 2:
            self.q3_tail_audit["refused"] += 1
            return None
        if not self._q3_tail_activated:
            self._q3_tail_activated = True
            self.q3_tail_audit.update({
                "activated": True,
                "activated_step": None,   # authoritative step/vtime is in the trace
                "confirmed_at_activation": (
                    len(ks.by_status(ChannelStatus.ACTIVE)) +
                    len(ks.by_status(ChannelStatus.READY)) +
                    len(ks.by_status(ChannelStatus.CLEARED))),
                "tasks_at_activation": len(tasks),
            })
        dist, service, start = self._order_pricing(tasks, position,
                                                   current_channel)
        order, method = self._order_solve(dist, service, start)
        planned_cost = self._order_path_cost(order, dist, service, start)
        if self.q3_order_tail_margin_s > 0.0:
            local_cost = self._order_local_cost(tasks, dist, service, start)
            if planned_cost > local_cost - self.q3_order_tail_margin_s:
                self.q3_tail_audit["refused"] += 1
                return None
        chosen = tasks[order[0]]
        self.q3_tail_audit["switched"] += 1
        if self.decision_listener is not None:
            trace = self._trace_base(ks, "q3_tail_order")
            trace.update({
                "activated": True,
                "activated_step": self.q3_tail_audit["activated_step"],
                "confirmed_channels": (
                    len(ks.by_status(ChannelStatus.ACTIVE)) +
                    len(ks.by_status(ChannelStatus.READY)) +
                    len(ks.by_status(ChannelStatus.CLEARED))),
                "tasks": len(tasks),
                "task_kinds": {"active": sum(1 for x in tasks
                                             if x["kind"] == "active"),
                               "ready": sum(1 for x in tasks
                                            if x["kind"] == "ready"),
                               "certificate": certificate_tasks},
                "method": method,
                "planned_cost_s": round(planned_cost, 3),
                "margin_s": self.q3_order_tail_margin_s,
                "remaining_anchors": int(max(
                    0, len(self._coverage_points) - self._coverage_index)),
            })
            trace["selected"] = {
                "kind": chosen["kind"],
                "channel": chosen.get("channel"),
                "point": [round(chosen["point"][0], 3),
                          round(chosen["point"][1], 3)],
            }
            trace["tie_break"] = ("tail plan: open path over live stops only "
                                  "(no certificate anchors)")
            self._emit(trace)
        return chosen["mission"]

    def _order_tasks(self, ks, position):
        """Executable, unfinished stop tasks of this decision.

        A task is ``{"kind", "point", "mission"}``.  Pending certificate points
        come first (they carry the finite proof), then one measurement stop per
        live ACTIVE channel at its current best candidate point.  READY clears
        are not planned here: production already gives them priority before
        this point in ``decide``, so admitting them would double-book the same
        action.
        """
        tasks = []
        for index in range(self._coverage_index, len(self._coverage_points)):
            point = self._coverage_points[index]
            mission = Mission(
                "scan", point,
                channels=[ch.channel_id for ch in ks.unknown],
                meta={"coverage_scan": True, "kind": "coverage",
                      "order_planned": True})
            tasks.append({"kind": "certificate", "index": index,
                          "point": (float(point[0]), float(point[1])),
                          "mission": mission})
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            if self.fallback.in_fallback(ch.channel_id):
                continue
            points = self._candidate_points(ch, position)
            if not points:
                continue
            point = points[0]
            if math.dist(point, position) <= 1.0 and len(points) > 1:
                point = points[1]
            tasks.append({
                "kind": "active", "channel": ch.channel_id,
                "point": (float(point[0]), float(point[1])),
                "mission": Mission("measure", point, channel=ch.channel_id,
                                   meta={"kind": "order_measure",
                                         "order_planned": True})})
        return tasks

    def _order_pricing(self, tasks, position, current_channel):
        """Travel matrix, per-stop service time and start distances (seconds)."""
        planner = getattr(self, "stop_planner", None)
        service = []
        for task in tasks:
            measures = []
            if planner is not None:
                plan = planner(task["mission"])
                if plan.get("kind") == "clear":
                    measures = list(plan.get("success", ()))
                else:
                    measures = list(plan.get("measures", ()))
            service.append(self._sequence_cost(measures, current_channel)
                           if measures else C.MEASURE_TIME)
        count = len(tasks)
        dist = [[0.0] * count for _ in range(count)]
        for i in range(count):
            for j in range(count):
                if i != j:
                    dist[i][j] = (math.dist(tasks[i]["point"],
                                            tasks[j]["point"]) / C.MOVE_SPEED)
        start = [math.dist(position, task["point"]) / C.MOVE_SPEED
                 for task in tasks]
        return dist, service, start

    @staticmethod
    def _order_path_cost(order, dist, service, start):
        if not order:
            return 0.0
        total = start[order[0]] + service[order[0]]
        for a, b in zip(order, order[1:]):
            total += dist[a][b] + service[b]
        return total

    @staticmethod
    def _order_held_karp(dist, service, start):
        """Exact open path through every task, starting at the current stop."""
        count = len(dist)
        size = 1 << count
        inf = float("inf")
        dp = [[inf] * count for _ in range(size)]
        parent = [[-1] * count for _ in range(size)]
        for i in range(count):
            dp[1 << i][i] = start[i] + service[i]
        for mask in range(size):
            row = dp[mask]
            for last in range(count):
                current = row[last]
                if current == inf:
                    continue
                base = dist[last]
                for nxt in range(count):
                    if mask & (1 << nxt):
                        continue
                    cand = current + base[nxt] + service[nxt]
                    if cand < dp[mask | (1 << nxt)][nxt]:
                        dp[mask | (1 << nxt)][nxt] = cand
                        parent[mask | (1 << nxt)][nxt] = last
        full = size - 1
        best, best_last = inf, -1
        for i in range(count):
            if dp[full][i] < best:
                best, best_last = dp[full][i], i
        order = []
        mask, last = full, best_last
        while last != -1:
            order.append(last)
            previous = parent[mask][last]
            mask ^= (1 << last)
            last = previous
        order.reverse()
        return order

    def _order_local_search(self, dist, service, start, passes=3):
        """Nearest-neighbour seed + 2-opt + or-opt (O(1) move deltas)."""
        count = len(dist)
        left = set(range(count))
        first = min(left, key=lambda i: start[i] + service[i])
        order = [first]
        left.discard(first)
        while left:
            last = order[-1]
            nxt = min(left, key=lambda i: dist[last][i] + service[i])
            order.append(nxt)
            left.discard(nxt)

        def into(index):
            if index == 0:
                return start[order[0]]
            return dist[order[index - 1]][order[index]]

        for _ in range(max(1, passes)):
            improved = False
            for i in range(count - 1):
                for j in range(i + 1, count):
                    previous = order[i - 1] if i > 0 else None
                    tail = order[j + 1] if j + 1 < count else None
                    old = into(i) + (into(j + 1) if tail is not None else 0.0)
                    new = ((start[order[j]] if previous is None
                            else dist[previous][order[j]]) +
                           (dist[order[i]][tail] if tail is not None else 0.0))
                    if new + 1e-9 < old:
                        order[i:j + 1] = reversed(order[i:j + 1])
                        improved = True
            for i in range(count):
                node = order[i]
                rest = order[:i] + order[i + 1:]
                for k in range(count):
                    if k == i:
                        continue
                    cand = rest[:k] + [node] + rest[k:]
                    if (self._order_path_cost(cand, dist, service, start) + 1e-9 <
                            self._order_path_cost(order, dist, service, start)):
                        order = cand
                        improved = True
                        break
            if not improved:
                break
        return order

    def _order_solve(self, dist, service, start):
        count = len(dist)
        if count <= 3:
            return list(range(count)), "trivial"
        if count <= self.order_exact_max:
            return self._order_held_karp(dist, service, start), "held-karp"
        return (self._order_local_search(dist, service, start),
                "nn+2opt+oropt")

    def _order_local_cost(self, order_tasks, dist, service, start):
        """Planned cost of the *production-priority* order over the same tasks.

        Production takes the pending certificate stop first (the cursor point)
        and then the live stops, so that is the order this reference prices.
        Both sides are priced with the identical ``plan_stop``-derived service
        times, so the comparison is apples to apples.
        """
        certificate = [i for i, task in enumerate(order_tasks)
                       if task["kind"] == "certificate"]
        live = [i for i, task in enumerate(order_tasks)
                if task["kind"] != "certificate"]
        return self._order_path_cost(certificate + live, dist, service, start)

    def _order_step(self, ks, position, current_channel):
        """First stop of the global plan, or None to keep the local rule.

        Four-ledger net gate (t23): the plan is compared against the
        production-priority order **over the same task set**, but the task set
        is first capped by ``order_live_budget`` (the live/ACTIVE measurement
        stops the plan may carry).  Without that cap the comparison was not
        like-for-like - t11 showed the planner takes many extra measurement
        stops, and t15's order-cost-only gate could therefore never fire,
        because an optimal order over a richer task set is always cheaper.
        With the cap, the two ledgers price the same work, and the gate only
        lets the plan through when its ``travel + service`` beats the
        production order by at least ``order_plan_margin_s`` seconds.
        """
        tasks = self._order_tasks(ks, position)
        if self.order_live_budget > 0:
            certificate = [t for t in tasks if t["kind"] == "certificate"]
            live = [t for t in tasks if t["kind"] != "certificate"]
            live.sort(key=lambda t: math.dist(position, t["point"]))
            tasks = certificate + live[:self.order_live_budget]
        if len(tasks) < 2:
            return None
        dist, service, start = self._order_pricing(tasks, position,
                                                  current_channel)
        order, method = self._order_solve(dist, service, start)
        planned_cost = self._order_path_cost(order, dist, service, start)
        local_cost = None
        if self.order_net_gate:
            local_cost = self._order_local_cost(tasks, dist, service, start)
            net = planned_cost - local_cost
            self._order_gate_stats["evaluated"] += 1
            self._order_gate_stats["by_n"].setdefault(
                self.mode, {"evaluated": 0, "blocked": 0, "blocked_loss_s": 0.0,
                            "switched": 0})
            stats = self._order_gate_stats["by_n"][self.mode]
            stats["evaluated"] += 1
            if planned_cost > local_cost - self.order_plan_margin_s:
                # Net ledger is not negative enough: do not intervene at all
                # this decision (the four-ledger net gate).
                self._order_gate_stats["blocked"] += 1
                self._order_gate_stats["blocked_loss_s"] += net
                stats["blocked"] += 1
                stats["blocked_loss_s"] += net
                if self.decision_listener is not None:
                    trace = self._trace_base(ks, "order_plan")
                    trace.update({"tasks": len(tasks), "method": method,
                                  "gated_out": True,
                                  "planned_cost_s": round(planned_cost, 3),
                                  "reference_cost_s": round(local_cost, 3),
                                  "net_s": round(net, 3),
                                  "margin_s": self.order_plan_margin_s,
                                  "live_budget": self.order_live_budget})
                    self._emit(trace)
                return None
            self._order_gate_stats["switched"] += 1
            stats["switched"] += 1
        chosen = tasks[order[0]]
        if chosen["kind"] == "certificate":
            # Keep the cursor honest: the executed anchor moves to the cursor
            # and the cursor advances, so `visited + remaining` still describes
            # the same proof.
            points = list(self._coverage_points)
            at = chosen["index"]
            cursor = self._coverage_index
            points[cursor], points[at] = points[at], points[cursor]
            self._coverage_points = points
            self._coverage_index += 1
            self._note_q3_scan_point(points[cursor])
            mission = Mission(
                "scan", points[cursor],
                channels=[ch.channel_id for ch in ks.unknown],
                meta={"coverage_scan": True, "kind": "coverage",
                      "order_planned": True})
        else:
            mission = chosen["mission"]
        if self.decision_listener is not None:
            trace = self._trace_base(ks, "order_plan")
            trace.update({
                "tasks": len(tasks),
                "method": method,
                "order_kinds": [tasks[i]["kind"] for i in order[:12]],
                "selected": {"kind": chosen["kind"],
                             "point": [round(chosen["point"][0], 3),
                                       round(chosen["point"][1], 3)]},
                "plan_cost_s": round(self._order_path_cost(order, dist, service,
                                                           start), 3),
            })
            self._emit(trace)
        return mission

    def _order_reorder_certificate_points(self, ks, position):
        """Q4: reorder the *remaining* certificate points by a global path."""
        pending = list(range(self._coverage_index, len(self._coverage_points)))
        if len(pending) < 3:
            return
        points = [self._coverage_points[i] for i in pending]
        dist = [[math.dist(a, b) / C.MOVE_SPEED for b in points]
                for a in points]
        service = [C.MEASURE_TIME + 1.0] * len(points)
        start = [math.dist(position, p) / C.MOVE_SPEED for p in points]
        order, _ = self._order_solve(dist, service, start)
        reordered = [points[i] for i in order]
        head = list(self._coverage_points[:self._coverage_index])
        self._coverage_points = head + reordered

    def _q4_pair_stage_point(self, ch, position, stage):
        """Stage 0: near the MEC centre; stage 1: cross-bearing baseline."""
        if ch.mec is None:
            return None
        centre = (float(ch.mec[0][0]), float(ch.mec[0][1]))
        if stage == 0:
            return centre
        dirs = [obs for obs in ch.observations
                if obs.get("result") == "direction" and "position" in obs]
        if not dirs:
            return None
        last = dirs[-1]
        theta = math.radians(float(last["bearing"]))
        offset = self.q4_pair_baseline_m
        best = None
        for sign in (-1.0, 1.0):
            angle = theta + sign * math.pi / 2.0
            point = (last["position"][0] + offset * math.cos(angle),
                     last["position"][1] + offset * math.sin(angle))
            if math.hypot(point[0], point[1]) > C.OMEGA_RADIUS:
                continue
            key = (math.dist(point, position), sign)
            if best is None or key < best[0]:
                best = (key, point)
        return None if best is None else best[1]

    def _q4_pair_step(self, ks, position, current_channel):
        """Next mission of the pairing template, or None for the normal pool."""
        plan = self._q4_pair_plan
        if plan is not None:
            channel = ks[plan["channel"]] if plan["channel"] in ks.channels \
                else None
            if (channel is None or self.fallback.in_fallback(plan["channel"])
                    or channel.status not in (ChannelStatus.ACTIVE,
                                              ChannelStatus.READY)):
                self._q4_pair_plan = None
                plan = None
        if plan is None:
            best = None
            for ch in ks.by_status(ChannelStatus.ACTIVE):
                if self.fallback.in_fallback(ch.channel_id) or ch.mec is None:
                    continue
                dirs = [obs for obs in ch.observations
                        if obs.get("result") == "direction"]
                if not dirs:
                    continue
                if (self.q4_pair_max_radius_m > 0.0 and
                        ch.mec_radius > self.q4_pair_max_radius_m):
                    continue
                distance = math.dist(position, ch.mec[0])
                if (self.q4_pair_max_distance_m > 0.0 and
                        distance > self.q4_pair_max_distance_m):
                    continue
                key = (distance, ch.mec_radius, ch.channel_id)
                if best is None or key < best[0]:
                    best = (key, ch)
            if best is None:
                return None
            self._q4_pair_plan = {"channel": best[1].channel_id, "stage": 0,
                                  "measures": 0}
            plan = self._q4_pair_plan
        channel = ks[plan["channel"]]
        stage = plan["stage"]
        point = self._q4_pair_stage_point(channel, position, stage)
        if point is None:
            self._q4_pair_plan = None
            return None
        if stage >= 2:
            mission = Mission("clear", (float(channel.mec[0][0]),
                                        float(channel.mec[0][1])),
                              channel=plan["channel"],
                              meta={"kind": "q4_pair_clear",
                                    "pair_stage": stage,
                                    "pair_channel": plan["channel"]})
            self._q4_pair_plan = None
        else:
            mission = Mission("measure", point, channel=plan["channel"],
                              meta={"kind": "q4_pair_measure",
                                    "pair_stage": stage,
                                    "pair_channel": plan["channel"]})
            plan["stage"] = stage + 1
            plan["measures"] = plan.get("measures", 0) + 1
        if self.decision_listener is not None:
            trace = self._trace_base(ks, "q4_pair")
            trace.update({"channel": plan["channel"],
                          "stage": mission.meta["pair_stage"],
                          "kind": mission.kind,
                          "point": [round(mission.target[0], 3),
                                    round(mission.target[1], 3)]})
            self._emit(trace)
        return mission

    def _rolling_coverage_candidate(self, ks, position=None):
        if (self.q4_covtrim and self.mode == "Q4" and
                self._q4_known_channels < self.q4_covtrim_min_known):
            # Trim the absence proof while the run is still a search for
            # MAX_SOURCES sources; the fallback cover and the cardinality cap
            # remain the completion path, so no criterion is relaxed.
            return None
        if (self.order_plan and self.order_plan_q4 and self.mode == "Q4"
                and position is not None):
            self._order_reorder_certificate_points(ks, position)
        return super()._rolling_coverage_candidate(ks, position)

    # ------------------------------------------------------------------
    # Joint (stop x demand-set) planning (default OFF, see __init__)
    # ------------------------------------------------------------------
    def _joint_demands(self, ks, position):
        """Demands of this decision: (kind, channel, point).

        A demand is what still has to be *served*, not where:  a pending
        certificate witness, a localisation measurement of a live ACTIVE
        channel, or a clear of a READY channel.  Merging happens later.
        """
        demands = []
        for index in range(self._coverage_index, len(self._coverage_points)):
            point = self._coverage_points[index]
            demands.append({"kind": "certificate", "index": index,
                            "channel": None,
                            "point": (float(point[0]), float(point[1]))})
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            if self.fallback.in_fallback(ch.channel_id):
                continue
            points = self._candidate_points(ch, position)
            if not points:
                continue
            point = points[0]
            if math.dist(point, position) <= 1.0 and len(points) > 1:
                point = points[1]
            demands.append({"kind": "active", "channel": ch.channel_id,
                            "point": (float(point[0]), float(point[1]))})
        return demands

    def _joint_stops(self, ks, position, current_channel):
        """(stop, demand set) pairs, priced with the executor's plan_stop.

        Single-linkage merge: a certificate/measurement demand becomes a stop;
        every other demand whose point lies within ``order_joint_merge_m`` of
        that stop rides along on the same stop.  The mission carries the
        companions through ``joint_channels`` (ACTIVE only - the runner
        executes them as ordinary /measure calls at the same stop), so the
        stop's plan - and therefore its cost - is exactly what will run.
        """
        demands = self._joint_demands(ks, position)
        if not demands:
            return []
        anchor_kinds = ("certificate", "active")
        anchors = [d for d in demands if d["kind"] in anchor_kinds]
        companions = [d for d in demands if d["kind"] not in anchor_kinds]
        stops = []
        used = set()
        for rank, anchor in enumerate(anchors):
            companions_here = []
            for demand in companions:
                if id(demand) in used:
                    continue
                if (math.dist(anchor["point"], demand["point"])
                        <= self.order_joint_merge_m):
                    companions_here.append(demand)
                    used.add(id(demand))
            # ACTIVE demands that are *not* the anchor can still be served at
            # this stop when their own best point is nearby.
            for demand in anchors:
                if demand is anchor or id(demand) in used:
                    continue
                if (demand["kind"] == "active" and
                        math.dist(anchor["point"], demand["point"])
                        <= self.order_joint_merge_m):
                    companions_here.append(demand)
                    used.add(id(demand))
            channels = [d["channel"] for d in companions_here
                        if d["channel"] is not None]
            if anchor["kind"] == "certificate":
                meta = {"coverage_scan": True, "kind": "coverage",
                        "order_planned": True, "joint_demands": len(channels) + 1}
                if channels:
                    meta["joint_channels"] = channels
                mission = Mission("scan", anchor["point"],
                                  channels=[ch.channel_id for ch in ks.unknown],
                                  meta=meta)
            else:
                meta = {"kind": "order_measure", "order_planned": True,
                        "joint_demands": len(channels) + 1}
                if channels:
                    meta["joint_channels"] = channels
                mission = Mission("measure", anchor["point"],
                                  channel=anchor["channel"], meta=meta)
            stops.append({"kind": anchor["kind"], "index": anchor.get("index"),
                          "channel": anchor["channel"], "point": anchor["point"],
                          "demands": len(channels) + 1, "mission": mission})
        return stops

    def _order_joint_step(self, ks, position, current_channel):
        """First stop of the joint plan, or None to keep the local rule.

        (Named apart from the section-19 ``_joint_step``, which chooses a scan
        set for one stop and returns ``(mission, rows)``.)
        """
        stops = self._joint_stops(ks, position, current_channel)
        if len(stops) < 2:
            return None
        tasks = [{"kind": s["kind"], "point": s["point"],
                  "mission": s["mission"], "index": s.get("index")}
                 for s in stops]
        dist, service, start = self._order_pricing(tasks, position,
                                                  current_channel)
        order, method = self._order_solve(dist, service, start)
        chosen = tasks[order[0]]
        if chosen["kind"] == "certificate":
            points = list(self._coverage_points)
            at = chosen["index"]
            cursor = self._coverage_index
            points[cursor], points[at] = points[at], points[cursor]
            self._coverage_points = points
            self._coverage_index += 1
            self._note_q3_scan_point(points[cursor])
            mission = chosen["mission"]
            mission.target = points[cursor]
        else:
            mission = chosen["mission"]
        if self.decision_listener is not None:
            trace = self._trace_base(ks, "order_joint")
            trace.update({
                "demands": sum(s["demands"] for s in stops),
                "stops": len(stops),
                "merged": sum(1 for s in stops if s["demands"] > 1),
                "method": method,
                "plan_cost_s": round(self._order_path_cost(order, dist, service,
                                                           start), 3),
                "selected": {"kind": chosen["kind"],
                             "point": [round(chosen["point"][0], 3),
                                       round(chosen["point"][1], 3)]},
            })
            self._emit(trace)
        return mission

    @staticmethod
    def _observed_at(ch, point):
        return any(math.dist(point, obs["position"]) <= 1.0
                   for obs in ch.observations if "position" in obs)

    def _joint_active_channels(self, ks, point, primary):
        """Rank observable ACTIVE channels that can benefit from this stop.

        The envelope test is deliberately conservative: a point is eligible
        when the channel MEC can intersect the guaranteed 1000 m signal disk.
        It does not assert a signal outcome or alter the channel geometry;
        those still come only from the simulator response and verifier.
        """
        if self.mode != "Q4" or self.joint_active_measure_limit <= 0:
            return []
        ranked = []
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            if ch.channel_id == primary or self.fallback.in_fallback(ch.channel_id):
                continue
            if self._observed_at(ch, point) or ch.mec is None:
                continue
            center, radius = ch.mec
            reach = C.R_EFF_MIN + max(0.0, float(radius))
            distance = math.dist(point, center)
            overlap = reach + self.joint_active_margin_m - distance
            if overlap < 0.0:
                continue
            dirs = sum(obs["result"] == "direction" for obs in ch.observations)
            no_signal = sum(obs["result"] == "no_signal" for obs in ch.observations)
            # Prefer channels with a broad unresolved envelope and little
            # directional evidence; the tie-break is deterministic.
            value = overlap / (1.0 + dirs) + 80.0 * min(1.0, no_signal / 3.0)
            ranked.append((value, -distance, -ch.channel_id, ch.channel_id))
        ranked.sort(reverse=True)
        return [item[-1] for item in ranked[:self.joint_active_measure_limit]]

    def _note_q3_scan_point(self, target):
        """Remember where a Q3 stop already scanned the UNKNOWN channels.

        The stop spacing is what makes the information-safe UNKNOWN scan filter
        effective: clustered stops re-measure the same channels, while spread
        stops keep discovering new ones.
        """
        if self.mode != "Q3":
            return
        point = (float(target[0]), float(target[1]))
        for prior in self._q3_scan_points:
            if math.dist(prior, point) <= 1.0:
                return
        self._q3_scan_points.append(point)

    def _q3_spread_ok(self, target):
        if self.q3_work_first_min_spread_m is None:
            return True
        limit = self.q3_work_first_min_spread_m
        if not self._q3_scan_points:
            return True
        return min(math.dist(target, prior)
                   for prior in self._q3_scan_points) >= limit

    def _q3_merged_allowed(self, ks):
        """Whether the merged route may still pre-empt the certificate ring.

        Two observation-only inputs: an optional density gate (how many
        distinct channels the first few certificate stops confirmed) and an
        optional dry-spell counter (how many completed clears failed to expose
        a new channel).  Neither reads the source count, the scenario or any
        truth value.
        """
        if self.q3_merged_density_gate > 0 and not self._q3_merged_enabled:
            if self._coverage_index < self.q3_merged_gate_after_points:
                return False
            known = (len(ks.by_status(ChannelStatus.ACTIVE))
                     + len(ks.by_status(ChannelStatus.READY))
                     + len(ks.by_status(ChannelStatus.CLEARED)))
            if known >= self.q3_merged_density_gate:
                self._q3_merged_enabled = True
            else:
                return False
        if self.q3_merged_switch_after_misses <= 0:
            return True
        return not self._q3_merged_disabled

    def _q3_scan_mode(self):
        """Opportunistic scan mode requested by merged-route stops."""
        if self._q3_scan_disabled:
            return "active_only"
        if self.valued_scan_share > 0.0:
            return "valued"
        return None

    def _variant_value(self, ks, point, variant, discovery_cache=None):
        """Value (seconds) of the channels a scan variant would add.

        Pure function: it never mutates scheduler state, so it is safe to call
        while evaluating candidates that are not selected.  The two terms are
        observable-only proxies:
          * an ACTIVE bearing is worth the part of its region radius the new
            ray can still cut (crossing angle against its last bearing);
          * an UNKNOWN measurement is worth the share of that channel's still
            possible region this stop can see, times the value of an early
            discovery.
        """
        value = 0.0
        if variant in ("active", "full"):
            gate = math.sin(math.radians(max(
                1.0, self.active_scan_angle_gate_deg or 30.0)))
            for ch in ks.by_status(ChannelStatus.ACTIVE):
                factor = self._bearing_cut_value(ch, point)
                if factor >= gate:
                    value += (factor * min(ch.mec_radius, 1500.0)
                              / C.MOVE_SPEED * self.joint_active_value_scale)
        if variant in ("discover", "full") and ks.unknown:
            key = (round(float(point[0]), 3), round(float(point[1]), 3))
            if discovery_cache is not None and key in discovery_cache:
                share = discovery_cache[key]
            else:
                share = self._discovery_share_at(ks, point)
                if discovery_cache is not None:
                    discovery_cache[key] = share
            value += share * self.joint_discovery_value_s
        return value

    def _discovery_share_at(self, ks, point):
        """Summed discovery share of the UNKNOWN channels at this point."""
        grid = self._nbv_grid()
        total = 0.0
        for channel in ks.unknown:
            if not channel.certificate_region:
                total += 1.0
                continue
            total += discovery_share(channel, point, grid)
        return total

    def _joint_scan_candidates(self, ks, position, current_channel, base):
        """Price every (stop, scan set) pair that shares ``base``'s stop.

        Each variant is priced with the runner's own stop plan and scored as
        ``plan cost + continuation proxy - added value``.  The candidate list is
        returned so the decision trace can show that different scan sets really
        competed for the same stop.
        """
        planner = getattr(self, "stop_planner", None)
        rows = []
        for variant in ("primary", "active", "discover", "full"):
            mission = Mission("measure", base.target, channel=base.channel,
                              meta=dict(base.meta))
            mission.meta["scan_variant"] = variant
            if planner is not None:
                plan = planner(mission)
                measures = len(plan.get("measures", ()))
            else:
                measures = 1
            travel = math.dist(position, mission.target) / C.MOVE_SPEED
            immediate = travel + measures * C.MEASURE_TIME
            continuation = self._rolling_future_proxy(ks, mission.target,
                                                      mission)
            value = self._variant_value(ks, mission.target, variant)
            rows.append({
                "variant": variant,
                "measures": measures,
                "immediate": immediate,
                "continuation": continuation,
                "value": value,
                "score": (immediate + self.joint_continuation_weight *
                          continuation - value),
                "mission": mission,
            })
        return rows

    def _joint_step(self, ks, position, current_channel):
        """Choose (stop, scan set) by comparing the priced full actions."""
        base = self._active_measure(ks, position, current_channel)
        if base is None:
            return None, None
        rows = self._joint_scan_candidates(ks, position, current_channel, base)
        if not rows:
            return None, None
        best = min(rows, key=lambda row: (row["score"], row["variant"]))
        mission = best["mission"]
        # Kept for audits: the priced candidate set of the latest joint choice.
        self._last_joint_rows = rows
        if best["variant"] == "full":
            # Committed only for the action actually returned; evaluating a
            # candidate must never move scheduler state.
            self._last_full_scan_position = (float(mission.target[0]),
                                             float(mission.target[1]))
        return mission, rows

    def _emit_joint_trace(self, ks, mission, rows, ring_point, position):
        """Record the joint (stop, scan set) competition.

        Every scan variant of the chosen stop, the certificate stop it was
        compared against, and the selected pair are written to the decision
        trace, so "different scan sets competed" is checkable from artifacts.
        """
        if self.decision_listener is None:
            return
        trace = self._trace_base(ks, "joint_stop")
        trace["selected"] = {
            "kind": mission.kind,
            "channel": mission.channel,
            "point": [round(mission.target[0], 3), round(mission.target[1], 3)],
            "scan_variant": mission.meta.get("scan_variant"),
        }
        trace["candidates"] = [{
            "variant": row["variant"],
            "measures": row["measures"],
            "immediate": round(row["immediate"], 3),
            "continuation": round(row["continuation"], 3),
            "value": round(row["value"], 3),
            "score": round(row["score"], 3),
        } for row in rows]
        if ring_point is not None:
            trace["candidates"].append({
                "variant": "certificate_stop",
                "point": [round(ring_point[0], 3), round(ring_point[1], 3)],
                "immediate": round(math.dist(position, ring_point)
                                   / C.MOVE_SPEED, 3),
            })
        trace["tie_break"] = ("min (immediate + %.2f*continuation - value, "
                              "variant name)" % self.joint_continuation_weight)
        self._emit(trace)

    def _joint_scan_variant(self, ks, point):
        """Spatial gate used when the joint comparison is disabled.

        A stop at least ``q3_scan_spacing_m`` away from the last discovery
        survey takes the full set; a nearer one takes only the ACTIVE bearings
        that can still cut a region; otherwise only its primary channel.
        """
        if self.q3_scan_spacing_m <= 0.0:
            return None
        last = self._last_full_scan_position
        if last is None or math.dist(point, last) >= self.q3_scan_spacing_m:
            self._last_full_scan_position = (float(point[0]), float(point[1]))
            return "full"
        gate = math.sin(math.radians(max(1.0, self.active_scan_angle_gate_deg)))
        for ch in ks.by_status(ChannelStatus.ACTIVE):
            if self._bearing_cut_value(ch, point) >= gate:
                return "active"
        return "primary"

    def _q3_commit_step(self, ks, position, current_channel):
        """Walk straight into one known source instead of orbiting it.

        The origin bearing already places the source on a ray, so the
        MEC-centre chain advances roughly half of the remaining radius per
        measurement: the robot approaches the target monotonically while every
        stop keeps scanning the UNKNOWN channels, which is what makes the
        discovery ride along with the clear route.  Only observable state is
        used, and the finite ring stays available whenever no live channel is
        known.
        """
        target = self._q3_target
        if target is not None:
            if target not in ks.channels:
                target = None
            else:
                channel = ks[target]
                if (channel.status in (ChannelStatus.CLEARED,
                                       ChannelStatus.CERTIFIED_ABSENT) or
                        self.fallback.in_fallback(target) or
                        self._q3_target_steps >= self.q3_target_max_steps):
                    target = None
        if target is None:
            best = None
            for channel in ks.by_status(ChannelStatus.ACTIVE):
                if (self.fallback.in_fallback(channel.channel_id) or
                        channel.mec is None):
                    continue
                key = (math.dist(position, channel.mec[0]),
                       channel.channel_id)
                if best is None or key < best[0]:
                    best = (key, channel.channel_id)
            if best is None:
                self._q3_target = None
                self._q3_target_steps = 0
                return None
            target = best[1]
            self._q3_target_steps = 0
        channel = ks[target]
        if channel.status != ChannelStatus.ACTIVE or channel.mec is None:
            self._q3_target = None
            self._q3_target_steps = 0
            return None
        point = channel.mec[0]
        if math.dist(position, point) < 5.0:
            # The chain has arrived: step sideways so the next bearing is not
            # a repeat of the one just taken, then continue.
            alternatives = [p for p in localization.candidate_points(
                channel, position,
                failed_points=self.failed_points.get(target),
                opportunistic_reuse=True)
                if math.dist(position, p) >= 5.0]
            if not alternatives:
                self._q3_target = None
                self._q3_target_steps = 0
                return None
            point = min(alternatives,
                        key=lambda p: (math.dist(position, p), p[0], p[1]))
        self._q3_target = target
        self._q3_target_steps += 1
        self._note_q3_scan_point(point)
        meta = {"kind": "approach", "direct_center": True, "q3_commit": True}
        mode = self._q3_scan_mode()
        if mode is not None:
            meta["scan_mode"] = mode
        return Mission("measure", point, channel=target, meta=meta)

    def on_probe_failure(self, channel_id, point):
        """Register a clear that failed outside the finite fallback.

        A failed clear is real information: the source is *not* inside the
        20 m disk around that point.  The convex feasible region cannot
        represent a hole, so the exclusion is kept here, in the decision
        layer, where the probe ladder consumes it.
        """
        if point is None:
            return
        self._probe_failures.setdefault(int(channel_id), []).append(
            (float(point[0]), float(point[1])))

    def probe_attempts(self, channel_id):
        return len(self._probe_failures.get(int(channel_id), ()))

    def _ladder_probe_point(self, ch):
        """Next clear point given the failed clears already paid for.

        Sampling the (small) MEC disk and dropping the disks excluded by
        earlier failures gives a decision-layer set that does contain holes.
        If the survivors fit inside a 20 m circle minus the sampling
        resolution, clearing at its centre is guaranteed; otherwise that
        centre is still the best available probe.  Certification state, the
        convex region and the verifier are untouched.
        """
        center, radius = ch.mec
        failed = self._probe_failures.get(ch.channel_id, ())
        if not failed:
            return center, False
        step = max(4.0, float(radius) / 6.0)
        samples = []
        polygon = ch.feasible_region
        count = int(math.ceil(float(radius) / step)) + 1
        for i in range(-count, count + 1):
            for j in range(-count, count + 1):
                x = center[0] + i * step
                y = center[1] + j * step
                dx, dy = x - center[0], y - center[1]
                if dx * dx + dy * dy > radius * radius:
                    continue
                if polygon and not contains_point(polygon, (x, y),
                                                  eps=-C.EPS):
                    # The MEC disk is only a bound; the source must also lie
                    # inside the feasible region, so a probe outside it would
                    # be wasted.
                    continue
                if any((x - fx) ** 2 + (y - fy) ** 2 <= C.CLEAR_RADIUS ** 2
                       for fx, fy in failed):
                    continue
                samples.append((x, y))
        if not samples:
            return None, False
        circle_center, circle_radius = mec(samples)
        if circle_radius + step * 0.71 <= C.CLEAR_RADIUS:
            return circle_center, True
        return circle_center, False

    def _work_first_active(self, ks, position, current_channel):
        """Pick a live-channel action to run before the next ring point.

        Returning ``None`` hands the decision back to the finite coverage ring,
        so the ring still advances whenever nothing live is worth doing and the
        absence certificate cannot be starved.  Only observable state is used:
        channel status, MEC and the recorded observations.
        """
        active = [ch for ch in ks.by_status(ChannelStatus.ACTIVE)
                  if not self.fallback.in_fallback(ch.channel_id)]
        if not active:
            return None
        mission = self._active_measure(ks, position, current_channel,
                                       active_override=active)
        if mission is None or mission.channel is None:
            return None
        channel = ks[mission.channel]
        if (self.q3_work_first_max_mec_m is not None and
                channel.mec_radius > self.q3_work_first_max_mec_m):
            return None
        if (self.q3_work_first_max_distance_m is not None and
                math.dist(position, mission.target) >
                self.q3_work_first_max_distance_m):
            return None
        if not self._q3_spread_ok(mission.target):
            # This stop would re-scan ground already covered; leave the ring to
            # do the discovery work instead.
            return None
        mission.meta["work_first"] = True
        mode = self._q3_scan_mode()
        if mode is not None:
            mission.meta["scan_mode"] = mode
        self._note_q3_scan_point(mission.target)
        return mission

    def decide(self, ks, position, current_channel):
        self._joint_route_position = position
        self._decision_position = position
        if (self.mode == "Q4" and self.q4_pair
                and not self.fallback.active_fallbacks()):
            # Pairing template first: two deliberate measurements on one
            # channel, then a clear at the shrunken region.  It only proposes;
            # every other decision stays with the ordinary policy.
            paired = self._q4_pair_step(ks, position, current_channel)
            if paired is not None:
                return paired
        if (self.mode == "Q3" and
                (self.q3_merged_switch_after_misses > 0 or
                 self.q3_scan_stop_after_misses > 0)):
            known = (len(ks.by_status(ChannelStatus.ACTIVE))
                     + len(ks.by_status(ChannelStatus.READY))
                     + len(ks.by_status(ChannelStatus.CLEARED)))
            cleared = len(ks.cleared)
            if cleared > self._q3_cleared_prev:
                # A clear just completed.  The merged route keeps paying only
                # while clearing one source keeps exposing the next one, so
                # the dry spell is counted per completed clear, not per
                # decision: a localization chain of five decisions must not
                # look like a stalled search.
                if known > self._q3_known_at_clear:
                    self._q3_misses = 0
                    # A new channel appeared: the case is still producing
                    # sources, so the merged route becomes worthwhile again.
                    self._q3_merged_disabled = False
                else:
                    self._q3_misses += 1
                    if (self.q3_merged_switch_after_misses > 0 and
                            self._q3_misses >=
                            self.q3_merged_switch_after_misses):
                        self._q3_merged_disabled = True
                    if (self.q3_scan_stop_after_misses > 0 and
                            self._q3_misses >=
                            self.q3_scan_stop_after_misses):
                        self._q3_scan_disabled = True
                self._q3_known_at_clear = known
                self._q3_cleared_prev = cleared
            self._q3_known_prev = known
        if self.mode == "Q3":
            self._q3_known_channels = (
                len(ks.by_status(ChannelStatus.ACTIVE))
                + len(ks.by_status(ChannelStatus.READY))
                + len(ks.by_status(ChannelStatus.CLEARED)))
        if (self.mode == "Q3" and self._q3_limit_locked is None
                and self._coverage_index >= 1):
            self._q3_limit_locked = (
                self.Q3_NO_SHRINK_LIMIT_HIGH
                if len(ks.by_status(ChannelStatus.ACTIVE)) >= self.Q3_LIMIT_SWITCH_ACTIVE
                else self.Q3_NO_SHRINK_LIMIT)
            self.fallback.no_shrink_limit = self._q3_limit_locked
        if self.mode == "Q4":
            known = (len(ks.by_status(ChannelStatus.ACTIVE))
                     + len(ks.by_status(ChannelStatus.READY))
                     + len(ks.by_status(ChannelStatus.CLEARED)))
            self._q4_known_channels = known
            self.fallback.no_shrink_limit = (
                self.Q4_NO_SHRINK_LIMIT_HIGH
                if known >= self.Q4_LIMIT_SWITCH_KNOWN
                else self.Q4_NO_SHRINK_LIMIT)
        if self.fallback.active_fallbacks():
            return self._fallback_route(ks, position, current_channel)
        if self._maybe_enter_early_fallback(ks, position):
            return self._fallback_route(ks, position, current_channel)
        rolling = self._rolling_decide(ks, position, current_channel)
        if rolling is not None:
            return rolling
        if ks.ready:
            # Deferral must be checked *before* the route branch: otherwise the
            # open-path order is applied to a singleton set and batching never
            # happens.
            defer = (self.ready_batch_min > 1
                     and len(ks.ready) < self.ready_batch_min
                     and (ks.active or self._coverage_scan_available(ks)))
            if not defer:
                if self.ready_open_route:
                    ready_route = self._ready_route_candidate(ks, position)
                    if ready_route is not None:
                        return ready_route
                return super().decide(ks, position, current_channel)
        q3_risky_radius = self._observed_q3_risky_radius(ks)
        if self.mode == "Q3" and q3_risky_radius > 0.0:
            for ch in ks.by_status(ChannelStatus.ACTIVE):
                point, guaranteed = self._ladder_probe_point(ch)
                if point is None:
                    continue
                # A guaranteed clear may always be taken: the failed-clear
                # exclusions prove the source sits inside the 20 m disk of this
                # point.  Unguaranteed probes stay capped at the ladder limit
                # so the policy cannot gamble repeatedly.
                if (not guaranteed and
                        self.probe_attempts(ch.channel_id) >=
                        self.probe_ladder_limit):
                    continue
                if ch.mec_radius > q3_risky_radius and not guaranteed:
                    continue
                if (self.q3_risky_clear_max_distance_m is not None and
                        math.dist(position, point) >
                        self.q3_risky_clear_max_distance_m):
                    continue
                self._q3_risky_clear_attempted.add(ch.channel_id)
                return Mission("clear", point, channel=ch.channel_id,
                               meta={"kind": "q3_risky_probe",
                                     "risky_probe": True,
                                     "ladder_guaranteed": guaranteed})
        if self.mode == "Q4" and self.q4_risky_clear_radius > 0.0:
            for ch in ks.by_status(ChannelStatus.ACTIVE):
                if (ch.channel_id in self._q4_risky_clear_attempted or
                        ch.mec_radius > self.q4_risky_clear_radius):
                    continue
                self._q4_risky_clear_attempted.add(ch.channel_id)
                return Mission("clear", ch.mec[0], channel=ch.channel_id,
                               meta={"kind": "q4_risky_probe",
                                     "risky_probe": True})
        if self.mode == "Q4" and self.q4_active_first and ks.active:
            mission = self._active_measure(ks, position, current_channel)
            if mission is not None:
                return mission
        if self.mode == "Q4" and self.q4_preprobe_once:
            pending = [ch for ch in ks.by_status(ChannelStatus.ACTIVE)
                       if ch.channel_id not in self._q4_preprobe_done
                       and not self.fallback.in_fallback(ch.channel_id)]
            if pending:
                mission = self._active_measure(
                    ks, position, current_channel,
                    active_override=pending)
                if mission is not None:
                    self._q4_preprobe_done.add(mission.channel)
                    return mission
                self._q4_preprobe_done.update(ch.channel_id
                                              for ch in pending)
        if self.mode == "Q3" and self.q3_interleave and ks.active:
            # One route for both jobs: the next certificate point and the next
            # live-channel measurement compete by travel, so clearing a source
            # no longer means abandoning the ring and paying for it twice.
            # The ring is still advanced whenever it is the nearer target, so
            # every certificate point is visited unless the cardinality cap
            # ends the search.
            peek = None
            if (self._coverage_index < len(self._coverage_points)
                    and ks.unknown):
                peek = self._coverage_points[self._coverage_index]
            if self.joint_action:
                # Joint comparison: price every scan set of the ACTIVE stop
                # against the certificate stop and take the cheapest action.
                mission, rows = self._joint_step(ks, position,
                                                 current_channel)
                if mission is not None:
                    if peek is not None:
                        ring_reach = math.dist(position, peek) / C.MOVE_SPEED
                        best = min(rows, key=lambda row: row["score"])
                        if best["immediate"] > ring_reach * self.q3_interleave_bias:
                            mission = None
                    if mission is not None:
                        self._note_q3_scan_point(mission.target)
                        mission.meta["interleaved"] = True
                        self._emit_joint_trace(ks, mission, rows, peek,
                                               position)
                        return mission
            else:
                mission = self._active_measure(ks, position, current_channel)
                if mission is not None:
                    if peek is None:
                        return mission
                    reach_work = math.dist(position, mission.target)
                    reach_ring = math.dist(position, peek)
                    if reach_work <= reach_ring * self.q3_interleave_bias:
                        self._note_q3_scan_point(mission.target)
                        mission.meta["interleaved"] = True
                        variant = self._joint_scan_variant(ks, mission.target)
                        if variant is not None:
                            mission.meta["scan_variant"] = variant
                        return mission
        if self.mode == "Q3" and self.q3_target_commit:
            mission = self._q3_commit_step(ks, position, current_channel)
            if mission is not None and self._q3_merged_allowed(ks):
                return mission
        if self.mode == "Q3" and self.q3_work_first and ks.active:
            mission = None
            if self._q3_merged_allowed(ks):
                mission = self._work_first_active(ks, position, current_channel)
            if mission is not None:
                return mission
        if self.order_joint and self.mode == "Q3" and ks.unknown:
            planned = self._order_joint_step(ks, position, current_channel)
            if planned is not None:
                return planned
        if self.order_plan and ks.unknown:
            # Global stop-order planning: the next stop is the first stop of an
            # open path through every executable, unfinished task.  Replanned
            # here, i.e. after every observation event.
            planned = self._order_step(ks, position, current_channel)
            if planned is not None:
                return planned
        coverage = self._coverage_scan(ks)
        if coverage is not None:
            return coverage
        if self.q3_order_tail_only and self.mode == "Q3":
            # Certificate phase is over (no pending anchor was returned): the
            # tail plan may now order the live stops.  Certificate anchors are
            # never part of its task set (t35).
            planned = self._order_tail_step(ks, position, current_channel)
            if planned is not None:
                return planned
        if ks.active:
            mission = self._active_measure(ks, position, current_channel)
            if mission is not None:
                joint = self._joint_active_channels(
                    ks, mission.target, mission.channel)
                if joint:
                    mission.meta["joint_channels"] = joint
                    mission.meta["joint_route"] = True
                self._note_q3_scan_point(mission.target)
                return mission
        return super().decide(ks, position, current_channel)

    def _fallback_route(self, ks, position, current_channel):
        """Interleave finite fallback covers by current travel time."""
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
                             "fallback_total": total,
                             "early_small_cover":
                                 cid in self._early_fallback_channels,
                             "suppress_failed_post_clear_scan":
                                 (cid in self._early_fallback_channels and
                                  self.early_fallback_suppress_failed_scan)})
