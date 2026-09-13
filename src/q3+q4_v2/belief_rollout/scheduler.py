"""Finite-budget, observation-only rollout over joint stop/scan actions.

No neural network is trained. Each candidate is executed once in each sampled
world and followed by the *unchanged* production controller to completion.
The real controller executes only the selected first action and replans from
the next actual observation. Finite sampling offers no policy-improvement
guarantee; complete-episode evaluation is the acceptance criterion.
"""
from __future__ import annotations

import copy
import math
import statistics
import time

from executor.action_executor import ActionExecutor
from experiment.config import MainlineConfig
from geometry import constants as C
from learned_search.scheduler import LearnedSearchScheduler
from policy.scheduler import Mission
from runtime import V2GameRunner
from .worlds import HypotheticalBackend, sample_worlds


EXCLUDE = {'decision_listener', 'stop_planner', 'rollout_log', 'rollout_stats'}


def policy_snapshot(scheduler):
    # Never deepcopy a bound stop_planner/listener: that would follow its
    # __self__ into the live runner, executor and hidden simulator state.
    return copy.deepcopy({k: v for k, v in scheduler.__dict__.items()
                          if k not in EXCLUDE})


def plain_scheduler(snapshot):
    obj = LearnedSearchScheduler.__new__(LearnedSearchScheduler)
    obj.__dict__.update(copy.deepcopy(snapshot))
    obj.decision_listener = None
    obj.stop_planner = None
    return obj


class QuietRunner(V2GameRunner):
    """Use the real execution/update code without exporting imagined logs."""
    def _traj(self, *args, **kwargs):
        pass

    def _action(self, *args, **kwargs):
        pass

    def _record_decision(self, *args, **kwargs):
        pass

    def _record_localization(self, *args, **kwargs):
        pass

    def _record_certificate(self, *args, **kwargs):
        pass


def rollout_cost(snapshot, ks, position, current_channel, mission, world,
                 noise_seed, runner_config, max_steps=150):
    backend = HypotheticalBackend(world, ks, position, current_channel, noise_seed)
    executor = ActionExecutor(backend)
    executor._last_measure_channel = current_channel
    runner = QuietRunner(ks.mode, executor, '', config=copy.deepcopy(runner_config))
    runner.ks = copy.deepcopy(ks)
    runner.attach_scheduler(plain_scheduler(snapshot))
    current = copy.deepcopy(mission)
    for step in range(max_steps):
        if current is None:
            break
        runner._current_mission = current
        runner._execute(current)
        runner._step = step + 1
        if runner.ks.is_complete():
            # A contradictory certificate must not make a hypothesis cheap.
            return (executor.virtual_time if not backend.world else math.inf)
        # The live belief controller takes one same-stop direction measurement
        # after a particle-clear miss.  Model that conditional second action
        # explicitly before handing the rest of the episode to production.
        if (current.meta.get('kind') == 'belief_particle_clear' and
                not runner.ks[current.channel].status.name == 'CLEARED'):
            current = Mission('measure', executor.position,
                              channel=current.channel,
                              meta={'kind': 'belief_probe_feedback',
                                    'scan_variant': 'primary'})
            continue
        current = runner.scheduler.decide(runner.ks, executor.position,
                                           executor.current_channel)
    return math.inf


class BeliefRolloutScheduler(LearnedSearchScheduler):
    def __init__(self, *args, br_enabled=True, br_worlds=4,
                 br_candidates=9, br_period=3, br_margin_s=20.0,
                 br_budget_s=240.0, br_step_limit=150,
                 br_min_win_fraction=0.5, br_objective='mean',
                 br_clear_radius=0.0, br_clear_candidates=3,
                 br_clear_only=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.br_enabled = bool(br_enabled)
        self.br_worlds = max(1, int(br_worlds))
        self.br_candidates = max(1, int(br_candidates))
        self.br_period = max(1, int(br_period))
        self.br_margin_s = float(br_margin_s)
        self.br_budget_s = float(br_budget_s)
        self.br_step_limit = int(br_step_limit)
        self.br_clear_radius = max(0.0, float(br_clear_radius))
        self.br_clear_candidates = max(0, int(br_clear_candidates))
        self.br_clear_only = bool(br_clear_only)
        self.br_min_win_fraction = float(br_min_win_fraction)
        if not 0.0 <= self.br_min_win_fraction <= 1.0:
            raise ValueError('br_min_win_fraction must be between 0 and 1')
        if br_objective not in ('mean', 'median'):
            raise ValueError("br_objective must be 'mean' or 'median'")
        self.br_objective = br_objective
        self.br_decisions = 0
        self._br_inflight_probe = None
        self._br_probe_feedback = None
        self.rollout_log = []
        self.rollout_stats = {'searches': 0, 'overrides': 0, 'world_failures': 0,
                              'incomplete_branches': 0, 'branches': 0,
                              'wall_s': 0.0, 'budget_stops': 0,
                              'clear_candidates': 0,
                              'clear_overrides': 0}

    def _particle_clear_choices(self, ks, position, worlds):
        """Rank risky clears from observable-history hypothesis positions.

        Candidate construction uses a 19 m scoring radius, leaving one metre
        of numerical margin inside the protocol's 20 m clear radius.  These
        samples estimate action value only; the ordinary geometric fallback
        remains responsible for finite-step completion.
        """
        if not worlds or self.br_clear_radius <= 0 or self.br_clear_candidates <= 0:
            return []
        ranked = []
        for ch in ks.active:
            if ch.mec is None or ch.mec_radius > self.br_clear_radius:
                continue
            cloud = [world[ch.channel_id].position for world in worlds
                     if ch.channel_id in world]
            if not cloud:
                continue
            # Hypothesis locations and close-pair midpoints are sufficient to
            # expose both a modal shot and a shot covering two nearby modes.
            centers = list(cloud)
            for i, a in enumerate(cloud):
                for b in cloud[i + 1:]:
                    if math.dist(a, b) <= 38.0:
                        centers.append(((a[0] + b[0]) / 2.0,
                                        (a[1] + b[1]) / 2.0))
            seen = set()
            for point in centers:
                key = (round(point[0], 3), round(point[1], 3))
                if key in seen:
                    continue
                seen.add(key)
                hits = sum(math.dist(point, p) <= 19.0 for p in cloud)
                probability = hits / len(cloud)
                travel = math.dist(position, point) / C.MOVE_SPEED
                immediate = travel + probability * C.CLEAR_SUCCESS_TIME + \
                    (1.0 - probability) * C.CLEAR_FAIL_TIME
                ranked.append((-probability, immediate, travel,
                               ch.channel_id, point))
        result = []
        for neg_probability, immediate, _travel, channel, point in sorted(ranked):
            if any(m.channel == channel and math.dist(m.target, point) < 1.0
                   for m in result):
                continue
            result.append(Mission(
                'clear', point, channel=channel,
                meta={'kind': 'belief_particle_clear',
                      'risky_probe': True,
                      # The second POMDP action is chosen explicitly after
                      # the miss, rather than being hidden in an automatic
                      # post-clear multi-channel scan.
                      'suppress_failed_post_clear_scan': True,
                      'particle_hit_probability': -neg_probability,
                      'particle_immediate_cost_s': immediate}))
            if len(result) >= self.br_clear_candidates:
                break
        return result

    def _alternatives(self, ks, position, base, worlds):
        choices, seen = [], set()

        def append(mission):
            if len(choices) >= self.br_candidates:
                return
            key = (mission.kind, mission.channel,
                   tuple(round(x, 4) for x in mission.target),
                   mission.meta.get('scan_variant'))
            if key not in seen:
                seen.add(key)
                choices.append(mission)

        append(base)
        # The same stop with an explicit primary-only scan is an independent
        # joint action, not an executor side effect.
        if not self.br_clear_only:
            for variant in ('primary', 'active'):
                m = copy.deepcopy(base)
                m.meta['scan_variant'] = variant
                m.meta.pop('joint_channels', None)
                append(m)
        for mission in self._particle_clear_choices(ks, position, worlds):
            append(mission)
            self.rollout_stats['clear_candidates'] += 1
        if self.br_clear_only:
            return choices
        channels = sorted(ks.active,
                          key=lambda ch: (math.dist(position, ch.mec[0]),
                                          ch.channel_id))
        # Reserve slots for both geometry families. Without this quota a
        # crowded ACTIVE set fills the pool with centers before any crossing
        # baseline can even be considered.
        center_quota = max(0, (self.br_candidates - len(choices) + 1) // 2)
        for geometry in ('center', 'perp'):
            added = 0
            for ch in channels:
                if geometry == 'center' and added >= center_quota:
                    break
                center, radius = ch.mec
                if geometry == 'center':
                    point = center
                else:
                    dirs = [o for o in ch.observations if o['result'] == 'direction']
                    if not dirs:
                        continue
                    theta = math.radians(dirs[-1]['bearing'])
                    offset = min(350.0, max(50.0, float(radius)))
                    options = [(center[0] + sign*offset*math.sin(theta),
                                center[1] - sign*offset*math.cos(theta))
                               for sign in (-1, 1)]
                    point = min(options, key=lambda p: math.dist(position, p))
                if math.dist(position, point) < 1.0:
                    continue
                if any(math.dist(point, obs['position']) < 1.0
                       for obs in ch.observations
                       if obs['result'] in ('direction', 'near', 'no_signal')):
                    continue
                # Alternate joint scan sizes across the candidate pool; all
                # selected actions still run the real plan_stop implementation.
                variant = 'active' if geometry == 'center' else 'primary'
                previous_count = len(choices)
                append(Mission('measure', point, channel=ch.channel_id,
                               meta={'kind': 'belief_rollout',
                                     'scan_variant': variant,
                                     'br_geometry': geometry}))
                added += len(choices) - previous_count
                if len(choices) >= self.br_candidates:
                    return choices
        return choices

    def decide(self, ks, position, current_channel):
        # A particle probe miss is a normal observation, not an exception.
        # Spend exactly one same-point measurement to turn the new exclusion
        # into a direction/near observation, then replan from that posterior.
        if self._br_probe_feedback is not None:
            channel, point = self._br_probe_feedback
            self._br_probe_feedback = None
            if ks[channel].status.name == 'ACTIVE':
                return Mission('measure', point, channel=channel,
                               meta={'kind': 'belief_probe_feedback',
                                     'scan_variant': 'primary'})
        if (self._br_inflight_probe is not None and
                ks[self._br_inflight_probe[0]].status.name == 'CLEARED'):
            self._br_inflight_probe = None
        self.br_decisions += 1
        eligible = (self.br_enabled and not ks.unknown and not ks.ready and
                    len(ks.active) >= 2 and not self.fallback.active_fallbacks() and
                    self.br_decisions % self.br_period == 0 and
                    self.rollout_stats['wall_s'] < self.br_budget_s)
        if not eligible:
            return super().decide(ks, position, current_channel)
        started = time.perf_counter()
        before = policy_snapshot(self)
        listener = self.decision_listener
        traces = []
        self.decision_listener = traces.append
        try:
            base = super().decide(ks, position, current_channel)
        finally:
            self.decision_listener = listener
        if base is None or base.kind != 'measure' or self.fallback.active_fallbacks():
            if listener:
                for trace in traces:
                    listener(trace)
            return base
        after = policy_snapshot(self)
        worlds = sample_worlds(ks, self._probe_failures, self.br_worlds,
                              seed=self.br_decisions)
        choices = self._alternatives(ks, position, base, worlds)
        self.rollout_stats['searches'] += 1
        selected = 0
        row = {'decision': self.br_decisions, 'mode': self.mode,
               'active': len(ks.active), 'known': len(ks.active)+len(ks.cleared),
               'candidates': [], 'chosen': 0, 'sampled_worlds': len(worlds)}
        if not worlds:
            self.rollout_stats['world_failures'] += 1
        else:
            # Only read the immutable runner configuration through this
            # callback. No live executor, simulator, seed or truth is read.
            owner = getattr(self.stop_planner, '__self__', None)
            config = copy.deepcopy(owner.config) if owner else MainlineConfig()
            costs = []
            deadline = started + max(0.0, self.br_budget_s-
                                     self.rollout_stats['wall_s'])
            for index, mission in enumerate(choices):
                values = []
                for wid, world in enumerate(worlds):
                    if time.perf_counter() >= deadline:
                        break
                    cost = rollout_cost(after if index == 0 else before, ks,
                                        position, current_channel, mission, world,
                                        (self.br_decisions, wid), config,
                                        self.br_step_limit)
                    self.rollout_stats['branches'] += 1
                    if not math.isfinite(cost):
                        self.rollout_stats['incomplete_branches'] += 1
                    values.append(cost)
                if len(values) != len(worlds):
                    self.rollout_stats['budget_stops'] += 1
                    break
                costs.append(values)
                row['candidates'].append({
                    'kind': mission.kind, 'channel': mission.channel,
                    'point': list(mission.target),
                    'scan_variant': mission.meta.get('scan_variant'),
                    'costs': [v if math.isfinite(v) else None for v in values],
                })
            # Require paired comparisons on identical worlds, with finite
            # completion on every world. A lucky truncated branch cannot win.
            if costs and all(math.isfinite(v) for v in costs[0]):
                best_delta = -self.br_margin_s
                for index, values in enumerate(costs[1:], 1):
                    if not all(math.isfinite(v) for v in values):
                        continue
                    delta = [a-b for a, b in zip(values, costs[0])]
                    score = (statistics.median(delta)
                             if self.br_objective == 'median'
                             else statistics.mean(delta))
                    wins = sum(d < 0 for d in delta) / len(delta)
                    if score < best_delta and wins >= self.br_min_win_fraction:
                        best_delta, selected = score, index
                row['predicted_delta_s'] = (0.0 if selected == 0 else best_delta)
                row['objective'] = self.br_objective
        if selected:
            # Restore ALL policy bookkeeping from before the unexecuted
            # production proposal, not only its coverage cursor.
            preserved = {k: self.__dict__[k] for k in EXCLUDE
                         if k in self.__dict__}
            self.__dict__.clear()
            self.__dict__.update(before)
            self.__dict__.update(preserved)
            self.rollout_stats['overrides'] += 1
        chosen = choices[selected]
        if selected and chosen.kind == 'clear':
            self.rollout_stats['clear_overrides'] += 1
            self._br_inflight_probe = (chosen.channel, tuple(chosen.target))
        chosen.meta['belief_rollout'] = selected != 0
        row['chosen'] = selected
        row['wall_s'] = time.perf_counter() - started
        self.rollout_stats['wall_s'] += row['wall_s']
        self.rollout_log.append(row)
        if listener:
            if selected:
                trace = self._trace_base(ks, 'belief_rollout')
                trace['selected'] = {'kind': chosen.kind, 'channel': chosen.channel,
                                     'point': list(chosen.target)}
                trace['belief_rollout'] = row
                listener(trace)
            else:
                for trace in traces:
                    listener(trace)
        return chosen

    def on_probe_failure(self, channel_id, point):
        """Record a legal miss and schedule its information-bearing follow-up."""
        super().on_probe_failure(channel_id, point)
        if (self._br_inflight_probe is not None and
                self._br_inflight_probe[0] == int(channel_id)):
            self._br_probe_feedback = (int(channel_id), tuple(point))
            self._br_inflight_probe = None
