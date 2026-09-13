"""Focused checks for hidden-state isolation and hypothetical action semantics."""
from __future__ import annotations

import math
import random
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT), str(ROOT / 'baseline' / 'code')]

from belief_rollout.worlds import (
    Hypothesis, HypotheticalBackend, sample_source, angle, angle_error)
from belief_rollout.scheduler import policy_snapshot, rollout_cost
from belief_rollout.scheduler import BeliefRolloutScheduler, QuietRunner
from state.knowledge_state import KnowledgeState
from state.channel_state import ChannelStatus
from executor.action_executor import ActionExecutor
from experiment.config import MainlineConfig
from policy.scheduler import Mission
from learned_search.scheduler import LearnedSearchScheduler
import production
import run


class RolloutChecks(unittest.TestCase):
    def test_callbacks_cannot_pull_live_backend_into_snapshot(self):
        class LiveOwner:
            def __deepcopy__(self, memo):
                raise AssertionError('live runner was copied')
            def callback(self, *args):
                pass
        scheduler = LearnedSearchScheduler('Q3')
        owner = LiveOwner()
        scheduler.stop_planner = owner.callback
        scheduler.decision_listener = owner.callback
        frozen = policy_snapshot(scheduler)
        self.assertNotIn('stop_planner', frozen)
        self.assertNotIn('decision_listener', frozen)
        self.assertIsNot(frozen['fallback'], scheduler.fallback)

    def test_q3_world_rejects_no_signal_and_failed_clear_exclusions(self):
        ks = KnowledgeState('Q3')
        ch = ks[1]
        ch.update_direction((0, 0), 0, 0)
        ch.update_no_signal((-900, 0), 1)
        for seed in range(12):
            h = sample_source(ch, 'Q3', [(500, 0)], random.Random(seed))
            self.assertIsNotNone(h)
            self.assertGreater(math.dist(h.position, (500, 0)), 20)
            self.assertLessEqual(angle_error(angle((0, 0), h.position), 0), 1)
            self.assertLess(math.hypot(*h.position), h.receive_radius + 1e-9)
            self.assertGreater(math.dist(h.position, (-900, 0)), h.receive_radius)

    def test_q4_no_signal_can_be_backside_even_within_1000m(self):
        ks = KnowledgeState('Q4')
        ch = ks[1]
        ch.feasible_region = [(490, -10), (510, -10), (510, 10), (490, 10)]
        ch.update_direction((0, 0), 0, 0)
        ch.update_no_signal((800, 0), 1)
        for seed in range(12):
            h = sample_source(ch, 'Q4', [], random.Random(seed))
            self.assertIsNotNone(h)
            self.assertTrue(h.directional)
            self.assertTrue(h.covers((0, 0)))
            self.assertFalse(h.covers((800, 0)))
            self.assertLess(math.dist(h.position, (800, 0)), 1000)

    def test_fixed_history_and_four_ledger_costs(self):
        ks = KnowledgeState('Q3')
        ks[1].update_direction((0, 0), 0.5, 0)
        backend = HypotheticalBackend(
            {1: Hypothesis((100, 0), 1000, False, 0)}, ks, (0, 0), 2, 99)
        executor = ActionExecutor(backend)
        executor._last_measure_channel = 2
        first = executor.move_and_measure(0, 0, 1)
        second = executor.move_and_measure(0, 0, 1)
        self.assertEqual(first.svd_deg, 0.5)
        self.assertEqual(second.svd_deg, first.svd_deg)
        self.assertEqual(executor.virtual_time, 11)
        executor.clear_at(0, 0, 1)
        self.assertEqual(executor.virtual_time, 14)
        self.assertEqual(executor.current_channel, 1)
        executor.clear_at(100, 0, 1)
        self.assertEqual(executor.virtual_time, 39)
        self.assertEqual(executor.current_channel, 1)
        self.assertEqual(executor.reconcile_warnings, [])

    def test_repeated_branch_is_exact_and_does_not_mutate_parent(self):
        ks = KnowledgeState('Q3')
        for ch in ks.channels.values():
            ch.status = ChannelStatus.CERTIFIED_ABSENT
        ks[1].status = ChannelStatus.ACTIVE
        ks[1].feasible_region = [(99, -1), (101, -1), (101, 1), (99, 1)]
        ks[1]._update_mec()
        scheduler_cfg, runner_cfg = production.split_config('Q3')
        scheduler = LearnedSearchScheduler('Q3', **scheduler_cfg)
        snapshot = policy_snapshot(scheduler)
        world = {1: Hypothesis((100, 0), 1000, False, 0)}
        mission = Mission('clear', (100, 0), channel=1)
        values = [rollout_cost(snapshot, ks, (0, 0), None, mission,
                               world, 99, MainlineConfig(**runner_cfg))
                  for _ in range(2)]
        self.assertEqual(values, [25.0, 25.0])
        self.assertEqual(ks[1].status, ChannelStatus.ACTIVE)
        self.assertIn(1, world)

    def test_first_measure_has_no_switch_charge(self):
        backend = HypotheticalBackend({}, KnowledgeState('Q3'), (0, 0), None, 1)
        executor = ActionExecutor(backend)
        executor.move_and_measure(0, 0, 1)
        self.assertEqual(executor.virtual_time, 5.0)
        self.assertEqual(executor.reconcile_warnings, [])

    def test_cli_choice_and_budget_forwarding(self):
        parser = run.build_parser()
        args = parser.parse_args(['--mode', 'q3', '--sim', 'synthetic',
                                  '--solver', 'belief-rollout',
                                  '--rollout-worlds', '7', '--rollout-budget', '0',
                                  '--rollout-clear-only', '--rollout-step-limit', '321'])
        cfg = run._scheduler_kwargs('Q3', args)
        self.assertEqual(args.policy, 'belief-rollout')
        self.assertEqual(cfg['br_worlds'], 7)
        self.assertEqual(cfg['br_budget_s'], 0)
        self.assertTrue(cfg['br_clear_only'])
        self.assertEqual(cfg['br_step_limit'], 321)
        default = parser.parse_args(['--mode', 'q3'])
        self.assertEqual(default.policy, 'learned')
        self.assertNotIn('br_worlds', run._scheduler_kwargs('Q3', default))

    def test_particle_clear_candidates_cover_sample_modes(self):
        ks = KnowledgeState('Q3')
        ch = ks[1]
        ch.status = ChannelStatus.ACTIVE
        ch.feasible_region = [(90, -10), (130, -10), (130, 10), (90, 10)]
        ch._update_mec()
        scheduler = BeliefRolloutScheduler(
            'Q3', br_clear_radius=50, br_clear_candidates=2)
        worlds = [
            {1: Hypothesis((100, 0), 1000, False, 0)},
            {1: Hypothesis((102, 0), 1000, False, 0)},
            {1: Hypothesis((128, 0), 1000, False, 0)},
        ]
        choices = scheduler._particle_clear_choices(ks, (0, 0), worlds)
        self.assertTrue(choices)
        self.assertTrue(all(m.kind == 'clear' and m.channel == 1
                            for m in choices))
        self.assertGreaterEqual(
            max(m.meta['particle_hit_probability'] for m in choices), 2 / 3)

    def test_particle_probe_miss_becomes_feedback_not_block(self):
        scheduler = BeliefRolloutScheduler('Q3')
        scheduler._br_inflight_probe = (1, (100.0, 0.0))
        scheduler.on_probe_failure(1, (100.0, 0.0))
        self.assertNotIn(1, scheduler.blocked)
        self.assertEqual(scheduler.probe_attempts(1), 1)
        self.assertEqual(scheduler._br_probe_feedback, (1, (100.0, 0.0)))

    def test_rollout_particle_miss_executes_feedback_before_leaf_policy(self):
        ks = KnowledgeState('Q3')
        for ch in ks.channels.values():
            ch.status = ChannelStatus.CERTIFIED_ABSENT
        ks[1].status = ChannelStatus.UNKNOWN
        ks[1].update_direction((0, 0), 0, 0)
        cfg, runner_cfg = production.split_config('Q3')
        scheduler = LearnedSearchScheduler('Q3', **cfg)
        mission = Mission('clear', (60, 0), channel=1,
                          meta={'kind': 'belief_particle_clear',
                                'risky_probe': True,
                                'suppress_failed_post_clear_scan': True})
        world = {1: Hypothesis((100, 0), 1000, False, 0)}
        actions = []
        execute = QuietRunner._execute

        def record(runner, action):
            actions.append((action.kind, tuple(action.target), action.channel))
            return execute(runner, action)

        with patch.object(QuietRunner, '_execute', record), patch.object(
                LearnedSearchScheduler, 'decide', return_value=None):
            rollout_cost(policy_snapshot(scheduler), ks, (0, 0), 1,
                         mission, world, 99, MainlineConfig(**runner_cfg), 3)
        self.assertEqual(actions, [('clear', (60, 0), 1),
                                   ('measure', (60, 0), 1)])
        self.assertEqual(len(ks[1].observations), 1)


if __name__ == '__main__':
    unittest.main()
