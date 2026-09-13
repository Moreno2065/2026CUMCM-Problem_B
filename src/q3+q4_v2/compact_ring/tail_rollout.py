"""Observation-only posterior rollout for the compact-ring tail.

Search starts only after every channel has either positive evidence or an
absence certificate.  The sampled worlds therefore use only recorded feasible
regions, bearings, no-signal witnesses and failed-clear exclusions.  Each
candidate is replayed through the ordinary compact controller to completion.

This is a bounded root rollout: the real controller executes one action and
replans after the next real observation.  It cannot turn a sampled hypothesis
into a certificate or inspect the live simulator's source locations.
"""
from __future__ import annotations

import copy
import math
import statistics
import time

from belief_rollout.worlds import sample_worlds
from geometry import constants as C
from policy.scheduler import Mission

from .stop_fusion import EXCLUDE, replay


def _key(mission):
    return (mission.kind, mission.channel,
            round(float(mission.target[0]), 3),
            round(float(mission.target[1]), 3),
            tuple(mission.meta.get('joint_channels', ())))


def candidates(policy, ks, position, base, limit):
    """Return real executable tail actions, always including ``base`` first."""
    if base is None or base.kind not in ('measure', 'clear'):
        return [base] if base is not None else []
    result, seen = [], set()

    def add(mission):
        if mission is None or len(result) >= limit:
            return
        marker = _key(mission)
        if marker not in seen:
            seen.add(marker)
            result.append(mission)

    add(base)
    immediate = []
    for channel in ks.ready:
        if channel.channel_id in policy.blocked:
            continue
        target = policy._clear_target(channel, position)
        post = policy._post_clear_channels(ks, target,
                                           exclude=channel.channel_id)
        meta = {'kind': 'compact_tail_rollout_clear', 'ready_route': True}
        if post is not None:
            meta['post_clear_channels'] = post
        immediate.append((math.dist(position, target) / C.MOVE_SPEED,
                          channel.channel_id, 'clear', target, meta))
    for channel in ks.active:
        channel_id = channel.channel_id
        if (policy.fallback.in_fallback(channel_id) or
                policy._compact_route_attempts.get(channel_id, 0) >=
                policy.compact_route_active_attempts):
            continue
        # The regular compact controller uses the first candidate. Keeping a
        # second legal geometry lets rollout compare a route/angle decision
        # without flooding the root with near-duplicate actions.
        for rank, target in enumerate(policy._active_route_candidates(
                channel, position)[:2]):
            immediate.append((math.dist(position, target) / C.MOVE_SPEED,
                              channel_id, 'measure', target,
                              {'kind': 'compact_tail_rollout_measure',
                               'scan_variant': 'primary',
                               'candidate_rank': rank}))
    immediate.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    for _, channel_id, kind, target, meta in immediate:
        add(Mission(kind, target, channel=channel_id, meta=meta))
    return result


def _restore_before(policy, before):
    """Undo bookkeeping from an unexecuted base proposal.

    ``_compact_decide`` increments route-attempt counters while it constructs
    a measure proposal. If rollout selects another root action, preserving
    those increments would silently block a valid future action.
    """
    preserved = {name: policy.__dict__[name] for name in EXCLUDE
                 if name in policy.__dict__}
    policy.__dict__.clear()
    policy.__dict__.update(copy.deepcopy(before))
    policy.__dict__.update(preserved)


def choose(policy, before, ks, position, current_channel, base):
    """Return the conservative cross-world winner, or the base action."""
    stats = policy.tail_rollout_stats
    if (base is None or ks.unknown or not ks.active or
            policy.fallback.active_fallbacks() or
            stats['wall_s'] >= policy.compact_tail_rollout_budget):
        return base
    started = time.perf_counter()
    deadline = started + max(0.0, policy.compact_tail_rollout_budget -
                             stats['wall_s'])
    choices = candidates(policy, ks, position, base,
                         policy.compact_tail_rollout_candidates)
    if len(choices) <= 1:
        stats['wall_s'] += time.perf_counter() - started
        return base
    stats['searches'] += 1
    decision = stats['searches']
    failures = {channel.channel_id: channel.excluded_clear_points
                for channel in ks.active + ks.ready}
    worlds = sample_worlds(ks, failures, policy.compact_tail_rollout_worlds,
                           seed=('compact-tail', decision))
    costs, selected = [], 0
    if worlds:
        owner = getattr(policy.stop_planner, '__self__', None)
        config = copy.deepcopy(owner.config) if owner is not None else None
        if config is None:
            stats['world_failures'] += 1
        else:
            saved = copy.deepcopy(before)
            for candidate in choices:
                values = []
                for world_id, world in enumerate(worlds):
                    value = replay(saved, ks, position, current_channel,
                                   candidate, world, config,
                                   ('compact-tail', decision, world_id),
                                   deadline,
                                   limit=policy.compact_tail_rollout_step_limit)
                    stats['branches'] += 1
                    values.append(value)
                    if (not math.isfinite(value) or
                            time.perf_counter() >= deadline):
                        break
                if len(values) != len(worlds) or not all(math.isfinite(value)
                                                          for value in values):
                    stats['incomplete_candidates'] += 1
                    costs.append(None)
                else:
                    costs.append(values)
                if time.perf_counter() >= deadline:
                    break
            if costs and costs[0] is not None:
                best_gain = policy.compact_tail_rollout_margin_s
                for index, values in enumerate(costs[1:], 1):
                    if values is None:
                        continue
                    gains = [reference - candidate
                             for reference, candidate in zip(costs[0], values)]
                    score = (statistics.median(gains)
                             if policy.compact_tail_rollout_objective == 'median'
                             else statistics.mean(gains))
                    wins = sum(gain > 0.0 for gain in gains) / len(gains)
                    if (score >= best_gain and
                            wins >= policy.compact_tail_rollout_min_win_fraction and
                            min(gains) >= -policy.compact_tail_rollout_margin_s):
                        best_gain, selected = score, index
    else:
        stats['world_failures'] += 1
    stats['overrides'] += int(selected != 0)
    stats['wall_s'] += time.perf_counter() - started
    policy.tail_rollout_log.append({
        'decision': decision,
        'chosen': selected,
        'known': len(ks.active) + len(ks.ready) + len(ks.cleared),
        'candidates': [{'kind': mission.kind, 'channel': mission.channel,
                        'target': list(mission.target),
                        'costs': costs[index] if index < len(costs) else None}
                       for index, mission in enumerate(choices)],
    })
    if selected:
        _restore_before(policy, before)
    return choices[selected]
