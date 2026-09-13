"""Bounded, observation-contingent source-completion segments, without NN.

Search includes the discovery phase. Unknown-source worlds are a documented
planning prior, NOT a calibrated posterior or an absence certificate. A
candidate performs up to eight actual feedback-dependent actions, followed
by the constrained production controller to completion in each sampled world.
One production action separates committed segments to prevent coverage
starvation. All online inputs are observations and controller bookkeeping.
"""
from __future__ import annotations

import copy
import math
import random
import statistics
import time

from shapely.geometry import Point
from executor.action_executor import ActionExecutor
from geometry import constants as C
from policy.scheduler import Mission
from state.channel_state import ChannelStatus
from belief_rollout.scheduler import QuietRunner, plain_scheduler
from belief_rollout.worlds import (Hypothesis, HypotheticalBackend, sample_source,
                                  _sample_point, _triangles, point_key)
from .scheduler import ConstraintSearchScheduler


EXCLUDE = {'decision_listener', 'stop_planner', 'segment_log', 'segment_stats',
           '_segment_pending'}


def snapshot(policy):
    return copy.deepcopy({k: v for k, v in vars(policy).items() if k not in EXCLUDE})


def unknown_hypothesis(ch, rng):
    if not ch.feasible_region:
        return None
    triangles, total = _triangles(ch.feasible_region)
    negative = [o['position'] for o in ch.observations if o['result'] == 'no_signal']
    for _ in range(600):
        p = _sample_point(triangles, total, rng, ch.feasible_region)
        if math.hypot(*p) > C.OMEGA_RADIUS:
            continue
        if not ch.position_set.covers(Point(p)):
            continue
        upper = min([C.R_EFF_MAX] + [math.dist(p, q) - 1e-7 for q in negative])
        if upper >= C.R_EFF_MIN:
            return Hypothesis(p, rng.uniform(C.R_EFF_MIN, upper), False, 0.0)
    return None


def worlds_from_observations(ks, number, decision):
    """Conditional feasible hypotheses; source-count prior uses only 10..16.

Total count is uniform on feasible counts; unknown channels are drawn without
replacement with remaining-position area weights. This is an approximation,
deliberately never described as a calibrated Bayesian posterior.
"""
    worlds = []
    known = len(ks.active) + len(ks.ready) + len(ks.cleared)
    eligible = [ch for ch in ks.unknown if ch.position_set.area > 1e-6]
    low, high = max(known, 10), min(C.MAX_SOURCES, known + len(eligible))
    if low > high:
        return []
    for wid in range(number):
        rng = random.Random(f'constraint-segment:{decision}:{wid}')
        world = {}
        for ch in ks.active + ks.ready:
            h = sample_source(ch, 'Q3', ch.excluded_clear_points, rng)
            if h is None:
                return []
            world[ch.channel_id] = h
        needed = rng.randint(low, high) - known
        pool = list(eligible)
        for _ in range(needed):
            weights = [max(1e-9, ch.position_set.area) for ch in pool]
            ch = rng.choices(pool, weights=weights)[0]
            pool.remove(ch)
            h = unknown_hypothesis(ch, rng)
            if h is None:
                return []
            world[ch.channel_id] = h
        worlds.append(world)
    return worlds


def finish_action(plan, ks, position, policy):
    """Feedback-dependent approach / crossing bearing / clear package."""
    while plan['channels'] and ks[plan['channels'][0]].status in (
            ChannelStatus.CLEARED, ChannelStatus.CERTIFIED_ABSENT):
        plan['channels'].pop(0)
    if not plan['channels'] or plan['used'] >= 8 or policy.fallback.active_fallbacks():
        return None
    ch = ks[plan['channels'][0]]
    cid = ch.channel_id
    variant = plan['variant']
    if ch.status == ChannelStatus.READY:
        point = policy._clear_target(ch, position)
        return Mission('clear', point, channel=cid,
                       meta={'kind': 'constraint_segment', 'post_clear_channels': []})
    if ch.status != ChannelStatus.ACTIVE:
        return None
    center, radius = ch.mec
    # One cheap optical attempt near a small residual region; all failure
    # travel and subsequent completion are included in candidate rollouts.
    if radius <= 35 and not ch.excluded_clear_points:
        return Mission('clear', center, channel=cid,
                       meta={'kind': 'constraint_segment', 'post_clear_channels': []})
    dirs = [o for o in ch.observations if o['result'] == 'direction']
    point = center
    # Once at a bearing stop, create a short crossing baseline before leaving
    # the source neighbourhood. Direction comes from the REAL latest reply.
    if dirs and math.dist(position, dirs[-1]['position']) < 1.0:
        theta = math.radians(dirs[-1]['bearing'])
        offset = min(160., max(25., .7 * radius))
        options = [(position[0] + sign * offset * math.sin(theta),
                    position[1] - sign * offset * math.cos(theta))
                   for sign in (-1, 1)]
        next_point = (ks[plan['channels'][1]].mec[0]
                      if len(plan['channels']) > 1 else center)
        point = min(options, key=lambda p: math.dist(p, center) + math.dist(p, next_point))
    if any(math.dist(point, o['position']) < 1 for o in ch.observations):
        return None
    return Mission('measure', point, channel=cid,
                   meta={'kind': 'constraint_segment', 'scan_variant': variant})


def segment_cost(saved, ks, position, current_channel, world, config,
                 decision, wid, base=None, plan=None, deadline=math.inf):
    backend = HypotheticalBackend(world, ks, position, current_channel, (decision, wid))
    # Historical UNKNOWN no-signal observations are part of the same history.
    for ch in ks.unknown:
        for o in ch.observations:
            backend.history[(ch.channel_id, point_key(o['position']))] = {
                'measure_result': o['result']}
    executor = ActionExecutor(backend)
    executor._last_measure_channel = current_channel
    runner = QuietRunner('Q3', executor, '', config=copy.deepcopy(config))
    runner.ks = copy.deepcopy(ks)
    runner.attach_scheduler(plain_scheduler(saved))
    pending = copy.deepcopy(plan)
    first = copy.deepcopy(base)
    for step in range(180):
        if time.perf_counter() >= deadline:
            return math.inf
        if first is not None:
            action, first = first, None
        else:
            action = (finish_action(pending, runner.ks, executor.position,
                                    runner.scheduler) if pending else None)
            if action is not None:
                pending['used'] += 1
            else:
                pending = None
                action = runner.scheduler.decide(runner.ks, executor.position,
                                                 executor.current_channel)
        if action is None:
            return math.inf
        runner._current_mission = action
        runner._execute(action)
        runner._step = step + 1
        if runner.ks.is_complete():
            return executor.virtual_time if not backend.world else math.inf
    return math.inf


class ConstraintMacroScheduler(ConstraintSearchScheduler):
    def __init__(self, mode='Q3', *, segment_budget=60., segment_worlds=3,
                 segment_margin=100., segment_max_branches=300,
                 segment_min_win_fraction=1.0, **kwargs):
        super().__init__(mode, **kwargs)
        self.segment_budget = float(segment_budget)
        self.segment_worlds = int(segment_worlds)
        self.segment_margin = float(segment_margin)
        self.segment_max_branches = int(segment_max_branches)
        self.segment_min_win_fraction = float(segment_min_win_fraction)
        self.segment_decisions = 0
        self._segment_pending = None
        self.segment_log = []
        self.segment_stats = dict(searches=0, overrides=0, world_failures=0,
                                  branches=0, wall_s=0., actions=0,
                                  discovery_searches=0)

    def decide(self, ks, position, current_channel):
        self.segment_decisions += 1
        if self._segment_pending is not None:
            action = finish_action(self._segment_pending, ks, position, self)
            if action is not None:
                self._segment_pending['used'] += 1
                self.segment_stats['actions'] += 1
                return action
            self._segment_pending = None
            # An actual production step between segments preserves progress of
            # the finite certificate route even if sampled priorities err.
            return super().decide(ks, position, current_channel)
        eligible = (ks.active or ks.ready) and not self.fallback.active_fallbacks()
        if (not eligible or self.segment_stats['wall_s'] >= self.segment_budget
                or self.segment_stats['branches'] + self.segment_worlds
                > self.segment_max_branches):
            return super().decide(ks, position, current_channel)
        started = time.perf_counter()
        before = snapshot(self)
        listener, traces = self.decision_listener, []
        self.decision_listener = traces.append
        try:
            base = super().decide(ks, position, current_channel)
        finally:
            self.decision_listener = listener
        if base is None or self.fallback.active_fallbacks():
            if listener:
                for trace in traces:
                    listener(trace)
            return base
        after = snapshot(self)
        candidates = [(None, True)]
        nearest = sorted(ks.active + ks.ready,
                         key=lambda ch: math.dist(position, ch.mec[0]) + ch.mec_radius)
        for ch in nearest[:2]:
            candidates.append((dict(channels=[ch.channel_id], used=0,
                                    variant='primary'), False))
        if len(nearest) > 1:
            pair = [nearest[0].channel_id, nearest[1].channel_id]
            candidates.append((dict(channels=pair, used=0, variant='primary'), False))
            candidates.append((dict(channels=pair, used=0, variant='discover'), True))
        worlds = worlds_from_observations(ks, self.segment_worlds, self.segment_decisions)
        self.segment_stats['searches'] += 1
        self.segment_stats['discovery_searches'] += bool(ks.unknown)
        row = dict(decision=self.segment_decisions, unknown=len(ks.unknown),
                   candidates=[], chosen=0, worlds=len(worlds))
        selected, costs = 0, []
        deadline = started + self.segment_budget - self.segment_stats['wall_s']
        if worlds:
            # Only the configuration object is read; never the live simulator.
            config = copy.deepcopy(self.stop_planner.__self__.config)
            for index, (plan, base_first) in enumerate(candidates):
                if self.segment_stats['branches'] + len(worlds) > self.segment_max_branches:
                    break
                values = []
                for wid, world in enumerate(worlds):
                    if time.perf_counter() >= deadline:
                        break
                    value = segment_cost(after if base_first else before, ks,
                        position, current_channel, world, config,
                        self.segment_decisions, wid, base=base if base_first else None,
                        plan=plan, deadline=deadline)
                    self.segment_stats['branches'] += 1
                    values.append(value)
                if len(values) != len(worlds):
                    break
                costs.append(values)
                row['candidates'].append(dict(plan=plan, base_first=base_first,
                    costs=[v if math.isfinite(v) else None for v in values]))
            if costs and all(math.isfinite(v) for v in costs[0]):
                best = statistics.mean(costs[0]) + .2 * max(costs[0])
                for i, values in enumerate(costs[1:], 1):
                    if not all(math.isfinite(v) for v in values):
                        continue
                    score = statistics.mean(values) + .2 * max(values)
                    wins = sum(a < b for a, b in zip(values, costs[0]))
                    if (score < best and wins >= math.ceil(
                            len(worlds) * self.segment_min_win_fraction)
                            and statistics.mean(costs[0]) - statistics.mean(values)
                            >= self.segment_margin):
                        best, selected = score, i
        else:
            self.segment_stats['world_failures'] += 1
        chosen = base
        if selected:
            plan, base_first = candidates[selected]
            if not base_first:
                preserve = {k: vars(self)[k] for k in EXCLUDE if k in vars(self)}
                self.__dict__.clear()
                self.__dict__.update(before)
                self.__dict__.update(preserve)
            self._segment_pending = copy.deepcopy(plan)
            if not base_first:
                chosen = finish_action(self._segment_pending, ks, position, self)
                if chosen is None:
                    self._segment_pending = None
                    # Replay the original proposal once, including bookkeeping.
                    chosen = super().decide(ks, position, current_channel)
                    selected = 0
                else:
                    self._segment_pending['used'] += 1
                    self.segment_stats['actions'] += 1
            self.segment_stats['overrides'] += bool(selected)
        row['chosen'] = selected
        row['wall_s'] = time.perf_counter() - started
        self.segment_stats['wall_s'] += row['wall_s']
        self.segment_log.append(row)
        if listener:
            if selected:
                trace = self._trace_base(ks, 'constraint_segment')
                trace.update(selected={'kind': chosen.kind, 'channel': chosen.channel,
                                       'point': list(chosen.target)}, segment=row)
                listener(trace)
            else:
                for trace in traces:
                    listener(trace)
        return chosen
