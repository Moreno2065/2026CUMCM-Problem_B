"""Regression checks for real-policy replay and legal region routing."""
import copy
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'baseline' / 'code')]

from compact_ring.scheduler import CompactRingScheduler
from compact_ring.stop_fusion import snapshot, replay
from compact_ring.tail_rollout import candidates as tail_candidates
from compact_ring.coverage_rollout import (
    anchor_candidates, anchor_scan_pruning_candidates,
    certificate_template_candidates, density_candidates,
    post_service_candidates,
)
from compact_ring.region_route import clear_on_route
from belief_rollout.worlds import Hypothesis
from geometry.clear_zone import closest_clear_point
from state.knowledge_state import KnowledgeState
from state.channel_state import ChannelStatus
from policy.scheduler import Mission
from experiment.config import MainlineConfig
import production
import run


class RouteChecks(unittest.TestCase):
    def test_two_leg_clear_point_stays_legal_and_shortens_path(self):
        vertices = [(-2, 8), (2, 8), (2, 12), (-2, 12)]
        previous, following = (-100., 0.), (100., 0.)
        original = closest_clear_point(vertices, previous)
        chosen = clear_on_route(vertices, original, previous, following)
        length = lambda p: math.dist(previous, p) + math.dist(p, following)
        self.assertLess(length(chosen), length(original) - .01)
        self.assertTrue(all(math.dist(chosen, p) <= 20 for p in vertices))

    def test_region_route_does_not_move_an_already_straight_stop(self):
        vertices = [(-2, -2), (2, -2), (2, 2), (-2, 2)]
        self.assertEqual(clear_on_route(vertices, (0., 0.), (-100., 0.),
                                        (100., 0.)), (0., 0.))

    def test_fusion_snapshot_cannot_copy_live_owner(self):
        class Live:
            def __deepcopy__(self, memo):
                raise AssertionError('copied live backend owner')
            def callback(self, *args):
                pass
        policy = CompactRingScheduler(segment_budget=0)
        policy.stop_planner = Live().callback
        policy.decision_listener = Live().callback
        frozen = snapshot(policy)
        self.assertNotIn('stop_planner', frozen)
        self.assertNotIn('decision_listener', frozen)

    def test_replay_restores_observed_constrained_state_without_mutation(self):
        ks = KnowledgeState('Q3')
        cfg, runner_cfg = production.split_config('Q3')
        policy = CompactRingScheduler(segment_budget=0, **cfg)
        policy.initialize_knowledge(ks)
        for channel in ks.channels.values():
            channel.status = ChannelStatus.CERTIFIED_ABSENT
        ks[1].status = ChannelStatus.UNKNOWN
        ks[1].update_direction((0, 0), 0, 0)
        saved = snapshot(policy)
        history = copy.deepcopy(ks[1].observations)
        world = {1: Hypothesis((100, 0), 1000, False, 0)}
        mission = Mission('clear', (100, 0), channel=1,
                          meta={'post_clear_channels': []})
        values = [replay(saved, ks, (0, 0), 1, mission, world,
                         MainlineConfig(**runner_cfg), 99) for _ in range(2)]
        self.assertEqual(values, [25., 25.])
        self.assertEqual(ks[1].observations, history)
        self.assertEqual(ks[1].status, ChannelStatus.ACTIVE)
        self.assertIn(1, world)
        # The leaf really calls compact-ring, rather than restoring its
        # fields into a LearnedSearchScheduler with a different decide().
        mission = Mission('measure', (10, 0), channel=1,
                          meta={'scan_variant': 'primary'})
        with patch.object(CompactRingScheduler, '_compact_decide',
                          return_value=None) as leaf:
            replay(saved, ks, (0, 0), 1, mission, world,
                   MainlineConfig(**runner_cfg), 99)
        leaf.assert_called_once()

    def test_cli_options_reach_controller(self):
        args = run.build_parser().parse_args([
            '--mode', 'q3', '--solver', 'compact-ring',
            '--compact-center-anchor',
            '--compact-joint-service-preset',
            '--compact-fusion-budget', '7', '--compact-fusion-worlds', '6',
            '--compact-fusion-views-only', '--compact-clear-region-route',
            '--compact-tail-rollout-budget', '9',
            '--compact-tail-rollout-worlds', '5',
            '--compact-tail-rollout-candidates', '7',
            '--compact-tail-rollout-margin', '3',
            '--compact-tail-rollout-min-win-fraction', '.8',
            '--compact-tail-rollout-objective', 'mean',
            '--compact-tail-rollout-step-limit', '111',
            '--compact-joint-ring-active-radius', '260',
            '--compact-joint-ring-active-attempts', '1',
            '--compact-joint-ring-min-directions', '2',
            '--compact-joint-ring-service-worst', '20',
            '--compact-joint-ring-or-opt',
            '--compact-service-certificate',
            '--compact-service-certificate-radius', '190',
            '--compact-service-certificate-max-services', '3',
            '--compact-service-certificate-depth', '2',
            '--compact-service-certificate-min-saving', '17',
            '--compact-coverage-rollout-budget', '8',
            '--compact-coverage-rollout-worlds', '2',
            '--compact-coverage-rollout-candidates', '4',
            '--compact-coverage-rollout-points', '2',
            '--compact-coverage-rollout-service-scan',
            '--compact-coverage-rollout-service-channels', '3',
            '--compact-coverage-rollout-post-service-scan',
            '--compact-coverage-rollout-margin', '6',
            '--compact-coverage-rollout-min-win-fraction', '.9',
            '--compact-coverage-branch-actions', '3',
            '--compact-coverage-branch-detour', '275',
            '--compact-coverage-rollout-step-limit', '99'])
        cfg = run._scheduler_kwargs('Q3', args)
        self.assertEqual(cfg['compact_fusion_budget'], 7)
        self.assertTrue(cfg['compact_center_anchor'])
        self.assertEqual(cfg['compact_fusion_worlds'], 6)
        self.assertTrue(cfg['compact_fusion_views_only'])
        self.assertTrue(cfg['compact_clear_region_route'])
        self.assertEqual(cfg['compact_tail_rollout_budget'], 9)
        self.assertEqual(cfg['compact_tail_rollout_worlds'], 5)
        self.assertEqual(cfg['compact_tail_rollout_candidates'], 7)
        self.assertEqual(cfg['compact_tail_rollout_margin_s'], 3)
        self.assertEqual(cfg['compact_tail_rollout_min_win_fraction'], .8)
        self.assertEqual(cfg['compact_tail_rollout_objective'], 'mean')
        self.assertEqual(cfg['compact_tail_rollout_step_limit'], 111)
        self.assertEqual(cfg['compact_joint_ring_active_radius'], 260)
        self.assertEqual(cfg['compact_joint_ring_active_attempts'], 1)
        self.assertEqual(cfg['compact_joint_ring_min_directions'], 2)
        self.assertEqual(cfg['compact_joint_ring_service_worst'], 20)
        self.assertTrue(cfg['compact_joint_ring_or_opt'])
        self.assertTrue(cfg['compact_service_certificate'])
        self.assertEqual(cfg['compact_service_certificate_radius'], 190)
        self.assertEqual(cfg['compact_service_certificate_max_services'], 3)
        self.assertEqual(cfg['compact_service_certificate_depth'], 2)
        self.assertEqual(cfg['compact_service_certificate_min_saving_m'], 17)
        self.assertEqual(cfg['compact_coverage_rollout_budget'], 8)
        self.assertEqual(cfg['compact_coverage_rollout_worlds'], 2)
        self.assertEqual(cfg['compact_coverage_rollout_candidates'], 4)
        self.assertEqual(cfg['compact_coverage_rollout_points'], 2)
        self.assertTrue(cfg['compact_coverage_rollout_service_scan'])
        self.assertEqual(cfg['compact_coverage_rollout_service_channels'], 3)
        self.assertTrue(cfg['compact_coverage_rollout_post_service_scan'])
        self.assertEqual(cfg['compact_coverage_rollout_margin_s'], 6)
        self.assertEqual(cfg['compact_coverage_rollout_min_win_fraction'], .9)
        self.assertEqual(cfg['compact_coverage_branch_actions'], 3)
        self.assertEqual(cfg['compact_coverage_branch_detour_m'], 275)
        self.assertEqual(cfg['compact_coverage_rollout_step_limit'], 99)

    def test_tail_rollout_candidates_include_another_live_channel(self):
        ks = KnowledgeState('Q3')
        for channel in ks.channels.values():
            channel.status = ChannelStatus.CERTIFIED_ABSENT
        ks[1].status = ChannelStatus.UNKNOWN
        ks[2].status = ChannelStatus.UNKNOWN
        ks[1].update_direction((0., 0.), 0., 0.)
        ks[2].update_direction((0., 0.), 45., 0.)
        policy = CompactRingScheduler(segment_budget=0)
        base = Mission('measure', (500., 0.), channel=1,
                       meta={'scan_variant': 'primary'})
        options = tail_candidates(policy, ks, (0., 0.), base, limit=8)
        self.assertEqual(options[0], base)
        self.assertIn(2, [mission.channel for mission in options])

    def test_two_anchor_rebuild_does_not_skip_default_anchor(self):
        ks = KnowledgeState('Q3')
        policy = CompactRingScheduler(segment_budget=0)
        # A local B -> A rebuild may issue B before the ordinary next A.
        # Scheduling B must leave A as the next default anchor, then advance
        # to C only after A itself is issued.
        policy._ring_scan(ks, anchor_index=1)
        self.assertEqual(policy._coverage_index, 0)
        self.assertNotIn(1, policy._coverage_remaining)
        policy._ring_scan(ks, anchor_index=0)
        self.assertEqual(policy._coverage_index, 2)
        self.assertNotIn(0, policy._coverage_remaining)

    def test_joint_ring_scan_keeps_real_anchor_identity(self):
        """A joint route's ordinal is not the identity of its anchor."""
        ks = KnowledgeState('Q3')
        policy = CompactRingScheduler(segment_budget=0,
                                      compact_joint_ring_route=True)
        mission = policy._ring_scan(ks, anchor_index=5)
        self.assertEqual(mission.meta['coverage_anchor_index'], 5)
        self.assertEqual(policy._coverage_index, 1)

    def test_center_plus_six_outer_anchors_is_a_q3_certificate(self):
        policy = CompactRingScheduler(segment_budget=0,
                                      compact_center_anchor=True,
                                      compact_ring_radius=1150.,
                                      compact_ring_points=6)
        self.assertEqual(len(policy._coverage_points), 7)
        self.assertEqual(policy._coverage_points[0], (0., 0.))

    def test_paid_source_stop_can_offer_unknown_scan_before_next_source(self):
        ks = KnowledgeState('Q3')
        policy = CompactRingScheduler(
            segment_budget=0, compact_coverage_rollout_post_service_scan=True)
        policy._compact_service_current = (10., 20.)
        base = Mission('measure', (100., 50.), channel=1,
                       meta={'kind': 'compact_joint_ring_measure'})
        choices = post_service_candidates(policy, ks, (10., 20.), base)
        self.assertEqual(len(choices), 1)
        mission, plan = choices[0]
        self.assertEqual(mission.kind, 'scan')
        self.assertIsNone(plan)
        self.assertEqual(mission.target, (10., 20.))
        self.assertEqual(mission.channels, list(range(1, 21)))

    def test_or_opt_never_lengthens_large_open_route(self):
        items = [(index, (float((index * 37) % 181),
                          float((index * 71) % 149)), 'node')
                 for index in range(17)]
        start = (-25., 43.)
        baseline = CompactRingScheduler._hybrid_open_order(items, start)
        polished = CompactRingScheduler._hybrid_open_order(items, start,
                                                            or_opt=True)
        self.assertLessEqual(CompactRingScheduler._open_route_length(
            polished, start), CompactRingScheduler._open_route_length(
            baseline, start) + 1e-9)

    def test_coverage_branch_forces_b_then_a_return(self):
        ks = KnowledgeState('Q3')
        policy = CompactRingScheduler(segment_budget=0)
        policy._compact_coverage_branch = {
            'cid': 1, 'anchor_index': 1,
            'return_indices': [1, 0], 'return_issued': None,
            'remaining': 0, 'extra_spent_m': 0., 'extra_limit_m': 0.,
            'root_kind': 'measure'}
        first = policy._coverage_branch_mission(ks, (0., 0.))
        self.assertEqual(first.target, policy._coverage_points[1])
        # Issuing the scan removes B; the next decision must issue A.
        second = policy._coverage_branch_mission(ks, first.target)
        self.assertEqual(second.target, policy._coverage_points[0])
        # Once A is issued, regular coverage resumes from C with no retained
        # branch that could delay it again.
        self.assertIsNone(policy._coverage_branch_mission(ks, second.target))
        self.assertIsNone(policy._compact_coverage_branch)

    def test_clear_witness_keeps_anchors_when_unknown_scan_is_missing(self):
        """A clear position is never counted as a witness by declaration."""
        ks = KnowledgeState('Q3')
        policy = CompactRingScheduler(segment_budget=0,
                                      compact_joint_ring_route=True,
                                      compact_joint_clear_witness=True)
        mission = Mission(
            'clear', (100., 100.), channel=1,
            meta={'certificate_clear_witness': True,
                  'certificate_unknown_channels': [1, 2],
                  'post_clear_channels': [1, 2]})
        before = set(policy._coverage_remaining)
        policy.on_certificate_clear_witness_complete(mission, ks, set())
        self.assertEqual(policy._coverage_remaining, before)
        self.assertEqual(policy.compact_stats['joint_clear_witness_rejected'], 1)

    def test_useful_clear_witness_gate_requires_a_real_anchor_replacement(self):
        """The expensive UNKNOWN suffix is only admissible when it can pay."""
        ks = KnowledgeState('Q3')
        policy = CompactRingScheduler(
            segment_budget=0, compact_joint_clear_witness=True,
            compact_joint_clear_witness_useful_only=True,
            compact_joint_clear_witness_max_unknown=4)
        # The cardinality gate alone blocks an early full-channel sweep.
        self.assertEqual(policy._joint_clear_witness_drops(
            ks, policy._coverage_points[0]), ())
        # With just one channel still requiring absence proof, an actual scan
        # at a duplicate of anchor 0 could replace precisely that anchor.  The
        # helper plans that opportunity but has not mutated coverage state.
        for channel in ks.channels.values():
            channel.status = ChannelStatus.CERTIFIED_ABSENT
        ks[1].status = ChannelStatus.UNKNOWN
        self.assertIn(0, policy._joint_clear_witness_drops(
            ks, policy._coverage_points[0]))
        self.assertIn(0, policy._coverage_remaining)

    def test_ready_stop_can_substitute_an_equivalent_pending_anchor(self):
        """Fusing a clear with a station keeps the exact eight-point cover."""
        ks = KnowledgeState('Q3')
        policy = CompactRingScheduler(
            segment_budget=0, compact_joint_anchor_substitution=True)
        point = policy._coverage_points[0]
        self.assertEqual(policy._joint_anchor_substitution(ks, point), 0)
        policy._issue_joint_anchor_substitution(ks, point, ks[1], 0)
        self.assertNotIn(0, policy._coverage_remaining)
        self.assertEqual(policy._coverage_points[0], point)
        self.assertEqual(policy.compact_stats['joint_anchor_substitutions'], 1)

    def test_active_stop_can_become_a_certificate_station(self):
        """The scan form preserves UNKNOWN evidence and adds its ACTIVE view."""
        ks = KnowledgeState('Q3')
        policy = CompactRingScheduler(
            segment_budget=0, compact_joint_anchor_substitution=True)
        point = policy._coverage_points[0]
        mission = policy._issue_joint_anchor_measure_substitution(
            ks, point, ks[1], 0)
        self.assertEqual(mission.kind, 'scan')
        self.assertEqual(mission.meta['coverage_anchor_index'], 0)
        self.assertEqual(mission.meta['joint_channels'], [1])
        self.assertNotIn(0, policy._coverage_remaining)
        self.assertEqual(policy.compact_stats[
            'joint_anchor_substitution_measures'], 1)

    def test_joint_service_root_offers_unconsumed_anchor_alternatives(self):
        """Reverse rollout candidates must not spend certificate state early."""
        ks = KnowledgeState('Q3')
        ks[1].update_direction((0., 0.), 0., 0.)
        policy = CompactRingScheduler(
            segment_budget=0, compact_joint_ring_route=True)
        before = set(policy._coverage_remaining)
        base = Mission('measure', (100., 0.), channel=1,
                       meta={'kind': 'compact_joint_ring_measure'})
        choices = anchor_candidates(policy, ks, (0., 0.), base)
        self.assertEqual(len(choices), 2)
        self.assertEqual(set(policy._coverage_remaining), before)
        mission, plan = choices[0]
        self.assertEqual(mission.kind, 'scan')
        self.assertEqual(plan['root_kind'], 'anchor')

    def test_anchor_scan_pruning_keeps_unknown_certificate_work(self):
        """A scan-pruning branch changes only optional ACTIVE bearings."""
        ks = KnowledgeState('Q3')
        ks[1].update_direction((0., 0.), 0., 0.)
        ks[2].update_direction((0., 0.), 20., 0.)
        policy = CompactRingScheduler(segment_budget=0,
                                      compact_joint_ring_route=True,
                                      compact_coverage_rollout_candidates=3)
        base = Mission('scan', policy._coverage_points[0],
                       channels=[ch.channel_id for ch in ks.unknown],
                       meta={'kind': 'compact_ring', 'coverage_scan': True,
                             'coverage_anchor_index': 0,
                             'joint_channels': [1, 2]})
        before = set(policy._coverage_remaining)
        choices = anchor_scan_pruning_candidates(policy, ks, base)
        self.assertEqual(len(choices), 3)  # omit 1, omit 2, omit all
        for mission, plan in choices:
            self.assertEqual(mission.kind, 'scan')
            self.assertEqual(mission.channels, base.channels)
            self.assertEqual(mission.meta['coverage_anchor_index'], 0)
            self.assertEqual(plan['root_kind'], 'anchor')
        self.assertEqual(set(policy._coverage_remaining), before)

    def test_low_first_discovery_can_rebuild_only_the_pending_ring(self):
        """The adaptive dense ring is gated by real first-stop witnesses."""
        ks = KnowledgeState('Q3')
        policy = CompactRingScheduler(
            segment_budget=0, compact_joint_ring_route=True,
            compact_adaptive_ring_points=10,
            compact_adaptive_ring_radius=881.,
            compact_adaptive_ring_known_max=3)
        first = policy._coverage_points[0]
        policy._coverage_remaining.discard(0)  # real first scan was issued
        policy._coverage_index = 1
        for channel in ks.unknown:
            channel.update_no_signal(first, 0.)
        ks[1].update_direction(first, 0., 0.)
        policy._adapt_ring_density(ks)
        self.assertEqual(policy.compact_ring_points, 10)
        self.assertEqual(policy._coverage_points[0], first)
        self.assertEqual(policy._coverage_remaining, set(range(1, 10)))
        self.assertEqual(policy.compact_stats['adaptive_ring_uses'], 1)

    def test_density_rollout_candidate_is_uncommitted_until_selected(self):
        """Posterior layout comparison cannot spend future certificate work."""
        ks = KnowledgeState('Q3')
        policy = CompactRingScheduler(
            segment_budget=0, compact_joint_ring_route=True,
            compact_adaptive_ring_points=10,
            compact_adaptive_ring_radius=881.,
            compact_adaptive_ring_rollout=True)
        first = policy._coverage_points[0]
        policy._coverage_remaining.discard(0)
        policy._coverage_index = 1
        for channel in ks.unknown:
            channel.update_no_signal(first, 0.)
        ks[1].update_direction(first, 0., 0.)
        before = snapshot(policy)
        after = snapshot(policy)
        base = Mission('measure', (100., 0.), channel=1,
                       meta={'kind': 'compact_joint_ring_measure'})
        choices = density_candidates(policy, before, after, ks, first)
        self.assertEqual(len(choices), 1)
        mission, plan = choices[0]
        self.assertEqual(mission.kind, 'scan')
        self.assertEqual(plan['root_kind'], 'density_anchor')
        self.assertEqual(policy.compact_ring_points, 8)
        self.assertEqual(policy._coverage_remaining, set(range(1, 8)))

    def test_ring_direction_cap_does_not_cap_unknown_certificate_scan(self):
        """A capped ACTIVE channel is omitted, while UNKNOWN stays on stop."""
        ks = KnowledgeState('Q3')
        policy = CompactRingScheduler(
            segment_budget=0, compact_ring_active_max_directions=2)
        point = policy._coverage_points[0]
        ks[1].update_direction(point, 180., 0.)
        ks[1].update_direction((-point[0], -point[1]), 0., 0.)
        mission = policy._ring_scan(ks, anchor_index=0)
        self.assertEqual(mission.kind, 'scan')
        self.assertNotIn(1, mission.meta['joint_channels'])
        self.assertIn(2, mission.channels)

    def test_service_certificate_rollout_keeps_template_uncommitted(self):
        """A template is evidence-free until its selected root executes."""
        ks = KnowledgeState('Q3')
        policy = CompactRingScheduler(
            segment_budget=0, compact_service_certificate=True,
            compact_service_certificate_rollout=True)
        before = snapshot(policy)
        after = snapshot(policy)
        proposal = (80., (0,), [
            {'key': 1010, 'channel': 1, 'point': (100., 0.),
             'kind': 'measure'},
        ])
        with patch.object(CompactRingScheduler,
                          '_certificate_service_template_candidate',
                          return_value=proposal):
            choices = certificate_template_candidates(
                policy, before, after, ks, (0., 0.))
        self.assertEqual(len(choices), 1)
        mission, plan = choices[0]
        self.assertEqual(mission.kind, 'scan')
        self.assertEqual(plan['root_kind'], 'service_certificate_template')
        self.assertIsNone(policy._certificate_service_template)
        self.assertIn(0, policy._coverage_remaining)

    def test_center_bearing_dispersion_gates_anchor_warmup(self):
        """Only actual, concentrated centre bearings protect an anchor prefix."""
        ks = KnowledgeState('Q3')
        policy = CompactRingScheduler(
            segment_budget=0, compact_center_anchor=True,
            compact_center_warmup_resultant_threshold=.3,
            compact_center_warmup_min_stops=3)
        policy._coverage_remaining.discard(0)  # the origin scan completed
        ks[1].update_direction((0., 0.), 0., 0.)
        ks[2].update_direction((0., 0.), 10., 0.)
        policy._adapt_center_warmup(ks)
        self.assertEqual(policy._joint_ring_min_stops_now(), 3)
        self.assertEqual(policy.compact_stats['center_warmup_adaptations'], 1)

        diffuse = CompactRingScheduler(
            segment_budget=0, compact_center_anchor=True,
            compact_center_warmup_resultant_threshold=.3,
            compact_center_warmup_min_stops=3)
        diffuse._coverage_remaining.discard(0)
        ks2 = KnowledgeState('Q3')
        ks2[1].update_direction((0., 0.), 0., 0.)
        ks2[2].update_direction((0., 0.), 180., 0.)
        diffuse._adapt_center_warmup(ks2)
        self.assertEqual(diffuse._joint_ring_min_stops_now(), 0)
        self.assertEqual(diffuse.compact_stats['center_warmup_adaptations'], 0)

    def _service_certificate_state(self, unknown=(1,)):
        ks = KnowledgeState('Q3')
        for channel in ks.channels.values():
            channel.status = ChannelStatus.CERTIFIED_ABSENT
        for cid in unknown:
            ks[cid].status = ChannelStatus.UNKNOWN
        policy = CompactRingScheduler(
            segment_budget=0, compact_service_certificate=True)
        return policy, ks

    def test_service_certificate_does_not_spend_planned_witness_early(self):
        """A planned source stop cannot remove an anchor before its scan."""
        policy, ks = self._service_certificate_state()
        anchor = policy._coverage_points[0]
        policy._certificate_service_template = {
            'remove_anchors': {0},
            'services': [dict(key=101, channel=1, point=anchor,
                              kind='measure')],
            'remaining_services': {101},
        }
        # The plan is geometrically sufficient only if its future service
        # point is executed.  It must leave both state and evidence untouched.
        self.assertTrue(policy._service_certificate_plan_valid(
            ks, set(range(1, policy.compact_ring_points)),
            assumed_service_points=[anchor]))
        self.assertIn(0, policy._coverage_remaining)
        self.assertEqual(policy._certificate_service_channel_witnesses[1], [])

    def test_service_certificate_drops_anchor_after_real_channel_witness(self):
        """One real no-signal service scan may replace its matching anchor."""
        policy, ks = self._service_certificate_state()
        anchor = policy._coverage_points[0]
        ks[1].update_no_signal(anchor, 0.)
        policy._certificate_service_template = {
            'remove_anchors': {0},
            'services': [dict(key=101, channel=1, point=anchor,
                              kind='measure')],
            'remaining_services': {101},
        }
        mission = Mission(
            'scan', anchor, channels=[1],
            meta={'kind': 'compact_service_certificate',
                  'certificate_service_key': 101,
                  'certificate_service_channel': 1,
                  'certificate_unknown_channels': [1]})
        policy.on_certificate_service_complete(mission, ks, {1})
        self.assertNotIn(0, policy._coverage_remaining)
        self.assertEqual(policy._certificate_service_channel_witnesses[1],
                         [anchor])
        self.assertEqual(policy.compact_stats[
            'service_certificate_actual_witnesses'], 1)

    def test_service_certificate_never_shares_one_channels_witness(self):
        """An actual witness for channel 1 cannot delete channel 2's anchor."""
        policy, ks = self._service_certificate_state(unknown=(1, 2))
        anchor = policy._coverage_points[0]
        ks[1].update_no_signal(anchor, 0.)
        policy._certificate_service_template = {
            'remove_anchors': {0},
            'services': [dict(key=101, channel=1, point=anchor,
                              kind='measure')],
            'remaining_services': {101},
        }
        mission = Mission(
            'scan', anchor, channels=[1],
            meta={'kind': 'compact_service_certificate',
                  'certificate_service_key': 101,
                  'certificate_service_channel': 1,
                  'certificate_unknown_channels': [1]})
        policy.on_certificate_service_complete(mission, ks, {1})
        self.assertIn(0, policy._coverage_remaining)
        self.assertEqual(policy._certificate_service_channel_witnesses[2], [])
        self.assertEqual(policy.compact_stats[
            'service_certificate_channel_proof_rejected'], 1)


if __name__ == '__main__':
    unittest.main()
