"""Compare replacing two localisation stops by one shared observation stop.

Hypotheses are observation-conditioned planning samples, not certificates.
Every alternative is followed by the actual compact-ring policy (with this
search disabled), so moving to clear the second source is still charged.
"""
from __future__ import annotations

import copy
import math
import statistics
import time

from belief_rollout.scheduler import QuietRunner
from belief_rollout.worlds import HypotheticalBackend, sample_worlds
from executor.action_executor import ActionExecutor
from geometry import constants as C
from policy import localization
from state.channel_state import ChannelStatus


EXCLUDE = {'decision_listener', 'stop_planner', 'fusion_log', 'fusion_stats',
           'tail_rollout_log', 'tail_rollout_stats', 'segment_log',
           'segment_stats', 'coverage_rollout_log', 'coverage_rollout_stats'}


def snapshot(policy):
    # Do not follow bound callbacks into the live runner or simulator.
    return copy.deepcopy({k: v for k, v in vars(policy).items()
                          if k not in EXCLUDE})


def replay(saved, ks, position, current_channel, mission, world, config,
           noise_seed, deadline=math.inf, limit=180, policy_setup=None):
    from .scheduler import CompactRingScheduler

    policy = CompactRingScheduler.__new__(CompactRingScheduler)
    policy.__dict__.update(copy.deepcopy(saved))
    policy.compact_fusion_budget = 0.0
    # A tail rollout evaluates one root action then follows the ordinary
    # compact policy. An imagined branch must never recursively launch search.
    policy.compact_tail_rollout_budget = 0.0
    policy.compact_coverage_rollout_budget = 0.0
    policy.segment_budget = 0.0
    policy.segment_stats = {'wall_s': 0.0, 'branches': 0}
    policy.segment_log = []
    policy.fusion_stats = {'wall_s': 0.0}
    policy.fusion_log = []
    policy.coverage_rollout_stats = {
        'searches': 0, 'overrides': 0, 'branches': 0,
        'incomplete_candidates': 0, 'world_failures': 0, 'wall_s': 0.0,
        'branch_actions': 0, 'forced_returns': 0}
    policy.coverage_rollout_log = []
    if policy_setup is not None:
        policy_setup(policy)
    backend = HypotheticalBackend(world, ks, position, current_channel, noise_seed)
    executor = ActionExecutor(backend)
    executor._last_measure_channel = current_channel
    runner = QuietRunner('Q3', executor, '', config=copy.deepcopy(config))
    # initialize_knowledge may only run on a fresh state. Restore the actual
    # observation history afterwards; retain the nonconvex constrained state.
    runner.attach_scheduler(policy)
    runner.ks = copy.deepcopy(ks)
    action = copy.deepcopy(mission)
    for step in range(limit):
        if action is None or time.perf_counter() >= deadline:
            return math.inf
        runner._current_mission = action
        runner._execute(action)
        runner._step = step + 1
        if runner.ks.is_complete():
            return executor.virtual_time if not backend.world else math.inf
        action = policy.decide(runner.ks, executor.position,
                               executor.current_channel)
    return math.inf


def posterior_ratio(ch, point):
    if (ch.mec is None or not ch.feasible_region
            or math.dist(ch.mec[0], point) + ch.mec_radius > C.R_EFF_MIN
            or any(math.dist(o['position'], point) < 2 for o in ch.observations)):
        return math.inf
    step = localization._adaptive_step(ch.feasible_region, point)
    # This sampled bearing sweep only screens candidates. The actual state
    # update and READY decision always use the full constrained geometry.
    return localization._eval_worst(ch.feasible_region, point, step,
                                    mode='radius') / max(ch.mec_radius, 1e-6)


def candidates(policy, ks, position, base):
    plan = policy.stop_planner(base)
    measured = set(plan.get('measures', plan.get('success', [])))
    if base.channel is not None:
        measured.add(base.channel)
    ranked = []
    for ch in ks.active:
        if (ch.channel_id in measured or ch.channel_id in policy.blocked
                or policy.fallback.in_fallback(ch.channel_id)):
            continue
        ratio = posterior_ratio(ch, base.target)
        if ratio <= 0.85:
            ranked.append((ratio, math.dist(base.target, ch.mec[0]),
                           ch.channel_id))
    ranked.sort()
    result = [base]
    # An earlier bearing on the already planned leg can make the centre stop
    # obsolete. Only screen predicted terminal views; the rollout still pays
    # for any nonterminal outcome, further measurement and actual clearing.
    if base.kind == 'measure' and ks[base.channel].status == ChannelStatus.ACTIVE:
        primary = ks[base.channel]
        views = []
        for fraction in (0.0, 0.25, 0.5, 0.75):
            point = tuple(a + fraction * (b-a) for a, b in zip(position, base.target))
            if math.dist(point, base.target) < 20:
                continue
            ratio = posterior_ratio(primary, point)
            if ratio * primary.mec_radius <= C.CLEAR_RADIUS:
                views.append((fraction, ratio, point))
        for _, _, point in views[:1]:
            chosen = copy.deepcopy(base)
            chosen.target = point
            chosen.meta['scan_variant'] = 'primary'
            chosen.meta['joint_channels'] = []
            chosen.meta['stop_fusion'] = {'variant': 'early_terminal_view',
                                          'channels': [base.channel]}
            result.append(chosen)
    if policy.compact_fusion_views_only:
        return result
    for count in (1, 2):
        if len(ranked) < count:
            continue
        chosen = copy.deepcopy(base)
        extra = [row[2] for row in ranked[:count]]
        if base.kind == 'clear':
            chosen.meta['post_clear_channels'] = sorted(measured - {base.channel}
                                                        | set(extra))
        else:
            chosen.meta['joint_channels'] = sorted(
                set(chosen.meta.get('joint_channels', [])) | set(extra))
        chosen.meta['stop_fusion'] = {'variant': 'same_stop', 'channels': extra}
        result.append(chosen)
    # Also try servicing the original primary at a future ACTIVE node. Both
    # channels are measured there, then normal feedback decides what remains.
    if base.kind == 'measure' and ks[base.channel].status == ChannelStatus.ACTIVE:
        primary = ks[base.channel]
        others = sorted((ch for ch in ks.active if ch.channel_id not in measured
                         and not policy.fallback.in_fallback(ch.channel_id)),
                        key=lambda ch: math.dist(base.target, ch.mec[0]))
        for ch in others[:3]:
            point = policy._active_route_point(ch, position)
            if (point is None or math.dist(point, base.target) < 2
                    or posterior_ratio(primary, point) > 0.85):
                continue
            chosen = copy.deepcopy(base)
            chosen.target = point
            chosen.meta['scan_variant'] = 'primary'
            chosen.meta['joint_channels'] = [ch.channel_id]
            chosen.meta['stop_fusion'] = {'variant': 'replace_stop',
                                          'channels': [ch.channel_id]}
            result.append(chosen)
            break
    return result


def choose(policy, ks, position, current_channel, base):
    if (base is None or base.kind not in ('measure', 'clear') or ks.unknown
            or not ks.active or policy.fallback.active_fallbacks()
            or policy.fusion_stats['wall_s'] >= policy.compact_fusion_budget):
        return base
    started = time.perf_counter()
    deadline = started + policy.compact_fusion_budget - policy.fusion_stats['wall_s']
    choices = candidates(policy, ks, position, base)
    if len(choices) == 1:
        policy.fusion_stats['wall_s'] += time.perf_counter() - started
        return base
    policy.fusion_stats['searches'] += 1
    decision = policy.fusion_stats['searches']
    failures = {ch.channel_id: ch.excluded_clear_points for ch in ks.active + ks.ready}
    worlds = sample_worlds(ks, failures, policy.compact_fusion_worlds, decision)
    # Only config is read from the owner. No backend/seed/truth reaches replay.
    config = copy.deepcopy(policy.stop_planner.__self__.config)
    saved = snapshot(policy)
    costs, selected = [], 0
    if worlds:
        for candidate in choices:
            values = []
            for wid, world in enumerate(worlds):
                value = replay(saved, ks, position, current_channel, candidate,
                               world, config, (decision, wid), deadline)
                values.append(value)
                policy.fusion_stats['branches'] += 1
                if not math.isfinite(value):
                    break
            if len(values) != len(worlds) or not all(map(math.isfinite, values)):
                policy.fusion_stats['incomplete_candidates'] += 1
                costs.append(None)
            else:
                costs.append(values)
            if time.perf_counter() >= deadline:
                break
        if costs and costs[0] is not None:
            best = 0.0
            for index, values in enumerate(costs[1:], 1):
                if values is None:
                    continue
                gains = [a-b for a, b in zip(costs[0], values)]
                gain = statistics.mean(gains)
                if (gain >= policy.compact_fusion_margin and gain > best
                        and sum(g > 0 for g in gains) >= math.ceil(.75 * len(worlds))
                        and min(gains) >= -policy.compact_fusion_margin):
                    best, selected = gain, index
    else:
        policy.fusion_stats['world_failures'] += 1
    policy.fusion_stats['overrides'] += bool(selected)
    row = {'decision': decision, 'chosen': selected,
           'candidates': [{'target': list(m.target),
                           'fusion': m.meta.get('stop_fusion'),
                           'costs': costs[i] if i < len(costs) else None}
                          for i, m in enumerate(choices)]}
    policy.fusion_log.append(row)
    policy.fusion_stats['wall_s'] += time.perf_counter() - started
    return choices[selected]
